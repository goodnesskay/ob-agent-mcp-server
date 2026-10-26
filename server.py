"""Ogabassey Order Desk: MCP tools for a Chord teammate.

Every tool returns {"ok": bool, ...}. On failure it returns an error_code and a
staff_message the teammate can relay. The key safety rule ("never finalize without
a verified payment") is enforced here in code, not only in the skill prompt.
"""
import datetime as dt
import functools
import hmac
import json
import logging
import os
import time

import httpx
from mcp.server.fastmcp import FastMCP

try:  # local dev: read .env before bumpa/store read the environment
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import bumpa
import store
from bumpa import BumpaError, pick

log = logging.getLogger("order-desk")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

mcp = FastMCP("ogabassey-order-desk", stateless_http=True, json_response=True)

# VERIFY all three sets against Bumpa's real payment statuses. "completed" is deliberately NOT in PAID:
# it may describe the checkout, not the payment.
PAID = {"paid", "success", "successful"}
PENDING = {"pending", "processing", "initiated", "awaiting_payment"}
FAILED = {"failed", "abandoned", "cancelled", "expired", "reversed"}


def safe(fn):
    """Guarantee 5: an unexpected exception still comes back as {"ok": False, error_code, staff_message}."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            log.exception("unhandled error in %s", fn.__name__)
            return {"ok": False, "error_code": "internal_error",
                    "staff_message": "Something went wrong on our side. Nothing was changed that I know of; "
                                     "try again, or flag it for the manager."}
    return wrapper


def fail(code, staff_message, **extra):
    log.warning("tool failure %s: %s %s", code, staff_message, extra)
    return {"ok": False, "error_code": code, "staff_message": staff_message, **extra}


def bumpa_fail(e: BumpaError, action):
    messages = {
        "auth": "Bumpa rejected our API key. The owner needs to check the integration settings.",
        "timeout": f"Bumpa didn't respond while trying to {action}. Try again in a minute.",
        "server": f"Bumpa had an error while trying to {action}. Try again in a minute.",
        "not_found": f"Bumpa couldn't find what we asked for while trying to {action}.",
        "bad_request": f"Bumpa refused to {action}: {e}",
    }
    return fail(f"bumpa_{e.kind}", messages.get(e.kind, f"Something went wrong trying to {action}."),
                status=e.status)


def _alert(text):
    """Optional push alert (e.g. a Slack/WhatsApp webhook) alongside the Chord escalation rule."""
    url = os.getenv("ALERT_WEBHOOK_URL")
    if url:
        try:
            httpx.post(url, json={"text": text}, timeout=5)
        except httpx.HTTPError:
            log.exception("alert webhook failed")


@mcp.tool()
@safe
def find_product(query: str, condition: str = "") -> dict:
    """Search Ogabassey's Bumpa catalog. query: e.g. 'iPhone 13 Pro Max 256GB Graphite'.
    condition: 'New', 'UK-used' or 'Locally used'. Returns up to 5 matches with stock."""
    try:
        body, _ = bumpa.call("list_products", params={"search": query, "limit": 20})
    except BumpaError as e:
        return bumpa_fail(e, "search the catalog")

    products = pick(body, "data.products", "data", "products", default=[]) or []
    qwords = [w.lower() for w in query.split() if w]
    cwords = [w.lower() for w in condition.split() if w]
    matches = []
    for p in products:
        name = str(pick(p, "name", "title", default=""))
        # VERIFY: variants may be under "variants" or "variations"
        variants = p.get("variants") or p.get("variations") or []
        haystack = (name + " " + json.dumps(variants)).lower()
        qscore = sum(w in haystack for w in qwords)
        if qscore:
            matches.append((qscore * 10 + sum(w in haystack for w in cwords), qscore, {
                "product_id": pick(p, "id", "uuid"),
                "name": name,
                "price": pick(p, "price", "selling_price", "amount"),
                "stock": pick(p, "stock", "quantity", "inventory.quantity"),
                "variants": [{"variant_id": pick(v, "id"), "name": pick(v, "name", "title"),
                              "price": pick(v, "price"), "stock": pick(v, "stock", "quantity")}
                             for v in variants],
            }))
    if not matches:
        return fail("not_in_catalog", f"I can't find '{query}' in Bumpa.", searched=query)
    full = [m for m in matches if m[1] == len(qwords)]  # prefer products matching every query word
    matches = full or matches
    matches.sort(key=lambda m: -m[0])
    return {"ok": True, "matches": [m[2] for m in matches[:5]]}


@mcp.tool()
@safe
def create_order_draft(product_id: str, quantity: int, customer_name: str, customer_phone: str,
                       delivery_address: str, customer_email: str, variant_id: str = "",
                       agreed_price: float = 0) -> dict:
    """Create a Bumpa cart and checkout for a confirmed order. Call ONLY after staff reply YES
    to the order summary. customer_email is required: Bumpa won't create a payment link without it.
    Returns checkout_id and the Bumpa total."""
    if quantity < 1:
        return fail("bad_quantity", "Quantity must be at least 1.")
    if "@" not in customer_email:
        return fail("email_required", "I need the customer's email address before I can create the payment link.")
    first, _, last = customer_name.strip().partition(" ")
    try:
        cart, headers = bumpa.call("create_cart", json={"location_id": bumpa.location_id()})
        # Docs: guest mode returns the token as cart_token. VERIFY whether it is in the body, a header, or both.
        cart_token = headers.get("X-Cart-Token") or pick(cart, "cart_token", "data.cart_token", "data.token")
        cart_id = pick(cart, "data.id", "id", "data.cart_id", "cart_id", "data.cart.id")  # VERIFY response path
        if not cart_token or cart_id is None:
            return fail("bumpa_unexpected_response", "Bumpa created a cart but I couldn't read it back. "
                        "Nothing was ordered; try again.", raw_keys=list(cart.keys()) if isinstance(cart, dict) else None)
        item = {"location_id": bumpa.location_id(), "product_id": product_id, "quantity": quantity}
        if variant_id:
            item["product_variation_id"] = variant_id
        bumpa.call("add_cart_item", json=item, cart_token=cart_token)

        # Fulfillment: pickup needs pickup_location_id; delivery needs shipping_method_id (docs).
        # Configured via env; VERIFY which one Ogabassey's staging store accepts.
        checkout_body = {
            "cart_id": cart_id,
            # VERIFY: Bumpa documents email/first_name/last_name only; "phone" is an assumed field.
            "customer_context": {"email": customer_email, "first_name": first, "last_name": last, "phone": customer_phone},
        }
        if os.getenv("BUMPA_PICKUP_LOCATION_ID"):
            checkout_body["fulfillment_context"] = {"type": "pickup",
                                                    "pickup_location_id": int(os.environ["BUMPA_PICKUP_LOCATION_ID"])}
        elif os.getenv("BUMPA_SHIPPING_METHOD_ID"):
            checkout_body["fulfillment_context"] = {"type": "delivery",
                                                    "shipping_method_id": int(os.environ["BUMPA_SHIPPING_METHOD_ID"])}
        checkout, _ = bumpa.call("create_checkout", cart_token=cart_token, json=checkout_body)
        checkout_id = pick(checkout, "data.id", "id", "data.checkout_id")  # VERIFY response path
        if checkout_id is None:
            return fail("bumpa_unexpected_response", "Bumpa created the checkout but I couldn't read its id. "
                        "Nothing was ordered; try again.", raw_keys=list(checkout.keys()) if isinstance(checkout, dict) else None)
        checkout_id = str(checkout_id)
        totals, _ = bumpa.call("calculate_totals", path_params={"checkout_id": checkout_id},
                               cart_token=cart_token, json={})
    except BumpaError as e:
        if e.kind == "bad_request" and "stock" in str(e).lower():
            return fail("out_of_stock", "Bumpa says this item is out of stock.")
        return bumpa_fail(e, "create the order draft")

    total = float(pick(totals, "data.total", "total", "data.grand_total", default=0) or 0)  # VERIFY response path
    store.save(checkout_id, cart_token=cart_token, expected_total=total, status="draft",
               customer={"name": customer_name, "phone": customer_phone, "email": customer_email,
                         "address": delivery_address},
               items=[{"product_id": product_id, "variant_id": variant_id, "quantity": quantity}])

    result = {"ok": True, "checkout_id": checkout_id, "total": total}
    if agreed_price and abs(agreed_price * quantity - total) > 1:
        result["price_warning"] = (f"Bumpa total is ₦{total:,.0f} but the agreed price was "
                                   f"₦{agreed_price * quantity:,.0f}. Confirm with staff before sending a link.")
    return result


@mcp.tool()
@safe
def create_payment_link(checkout_id: str) -> dict:
    """Create the Paystack payment link (via Bumpa) for a draft checkout."""
    order = store.get(checkout_id)
    if not order:
        return fail("unknown_checkout", "I don't have a draft for that order. Let's start it again.")
    if order["status"] == "finalized":
        return fail("already_finalized", f"This order is already paid and recorded as #{order['bumpa_order_id']}.")
    try:
        body, _ = bumpa.call("create_payment_intent", path_params={"checkout_id": checkout_id},
                             cart_token=order["cart_token"], json={}, retries=1)
    except BumpaError as e:
        return bumpa_fail(e, "create the payment link")

    # Docs: the intent returns authorization_url, reference, amount, amount_minor, currency, order_id.
    # VERIFY whether they sit at the top level or under "data".
    url = pick(body, "authorization_url", "data.authorization_url", "data.payment_url", "data.url")
    reference = pick(body, "reference", "data.reference", "data.payment_reference")
    intent_order_id = pick(body, "order_id", "data.order_id")
    if not url:
        return fail("no_payment_url", "Bumpa responded but didn't include a payment link. I've kept the draft.",
                    raw_keys=list(body.keys()) if isinstance(body, dict) else None)
    store.save(checkout_id, payment_url=url, payment_reference=reference, status="link_sent",
               bumpa_order_id=str(intent_order_id) if intent_order_id is not None else None)
    return {"ok": True, "payment_url": url, "amount": order["expected_total"]}


@mcp.tool()
@safe
def verify_payment(checkout_id: str) -> dict:
    """Check with Bumpa whether the customer has actually paid. This is the ONLY valid proof of
    payment. Screenshots and bank alerts are not. Returns status: verified | pending | failed | mismatch."""
    order = store.get(checkout_id)
    if not order:
        return fail("unknown_checkout", "I don't have a record of that order.")
    if order["status"] == "finalized":
        return {"ok": True, "status": "verified", "already_finalized": True, "order_id": order["bumpa_order_id"]}
    if order["status"] == "finalizing":
        return {"ok": True, "status": "pending", "staff_message": "This order is being recorded right now."}
    try:
        body, _ = bumpa.call("get_checkout", path_params={"checkout_id": checkout_id},
                             cart_token=order["cart_token"])
    except BumpaError as e:
        return bumpa_fail(e, "check the payment")

    # VERIFY all of these response paths against a real Get Checkout response.
    status = str(pick(body, "data.payment.status", "data.payment_status", "payment_status", default="")).lower()
    paid = pick(body, "data.payment.amount", "data.amount_paid", "amount_paid")
    if paid is None:
        minor = pick(body, "data.payment.amount_minor", "data.amount_minor", "amount_minor")
        paid = float(minor) / 100 if minor is not None else None
    expected = order["expected_total"] or 0

    if status in PAID:
        # If Bumpa reports no amount we can't compare, so we don't invent a mismatch; the reply says so.
        if paid is not None and expected and abs(float(paid) - expected) > 1:
            paid = float(paid)
            store.save(checkout_id, status="flagged")
            store.add_flag(checkout_id, "amount_mismatch", f"paid {paid}, expected {expected}")
            _alert(f"Amount mismatch on checkout {checkout_id}: paid ₦{paid:,.0f}, expected ₦{expected:,.0f}")
            return {"ok": True, "status": "mismatch", "paid": paid, "expected": expected,
                    "staff_message": f"Customer paid ₦{paid:,.0f} but the order is ₦{expected:,.0f}. "
                                     "Flagged for the manager. Don't release the phone."}
        store.save(checkout_id, status="paid")
        return {"ok": True, "status": "verified", "paid": paid, "amount_checked": paid is not None}
    if status in FAILED:
        return {"ok": True, "status": "failed", "staff_message": "This payment didn't go through. I can create a fresh link."}
    return {"ok": True, "status": "pending", "bumpa_status": status or "unknown",
            "staff_message": "Payment isn't confirmed yet. It can take a few minutes."}


@mcp.tool()
@safe
def finalize_order(checkout_id: str) -> dict:
    """Finalize a VERIFIED checkout into a Bumpa order and confirm it exists. Safe to call twice."""
    order = store.get(checkout_id)
    if not order:
        return fail("unknown_checkout", "I don't have a record of that order.")
    if order["status"] == "finalized":  # idempotent: never create a second order
        return {"ok": True, "order_id": order["bumpa_order_id"], "already_finalized": True}
    # Enforced in code, not just in the prompt. "unconfirmed" = Bumpa finalized but the order wasn't visible yet;
    # retrying is safe because Bumpa's finalize is idempotent after completion.
    if order["status"] not in ("paid", "unconfirmed"):
        return fail("payment_not_verified", "I can't record this order until the payment is verified in Bumpa.")
    if not store.claim(checkout_id, ("paid", "unconfirmed"), "finalizing"):  # only one concurrent caller proceeds
        return fail("finalize_in_progress", "This order is already being recorded. Check again in a moment.")
    try:
        # Docs: an empty body works once payment is confirmed on Bumpa's side. Pending payment -> 422.
        body, _ = bumpa.call("finalize_checkout", path_params={"checkout_id": checkout_id},
                             cart_token=order["cart_token"], json={})
    except BumpaError as e:
        store.save(checkout_id, status=order["status"])  # release the claim so staff can retry
        return bumpa_fail(e, "record the order")
    except Exception:
        store.save(checkout_id, status=order["status"])
        raise

    # VERIFY response path
    order_id = pick(body, "data.order.id", "data.order_id", "order_id", "data.id") or order["bumpa_order_id"]
    reference = order["payment_reference"]
    # Confirm on the merchant side (explicit location_id) that the order really landed.
    found = None
    search = reference or order_id
    for attempt in range(2 if search else 0):
        try:
            orders, _ = bumpa.call("list_orders", params={"search": search})
            # Docs: response is {"success": true, "orders": <paginator>}. VERIFY the paginator's list key.
            for o in pick(orders, "orders.data", "orders", "data.orders", "data", default=[]) or []:
                if not isinstance(o, dict):
                    continue
                o_ref = pick(o, "payment_reference", "reference")
                if (order_id and str(pick(o, "id")) == str(order_id)) or (reference and o_ref == reference):
                    found = o
                    break
        except BumpaError as e:
            log.warning("list_orders failed: %s", e)
        if found:
            break
        time.sleep(2)

    if not found:
        store.save(checkout_id, status="unconfirmed", bumpa_order_id=str(order_id) if order_id else None)
        store.add_flag(checkout_id, "order_not_found", f"finalize returned {order_id}, not visible in list_orders")
        _alert(f"Paid order not visible in Bumpa: checkout {checkout_id}")
        return fail("order_not_visible", "Payment is confirmed but I can't see the order in Bumpa yet. "
                    "I've flagged it; calling finalize again later will re-check.", order_id=order_id)

    store.save(checkout_id, status="finalized", bumpa_order_id=str(order_id or pick(found, "id")))
    return {"ok": True, "order_id": order_id or pick(found, "id"), "total": order["expected_total"]}


@mcp.tool()
@safe
def record_imei(checkout_id: str, imei: str) -> dict:
    """Attach the IMEI of the unit handed to the customer. Validates length and checksum."""
    digits = "".join(c for c in imei if c.isdigit())
    if len(digits) != 15 or not _luhn(digits):
        return fail("invalid_imei", "That IMEI doesn't look right. It should be 15 digits (dial *#06# on the phone).")
    order = store.get(checkout_id)
    if not order:
        return fail("unknown_checkout", "I don't have a record of that order.")
    if order["status"] != "finalized":
        return fail("order_not_finalized", "Record the IMEI after the order is finalized in Bumpa.")
    other = store.imei_used(digits, checkout_id)
    if other:
        store.add_flag(checkout_id, "duplicate_imei", f"IMEI {digits} already recorded on checkout {other}")
        _alert(f"Duplicate IMEI {digits}: checkouts {checkout_id} and {other}")
        return fail("duplicate_imei", "That IMEI is already recorded on another order. Flagged for the manager; "
                    "don't release the phone.")
    # The Postman collection has no order-note route, so the IMEI lives only in our store for now.
    store.save(checkout_id, imei=digits)  # VERIFY: also push to a Bumpa order note if the API supports it
    return {"ok": True, "imei": digits}


@mcp.tool()
@safe
def flag_for_review(reason: str, details: str, checkout_id: str = "") -> dict:
    """Send an order to a human manager. Use for screenshot-only payment proof, amount mismatches,
    unusual discounts or bulk orders, or anything uncertain."""
    store.add_flag(checkout_id or None, reason, details)
    existing = store.get(checkout_id) if checkout_id else None
    # A finalized order stays finalized (so finalize stays idempotent); the flag record still holds the reason.
    if existing and existing["status"] not in ("finalized", "finalizing"):
        store.save(checkout_id, status="flagged")
    _alert(f"Flagged for review ({reason}): {details}")
    return {"ok": True, "staff_message": "I've flagged this for the manager. Don't release the phone until they confirm."}


@mcp.tool()
@safe
def daily_summary() -> dict:
    """Today's orders for the owner: recorded, awaiting payment, flagged, missing IMEI."""
    start = dt.datetime.combine(dt.date.today(), dt.time.min).timestamp()
    orders, flags = store.since(start)
    done = [o for o in orders if o["status"] == "finalized"]
    return {"ok": True,
            "recorded": len(done), "recorded_value": sum(o["expected_total"] or 0 for o in done),
            "awaiting_payment": sum(o["status"] == "link_sent" for o in orders),
            "flagged": [{"reason": f["reason"], "details": f["details"]} for f in flags],
            "missing_imei": [o["bumpa_order_id"] for o in done if not o["imei"]]}


def _luhn(num):
    total = 0
    for i, d in enumerate(reversed(num)):
        n = int(d) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


# --- HTTP app with bearer auth, so only Chord can call the tools ---------------------------
def build_app():
    from starlette.responses import JSONResponse

    inner = mcp.streamable_http_app()
    token = os.getenv("MCP_AUTH_TOKEN")
    allow_open = os.getenv("ALLOW_NO_AUTH") == "1"  # local dev only
    if not token and not allow_open:
        log.error("MCP_AUTH_TOKEN is not set; refusing all /mcp requests (set ALLOW_NO_AUTH=1 for local dev)")

    async def app(scope, receive, send):
        if scope["type"] == "http" and scope["path"] == "/health":
            return await JSONResponse({"ok": True})(scope, receive, send)
        if scope["type"] == "http" and not allow_open:
            if not token:
                return await JSONResponse({"error": "server auth not configured"}, status_code=503)(scope, receive, send)
            auth = dict(scope["headers"]).get(b"authorization", b"").decode()
            if not hmac.compare_digest(auth.encode(), f"Bearer {token}".encode()):
                return await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
        return await inner(scope, receive, send)

    return app


app = build_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
