# Ogabassey Order Desk: project context for Claude Code

## What this is
A submission for the TSG Labs (Paystack) build exercise. Role: Technical Product Manager. We're building a Chord teammate that runs on WhatsApp and does one job end to end:

Ogabassey (a Lagos phone retailer) sales staff paste a customer's WhatsApp order chat → the teammate extracts the order → staff confirm → it creates a Bumpa cart and checkout → it gets a Paystack payment link via Bumpa → it verifies payment through Bumpa (never from a screenshot) → it finalizes the order and confirms it exists in Bumpa → it records the phone's IMEI.

Graders weight integration and payment/merchant systems most heavily, so real API calls with honest error handling matter more than features.

## Repo layout
```
CLAUDE.md                          this file
FIELD_NOTES.md                     running log of build/deploy problems (most important deliverable)
skills/ogabassey-order-desk.md     Chord skill file (business context, workflow, rules)   [not yet in this folder]
mcp-server/                        [currently flat in the repo root]
  server.py    FastMCP tool server (8 tools), bearer auth, /health
  bumpa.py     Bumpa API client; ALL endpoint paths and assumed response fields live here
  store.py     Postgres order state (cart tokens stay server-side)
  render.yaml, requirements.txt, .env.example, README.md
```

## Stack
Python 3.11+, the `mcp` SDK pinned `<2` (v2 renamed FastMCP to MCPServer; don't upgrade), httpx, uvicorn, psycopg (Postgres). Hosted on Render. Chord connects to it as a remote MCP server over streamable HTTP at `/mcp`, with `Authorization: Bearer $MCP_AUTH_TOKEN`.

## Bumpa API (staging)
- Base: `https://api.bumpa.xyz/api/commerce/v1`. Docs: https://docs.bumpa.io
- Public key (`X-Api-Key`) for catalog, cart and checkout. Secret key for merchant orders and analytics.
- Guest cart and checkout need `X-Cart-Token`, returned after cart creation.
- Merchant routes are location-scoped. ALWAYS pass `location_id` (it silently falls back to the default otherwise).
- There is NO merchant create-order endpoint. Orders come from: Create Cart → Add Cart Item → Create Checkout → Calculate Totals → Create Payment Intent → Finalize Checkout.
- Bumpa collects payment through its own Paystack integration. We can't verify on Paystack directly; we verify through Bumpa's checkout payment status.
- Lines marked `VERIFY` in `bumpa.py` and `server.py` are assumptions. Confirm each against the docs or a real staging response before removing the marker.

## Guarantees that must not be broken
1. `finalize_order` refuses unless `verify_payment` has set status `paid`. This is enforced in code.
2. `finalize_order` is idempotent: a second call returns the existing order and never creates another.
3. Cart tokens and API keys never appear in tool outputs.
4. A screenshot or bank alert is never treated as payment. Those go to `flag_for_review`.
5. Every tool returns `{"ok": bool, ...}`; failures include `error_code` and a plain `staff_message`.

## Rules for working in this repo
- Test keys and made-up data only. Never use live Bumpa keys, real customer data or real phone numbers.
- Never commit `.env` or any key. Check `.gitignore` before every commit.
- Ask before deploying, pushing to a remote, or running anything that writes to Bumpa staging.
- Log every real problem in `FIELD_NOTES.md` the moment it happens, using the template there: what happened, the exact error, how the cause was found, the fix, what Chord/Bumpa should change, and time lost. Short and specific. Don't invent or embellish entries.
- If something blocks progress for more than ~20 minutes, stop and tell me rather than working around it silently.
- Keep changes small and explain them in a sentence or two.

## Current status
Done: skill file draft; MCP server with 8 tools; local tests passed (tool listing over HTTP, 401 without token, payment guard, idempotent finalize, IMEI Luhn check). Not yet tested against real Bumpa: every network call failed in the original sandbox (no internet).
