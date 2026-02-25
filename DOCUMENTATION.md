# BehaveBot — Full Project Documentation

---

## Executive Summary (1 page)

**BehaveBot** is a Telegram bot that records user trading *behavior* (emotions, reasons, risk perception) around token positions without executing trades or connecting wallets. It uses **aiogram 3.13**, **SQLite**, and the **DexScreener API** to fetch token data. The bot is strictly observational: it does not give signals, trade, or connect to any wallet.

**Core value:** "Focus on your behavior, not the market."

**Technical stack:** Python 3.12, aiogram 3.13.1, aiosqlite, aiohttp, python-dotenv. Single-process polling; no webhooks. State is per-user (FSM + in-memory pending token). Database: two tables (`trades`, `feedback`); trades support open/close lifecycle, questionnaire (emotion, reason, category, risk on open; emotion, reason, discipline on close), and optional marking as invalid (excluded from stats).

**Architecture:** Flat handler modules (start, guide, token, open_position, close_position, stats, feedback, misc) mounted on one Dispatcher; **token router is last** so FSM handlers get text first when user is in "Other" free-text states. No dependency injection; config and DB are imported where needed. Duplicate-open protection is DB-backed (one open trade per user per token); pending token and token cache are process-local dicts.

**Gaps and risks:** Slash commands and menu buttons duplicate logic (separate handlers that do the same thing). No explicit /start FSM clear (only cancel and back_home clear state). ADMIN_IDS is loaded but unused. No retries or backoff on DexScreener. Chart/image generation is not implemented (chart_url is stored but not rendered). Feedback is stored with no admin notification. Another engineer could rebuild the bot from this document plus the codebase.

---

# 1. Product Identity

## 1.1 Bot Name
**BehaveBot**

## 1.2 Tagline
"Focus on your behavior, not the market."

## 1.3 Mission
Record how users trade, why they trade, and what patterns lead to profit or loss—without executing any trade or connecting any wallet.

## 1.4 Core Philosophy
- The market does not make you lose money; your decisions do.
- Self-awareness (emotions, reasons, discipline) is the lever.
- The bot is a behavioral log and statistics tool, not a trading or signal tool.

## 1.5 What It DOES
- Accepts token contract addresses (CA).
- Fetches token data (price, mcap, liquidity, volume, age) from DexScreener.
- Lets users "open" and "close" positions as *records* (no real trades).
- Captures at open: emotion, reason, token category, risk perception (and optional free-text notes).
- Captures at close: close price (from API or last open price), duration, PnL %, exit emotion, exit reason, discipline (plan followed or not).
- Stores feedback (text and/or image) in DB and filesystem.
- Computes statistics on *valid* closed trades: wins/losses, emotion vs result, time buckets (3h UTC), token category vs result.
- Allows marking trades as invalid (excluded from stats, still stored).
- Provides main menu (Guide, My Stats, Current Positions, Command List, Premium, Feedback) and slash commands.

## 1.6 What It DOES NOT Do
- Does not connect to any wallet.
- Does not execute trades.
- Does not give trading signals.
- Does not generate or send chart images (chart_url is fetched but not used in UI).
- Does not notify admins of feedback (only storage).

## 1.7 Target User
Retail users who trade (or consider trading) tokens and want to reflect on their behavior and patterns.

## 1.8 Psychological Positioning
Educational and reflective: the bot positions itself as a mirror for decision-making, not as a market or alpha source.

---

# 2. User Experience Flow

## 2.1 /start Flow
1. User sends `/start`.
2. Handler: `cmd_start` in `bot/handlers/start.py`.
3. Bot sends **WELCOME** text and **ReplyKeyboardMarkup** with 6 buttons:
   - Row 1: 📖 Guide | 📊 My Stats  
   - Row 2: 📈 Current Positions  
   - Row 3: 🧭 Command List | 💎 Premium  
   - Row 4: 📨 Feedback  
4. No FSM state is set; no inline keyboard. Reply keyboard is persistent (`is_persistent=True`).
5. **Note:** The code does *not* explicitly call `state.clear()` on `/start`. If the user was in an FSM, that state can remain until they use /cancel or Back to Menu.

## 2.2 Guide Flow
- **Entry:** User taps "📖 Guide" (reply) or sends `/guide` or taps inline "Guide" (if any) → callback `guide`.
- **Button:** `menu_guide` (F.text == "📖 Guide") or `cmd_guide` (Command("guide")) → both send GUIDE text + `kb_back_to_menu()` (single inline: "⬅ Back to Menu").
- **Callback:** `show_guide` (F.data == "guide") → edits message to GUIDE + `kb_back_to_menu()`.
- **Exit:** User taps "⬅ Back to Menu" → `back_home`: state cleared, pending token cleared, message edited to WELCOME + `kb_empty()`. Reply keyboard remains (it is chat-level).

## 2.3 Send CA (Contract Address) Flow
1. User sends a text message of length ≥ 20 that looks like a CA (0x + 40 hex or 40 hex).
2. **Routing:** Handled by `token` router's `on_text` only if:
   - No FSM state, or
   - FSM state is not a "free-text" state (emotion_note, reason_note, category_note for open; emotion_note, reason_note for close; reason_note for mark invalid), or
   - FSM state is one of those but token handler returns without replying (so FSM handler can consume the message).
3. If state is another FSM state (e.g. emotion, reason, risk): bot replies "Finish this step or use /cancel to reset."
4. If text length < 20: bot replies GUIDE_RANDOM ("To get started, send a token contract address (0x...). Or use the menu.") + `kb_back_to_menu()`.
5. **Fetch:** CA normalized (lowercase, 0x prefix). If cached (45s TTL), use cache; else send "Fetching latest data…", call DexScreener, delete loading msg, cache result.
6. **Same token already open:** If user already has an open trade for this token → message "You already have an open position for this token. Close it first before opening again." Pending token cleared.
7. **Other open positions:** If user has other open positions → list them (symbol + minutes) + "Token: {name} (${symbol}). Open new position?" + `kb_token_preview()` (🔄 Refresh | ✅ Open Position | ❌ Cancel).
8. **Previously traded same token:** If user has a closed trade for this token → "You traded {symbol} before. Previous result: ±X.X%. Token: … Open new position?" + same preview keyboard.
9. **First time token:** Token card (name, symbol, price, mcap, liquidity, volume 1h, age) + "Do you want to open a position?" + `kb_token_preview()`.
10. **Refresh:** Callback `token_refresh` re-fetches token for current pending CA and updates the same message.
11. **Cancel:** Callback `token_cancel` clears pending, clears state, edits message to WELCOME + `kb_empty()`.

## 2.4 Open Position Flow
1. User taps "✅ Open Position" (callback `open_position`).
2. Handler in `open_position.py`: `start_open_position`.
3. **Pre-check:** Pending token must exist; else "Please send a token contract address first."
4. **Re-fetch:** Message edited to "Fetching latest data…"; `fetch_token_data(pending.token_address)`; on failure, show error + previous token card + `kb_token_preview()` and return.
5. **Duplicate check:** `get_open_trade_for_token(user_id, token_address)`; if found, "You already have an open position for this token."
6. **Create trade row:** INSERT into `trades` with open_time=now, open_price, mcap_open, close_time=NULL, status='valid', emotion/reason/category/risk empty. `trade_id` from last_insert_rowid.
7. Pending token cleared. FSM data: trade_id, token_address, token_symbol. State → `OpenPositionStates.emotion`.
8. **Q1 Emotion:** "What was your emotion when opening this position?" + buttons (FOMO, Calm, Fear, Confident, Greedy, Revenge, Other ✍️). If "Other" → state emotion_note, ask "Please write your emotion:" (no inline keyboard).
9. **Q2 Reason:** "Why did you open this trade?" (Following Twitter, Chart setup, Friend signal, Pump chase, Plan, Other ✍️). Other → reason_note + free text.
10. **Q3 Category:** Meme, AI, DeFi, Gaming, NFT, Other ✍️. Other → category_note + free text.
11. **Q4 Risk:** Low / Medium / High / Yolo.
12. On risk chosen: UPDATE trades SET emotion_open, emotion_open_note, reason_open, reason_open_note, token_category, token_category_note, risk_level WHERE trade_id. State cleared. Message: "✅ Trade is now being tracked. Press CLOSE POSITION when you exit." + inline "Close Position" with callback `close_position:{trade_id}`.

## 2.5 Close Position Flow
1. Entry: User taps "Close Position" from tracked message or from Current Positions → position detail → "✅ Close Position" (callback `close_position:{trade_id}`).
2. Handler in `close_position.py`: load trade by id and user_id; must exist and close_time IS NULL.
3. **Close snapshot:** Fetch current price from DexScreener (or use open_price if fetch fails). close_time = now. duration_mins = (close_time - open_time) in minutes. PnL % = (close_price - open_price) / open_price * 100.
4. FSM data: trade_id, token_symbol, open_price, close_price, close_time (iso), mcap_close, duration_mins. State → ClosePositionStates.emotion.
5. Show summary: "🔴 Position Closed: {symbol}. Open/Close/Result %/Duration. Now help me understand why you closed."
6. **Q5 Exit emotion:** Relief, Regret, Greedy, Fear, Confident, Other ✍️. Other → emotion_note + text.
7. **Q6 Exit reason:** Target hit, Stop loss, Market fear, Paper hands, Other ✍️. Other → reason_note + text.
8. **Q7 Discipline:** Yes / No / I had no plan.
9. On discipline: `update_trade_close(...)` (close_time, close_price, mcap_close, duration, emotion_close, reason_close, discipline). State cleared. Message: "✅ Trade recorded successfully." + View Report | Mark as Invalid | ⬅ Back to Menu.

## 2.6 Mark Invalid Flow
1. Entry: "Mark as Invalid" after close, or "🚫 Mark Invalid Token" from position detail (open or closed).
2. Callback `mark_invalid:{trade_id}`. FSM: invalid_trade_id = trade_id, state = MarkInvalidStates.confirm.
3. Message: "Mark this trade as invalid? It will be excluded from statistics but still saved." + Yes, mark invalid | Cancel.
4. Cancel (invalid_confirm:no): state cleared, message edited to WELCOME + kb_empty().
5. Yes: state → MarkInvalidStates.reason. "Reason:" + Forgot to close | Wrong token | Test trade | Other ✍️.
6. If Other: state → reason_note, "Please specify reason:", then on text: set_trade_invalid(trade_id, message.text).
7. Else: set_trade_invalid(trade_id, value). DB: UPDATE trades SET status='invalid', invalid_reason=? WHERE trade_id.
8. Confirmation message + kb_back_to_menu().

## 2.7 Stats Flow
- **Entry:** "📊 My Stats" (reply), `/mystats`, or callback `stats`.
- **Button/cmd:** Get `get_valid_trades_for_stats(user_id)` (valid + closed only), call `_build_stats(user_id, trades)`, send/edit text + kb_back_to_menu().
- **Callback:** Same: edit message to stats text + kb_back_to_menu().
- Content: see Statistics Engine below.

## 2.8 Feedback Flow
1. Entry: "📨 Feedback" (reply), `/feedback`, or callback `feedback`.
2. State → FeedbackStates.text. Message: "📨 Send your feedback (text and/or image):" + kb_back_to_menu().
3. On text: insert_feedback(user_id, text, None); state clear; "✅ Thank you! Your feedback has been saved." + kb_back_to_menu().
4. On photo (no caption): download to FEEDBACK_DIR, insert_feedback(user_id, None, path); same confirmation.
5. On photo with caption: insert_feedback(user_id, caption, path); same confirmation.

## 2.9 Current Positions Flow
- **Entry:** "📈 Current Positions" (reply) or `/positions`.
- Load `get_open_trades(user_id)`. If none: "You have no open positions." + kb_back_to_menu().
- Else: list "• {symbol} ({mins} min)" + "Tap a position:" + inline list of "📌 {symbol}" with callback `position_detail:{trade_id}` + "⬅ Back to Menu".
- **Position detail** (callback `position_detail:{trade_id}`): Show symbol, open price, duration. Buttons: ✅ Close Position, 🚫 Mark Invalid Token, ⬅ Back (callback `positions_list`).
- **positions_list:** Re-shows the list of open positions (same as above).

## 2.10 Command List & Premium
- **Command List:** Text list of /start, /guide, /mystats, /positions, /premium, /feedback, /commandlist, /cancel + kb_back_to_menu(). Triggered by "🧭 Command List" or `/commandlist`.
- **Premium:** Placeholder text "Premium features are coming soon. Focus on your behavior first." + kb_back_to_menu(). Triggered by "💎 Premium" or `/premium`.

---

# 3. Technical Architecture

## 3.1 Framework
- **aiogram 3.13.1** (async Telegram Bot API).
- **Polling:** `dp.start_polling(bot)`. No webhook.
- **Parse mode:** DefaultBotProperties(parse_mode=ParseMode.HTML). No Markdown.

## 3.2 Folder Structure
```
BehaveBotV1/
├── main.py                 # Entry: path fix, init_db, Bot, set_my_commands, Dispatcher, polling
├── config.py               # dotenv, BOT_TOKEN (required), ADMIN_IDS, DB_PATH, FEEDBACK_DIR, DEXSCREENER_BASE
├── requirements.txt
├── .env.example
├── bot/
│   ├── __init__.py
│   ├── database/
│   │   ├── __init__.py
│   │   ├── db.py           # SQLite connection, schema, CRUD
│   │   └── models.py       # Trade, Feedback dataclasses; to_row/from_row
│   ├── services/
│   │   ├── __init__.py
│   │   ├── dexscreener.py  # TokenData, fetch_token_data (DexScreener API)
│   │   └── state.py        # Pending token dict, token cache (45s TTL)
│   ├── states/
│   │   ├── __init__.py
│   │   ├── open_position.py   # OpenPositionStates
│   │   ├── close_position.py # ClosePositionStates
│   │   ├── mark_invalid.py    # MarkInvalidStates
│   │   └── feedback.py       # FeedbackStates
│   ├── keyboards/
│   │   ├── __init__.py
│   │   └── inline.py       # All Reply/Inline keyboards
│   └── handlers/
│       ├── __init__.py     # setup_routers() — token router last
│       ├── start.py        # /start, /cancel, back_home, menu + slash for Guide/Stats/Positions/CommandList/Premium/Feedback
│       ├── guide.py        # callback guide → GUIDE + Back
│       ├── token.py        # F.text (CA), token_refresh, token_cancel
│       ├── open_position.py # open_position, view_open_trades, emotion/reason/category/risk (open)
│       ├── close_position.py # close_position:{id}, emotion/reason/discipline (close)
│       ├── stats.py        # _build_stats, callback stats
│       ├── feedback.py     # callback feedback, FeedbackStates.text + text/photo handlers
│       └── misc.py         # view_past_trades, position_detail, positions_list, view_report, mark_invalid
```

## 3.3 Entry Point
- `main.py`: Adds project root to `sys.path`, loads config (raises if BOT_TOKEN missing), `asyncio.run(main())`. `main()`: init_db(), Bot with DefaultBotProperties(parse_mode=HTML), set_my_commands(8 commands), Dispatcher, setup_routers(), start_polling(bot). finally: close_db(), bot.session.close().

## 3.4 Dependency Injection
- None. Config and `get_db()` are imported and used directly. No container or factory.

## 3.5 Database Initialization
- `init_db()` in db.py: get_db() (creates dir and connection if needed), executes TRADES_SCHEMA and FEEDBACK_SCHEMA, then ALTER TABLE trades ADD COLUMN invalid_reason TEXT (ignored if already exists). Single global aiosqlite connection; row_factory = Row.

## 3.6 Token API Integration
- **Config:** DEXSCREENER_BASE from env (default: https://api.dexscreener.com/latest/dex/tokens).
- **dexscreener.py:** `fetch_token_data(token_address)` normalizes CA (0x + 40 hex lower), GET `{DEXSCREENER_BASE}/{ca}`, parse JSON. Pairs list required; prefer pair where baseToken.address == ca else first pair. Extract: priceUsd, liquidity (dict.usd or scalar), volume (h24 or scalar), fdv as mcap, pairCreatedAt/pairCreationTime for age string. Returns TokenData or None. Timeout 15s; any exception → None.

## 3.7 State Management Per User
- **FSM:** aiogram FSMContext (keyed by user_id and chat_id). Stored in memory (default FSM storage).
- **Pending token:** `_user_pending_token: dict[int, TokenData]` in state.py. Set when user sends CA and sees preview; cleared when they open position or cancel.
- **Token cache:** `_token_cache: dict[str, (TokenData, float)]` keyed by normalized CA; timestamp for 45s TTL. Used only in token handler for CA input to avoid duplicate API calls.

## 3.8 Open Trades Validation
- **Open trades:** `get_open_trades(user_id)` → SELECT WHERE user_id=? AND close_time IS NULL AND status='valid'.
- **Duplicate token:** Before creating a new trade, `get_open_trade_for_token(user_id, token_address)` is used. If not None, user cannot open again for that token.

## 3.9 Duplicate Token Prevention
- When user sends a CA: after fetch, code checks `has_same_open = any(t.token_address.lower() == td.token_address for t in open_trades)`. If true, message and clear pending.
- When user taps "Open Position": after re-fetch, `get_open_trade_for_token(user_id, pending.token_address)`; if found, abort.
- DB stores token_address in lowercase for comparisons.

## 3.10 Resuming After Restart
- Open trades are rows with close_time IS NULL. No in-memory "session" for open trades. After bot restart, user can go to "Current Positions" and see the same list from DB. Pending token and FSM are lost (in-memory). So: open positions persist; "preview" state (pending token) does not.

---

# 4. Database Schema

## 4.1 Table: trades
| Column | Type | Description |
|--------|------|-------------|
| trade_id | INTEGER PK AUTOINCREMENT | Unique trade record id. |
| user_id | INTEGER NOT NULL | Telegram user id. |
| token_address | TEXT NOT NULL | Contract address (normalized lower). |
| token_symbol | TEXT NOT NULL | e.g. BEAN. |
| open_time | TEXT NOT NULL | ISO datetime. |
| close_time | TEXT | ISO datetime when closed; NULL = open. |
| open_price | REAL NOT NULL | Price at open. |
| close_price | REAL | Price at close. |
| mcap_open | REAL | Market cap / FDV at open (optional). |
| mcap_close | REAL | At close (optional). |
| duration | REAL | Minutes (open→close). |
| emotion_open | TEXT | e.g. FOMO, Calm, Other. |
| emotion_open_note | TEXT | Free text if Other. |
| reason_open | TEXT | e.g. Chart setup, Plan. |
| reason_open_note | TEXT | Free text if Other. |
| token_category | TEXT | Meme, AI, DeFi, etc. |
| token_category_note | TEXT | Free text if Other. |
| risk_level | TEXT | Low/Medium/High/Yolo. |
| emotion_close | TEXT | Relief, Regret, etc. |
| emotion_close_note | TEXT | Free text if Other. |
| reason_close | TEXT | Target hit, Stop loss, etc. |
| reason_close_note | TEXT | Free text if Other. |
| discipline | TEXT | Yes/No/I had no plan. |
| status | TEXT NOT NULL DEFAULT 'valid' | 'valid' or 'invalid'. |
| invalid_reason | TEXT | Optional reason when status='invalid'. |

**Indexes:** idx_trades_user (user_id), idx_trades_user_token (user_id, token_address), idx_trades_status (status).

**Relationships:** None (single table). user_id references Telegram id only (no FK).

## 4.2 Table: feedback
| Column | Type | Description |
|--------|------|-------------|
| feedback_id | INTEGER PK AUTOINCREMENT | Unique id. |
| user_id | INTEGER NOT NULL | Telegram user id. |
| text | TEXT | Optional text. |
| image_path | TEXT | Optional path under FEEDBACK_DIR. |
| created_at | TEXT NOT NULL | ISO datetime. |

No indexes beyond PK.

## 4.3 Valid vs Invalid and Statistics
- **Valid trades:** status = 'valid'. For "open" list: close_time IS NULL. For stats: close_time IS NOT NULL.
- **Invalid:** status = 'invalid'. Excluded from get_open_trades (because status='valid' is required) and from get_valid_trades_for_stats. Row remains; invalid_reason can be set.
- **Mark invalid:** Can be called for open or closed trades; both set status='invalid'.

---

# 5. Trade Lifecycle (Detailed)

## 5.1 State Before Open
- User has no trade row for this token yet. Optional: pending TokenData in memory and optional token cache entry.

## 5.2 Snapshot Capture (Open)
- When user taps "Open Position": token data re-fetched; then Trade created with open_time=now (UTC), open_price from TokenData.price, mcap_open from TokenData.mcap. token_address and token_symbol from TokenData. close_time, close_price, mcap_close, duration, and all close-related fields NULL/empty. status='valid'.

## 5.3 Emotion / Reason / Category / Risk Capture
- Stored in FSM during OpenPositionStates; on risk selection, single UPDATE writes emotion_open, emotion_open_note, reason_open, reason_open_note, token_category, token_category_note, risk_level into the same trade row.

## 5.4 Close Snapshot
- On "Close Position": close_time = now (UTC). close_price = DexScreener current price or, on failure, trade.open_price. mcap_close from API if available. duration = (close_time - open_time) in minutes (integer).

## 5.5 PnL Calculation
- pnl_pct = (close_price - open_price) / open_price * 100. Used in close summary and in stats. Win: close_price >= open_price; loss otherwise.

## 5.6 Duration
- duration = (close_time - open_time).total_seconds() / 60, stored as float in DB; displayed as integer minutes.

## 5.7 Invalid Marking
- UPDATE trades SET status='invalid', invalid_reason=? WHERE trade_id. No deletion. Stats and open lists ignore invalid rows.

## 5.8 Data Flow Summary
1. User sends CA → fetch/cache → set_pending_token → show preview.
2. Open Position → re-fetch → insert_trade (open snapshot) → FSM Q1–Q4 → UPDATE trade with questionnaire → state clear, show Close Position button.
3. Close Position → load trade → fetch close price → FSM data → Q5–Q7 → update_trade_close (close snapshot + questionnaire) → state clear, show View Report / Mark Invalid / Back.

---

# 6. Statistics Engine

## 6.1 Data Source
- `get_valid_trades_for_stats(user_id)`: SELECT WHERE user_id=? AND status='valid' AND close_time IS NOT NULL, ORDER BY close_time DESC.

## 6.2 Win/Loss
- **Win:** close_price >= open_price (count). **Loss:** total - wins. No tie-break; equal price counts as win.

## 6.3 PnL Aggregation
- Per trade: pnl = (close_price - open_price) / open_price * 100. Used for emotion and category averages and for time buckets.

## 6.4 Emotion vs Result
- Group by emotion_open. For each emotion, list of PnL values. Average PnL = sum(pnls)/len(pnls). Display: "{emotion} → {count} trades → {avg:+.0f}%". Sorted by count descending. "Other" gets note "*Note: custom entry".

## 6.5 Time Buckets
- Per trade: close_time hour (UTC) → bucket = (hour // 3) * 3. All PnL values in same bucket concatenated. Best bucket: max by average PnL (empty = -999). Worst bucket: min by average PnL (empty = 999). Display: "Best Time: HH:00–HH+3:00 UTC → ±X%", "Worst Time: ...".

## 6.6 Category Performance
- Group by token_category; same as emotion: list of PnL, average, "{category} → {avg:+.0f}%". "Other" gets "*Note: custom".

## 6.7 Order of Sections in Output
- Total Trades, Wins, Losses → Emotion vs Result → Best Time → Worst Time → Token Category.

---

# 7. Error Handling & Edge Cases

## 7.1 User Sends Random Text
- If length < 20: GUIDE_RANDOM + kb_back_to_menu() (token handler, last router).
- If length >= 20 and not valid CA: still passed to fetch_token_data; normalization fails or API returns no pairs → TOKEN_FETCH_FAIL. No crash.

## 7.2 User Sends CA Mid-Questionnaire
- If in "free-text" FSM state (emotion_note, reason_note, category_note, etc.): token handler returns without replying; FSM handler gets the message (token router is last).
- If in other FSM state: "Finish this step or use /cancel to reset." (CA_WHILE_ANSWERING).

## 7.3 User Restarts Bot
- FSM and pending token lost. Open trades remain in DB. User can use Current Positions and continue (e.g. close). No explicit "resume" flow.

## 7.4 User Closes Without Open Trade
- "Close Position" with invalid/missing trade_id or trade not found or already closed → message "You have no open position to close. Send a token CA to open one."

## 7.5 API Failure
- DexScreener: fetch_token_data returns None on non-200, exception, or empty pairs. Open flow: error message + previous token card + Refresh. Token input: TOKEN_FETCH_FAIL. Close: close_price falls back to open_price.

## 7.6 DB Failure
- No try/except around DB calls in handlers. Connection is single global; init_db creates tables. If aiosqlite raises, the update will propagate and polling may continue depending on aiogram behavior.

## 7.7 Timeout
- aiohttp timeout 15s for DexScreener. No retries or backoff. No timeout on DB operations.

---

# 8. Security & Data Integrity

## 8.1 Input Validation
- CA: regex 0x[0-9a-fA-F]{40} or 40 hex; normalized to lowercase. No length limit on text feedback; stored as-is.
- trade_id from callbacks: int(callback.data.split(":")[1]); ValueError/IndexError caught in places (e.g. misc, close_position).

## 8.2 SQL Injection
- All queries use parameterized placeholders (?). No string formatting of user input into SQL.

## 8.3 Telegram ID
- user_id from message.from_user.id / callback.from_user.id. Used in DB and in-memory dicts. No verification that user_id matches a known list except ADMIN_IDS (which is loaded but not used anywhere in the code).

## 8.4 Race Conditions
- Two "Open Position" clicks in parallel could in theory insert two rows (no unique constraint on user_id+token_address for open trades). Duplicate check is in application code (get_open_trade_for_token) before insert. No DB-level unique constraint on (user_id, token_address) where close_time IS NULL.

## 8.5 Duplicate Trade Protection
- Application-level: before insert, get_open_trade_for_token; when displaying CA, has_same_open check. token_address compared in lower case.

---

# 9. Limitations

- **No /start FSM clear:** /start does not call state.clear(); only /cancel and back_home do.
- **Slash vs buttons:** Guide, Stats, Positions, Premium, Feedback, Command List have separate handlers for reply buttons vs slash commands; logic and text are duplicated, not a single shared function.
- **ADMIN_IDS unused:** Loaded and validated in config but never used (e.g. no admin-only commands or feedback routing).
- **Single DB connection:** One global aiosqlite connection; fine for single-process polling.
- **No retries:** DexScreener and DB have no retry/backoff.
- **No chart/image generation:** chart_url in TokenData and pair URL are not used to send images to the user.
- **Feedback to admin:** Feedback is only stored; no forward or notification to admins.
- **set_my_commands:** Uses "commandlist" (one word); user asked for /command_list in a different task; doc reflects current code.
- **FSM storage:** Default in-memory; not persistent across restarts.
- **Token cache:** Process-local; 45s TTL; no distributed cache.

---

# 10. Future Improvement Suggestions

- **PostgreSQL:** Replace aiosqlite with async PostgreSQL driver; add connection pool; optional read replicas for stats.
- **Analytics engine:** Precompute stats per user (materialized view or cron); expose via /mystats and optional daily digest.
- **Admin dashboard:** Web UI for feedback list, trade counts, invalid reasons; use ADMIN_IDS for auth.
- **Cloud deployment:** Run in container; use managed DB and secrets; optional webhook instead of polling for production scale.
- **AI behavior layer:** Optional pipeline that consumes trades (emotions, reasons, PnL) and produces insights or prompts; keep current bot as data collector.
- **Unify commands and buttons:** Single functions e.g. show_guide(msg_or_callback), show_stats(...), invoked from both Command and F.text and callback handlers.
- **Clear state on /start:** Explicit state.clear() in cmd_start for consistent UX.
- **Unique constraint:** (user_id, token_address) WHERE close_time IS NULL enforced in DB (e.g. partial unique index) to harden duplicate-open protection.

---

# 11. File Structure Overview

| Path | Purpose |
|------|--------|
| main.py | Entry, logging, Bot, set_my_commands, Dispatcher, polling, exit on ValueError |
| config.py | Env load, BOT_TOKEN required, ADMIN_IDS list, DB_PATH, FEEDBACK_DIR, DEXSCREENER_BASE |
| bot/database/db.py | get_db, close_db, init_db, insert_trade, update_trade_close, set_trade_invalid, get_open_trades, get_open_trade_for_token, get_last_closed_trade_for_token, get_trade_by_id, get_valid_trades_for_stats, insert_feedback |
| bot/database/models.py | Trade (to_row, from_row), Feedback dataclass |
| bot/services/dexscreener.py | TokenData, _normalize_ca, _safe_float, fetch_token_data |
| bot/services/state.py | Pending token get/set/clear, token cache get/set (45s TTL) |
| bot/states/*.py | OpenPositionStates, ClosePositionStates, MarkInvalidStates, FeedbackStates |
| bot/keyboards/inline.py | Main menu reply, back to menu, token preview, open/close/invalid keyboards, empty |
| bot/handlers/start.py | /start, back_home, /cancel, menu + slash for Guide/Stats/Positions/CommandList/Premium/Feedback |
| bot/handlers/guide.py | callback guide → GUIDE + Back |
| bot/handlers/token.py | on_text (CA flow), token_refresh, token_cancel; FSM skip for free-text states |
| bot/handlers/open_position.py | open_position, view_open_trades, Q1–Q4 (emotion, reason, category, risk) |
| bot/handlers/close_position.py | close_position:{id}, Q5–Q7 (emotion, reason, discipline), update_trade_close |
| bot/handlers/stats.py | _build_stats, callback stats |
| bot/handlers/feedback.py | callback feedback, FeedbackStates.text + text/photo handlers |
| bot/handlers/misc.py | view_past_trades, position_detail, positions_list, view_report, mark_invalid (confirm + reason) |
| bot/handlers/__init__.py | setup_routers; token_router included last |

---

# 12. Dependencies

- **aiogram==3.13.1** — Telegram Bot API (async, FSM, filters, keyboards).
- **aiohttp==3.10.10** — HTTP client for DexScreener.
- **aiosqlite==0.20.0** — Async SQLite.
- **python-dotenv==1.0.1** — .env loading.

---

# 13. Session Management Logic

- **No explicit "session" object.** User is identified by Telegram user_id (and chat_id in FSM).
- **FSM:** aiogram default storage (in-memory). State key includes user and chat. Cleared on /cancel and back_home; not cleared on /start.
- **Pending token:** One TokenData per user_id in a dict; overwritten on new CA; cleared on open or cancel.
- **Token cache:** Global by normalized CA; TTL 45s; shared by all users.

---

# 14. Callback & Command Handlers (Reference)

| Trigger | Handler | File |
|---------|---------|------|
| /start | cmd_start | start.py |
| /cancel | cmd_cancel | start.py |
| back_home | back_home | start.py |
| F.text == "📖 Guide" | menu_guide | start.py |
| Command("guide") | cmd_guide | start.py |
| F.data == "guide" | show_guide | guide.py |
| F.text == "📊 My Stats" | menu_stats | start.py |
| Command("mystats") | cmd_mystats | start.py |
| F.data == "stats" | show_stats | stats.py |
| F.text == "📈 Current Positions" | menu_positions | start.py |
| Command("positions") | cmd_positions | start.py |
| F.data == "positions_list" | positions_list | misc.py |
| F.data.startswith("position_detail:") | position_detail | misc.py |
| F.text == "🧭 Command List" | menu_command_list | start.py |
| Command("commandlist") | cmd_commandlist | start.py |
| F.text == "💎 Premium" | menu_premium | start.py |
| Command("premium") | cmd_premium | start.py |
| F.text == "📨 Feedback" | menu_feedback | start.py |
| Command("feedback") | cmd_feedback | start.py |
| F.data == "feedback" | start_feedback | feedback.py |
| F.text (generic) | on_text | token.py |
| F.data == "token_cancel" | token_cancel | token.py |
| F.data == "token_refresh" | token_refresh | token.py |
| F.data == "open_position" | start_open_position | open_position.py |
| F.data.startswith("emotion_open:") | emotion_open_cb | open_position.py |
| F.data.startswith("reason_open:") | reason_open_cb | open_position.py |
| F.data.startswith("category:") | category_cb | open_position.py |
| F.data.startswith("risk:") | risk_cb | open_position.py |
| F.data == "view_open_trades" | view_open_trades | open_position.py |
| F.data.startswith("close_position:") | start_close_position | close_position.py |
| F.data.startswith("emotion_close:") | emotion_close_cb | close_position.py |
| F.data.startswith("reason_close:") | reason_close_cb | close_position.py |
| F.data.startswith("discipline:") | discipline_cb | close_position.py |
| F.data.startswith("view_report:") | view_report | misc.py |
| F.data.startswith("mark_invalid:") | mark_invalid_start | misc.py |
| F.data.startswith("invalid_confirm:") | mark_invalid_confirm_cb | misc.py |
| F.data.startswith("invalid_reason:") | mark_invalid_reason_cb | misc.py |
| F.data == "view_past_trades" | view_past_trades | misc.py |

Message handlers for FSM (emotion_note, reason_note, category_note, reason_note for close, mark_invalid reason_note, FeedbackStates.text) are in open_position, close_position, misc, feedback respectively.

---

# 15. Architectural Critique

**Strengths**
- Clear separation: database, services, states, keyboards, handlers.
- Single source of truth for open/valid trades (DB); duplicate-open checks in both token and open_position.
- Parameterized SQL; no injection risk.
- Token router last so FSM free-text states work without being overridden by CA handler.
- Re-fetch on Open Position and optional cache reduce stale data.

**Weaknesses**
- **Duplicate handler logic:** Menu buttons and slash commands repeat the same content and keyboard in separate handlers; one shared function per feature would reduce drift and bugs.
- **/start does not clear FSM:** Users returning with /start can remain in an FSM state; only /cancel or Back to Menu clear it.
- **ADMIN_IDS unused:** Dead configuration; either use (e.g. feedback routing, admin commands) or remove.
- **No DB transaction across open + questionnaire:** Trade is inserted, then updated in risk_cb; if the update failed, the row would exist with empty questionnaire fields (no rollback).
- **Global DB connection:** Fine for one process; limits horizontal scaling without changing to a pool.
- **Error handling:** No retries for API/DB; no user-facing "something went wrong, try again" for generic exceptions.
- **set_my_commands:** Registers "commandlist" (one word); documentation and UX may expect "command_list" (underscore); Telegram commands cannot contain underscores in the command name, so "commandlist" is correct for Telegram.

**Honest assessment:** The codebase is maintainable and matches the stated product (behavior logging, no trading). The main improvements are unifying command/button handlers, clearing FSM on /start, and using or removing ADMIN_IDS. Statistics and trade lifecycle are consistent and traceable from DB to UI.

---

*End of documentation. Rebuild: implement DB schema, services (DexScreener + state), FSM states, keyboards, then handlers in the order given in setup_routers (token last), and main.py as entry with set_my_commands.*
