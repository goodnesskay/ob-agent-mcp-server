"""Thin Bumpa Commerce API client.

Every endpoint path and response field the agent depends on is declared here,
so matching the code to Bumpa's docs is a one-file job. Anything marked VERIFY
is an assumption to check against https://docs.bumpa.io before relying on it.
The docs list routes and request bodies but no example responses, so every response
field path (the pick(...) calls) is unconfirmed until seen in a real staging response.
"""
import os
import time
import httpx

BASE_URL = os.getenv("BUMPA_BASE_URL", "https://api.bumpa.xyz/api/commerce/v1")  # staging
PUBLIC_KEY = os.getenv("BUMPA_PUBLIC_KEY", "")
SECRET_KEY = os.getenv("BUMPA_SECRET_KEY", "")
LOCATION_ID = os.getenv("BUMPA_LOCATION_ID", "")  # always sent: merchant routes silently fall back to default without it

# Paths confirmed against the Bumpa Postman collection (docs.bumpa.io) on 2026-10-22.
ENDPOINTS = {
    "list_products":         ("GET",   "/products"),
    "create_cart":           ("POST",  "/carts"),
    "add_cart_item":         ("POST",  "/carts/items"),
    "create_checkout":       ("POST",  "/checkouts"),
    "calculate_totals":      ("POST",  "/checkouts/{checkout_id}/calculate-totals"),
    "create_payment_intent": ("POST",  "/checkouts/{checkout_id}/payment-intent"),
    "get_checkout":          ("GET",   "/checkouts/{checkout_id}"),
    "finalize_checkout":     ("POST",  "/checkouts/{checkout_id}/finalize"),
    "list_orders":           ("GET",   "/orders"),
}
SECRET_ROUTES = {"list_orders"}  # merchant routes use the secret key; the rest use the public key
LOCATION_PARAM_ROUTES = {"list_products", "list_orders"}  # take location_id as a query param


def location_id():
    """Numeric when possible: the docs send location_id as a JSON number in bodies."""
    return int(LOCATION_ID) if LOCATION_ID.isdigit() else LOCATION_ID


class BumpaError(Exception):
    """kind: auth | not_found | bad_request | timeout | server | unexpected"""

    def __init__(self, kind, message, status=None, body=None):
        super().__init__(message)
        self.kind, self.status, self.body = kind, status, body


def pick(data, *paths, default=None):
    """Return the first value found at any dotted path. Absorbs response-shape uncertainty."""
    for path in paths:
        cur = data
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                cur = None
                break
        if cur is not None:
            return cur
    return default


def call(name, *, path_params=None, json=None, params=None, cart_token=None, retries=None):
    method, path = ENDPOINTS[name]
    url = BASE_URL + path.format(**(path_params or {}))
    headers = {
        "X-Api-Key": SECRET_KEY if name in SECRET_ROUTES else PUBLIC_KEY,
        "Accept": "application/json",
    }
    if cart_token:
        headers["X-Cart-Token"] = cart_token
    params = dict(params or {})
    if name in LOCATION_PARAM_ROUTES and LOCATION_ID:
        params.setdefault("location_id", LOCATION_ID)

    # Retry reads by default; writes only when the caller opts in.
    attempts = 1 + (retries if retries is not None else (1 if method == "GET" else 0))
    last = None
    for attempt in range(attempts):
        try:
            r = httpx.request(method, url, headers=headers, json=json, params=params, timeout=20)
        except httpx.TimeoutException:
            last = BumpaError("timeout", f"Bumpa timed out on {name}")
        except httpx.HTTPError as e:
            last = BumpaError("server", f"Could not reach Bumpa on {name}: {e}")
        else:
            body = _json(r)
            if r.status_code < 300:
                return body, r.headers
            if r.status_code in (401, 403):
                raise BumpaError("auth", f"Bumpa rejected the API key on {name}", r.status_code, body)
            if r.status_code == 404:
                raise BumpaError("not_found", f"Bumpa returned 404 on {name}", r.status_code, body)
            if 400 <= r.status_code < 500:
                msg = pick(body, "message", "error.message", "error", default=r.text[:300])
                raise BumpaError("bad_request", f"Bumpa refused {name}: {msg}", r.status_code, body)
            last = BumpaError("server", f"Bumpa error {r.status_code} on {name}", r.status_code, body)
        if attempt < attempts - 1:
            time.sleep(1.5)
    raise last


def _json(r):
    try:
        return r.json()
    except ValueError:
        return {"raw": r.text[:500]}
