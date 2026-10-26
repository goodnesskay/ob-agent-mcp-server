# Ogabassey Order Desk: MCP server

Tools for the Chord teammate (see [skills/ogabassey-order-desk.md](skills/ogabassey-order-desk.md)). Talks to Bumpa **staging** only, with test keys.

Live: https://ob-agent-mcp-server.onrender.com (MCP endpoint `/mcp`, health `/health`)
Repo: https://github.com/goodnesskay/ob-agent-mcp-server

## Tools
`find_product`, `create_order_draft`, `create_payment_link`, `verify_payment`, `finalize_order`, `record_imei`, `flag_for_review`, `daily_summary`. Every tool returns `{"ok": bool, ...}`; failures include `error_code` and a plain `staff_message`.

## Environment variables
| Variable | Required | Value / notes |
|---|---|---|
| `BUMPA_BASE_URL` | yes | `https://staging.bumpa.xyz/api/commerce/v1` (not `api.bumpa.xyz`, which 404s) |
| `BUMPA_PUBLIC_KEY` | yes | Bumpa `pk_test_...` key (catalog, cart, checkout) |
| `BUMPA_SECRET_KEY` | yes | Bumpa `sk_test_...` key (merchant orders) |
| `BUMPA_LOCATION_ID` | recommended | Staging store location: `429000059`. If unset, Bumpa uses the store default |
| `BUMPA_SHIPPING_METHOD_ID` | yes* | Staging "Pick Up" method: `429000151` (₦0). Checkout fails without a fulfillment type |
| `BUMPA_PICKUP_LOCATION_ID` | no* | Alternative to the above; set only one of the two |
| `MCP_AUTH_TOKEN` | yes | Long random string. Chord sends it as `Authorization: Bearer <token>`. The server refuses `/mcp` without it |
| `DATABASE_URL` | yes | Postgres connection string (Render Postgres: use the external URL) |
| `ALERT_WEBHOOK_URL` | no | Webhook that receives flagged-order alerts |
| `ALLOW_NO_AUTH` | no | `1` skips bearer auth. Local dev only |

\* Find a store's shipping methods with `POST /shipping-options` (needs a cart); see `FIELD_NOTES.md`.

## Run locally
Needs Python 3.10+ (the `mcp` SDK does not install on 3.9).

    python3.12 -m venv .venv && . .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env   # fill in the keys and DATABASE_URL; the server loads .env itself
    python server.py       # http://localhost:8000/mcp  (health: /health)

## Deploy (Render)
1. Push to GitHub and create a Render web service from `render.yaml` (build `pip install -r requirements.txt`, start `python server.py`).
2. Set the environment variables above in the Render dashboard. `render.yaml` marks the secrets `sync: false`, so Render does not fill them in.
3. In Chord, add `https://ob-agent-mcp-server.onrender.com/mcp` as a remote MCP server with the header `Authorization: Bearer <MCP_AUTH_TOKEN>`.

Check a deploy without writing to Bumpa: `/health` returns 200, `/mcp` without a token returns 401, and `tools/list` with the token lists 8 tools.

## Behaviour to know about
- `create_order_draft` needs `customer_email`: Bumpa will not create a payment link without it.
- One product line per draft. A chat with several different phones needs one draft per phone.
- Fulfillment uses the configured shipping method. The delivery address is stored in our database but not sent to Bumpa.
- Payment is verified only through Bumpa's checkout (`payment_intent.status = succeeded`). `finalize_order` refuses otherwise and is idempotent.
- The IMEI is stored in our Postgres only; Bumpa has no order-note route.
- Bumpa's published docs have no example responses; confirmed response shapes and every staging quirk are in `FIELD_NOTES.md`. Remaining assumptions are marked `VERIFY` in `bumpa.py` and `server.py`.
