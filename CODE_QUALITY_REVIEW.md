# Code Quality Review — interview-us-too

_Full-repo sweep, 7 parallel read-only audits (security, correctness ×2, billing/money, extension, tests, maintainability/deps, performance). No code was changed. Findings only._

Date: 2026-05-28 · Scope: backend (`server.py`, `billing.py`, `auth.py`, `models.py`, `database.py`, `config.py`, `mailer.py`, `analytics.py`), Chrome extension (`extension/*.js`), tests (`tests/*`), deps.

---

## Executive summary

**Overall health: functional but with several money-losing and data-exfiltration risks that should be fixed before any real traffic.** The code is readable, the ORM usage is safe from SQL injection, JWT handling is sound, and the test suite is genuinely good for a custom harness (~190 state-asserting tests). The serious problems cluster in three places: **Stripe webhook handling has no idempotency**, the **extension trusts any website** to repoint it, and the **async app blocks its own event loop** on nearly every request.

### Top 5 issues (fix these first)

1. **Stripe webhook has no idempotency / replay protection** — redelivered events double-grant sessions and double-credit referrers (real money + free product). `billing.py:128,228,245`.
2. **Any website can hijack the extension's token + server URL** — `interview-ace:connect` listener on `<all_urls>` with no origin check turns every screenshot/audio capture into an exfiltration channel. `extension/content.js:87`.
3. **Sync I/O blocks the event loop on every request** — sync SQLAlchemy, `stripe.*`, and `resend` calls inside `async def` handlers stall *all* concurrent users. `auth.py:74`, `billing.py` (all), `mailer.py`.
4. **`sessions_remaining` deduction is non-atomic and audio capture skips it entirely** — concurrent captures double-deduct; `/api/audio-capture` never deducts, so paid-out users get free audio analysis. `server.py:712,775,816`.
5. **CORS `allow_origins=["*"]` + no CSRF + cookie missing `Secure`** — cross-site reads/actions against cookie-auth routes. `server.py:60,314`.

### Cross-cutting themes
- **No idempotency anywhere money/credits move** (webhooks, referral credit, invoice deduction).
- **Race conditions from read-then-write without row locks** (sessions, trial start, referral apply).
- **Sync-on-async** is systemic, not a one-off.
- **Duplication breeds bugs** — the audio-capture gating bug is a direct result of copy-pasted capture logic.

---

## Findings — sorted by severity (deduplicated)

Severity: **B** blocker · **MA** major · **MI** minor · **N** nit. "Dims" = which audits flagged it.

| # | Sev | Area | File:line | Issue | Suggested fix |
|---|-----|------|-----------|-------|---------------|
| 1 | B | Billing | `billing.py:128,228,245` | Webhook has no event-id dedup; redelivered `checkout.session.completed` re-runs `sessions_remaining += 2/3` and re-credits referrers. Stripe redelivers routinely. | Persist `event["id"]` in a `ProcessedStripeEvent` table; return early if seen, inside the same txn. Fixes credit + session double-grant. |
| 2 | B | Billing | `billing.py:21-36,265-280` | Referral credit / one-time-purchase balance resync are non-idempotent; a redeliver or a crash between Stripe call and `db.commit()` permanently diverges DB counter from Stripe balance (in user's favour). | Same event-id dedup as #1; treat DB flag + Stripe call as one logical unit guarded by dedup. |
| 3 | B | Security/Ext | `extension/content.js:87-92,181-191` | `interview-ace:connect` (and hotkey/replay bridges) run on `<all_urls>` and write attacker-supplied `token`/`server_url` to storage with **no origin check** → any site repoints captures/audio to its own server. Background `onMessage` also does no sender validation. | Gate every page-bridge listener on the app origin; narrow `content_scripts.matches` + `host_permissions` from `<all_urls>` to the app origin; validate `sender.url` for state-changing messages. |
| 4 | B | Perf | `auth.py:61,74`; `server.py` pervasive | Sync SQLAlchemy (`db.query/commit`) runs on the event loop in every `async def` handler — incl. `get_user_by_token` on every extension call. Blocks all concurrent users. | Move to async SQLAlchemy (`AsyncSession`) or wrap DB blocks in `run_in_threadpool`. Enable WAL. |
| 5 | B | Perf | `billing.py` (all); `server.py:976,1012,1029,1067` | Synchronous `stripe.*` SDK called from async routes; webhook makes 3-5 serial blocking Stripe calls on the loop. | Wrap billing calls in `run_in_threadpool`; offload whole `handle_webhook_event`. |
| 6 | B | Perf | `mailer.py:19,69`; `server.py:353,370,1020,1040` | `resend` (sync `requests`) called inline from async register/cancel/feedback routes — blocks loop on every signup. | `run_in_threadpool` or fire-and-forget `BackgroundTasks` (response doesn't need email result). |
| 7 | B/MA | Security | `server.py:59-64,314,359` | `allow_origins=["*"]` while many routes use cookie auth; **no CSRF**; session cookie missing `Secure`. State-changing GETs (`/billing/checkout`, `/billing/portal`, `/auth/logout`). | Restrict CORS to app + extension origin; add CSRF tokens (or require Bearer) on state-changing POSTs; add `secure=True`; make mutations POST-only. |
| 8 | MA | Correctness | `server.py:712-726,775-789` | `sessions_remaining -= 1` is read-then-write with no row lock; two concurrent captures double-deduct and create duplicate active sessions. | Atomic `UPDATE ... SET sessions_remaining = sessions_remaining-1 WHERE sessions_remaining>0`, check rowcount. |
| 9 | MA | Correctness/Maint | `server.py:816-871` | `/api/audio-capture` omits the paid-session gating block that capture/text-capture have → paid users with 0 sessions get free audio analysis. Direct result of copy-paste duplication. | Extract `_consume_paid_session(db,user)` helper; call in all three endpoints. |
| 10 | MA | Correctness | `server.py:724-757,790-805` | Session deducted + `capture_id` incremented + "working" broadcast **before** the Anthropic stream; if the stream raises, user loses a session and dashboard hangs in "working" with no error event. | Decrement only on success (or refund on failure); broadcast `capture-error` in an except block (audio endpoint already does). |
| 11 | MA | Correctness | `server.py:1089` | `/stream` `async for msg in pubsub.listen()` never detects silent client disconnect → Redis pub/sub connection leaks per dead client; `finally` cleanup never runs. | Poll `request.is_disconnected()` / use `get_message(timeout=...)` loop or keepalives. |
| 12 | MA | Billing | `billing.py:155-181` | `trialing` → `unlimited` (full access during unpaid 7-day trial); `past_due`/`incomplete` fall through both branches, leaving user `unlimited` until a later event. | Confirm trial-access intent; add `past_due` to the downgrade branch; reconsider granting `unlimited` while unpaid. |
| 13 | MA | Billing | `billing.py:246-258` vs `164-176` | `sessions_pack` and `subscription` both consume the same `sub_credited` flag with sub-sized credit (300/500); a one-time pack purchase permanently consumes the subscription referral reward. | Confirm intent; use separate flags/amounts if pack ≠ sub. |
| 14 | MA | Billing | `billing.py:152,203,294` | Missing-user webhook handlers `return` with HTTP 200 → money taken, nothing granted, Stripe won't retry. | Raise non-2xx so Stripe retries; or look up by email fallback + alert. |
| 15 | MA | Correctness | `server.py:663-680` | `/api/trial/start` race: `existing` check + create not atomic, no unique constraint on `InterviewSession.user_id` → two trial sessions. | Add unique constraint or `SELECT FOR UPDATE`. |
| 16 | MA | Security | `mailer.py:13` | Full verification URL (incl. `verify_token`) logged to stdout on every signup/resend; token also never expires. | Don't log the token; add issued-at + expiry and reject stale tokens. |
| 17 | MA | Perf | `server.py:732,832-833,869` | Blocking screenshot `write_bytes`, audio `tmp.write`, `os.unlink` on capture hot paths. | Offload file I/O to threadpool; or stream audio bytes via `BytesIO` and skip temp file; consider dropping the disk screenshot. |
| 18 | MA | Perf | `server.py:156-160,193-208,734-737,760-762` | Hot paths issue many sequential Redis round-trips (rate-limit 4×, capture hset+publish groups). | Batch with `r.pipeline()`. |
| 19 | MA | Tests | `tests/test_billing.py` | **No test** for webhook idempotency/replay; fingerprint anti-abuse is skipped in test mode so never exercised. | Add: POST identical checkout event twice, assert `sessions_remaining` increments once. (Fails today — documents #1.) |
| 20 | MA | Tests | `tests/test_routes.py:121,135` | `/stream` only tested for 401/403; SSE happy path (event published → received) untested. Rate limiting untested entirely. | Add fakeredis SSE delivery test; add cooldown + per-minute cap tests. |
| 21 | MA | Maint | `server.py` (whole) | 1100-line monolith; all routes + SSE + business logic in one file. | Split into `APIRouter` modules + shared `deps.py`. |
| 22 | MA | Deps | `requirements.txt` | 14/16 deps unpinned (stripe, fastapi, anthropic ship breaking changes) → non-reproducible builds. | Pin `==`/`~=`, add lockfile. |
| 23 | MA | Deps | `auth.py:7` | `python-jose` is sparsely maintained, multiple CVEs; usage is trivial HS256. | Migrate to `pyjwt` (near drop-in). |
| 24 | MI | Security | `server.py:728-732,816-834` | `/api/capture` base64 + `/api/audio-capture` upload have no size cap, no content-type check, no decode error handling (→ 500, memory/disk abuse). | Add max body/upload size, content-type allowlist, try/except → 400; hard-code temp suffix. |
| 25 | MI | Security/Perf | `auth.py:74`; `server.py:942-955` | Bearer token matched by DB equality with no rate-limit/lockout on bad-token attempts; `/api/notify/*` unrate-limited. | Rate-limit failed Bearer auth; never log tokens (tokens are 256-bit so brute-force is impractical, but add the limiter). |
| 26 | MI | Correctness | `server.py:557-577` | `apply_referral_code` TOCTOU: concurrent double-submit → IntegrityError surfaces as unhandled 500 instead of friendly "already referred". | Catch IntegrityError, return the already-referred redirect. |
| 27 | MI | Billing | `billing.py:116-117` | `cancel_subscription` returns `None` when neither `cancel_at` nor `trial_end` present → UI shows no cancel date though sub is cancelling. | Fall back to `current_period_end`. |
| 28 | MI | Billing | `billing.py:194-196` | `_get_card_fingerprint` swallows all Stripe errors → transient error silently disables intro anti-abuse and grants discounted intro. | Defer (raise → retry) on fingerprint-retrieval failure in live mode. |
| 29 | MI | Billing | `server.py:991-999` | `billing_offer` doesn't check `retention_offer_claimed` before applying coupon (only template gates it) → re-claimable via direct POST. | Guard `if user.retention_offer_claimed: return` at route start. |
| 30 | MI | Billing | `billing.py:103-105,74-89` | Discount logic inconsistent per plan: subscription path ignores user's earned `referral_credit_pence`; sessions paths ignore signup discount. | Decide which discounts apply per plan and apply consistently. |
| 31 | MI | Perf | `billing.py:170,236,252` | Extra `User` lookup per referral event (re-query referrer by id). | Use relationship/join. |
| 32 | MI | Perf | `models.py:39` | `verify_token` filtered in `/verify` but not indexed (only un-indexed WHERE column). | `index=True`. |
| 33 | MI | Maint | `server.py:739-757,793-805,846-857` | Prompt-building + Claude streaming (`model="claude-sonnet-4-6"`, `max_tokens=1024`) duplicated 3×. | Extract `_stream_claude(...)` helper; lift model/tokens to constants. |
| 34 | MI | Maint | `billing.py:65-106,164-258` | Checkout kwargs built 3×; referral-credit block repeated 3×; `300 if intro_credited else 500` twice. | Extract common kwargs + `_credit_referrer_for(...)` helper. |
| 35 | MI | Maint | `billing.py` various | Magic numbers: credits `200/300/500`, sessions `2/3`, `trial_period_days:7`, rate-limit `5/6/10`. | Lift to named constants. |
| 36 | MI | Consistency | `analytics.py:26` vs `server.py:36` | `POSTHOG_HOST` defaults differ (`us.` vs `eu.`) → server/browser events split across regions. | Single constant in `config.py`. |
| 37 | MI | Consistency | `.env` / `CLAUDE.md` | `HOTKEY_LEFT/RIGHT` in `.env` unused (dead); `STRIPE_RETENTION_COUPON_ID`, `POSTHOG_HOST`, `NOTIFY_EMAIL` undocumented; no `.env.example`. | Delete dead vars; document the rest; add sanitized `.env.example`. |
| 38 | MI | Maint | `database.py:27-52` | Migration `ALTER TABLE` list hand-duplicates `models.py` schema; add-a-column requires editing both. | Adopt Alembic, or comment the coupling. |
| 39 | MI | Deps | `templates/index.html:4-11` | `marked` loaded unpinned (latest) + `highlight.js@11` from CDN, no SRI. | Pin exact versions + SRI, or vendor. |
| 40 | MI | Tests | `tests/test_billing.py:621` | `test_cancel_confirm_success` patches `cancel_subscription` to a no-op and asserts the mock, not DB effects. | Let it run against fake Stripe; assert `sub_cancel_at` set. |
| 41 | MI | Tests | multiple | Missing: paid-session-preserved-on-Claude-failure, trial-expired 403 path, `invoice.paid` replay, `/screenshot`, sessions/pack checkout, `/api/capture` Redis-state assertions. | Add the listed tests. |
| 42 | N | Extension | `background.js:271-311,291-297,469-487` | Audio-start `_stopPending` dead check; offscreen-ready / replay-slice promises can hang forever (no timeout); fire-and-forget `sendMessage` without `.catch` → "port closed" noise. | Add timeouts that reject+cleanup; `.catch(()=>{})` on all fire-and-forget sends. |
| 43 | N | Extension | `background.js:166-179,409-458` | Replay/audio live state lost on MV3 service-worker termination; not rehydrated from storage → "Armed" UI no-ops. | Rehydrate arm-state from storage at SW start. |
| 44 | N | Security/Maint | `init_db database.py:53-55` | f-string in `ALTER TABLE` DDL — safe today (hard-coded list) but latent injection footgun. | Keep list hard-coded / whitelist; comment. |
| 45 | N | Consistency | server-wide | Inconsistent response shapes (`{status:ok}` vs `{ok:true}` vs redirects vs raw); `datetime.utcnow()` deprecated; `?cancelled=1` set but never consumed by `settings.html`. | Settle a response convention; migrate to aware UTC; wire or drop the param. |
| 46 | N | Tests | `tests/harness.py:13` | Harness treats "returned None" as PASS; some tests (`test_*_no_user_is_noop`) assert nothing. | Add negative assertions (no row created/credited). |

---

## Verified-OK (checked, not vulnerabilities)

- **JWT**: algorithm pinned to HS256, `exp` enforced, single secret for sign+verify — no alg-confusion.
- **SQL injection**: all user queries use parameterised ORM filters (only DDL exception is #44).
- **IDOR**: data access keys off the authenticated `user.id`, not request input (screenshot/session/referral lookups scoped correctly).
- **Author Basic auth**: uses `secrets.compare_digest`, rejects empty password.
- **Token entropy**: `secrets.token_urlsafe(32)` (256-bit) for api/verify tokens — adequate.
- **Stripe webhook signature**: verified via `construct_event` (idempotency is the gap, not signature).
- **Money units**: consistently integer pence, `max(0,...)` clamps — no float money.
- **Whisper offload**: correctly uses `asyncio.to_thread` (the one SDK call done right).
- **Extension polling**: event-driven, no wasteful intervals; replay buffer bounded.

---

## Prioritized remediation plan

### Quick wins (low effort, high value — hours)
- **#16** stop logging verify token; **#32** add `verify_token` index; **#36** unify `POSTHOG_HOST`; **#37** clean `.env` + document; **#29** retention-offer guard; **#26** catch referral IntegrityError; **#27** cancel-date fallback; **#42** extension timeouts + `.catch`; **#24/#25** add size caps + bad-token rate-limit; **#22** pin deps; **#39** pin/SRI CDN scripts.
- **#7 (partial)** add `secure=True` to cookies and lock CORS to known origins.

### Medium effort (days)
- **#1/#2/#19** Stripe webhook idempotency table + dedup, with tests — single highest-value change for money safety.
- **#3** extension origin-gating + manifest scope narrowing (security blocker, but contained change).
- **#8/#9/#15** atomic session deduction + shared `_consume_paid_session` helper (fixes the audio free-ride) + trial uniqueness.
- **#10/#11** capture-failure refund/error-broadcast + `/stream` disconnect handling.
- **#12/#13/#14** billing status-transition + flag-conflict + missing-user decisions (need product confirmation first).
- **#20/#40/#41** fill the test gaps (SSE, rate limit, trial expiry, capture failure).
- **#33/#34/#35** extract capture/billing duplication into helpers + named constants.

### Larger refactors (weeks)
- **#4/#5/#6/#17/#18** get sync I/O off the event loop — async SQLAlchemy (or systematic `run_in_threadpool`), offload Stripe/Resend, pipeline Redis. Biggest performance lift; touches nearly every handler.
- **#21** split `server.py` into routers.
- **#23** migrate `python-jose` → `pyjwt`.
- **#38** adopt Alembic for migrations.
- Consider Postgres if real concurrency is expected (SQLite single-writer is a ceiling, #12-perf).

---

## Areas not fully assessed (and why)
- **Deployment/proxy config** — whether HTTPS, max body size, and `BASE_URL` scheme are enforced upstream (affects severity of #7, #24). Not in repo.
- **Runtime Stripe object shapes** — e.g. whether `cancel_at` / `total_details.amount_discount` are reliably populated without expansion (#27, #2). Needs live Stripe.
- **Webhook delivery concurrency** — serial vs parallel processing affects exploitability of the idempotency gaps (but absence of dedup makes them real regardless).
- **PostHog blocking behavior** (#5-perf) — depends on installed version's flush config; defaults to background flush.
- **Test suite execution** — could not run (deps not installed in audit env); test findings are static.
- **CSS internals** (~11k LOC) and detailed template review — out of scope by design.
- **Business-intent questions** (#12 unlimited-during-trial, #13 pack-vs-sub referral) — flagged for your decision, not assumed bugs.

---

**Nothing was changed. Which findings should I act on?** I'd suggest starting with the quick wins + webhook idempotency (#1/#2) and the extension origin gate (#3), since those carry the most money/security risk for the least code.
