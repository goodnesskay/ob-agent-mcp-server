# Field notes

Running log of real build/deploy problems. One entry per problem, written when it happens. No invented entries.

> **Read this first: the Bumpa Commerce API is new and not yet stable.** This project is one of the first integrations to run against it, so several problems below are Bumpa-side (docs pointing at the wrong staging host, no example responses, undocumented status values, staging routes that 404 or 500) rather than mistakes in our code. Treat every Bumpa response shape and status word here as observed on staging on the dates given, not as a guaranteed contract, and re-check them if Bumpa ships a change. Entries say "What Chord/Bumpa should change" so the platform teams can use them as feedback.

## Template

### YYYY-MM-DD: short title
- **What happened:**
- **Exact error:**
- **How the cause was found:**
- **Fix:**
- **What Chord/Bumpa should change:**
- **Time lost:**

---

### 2026-10-22: Bumpa docs unreadable by plain fetch
- **What happened:** Tried to confirm endpoint paths on https://docs.bumpa.io. WebFetch and curl returned only the page title; the docs are a JavaScript-rendered Postman site.
- **Exact error:** WebFetch returned only "Bumpa API v1"; `curl https://docs.bumpa.io/llms.txt` and `/openapi.json` returned Postman's "Not found" HTML page.
- **How the cause was found:** Opened the page in a browser, saw it loads its content from `/api/collections/54114412/2sBXqDsNUN` in the network log, and downloaded that JSON directly.
- **Fix:** Parsed the collection to get the real routes and request bodies. The collection has no saved example responses, so response field names are still unconfirmed.
- **What Chord/Bumpa should change:** Bumpa: publish an OpenAPI file or `llms.txt` and include example responses in the collection. Chord: n/a.
- **Time lost:** A few minutes.

### 2026-10-22: Project folder was not its own git repo
- **What happened:** `ob-mcp-server-project/` had no `.git`, so git resolved to a parent repo (no commits) whose untracked files include a real `.env` and personal documents.
- **Exact error:** `fatal: your current branch 'master' does not have any commits yet` from the parent repo.
- **How the cause was found:** `git status` listed parent-directory files.
- **Fix:** `git init` inside the folder, branch `main`, `.gitignore` excluding `.env`.
- **What Chord/Bumpa should change:** n/a.
- **Time lost:** Negligible.

### 2026-10-22: Most assumed Bumpa endpoint paths were wrong
- **What happened:** Compared `bumpa.py` against the real route list. Singular `/cart`, `/checkout`, `/merchant/orders` and `/totals` do not exist; Bumpa uses `/carts`, `/checkouts`, `/orders` and `/calculate-totals`. Bodies also differed (`cart_id`, `product_variation_id`, `customer_context.email`, `location_id`).
- **Exact error:** None yet; found by reading the docs before any live call.
- **How the cause was found:** Parsed the Postman collection (see first entry).
- **Fix:** Updated paths and bodies. Response field names are still unconfirmed and stay marked VERIFY.
- **What Chord/Bumpa should change:** Bumpa: add example responses. Payment intent needs `customer_context.email`, which a WhatsApp order chat rarely has; the skill must ask for it.
- **Time lost:** None (caught before running).

### 2026-10-26: Deployed /mcp returns 421 "Invalid Host header"
- **What happened:** After deploying to Render, `/health` returned 200 and `/mcp` returned 401 without a token, but a request with a valid bearer token to `/mcp` returned 421.
- **Exact error:** `HTTP 421` with body `Invalid Host header` (from `https://ob-agent-mcp-server.onrender.com/mcp`).
- **How the cause was found:** The 401 check passed our auth layer, so the 421 had to come from the MCP SDK; its FastMCP enables DNS-rebinding protection with a localhost-only host allow-list by default.
- **Fix:** Pass `TransportSecuritySettings` with the Render hostname (`RENDER_EXTERNAL_HOSTNAME`) in `allowed_hosts`. Confirmed locally (Python 3.12, mcp 1.30: wrong Host -> 421, Render Host -> 200) and on Render after redeploy (tools/list and tool calls return 200).
- **What Chord/Bumpa should change:** Chord docs for remote MCP hosting should mention this default; the MCP SDK could document it next to the Render/hosted-deploy guidance.
- **Time lost:** About 20 minutes including setting up Python 3.12 locally (this Mac only had 3.9, which can't install the `mcp` SDK).

### 2026-10-26: Bumpa staging public commerce routes return 404; merchant routes return 500
- **What happened:** First real read-only calls to Bumpa staging with the provided test keys. The public catalog, cart and checkout routes do not resolve, and the merchant routes fail on Bumpa's database.
- **Exact error:** `GET https://api.bumpa.xyz/api/commerce/v1/products` (also `/carts`, `/checkouts/1`) -> `404 {"message":"The route api/commerce/v1/products could not be found.","exception":"...NotFoundHttpException"}`. `GET .../orders` and `.../analytics/summary` with the secret key -> `500 SQLSTATE[HY000] [1045] Access denied for user 'stacey'@'10.10.10.40' (using password: YES)`.
- **How the cause was found:** Called Bumpa directly with curl (read-only GETs) after `find_product` returned `bumpa_not_found`. The docs' staging environment uses the same host (`https://api.bumpa.xyz`), so it is not a wrong-host mistake on our side. `/api/products` returns 401 (so the host is alive), and the two 500s mean the API key was accepted and the database behind the merchant routes is rejecting Bumpa's own connection.
- **Fix:** None possible on our side yet. Waiting on Bumpa: confirm the staging host/path for the public commerce API and fix the staging database credentials.
- **What Chord/Bumpa should change:** Bumpa: the published staging collection points at routes that 404 on `api.bumpa.xyz`; the merchant routes 500 on a DB auth error. A health or "ping" route per API surface would make this obvious.
- **Time lost:** About 10 minutes.

### 2026-10-26: Resolved: Bumpa staging host is staging.bumpa.xyz, not api.bumpa.xyz
- **What happened:** The previous entry's 404/500 errors came from using the host in Bumpa's docs and Postman environment (`https://api.bumpa.xyz`). The working staging host is `https://staging.bumpa.xyz`.
- **Exact error:** n/a (see previous entry). With the new host: `GET /api/commerce/v1/products?limit=2` -> 200 (paginator: top-level `data` list, 2 products, `price` as a string, stock in `quantity`); `GET /api/commerce/v1/orders?limit=2` with the secret key -> 200 `{"success": true, "orders": {...paginator}}`; `GET /carts` without a token -> 404 `Cart not found`.
- **How the cause was found:** Tried the host the user supplied.
- **Fix:** Changed the default base URL to `https://staging.bumpa.xyz/api/commerce/v1` in `bumpa.py`, `.env.example`, `render.yaml`, `CLAUDE.md`. Render's `BUMPA_BASE_URL` must be updated by hand if it was set in the dashboard.
- **What Chord/Bumpa should change:** Bumpa: correct the staging URL in the docs overview and the BUMPA_STAGING Postman environment.
- **Time lost:** About 25 minutes in total across both entries.

### 2026-10-26: Empty BUMPA_LOCATION_ID sent as "" -> 422; checkout needs a fulfillment type
- **What happened:** First write test on staging. With `BUMPA_LOCATION_ID` unset we sent `"location_id": ""`, and later, with no fulfillment configured, Calculate Totals failed.
- **Exact error:** `create_cart` -> `422 The location id must be an integer.` Then `calculate_totals` -> `422 The type field is required.` Also `create_checkout` with `pickup_location_id` = the store location id -> `422 The selected pickup location is invalid for this store.`
- **How the cause was found:** Error messages from Bumpa; the cart response shows the store's default `location_id` (429000059). `POST /shipping-options` lists delivery methods; the store's "Pick Up" method is a manual shipping method (id 429000151, amount 0), not a pickup location.
- **Fix:** Omit `location_id` when unset (Bumpa then uses the store default). Set `BUMPA_LOCATION_ID` and `BUMPA_SHIPPING_METHOD_ID` and use `fulfillment_context {type: delivery, shipping_method_id}`. Full draft -> payment link flow then worked and returned a real Paystack test link.
- **What Chord/Bumpa should change:** Bumpa: the docs say location_id is "optional", but an empty string 422s, and there is no documented way to list pickup locations or shipping methods without a cart (only POST /shipping-options with a cart). The Postman collection should include example responses.
- **Time lost:** About 25 minutes.

Confirmed response shapes on staging (top-level, no `data` wrapper): Create Cart -> `{id (uuid), location_id, cart_token, ...}` (token is in the body, not a header); Create Checkout / Get Checkout -> `{id (int), order_id, total, payment_intent{status, amount, amount_minor, reference, authorization_url}, status}`. Unpaid: `payment_intent.status = "pending"`, checkout `status = "payment_pending"`. The status word after a successful payment is still unconfirmed.

### 2026-10-26: Paid order reported "not visible" because order search used the Paystack reference
- **What happened:** After a Paystack test payment, `verify_payment` stayed `pending` and then `finalize_order` returned `order_not_visible`, even though Bumpa had created and finalized the order.
- **Exact error:** (1) `verify_payment` returned `bumpa_status: "succeeded"` but status `pending`, because our PAID set lacked `succeeded`. (2) `finalize_order` returned `order_not_visible` (order id 12030): `GET /orders?search=12030sc1793000442419` returned 0 rows, while `?search=12030` returned the order (`payment_status: PAID`, `status: OPEN`).
- **How the cause was found:** Read the raw Get Checkout (`payment_intent.status = "succeeded"`, checkout `status = "payment_confirmed"`) and the raw order list with both search terms.
- **Fix:** Added `succeeded` to PAID; search merchant orders by order id first, reference as fallback. Retrying `finalize_order` then recovered from `unconfirmed`, returned the order, and a second call returned `already_finalized` without a new order. IMEI recorded after finalize.
- **What Chord/Bumpa should change:** Bumpa: document the payment status values (`payment_intent.status: pending|succeeded`, checkout `payment_pending|payment_confirmed`) and that order search does not match the Paystack reference. Two stale `order_not_found` flags from the failed attempts remain in the flags table.
- **Time lost:** About 10 minutes.

### 2026-10-26: Chord teammate fails on test case 5 ("screenshot instead of payment"); no logs to debug with
- **What happened:** Test cases 1 to 4 ran through the Chord teammate and our MCP server (order 4 finalized, IMEI recorded; order 5 got a payment link). Test case 5 (staff says the customer sent a transfer screenshot and asks to release the phone) failed twice in Chord. No request reached our MCP server.
- **Exact error:** Chord UI: `Couldn't reach Becca — try again`.
- **How the cause was found:** Not found yet. Our server is healthy (`/health` 200, a direct `flag_for_review` call succeeds in ~2s), and our database shows no verify, flag or finalize after order 5's link was created, so the failure is before our server. Chord has no place to view the teammate's run log, so we can't see what failed.
- **Fix:** None yet. Cause unconfirmed; do not assume it is the screenshot wording or an attached image until tested.
- **What Chord/Bumpa should change:** Chord: show a per-teammate run log or error detail; "couldn't reach" should say whether the model, the channel or a tool server failed.
- **Time lost:** Ongoing.

### 2026-10-26: Chord "WhatsApp connect failed": Wasender account API key not configured on Chord's side
- **What happened:** Tried to connect WhatsApp to the Chord teammate. The connect step failed with a missing-configuration error from Chord's backend.
- **Exact error:** `WhatsApp connect failed: chord.connector.whatsapp.wasender.account-api-key is not configured`
- **How the cause was found:** The error names a server-side property of Chord's WhatsApp connector (Wasender provider), not anything in our MCP server or Bumpa. Nothing we can set; our server received no request.
- **Fix:** None on our side. Reported to Chord (to do). Possibly related to the earlier "Couldn't reach Becca" failures (unconfirmed).
- **What Chord/Bumpa should change:** Chord: configure the Wasender account API key for the workspace/environment, or hide the WhatsApp connect option until it is; show a user-facing message instead of the raw property name.
- **Time lost:** Ongoing.
