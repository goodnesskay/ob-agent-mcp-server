# Ogabassey Order Desk: MCP server

Tools for the Chord teammate. Talks to Bumpa staging only.

## Run locally
    python -m venv .venv && . .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env   # fill in Bumpa staging keys, then export them
    python server.py       # MCP endpoint: http://localhost:8000/mcp, health: /health

## Deploy (Render)
Push this folder to GitHub, create a Render Blueprint from `render.yaml`, add the Bumpa keys.
Register `https://<your-app>.onrender.com/mcp` in Chord as an MCP server with header
`Authorization: Bearer <MCP_AUTH_TOKEN>`.

## Before first real run
Endpoint paths and request bodies now match the Bumpa docs. Response field names do not:
the docs have no example responses, so check every line marked VERIFY (the `pick(...)` paths
and the payment statuses at the top of `server.py`) against a real staging response.
Set ONE of `BUMPA_PICKUP_LOCATION_ID` / `BUMPA_SHIPPING_METHOD_ID`, and `MCP_AUTH_TOKEN`
(the server refuses `/mcp` without it; `ALLOW_NO_AUTH=1` is for local dev only).
`create_order_draft` now requires `customer_email` (Bumpa won't create a payment link without it).
Order state lives in Postgres (`DATABASE_URL`); set it in the Render dashboard (a Render Postgres external connection string).
