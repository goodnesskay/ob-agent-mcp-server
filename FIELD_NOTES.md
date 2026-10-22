# Field notes

Running log of real build/deploy problems. One entry per problem, written when it happens. No invented entries.

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
