# Production (USER bot) deployment checklist

Use this when deploying the **same codebase** to production. This does **not** replace your `.env` — copy variables manually and never commit secrets.

## Identity & environment

1. Set **`ENVIRONMENT=production`** (or `prod`) in `.env` on the server.
2. Set **`BOT_TOKEN_PROD`** to the **production** bot token from @BotFather (do not reuse dev token).
3. Set **`WEBHOOK_URL`** to your HTTPS webhook URL (required when not in dev).
4. Set **`ADMIN_IDS`** to comma-separated Telegram user IDs (production admins).

## Database (do not overwrite)

- Production uses **`data/behavebot_prod.db`** (see `config.py`).
- **Do not** replace this file with a dev DB unless you intend a full data migration.
- On first start after code update, **`init_db()`** adds **new tables only** (e.g. `payments`, `support_tickets`) if missing — existing rows remain.

## Secrets (never in Git)

- **RPC URLs** (`SOL_RPC`, `BNB_RPC`, `BASE_RPC`) — set in `.env` on the server.
- **`PAYMENT_BASE_USDC_WALLET`** — optional; if unset, default in `config.py` applies.

## Payment flow (post-migration UX)

1. Plan picker → user selects Monthly / Yearly / Lifetime.  
2. Screen shows **wallet + instructions** (`PAYMENT_BASE_USDC_WALLET` from config / env).  
3. User sends **TX hash** in chat.  
4. Admin approves/rejects via **Admin Panel → Pending Payments** (no `/admin_payments` in the public command menu).

## Post-deploy smoke test

- `/start` → main menu  
- Premium → Unlock Premium → plan → TX → pending message  
- Settings → Contact Support (end-to-end)  
- Admin → **Report CS**, **Pending Payments** (as admin user)

---

**Do not** commit `.env`. Use `.env.example` only as a template.
