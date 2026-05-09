# InterviewAce — Feature Inventory

Technical reference for the author. Every claim links to a source file.
Not marketing copy — incomplete and janky bits are called out plainly.

---

## Core Capture / Analysis Flow

- **Screen capture endpoint** `POST /api/capture` (`server.py:564`) — accepts base64 PNG + complexity 1-3. Checks account gating, manages `InterviewSession`, saves screenshot to `screenshots/{user_id}.png`, streams Anthropic vision analysis via SSE.
- **Complexity levels 1/2/3** — hardcoded prompt suffixes in `server.py:62-66`. User adjustable via `POST /settings/complexity/{up|down}` (`server.py:500`) or extension popup.
- **SSE fan-out** `GET /stream` (`server.py:834`) — per-user `asyncio.Queue`; events: `capture`, `chunk`, `working`, `settings`, `disabled`, `enabled`, `trial_expired`, `audio-*`.
- **Latest state** `GET /latest` (`server.py:487`) and `GET /screenshot` (`server.py:492`) — current analysis + screenshot for dashboard polling.
- **In-process state** — `_subscribers`, `_capture_states`, `_settings` are plain dicts keyed by `user.id` (`server.py:92-94`). Will not survive a multi-worker deploy.

---

## Audio Recording (recently added — treat as beta)

- Hold-to-record hotkey: `keydown` starts, `keyup` stops (`extension/content.js:73-97`). Keyup detection triggers on any modifier release — easy to misfire.
- Offscreen document (`extension/offscreen.js`) holds `MediaRecorder`, encodes webm/opus, base64s it to background, which POSTs multipart to `POST /api/audio-capture` (`server.py:638`).
- Server transcribes with **OpenAI Whisper-1** (`server.py:668`) via `asyncio.to_thread`, then streams the transcript as a text-only prompt to Claude.
- SSE events: `audio-working` (before transcription), `chunk` (Claude streaming), `audio-analysis` (final with transcription text), `audio-error` (on failure).
- Temp file lifecycle: `NamedTemporaryFile` + `os.unlink` in `finally` (`server.py:693-694`).
- Mac support: `extension/content.js:67` uses `(e.ctrlKey || e.metaKey)` so Cmd key works.
- Known open plan items: "mic settings and mic test", "mac 'enable' the whole time" (`plan.txt:38-40`).

---

## Authentication & Accounts

- **JWT in HTTP-only cookie** (`auth.py:37-39`), 7-day expiry. `get_current_user` / `get_optional_user` deps (`auth.py:42-59`).
- **Bcrypt** password hashing (`auth.py:29-34`).
- Routes: `GET /login` (`server.py:170`), `POST /auth/login` (`server.py:177`), `POST /auth/register` (`server.py:194`), `GET|POST /auth/logout` (`server.py:261-266`).
- **Email verification** — token generated at register (`server.py:215`), sent via Resend, `GET /verify` flips `email_verified` (`server.py:248`). `POST /auth/resend-verification` (`server.py:238`).
- **API token** (bearer) for the extension — separate from the session cookie. Regen via `POST /api/token/regenerate` (`server.py:729`).
- Account gate on `/app`: unverified → `/verify-pending`, `free` → `/pricing`, trial + no setup → `/onboarding` (`server.py:278-289`).

---

## Billing (Stripe)

- Three plans in `billing.py`:
  - `subscription` — £25/mo, 7-day trial period, sets `account_level = unlimited`.
  - `sessions` / `sessions_pack` — one-time payments, increment `sessions_remaining`, set `account_level = paid`.
- Routes: `GET /billing/checkout` (`server.py:740`), `GET /billing/portal`, `GET /billing/success`, `GET /api/billing/status`, `POST /billing/webhook`.
- **In-app cancellation**: `/billing/cancel` → `cancel_confirm.html` → `POST /billing/cancel/confirm` sets `cancel_at_period_end=True` on the subscription and emails reason to `NOTIFY_EMAIL` (`server.py:763`, `mailer.py:52`).
- **`/billing/offer`** (`server.py:756`) — stub. Literal `# TODO: apply 50% coupon` comment. Nothing implemented.
- **Card-fingerprint anti-abuse** (`billing.py:142-183`) — for the £2 intro deal; auto-refunds duplicate fingerprints. Only active when key isn't `sk_test_` — currently toggled off for dev (`plan.txt:22`).
- **Webhook** handles `customer.subscription.created/updated/deleted` and `checkout.session.completed` (`billing.py`).
- Self-healing bug: `api_capture` notices subscribers wrongly tagged `paid` and upgrades them to `unlimited` (`server.py:582-586`). Dead code once clean data exists.
- Plan notes: "referals dont work on stripe - fix", "referal flow has a few edge cases" (`plan.txt:24-25`).

---

## Referrals

- `Referral` model with `status` enum (`signed_up/intro/subscribed`) and credit flags (`models.py:51-62`).
- `User.referral_code` + `User.referred_by_id` (`models.py:38-39`).
- `/r/{code}` sets a 30-day `ref` cookie (`server.py:357-368`), consumed at register (`server.py:199`).
- `/referral` page lists referees and credits earned (`server.py:372`).
- `POST /referral/apply` (`server.py:425`) — retroactive code entry; only works if user has no referrer.
- Stripe credit via `Customer.create_balance_transaction` in `billing._credit_referrer` (`billing.py`).
- 200p credit for intro purchase, 300p for subscription — `_handle_sessions_purchase` and `_sync_subscription` in `billing.py`.
- Self-referral guarded at register (`server.py:441-442`).

---

## Settings / Configurable Hotkeys

- `POST /api/settings/hotkeys` (`server.py:704`) — persists three hotkey strings to `User.hotkey_capture/audio/toggle` (`models.py:40-42`).
- `GET /api/me` (`server.py:699`) — returns `account_level` + current hotkeys (with defaults for nulls via `_user_hotkeys` at `server.py:83-88`).
- Extension picks up changes: `background.js:1-20` fetches `/api/me` on load; `content.js:43-53` listens for storage changes.
- Hotkey parser in extension supports Ctrl/Shift/Alt + single letter or digit only (`content.js:55-71`).
- Settings page at `/settings` (`server.py:449`) renders all three hotkeys as editable fields.
- Defaults: Capture `Ctrl+Shift+7`, Audio `Ctrl+Shift+8`, Toggle `Ctrl+Shift+9` (`server.py:80`).

---

## Tutorial / Onboarding

- `/onboarding` (`server.py:292`) — trial-only, shows API token, BASE_URL, hotkeys.
- 4-step in-app tutorial overlays inside `templates/index.html` (pin extension, start trial, etc.).
- `POST /api/setup/complete` (`server.py:515`) — sets `setup_complete = True`.
- `POST /api/trial/start` (`server.py:524`) — creates `InterviewSession` with `TRIAL_DURATION` (10 minutes, `server.py:58`); errors if already started.
- `GET /api/trial/status` (`server.py:543`) — returns `is_trial`, `started`, `seconds_remaining`, `expired`.

---

## Web Pages (templates/)

- `base.html` — Jinja2 layout shell, nav, CSS includes.
- `landing.html` — homepage; sign-in/app button switches based on auth state.
- `login.html` — combined sign-in / register with tab UI.
- `verify_pending.html` — "check your email" + resend button.
- `onboarding.html` — trial setup wizard with API token display and hotkey hint.
- `index.html` — main dashboard; SSE consumer, marked.js + highlight.js for code rendering, tutorial overlays.
- `pricing.html` — plan picker (sessions / subscription).
- `settings.html` — account level, hotkeys, API token, billing link, referral code entry.
- `referral.html` — your code, referee table, total earned.
- `cancel_confirm.html` — retention flow with confetti canvas and reason form.
- `billing_success.html` — polls `/api/billing/status` up to 12 times post-checkout.
- `trial_end.html` — post-trial upsell.
- `author.html` — CJ Coleman portfolio/contact page; HTTP basic-auth gated.

---

## Chrome Extension Surfaces

- `manifest.json` — MV3, permissions: `activeTab`, `storage`, `tabs`, `scripting`, `offscreen`. Host `<all_urls>`.
- `popup.html` / `popup.js` / `popup.css` — server URL + token entry, complexity stepper, ON/OFF toggle (with confirm modal), mic-permission button, hotkey footer.
- `background.js` — service worker: `doCapture` via `chrome.tabs.captureVisibleTab`, audio start/stop orchestration, REC/ERR badge via `OffscreenCanvas`, polls `/api/me` on load.
- `content.js` — keydown listener, hotkey matcher, `interview-ace:connect` custom event (lets onboarding page push token+URL into extension storage).
- `offscreen.html` / `offscreen.js` — minimal MV3 offscreen doc holding `MediaRecorder`.
- `grant-mic.html` / `grant-mic.js` — standalone tab that fires `getUserMedia` to trigger the mic permission prompt, then closes itself.

---

## Admin / Author

- `/verify-author` (`server.py:352`) — HTTP basic auth via `AUTHOR_PASSWORD` env var. Displays `author.html` personal portfolio. No real admin tooling.

---

## Email (Resend)

Two emails, both in `mailer.py`:
- **Verification email** (`mailer.py:10-39`) — triggered at register and resend. To the user.
- **Cancellation feedback email** (`mailer.py:52-99`) — triggered on `POST /billing/cancel/confirm`. To `NOTIFY_EMAIL` (defaults to `cjcoleman267@gmail.com` in `config.py:38`).
- Both no-op silently if `RESEND_API_KEY` is the placeholder `re_xxxxxxxxxxxx`.

---

## External APIs in Use

| Service | Purpose | Where |
|---|---|---|
| Anthropic `claude-sonnet-4-6` | Vision analysis + text streaming | `server.py:617`, `server.py:677` |
| OpenAI `whisper-1` | Audio transcription | `server.py:668` |
| Stripe | Checkout, subscriptions, billing portal, webhooks, refunds | `billing.py` |
| Resend | Transactional email | `mailer.py` |

Both sync (`client`) and async (`async_client`) Anthropic clients are instantiated at startup (`server.py:53-54`).

---

## Data Model

**User** (`models.py:16-42`):

| Column | Type | Notes |
|---|---|---|
| `account_level` | Enum | `free / trial / paid / unlimited` |
| `email_verified` | Bool | gates `/app` access |
| `setup_complete` | Bool | gates `/app` for trial |
| `api_token` | String | bearer auth for extension |
| `sessions_remaining` | Int | only used for `paid` sessions plan |
| `intro_redeemed` | Bool | one-time £2 intro deal lock |
| `stripe_customer_id` | String | unique |
| `stripe_sub_id` | String | unique |
| `sub_cancel_at` | DateTime | set when cancel scheduled |
| `referral_code` | String | unique, URL-safe |
| `referred_by_id` | FK → User | nullable |
| `hotkey_capture/audio/toggle` | String | nullable; defaults in `server.py:80` |

**Referral** (`models.py:51-62`): `referrer_id`, `referee_id` (unique), `status`, `intro_credited`, `sub_credited`, timestamps.

**InterviewSession** (`models.py:65-72`): `user_id`, `started_at`, `expires_at`, `ended_at`. Used to enforce trial window (10 min) and paid sessions (2 h 30 m).

**IntroCardFingerprint** (`models.py:75-80`): anti-abuse table for the £2 intro; one row per card fingerprint.

**Database**: SQLite (`users.db`) via SQLAlchemy. `database.init_db` does ad-hoc `ALTER TABLE` column additions on every startup (`database.py:24-46`). Not a real migration tool — will break on Postgres without replacement.

---

## Keyboard Shortcuts

| Action | Default |
|---|---|
| Capture | `Ctrl+Shift+7` |
| Audio (hold) | `Ctrl+Shift+8` |
| Toggle on/off | `Ctrl+Shift+9` |

All three are user-rebindable via `/settings` → synced to extension via `/api/me`.

**Note:** `README.md` says capture is `Ctrl+Shift+Y` and lists only two shortcuts — it is out of date as of commit `14db733`.

---

## Half-Finished / TODO / Janky Bits

- **`/billing/offer`** (`server.py:756`) — stub with TODO comment, does nothing.
- **`database.init_db` migrations** (`database.py:24-46`) — manual `ALTER TABLE` on every boot. Not production-grade; won't migrate cleanly on Postgres.
- **`CORSMiddleware allow_origins=["*"]`** (`server.py:48`) — permissive, fine for dev, bad for prod.
- **`BASE_URL` default** (`config.py:31`) — hardcoded LAN IP `192.168.4.21:8000`.
- **In-process `_subscribers` dict** (`server.py:92`) — no persistence; won't survive multi-worker/restart.
- **`account_level` transitions in `api_capture`** (`server.py:564-601`) — trial→paid, paid→free on exhaustion, paid→unlimited if sub exists. Hard to reason about; a cleanup pass is overdue.
- **Audio keyup detection** (`content.js:85-97`) — releases on any modifier; easy to accidentally stop recording.
- **Self-healing subscriber bug fix** (`server.py:582-586`) — corrects old bad data on every capture request; remove once data is clean.
- **`test_all.py`** at project root — claimed to be replaced by `run_tests.py` (`run_tests.py:2`); likely stale, not deleted yet.
- **Referral Stripe credits** — `plan.txt:24-25` acknowledges these are broken.
- **Referral `apply` route** (`server.py:425`) — no expiry or fraud checks beyond self-referral guard.
- **README keyboard shortcut docs** — stale (wrong keys, missing audio shortcut).
- **`_test_smoke_test_user` in `test_auth.py`** — users written to the real `users.db`, not an in-memory test DB. Cross-contamination risk if tests run in parallel.
