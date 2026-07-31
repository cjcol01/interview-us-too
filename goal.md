# InterviewAce Improvement Research

---

## 1. Inventory

### Extension user-facing surfaces

**popup.html / popup.js**
- Arm/disarm toggle (`#toggle_enabled`) with confirmation overlay for non-unlimited users
- Status line: shows last capture timestamp or last error (re-validated live against `/api/me`)
- Server URL + API token config (`#server_url`, `#api_token`) with token show/hide toggle
- Complexity selector 1–3 (`complexity_down`/`complexity_up`) with description line
- Response style pills: conversational · bullets · summary · one_liner
- Mic section: permission dot, device selector (`#mic-select`), test button with live VU meter, grant-permission button
- Replay section (visible only when `replay_enabled`): status pill (idle/arming/armed/stream-ended/error), locked-tab label, lock/unlock buttons, window-seconds slider (10–120 s)
- Version label (`#version-label`)

**grant-mic.html / grant-mic.js**
- Dedicated tab opened when the user needs to grant microphone permission to the extension origin. Reports success back to background.js. No other UI surface.

**content.js (injected into all pages)**
- Bridges the page and extension via `CustomEvent` on `document`: handles `interview-ace:ping/pong`, `interview-ace:mic-check`, `interview-ace:mic-grant`, `interview-ace:ext-stale`
- On `/app`: injects a toast when the extension is disabled and the capture hotkey is pressed
- Checks extension context validity on load and on tab focus/visibility-change; dispatches `ext-stale` if Chrome invalidated the context (e.g. after an extension update)

**background.js (service worker)**
- Hotkeys: Ctrl+Shift+7 (capture screenshot), Ctrl+Shift+8 (hold for audio), Ctrl+Shift+9 (toggle arm), Ctrl+Shift+6 (replay), Ctrl+Shift+5 (typing passthrough toggle) — all user-configurable
- Manages MV3 offscreen document for mic recording (`offscreen.html/offscreen.js`)
- Manages tab audio capture for instant-replay ring buffer
- Concurrent mic-check guard (`_micCheckInProgress`) to prevent double offscreen document creation
- Storage-change listener to open grant-mic tab (more reliable than sendMessage across service-worker wake cycles)
- Heartbeat: posts `POST /api/ext/status` every ~30 s when armed
- Sends screenshot via `POST /api/capture`, audio via `POST /api/audio-capture`

---

### API endpoints (auth type · what it costs to serve)

| Endpoint | Auth | Cost |
|---|---|---|
| `POST /api/capture` | Bearer token | Anthropic claude-sonnet-4-6 vision call (≤1024 tok); OpenAI gpt-4o fallback; Redis pub/sub broadcast; session deduction for paid users; rate-limited 6/min, 15/5min |
| `POST /api/text-capture` | Bearer token | Same as capture minus the base64 image; same rate limits |
| `POST /api/audio-capture` | Bearer token | OpenAI gpt-4o-transcribe; Anthropic vision call on transcript; Deepgram fallback on transcription failure; Redis broadcast |
| `GET /stream` | Cookie session | SSE: subscribes to Redis `user:{id}:events` pub/sub; keeps TCP connection open for session lifetime |
| `POST /api/trial/start` | Cookie | DB write (InterviewSession); Redis clear history |
| `GET /api/trial/status` | Cookie | DB read |
| `GET /api/session/status` | Cookie | DB read |
| `POST /api/session/feedback` | Cookie | DB write; PostHog event |
| `GET /api/me` | Bearer token | DB read; used by popup to revalidate errors |
| `POST /api/settings/complexity` | Bearer token | Redis write |
| `POST /api/settings/style` | Bearer token | DB write |
| `POST /api/settings/replay-window` | Bearer token | DB write |
| `POST /api/settings/hotkeys` | Cookie | DB write |
| `POST /api/settings/passthrough` | Cookie | DB write |
| `POST /api/settings/replay` | Cookie | DB write |
| `POST /api/settings/response-style` | Cookie | DB write |
| `POST /api/settings/interview-date` | Cookie | DB write |
| `POST /api/settings/context` | Cookie | DB write (InterviewContext) |
| `POST /api/settings/context/activate` | Cookie | DB write |
| `POST /api/settings/context/fixed` | Cookie | DB write (cv_context / behavioural_context) |
| `POST /api/settings/context/extract` | Cookie | Anthropic API call for CV compression; DB write |
| `POST /api/settings/account` | Cookie | DB write |
| `POST /api/settings/password` | Cookie | DB write |
| `POST /api/token/regenerate` | Cookie | DB write; invalidates existing token |
| `POST /api/notify/disabled` | Cookie | Redis write |
| `POST /api/notify/enabled` | Cookie | Redis write |
| `POST /api/ext/status` | Bearer token | Redis write (`user:{id}:ext_status`) |
| `GET /api/ext/status` | Cookie | Redis read |
| `POST /api/setup/complete` | Cookie | DB write; PostHog event (onboarding_completed/skipped) |
| `POST /api/tutorial/seen` | Cookie | DB write |
| `POST /api/onboarding/mobile-link` | Cookie | Resend email (magic link); DB/Lead write |
| `POST /api/welcome/interview-date` | Cookie | DB write; PostHog event |
| `POST /api/install-link` | None | Honeypot check; Resend email; Lead DB write/update |
| `GET /claim` | None | Lead token verify; User create or find; session cookie issue |
| `POST /billing/checkout` | Cookie | Stripe checkout session create |
| `GET /billing/portal` | Cookie | Stripe billing portal session create |
| `POST /billing/offer` | Cookie | DB write (50% off flag); Stripe coupon apply |
| `POST /billing/cancel/confirm` | Cookie | Stripe subscription cancel; PostHog event |
| `POST /billing/webhook` | Stripe-sig | DB writes; commission accrual; Resend email on cancel |
| `POST /referral/apply` | Cookie | DB writes; referral credit; PostHog event |
| `POST /partner/withdraw` | Cookie | DB write (Withdrawal); PostHog event |

---

### Landing page sections and primary actions

**`/` (`landing.html`)**
- Hero: headline "Stop blanking. Start acing." + desktop CTA ("Try free — no card" → `/login?register=1`) + ghost CTA ("See how it works" → `#how`) + trust row
- Mobile lead form (hidden on desktop ≥720px): email input + interview-date pills + honeypot; submits to `POST /api/install-link`; success state shows "Check your inbox"
- Demo tabs cycling through: Screenshot → Voice → Replay animated mockups
- "How it works" section (3-step explainer)
- Social proof / testimonials section
- FAQ and Support links in footer

**`/pricing`**
- Intro deal card (£2 for 1 session, one-time, shown until `intro_redeemed`)
- Sessions pack (£10 for 3 sessions)
- Monthly subscription card
- Referral credit display if applicable
- All CTAs gate on login state

**`/onboarding`** (5-step card flow)
- Step 1: Install Chrome extension (link to Web Store + ping/pong detection)
- Step 2: Connect extension to account (copy API token, paste into popup)
- Step 3: Grant microphone permission (dispatches mic-check; opens grant-mic tab)
- Step 4: Lock instant replay to a tab (replays last N seconds of tab audio)
- Step 5: Open a coding platform (LeetCode, HackerRank, Codility, CodeWars, CodeSignal)
- End: "Start your 10-minute test run" CTA → `POST /api/trial/start`

**`/app` (`index.html`)**
- Answer/response stream area (SSE feed via `/stream`)
- Extension status dot (green/yellow/red based on `GET /api/ext/status`)
- Session timer chip when a paid session is active
- "How did your interview go?" feedback modal (shown after N captures)
- History, settings sidebar nav

---

### Error states, empty states, and paywalls

| Where | Trigger | What the user sees |
|---|---|---|
| `POST /api/capture` | `account_level == free` | Extension shows "Subscription required" error toast; app dashboard shows no response |
| `POST /api/capture` | trial expired (no active InterviewSession) | 403 `trial_expired`; SSE `trial_expired` event → `/trial-end` redirect |
| `POST /api/capture` | `sessions_remaining == 0`, paid account | 403 `sessions_exhausted`; user silently downgraded to free in DB |
| `POST /api/capture` | rate limit hit (>6/min or >15/5min) | 429-equivalent 403 with text message; extension shows error |
| Extension popup | No server URL or API token | "Configure server URL and token below" error status |
| Extension popup | `/api/me` returns 401/403 | "Token invalid or expired — re-check your API token below" |
| Extension popup | Server unreachable | "Can't reach the server — check the URL below and your connection" |
| `/app` | Extension not connected (no recent heartbeat) | Yellow dot on extension status indicator |
| Onboarding step 3 | Mic permission denied | LED turns warn-orange; help text with link to settings |
| Onboarding step 3 | Mic check timed out (service worker not yet awake) | "Checking microphone…" or "Waiting for the extension" after 2 s |
| Onboarding step 4 | Replay locked to tab that navigated away | LED turns bad; "Lock dropped — that tab closed or navigated away" |
| `/verify-pending` | Email not verified | Blocking page; resend button |
| `/trial-end` | Trial expired, free account | Paywall page with CTA to pricing |
| `/app` on free account | Visiting the dashboard | Redirects/shows paywall; depends on `require_subscription` check |
| `POST /api/audio-capture` | Both OpenAI and Deepgram fail | 502/500; extension shows error, user loses the question they recorded |

---

### PostHog events currently instrumented

`login` · `signup` (referred, method) · `email_verified` · `password_reset` · `install_link_claimed` (outcome) · `finish_signup_completed` · `welcome_viewed` · `welcome_next_viewed` · `welcome_interview_date_saved` · `session_feedback_submitted` (rating, comment, session_type) · `onboarding_viewed` · `onboarding_skipped` · `onboarding_completed` · `pricing_viewed` · `referral_applied` · `partner_withdrawal_requested` · `partner_tier_granted` · `trial_started` · `trial_expired` · `capture_submitted` (complexity) · `text_capture_submitted` · `audio_capture_submitted` · `checkout_initiated` (plan) · `subscription_cancelled` (reason) · `account_deleted` (reason) · admin action events

### User actions NOT instrumented (the gaps that matter)

- First successful capture (no "first_capture" or "first_paid_capture" event; the transition from "set up" to "actually got an answer" is invisible)
- Onboarding step N completion (individual step events; `onboarding_viewed` + `onboarding_completed` is too coarse to see drop-off point)
- Extension popup open
- Arm/disarm toggle
- Replay lock/unlock
- Hotkey pressed while extension disabled (stored as `last_disabled_press` in storage, never sent to analytics)
- Rate limit hit by a user (every 429-equivalent is a silent frustration signal)
- Claude→OpenAI failover (an outage metric hidden in server logs but never in product analytics)
- CV upload / context extract (`POST /api/settings/context/extract` has no `track()` call)
- Sessions-remaining low watermark (user is about to run out; no event fires)
- Billing portal opened (`GET /billing/portal` has no `track()`)
- Retention offer shown / declined (`intro_declined` column is written but never tracked)
- Complexity or response style change (settings mutations are never tracked)

---

## 2. Proposals

### P1 — Onboarding step funnel tracking
**Category:** activation & first-run onboarding  
**Title:** Per-step completion events in `onboarding.html`  
**User value:** Team can see exactly which onboarding step loses the most new users and fix the right thing first.  
**Evidence:** `server.py:2138` tracks `onboarding_viewed` and `server.py:4614` tracks `onboarding_completed`/`onboarding_skipped` — nothing in between. `obComplete(n)` in `onboarding.html` is called at each step transition but emits no event. The missing events mean any drop-off between install and test-run-start is invisible in PostHog.  
**Effort:** S (<2h)  
**Sketch:** In `obComplete(n)` in `templates/onboarding.html`, after `_obCompleting.add(n)`, dispatch a fetch to a new server endpoint `POST /api/onboarding/step` (body: `{step: n}`) or just call the existing `/api/ext/status` pattern. In `server.py`, add a one-liner `track(user.id, "onboarding_step_completed", step=n)` in that handler. No schema change required.  
**Counterargument:** If >80% of users complete onboarding already, the funnel data is noise rather than signal.  
**Kill criterion:** If all five steps show >90% completion rate after 200 unique cohort users, remove the instrumentation; the signal is not actionable.

---

### P2 — Extension-connected auto-advance on step 2
**Category:** activation & first-run onboarding  
**Title:** Skip step 2 token-paste when extension heartbeat already detected  
**User value:** Users returning from the Web Store who already pasted their token weeks ago aren't forced to re-paste it to advance.  
**Evidence:** `templates/onboarding.html:~640` calls `_checkExtAlive()` on every tab return/focus, and on success calls `obComplete(1)` if step 1 is open — but not step 2. Step 2 ("connect extension") asks the user to copy and paste their API token, but the extension heartbeat (`POST /api/ext/status`) already proves the token works. The page has `_extensionConnected` state but never uses it to auto-complete step 2.  
**Effort:** S (<2h)  
**Sketch:** In `obInitStep2()` in `onboarding.html`, after the extension sends a `pong`, also check if `_obDone.has(1)` and `!_obDone.has(2)` — if so, call `obComplete(2)` immediately. No server change needed; the `pong` is already wired.  
**Counterargument:** A user might have the extension installed from a different account; auto-completing step 2 gives false confidence if the tokens don't match.  
**Kill criterion:** If support tickets about "extension connected but step 2 won't advance" appear, revert to manual.

---

### P3 — Trial-end page context recap
**Category:** free-to-paid conversion  
**Title:** Show a "what you just did" summary on the trial-end paywall  
**User value:** Users who finished their trial can see the captures they ran during it, reinforcing that the tool worked and making the upgrade CTA land harder.  
**Evidence:** `templates/trial_end.html` exists and is shown when `trial_expired` is broadcast. The `InterviewSession` model (`models.py:160`) stores `started_at` and `expires_at`. `UsageDaily` (`models.py:170`) stores `capture_count` and `audio_count` per day. None of these are passed to the trial-end template in `server.py:2162`.  
**Effort:** M (half day)  
**Sketch:** In `server.py:2162`, query `UsageDaily` for the user's trial period and pass `capture_count`/`audio_count` totals to `trial_end.html`. Display "You ran 7 captures and 3 voice queries in 10 minutes." above the upgrade CTA. Optionally surface the last AI response text from `r.hget(_capture_key(user.id), "analysis")`.  
**Counterargument:** Users who had a bad trial (zero captures, extension never connected) will see "You ran 0 captures" which is actively demotivating.  
**Kill criterion:** If trial→paid conversion rate doesn't improve within 60 days of launch, revert to the flat CTA.

---

### P4 — Intro deal urgency signal
**Category:** free-to-paid conversion  
**Title:** Add a countdown timer to the £2 intro deal card  
**User value:** Users know the intro deal expires and act before they forget.  
**Evidence:** `templates/pricing.html:29` shows the intro deal if `not intro_redeemed`. There is no expiry on the deal — `User.intro_redeemed` is false until the user purchases, with no time pressure. `User.created_at` exists and a "deal expires 7 days after signup" rule could be enforced cheaply.  
**Effort:** M (half day)  
**Sketch:** Add `intro_offer_expires_at = created_at + 7 days` to the context passed in `server.py:2192`. Render a countdown chip in `pricing.html` ("Deal expires in 2d 14h"). On the server side, skip rendering the intro card if the deadline has passed (or keep it but mark it expired). No Stripe change needed.  
**Counterargument:** Artificial urgency is a dark pattern that can erode trust among technically sophisticated users who recognise it.  
**Kill criterion:** If average intro-deal purchase time doesn't shorten, or trust/NPS scores drop, remove the timer.

---

### P5 — Pre-interview day-before push
**Category:** retention after the first successful session  
**Title:** Day-before reminder email when `interview_date` is set  
**User value:** Users who set their interview date get a reminder the evening before, prompting them to do a final check of their setup.  
**Evidence:** `User.interview_date` (column in `models.py:83`) and `User.interview_reminder_sent` (`models.py:84`) exist. `server.py:180` implements `_send_due_interview_reminders()` which already sends reminders. But `server.py:214` schedules the reminder job only inside the lifespan — if the server restarts it may miss users. Also, the reminder is a single generic email with no setup-check CTA.  
**Effort:** S (<2h)  
**Sketch:** The reminder is already implemented. The gap is the CTA inside the email body (`mailer.py`) — add a "test your setup now" link to `/onboarding` with `?check=1`. In `onboarding.html`, if `check=1`, auto-run the ping check on load and show "Your setup is ready" or a warning immediately. No new cron needed.  
**Counterargument:** Users might find a day-before nudge stressful rather than helpful if setup is already solid.  
**Kill criterion:** If users with `interview_date` set don't activate on the reminder-received day at a higher rate than the control group, stop sending the setup-check deep link.

---

### P6 — Re-engagement email after first session ends
**Category:** retention after the first successful session  
**Title:** "How did it go?" email sent 2 hours after a paid session expires  
**User value:** Users get a prompt to record their interview outcome and are reminded to book their next session while the experience is fresh.  
**Evidence:** `InterviewSession.expires_at` is stored. `SessionFeedback` (`models.py:243`) is the right model but the feedback modal in `/app` is only shown client-side after N captures, so users who close the tab early never see it. There is no outbound email triggered at session end. `mailer.py` already has a Resend-based email sender.  
**Effort:** M (half day)  
**Sketch:** In `server.py:180` alongside the interview-reminder loop, add a query for sessions that expired 1.5–3 hours ago where no `SessionFeedback` row exists for that user. Send a short Resend email ("How did your interview go? Tap to record the outcome") linking to `/app?feedback=1`. Add a query param handler in `templates/index.html` to auto-open the feedback modal.  
**Counterargument:** Sending email after every session is high volume and risks unsubscribes from users who interview frequently.  
**Kill criterion:** Unsubscribe rate above 2% on this email template → pause.

---

### P7 — Interview-mode popup focus state
**Category:** core extension UX during a live interview  
**Title:** Collapse configuration UI in the popup when the assistant is armed  
**User value:** During a live interview, the popup shows only the arm state and last-response status — no distraction from mic settings, token fields, or complexity sliders.  
**Evidence:** `extension/popup.html` and `popup.js` render all sections (server config, mic, replay, complexity, style) unconditionally. When `isEnabled == true`, the user is in an active interview, but the full configuration panel still occupies most of the popup space. The confirm overlay (`#confirm-overlay`) exists for the arm action, proving the team knows armed vs. unarmed are different modes.  
**Effort:** M (half day)  
**Sketch:** In `applyEnabledState()` in `popup.js`, when `isEnabled` is true, add class `popup--armed` to `document.body`. In `popup.css`, set `.popup--armed .config-section { display: none }` for all config rows. Show only the arm toggle, last-response line, and a "Settings" link to expand. Reverse on disarm. No server change needed.  
**Counterargument:** A panicked user mid-interview might need to change their token if a session expired; hiding settings could trap them.  
**Kill criterion:** If support tickets about "can't access settings during interview" appear, revert.

---

### P8 — Popup capture-in-progress indicator
**Category:** core extension UX during a live interview  
**Title:** Show a spinner or working indicator in the popup while a capture is processing  
**User value:** Users who open the popup during a capture know the request is in flight and don't press the hotkey again.  
**Evidence:** `background.js` receives the hotkey, sends `POST /api/capture`, and stores the result in `chrome.storage.local` as `last_capture` or `last_error`. The popup listens to `chrome.storage.onChanged` for `last_capture` and `last_error`, but there is no `in_flight` or `working` flag set in storage between keypress and response. The `broadcast` event `working` is sent via Redis SSE to the browser dashboard but never reaches the popup.  
**Effort:** S (<2h)  
**Sketch:** In `background.js`, before calling `fetch()` for `/api/capture`, do `chrome.storage.local.set({ last_working: true })`. On completion (success or error), `chrome.storage.local.set({ last_working: false })`. In `popup.js`, listen for `last_working` changes and set `statusEl.textContent = 'Analysing…'` with a CSS pulse animation. Clear it on `last_capture` / `last_error` change.  
**Counterargument:** The popup is often closed during a capture; the indicator would only be seen if the user manually reopens it, making the benefit marginal.  
**Kill criterion:** No measurable reduction in duplicate hotkey presses (tracked via rate-limit hits) after 4 weeks → remove.

---

### P9 — Visible Claude→OpenAI failover signal
**Category:** latency and reliability under load  
**Title:** Surface a "using backup AI" badge when OpenAI fallover is active  
**User value:** Users who get a slower or differently-styled response know it's a provider issue, not their connection, and don't blame the product.  
**Evidence:** `server.py:399` catches any Claude exception and silently falls over to OpenAI. The SSE stream continues identically — `broadcast(r, user_id, "chunk", payload)` sends the same event type regardless of which provider answered. There is no `provider` field on the `chunk` event. The `track()` call at `server.py:4802` (`capture_submitted`) fires before the response, so it can't record which provider served it.  
**Effort:** S (<2h)  
**Sketch:** In `_stream_ai_response`, before the fallback path, broadcast a new SSE event `{"type": "ai_provider", "provider": "openai"}`. In `templates/index.html` (the SSE consumer), listen for this event type and show a dismissible banner "⚡ Using backup AI provider — response may vary slightly." Also add `track(user_id, "ai_failover")` to give an outage frequency metric.  
**Counterargument:** "Backup AI" language could undermine confidence in the product quality rather than reassuring the user.  
**Kill criterion:** If failover frequency drops below 0.5% of captures (i.e. Claude is reliable), the badge never shows and the feature is free to keep.

---

### P10 — Rate-limit hit tracking
**Category:** latency and reliability under load  
**Title:** Track rate-limit rejections as PostHog events  
**User value:** The team can see when heavy users are hitting the rate limit and decide whether to raise limits or add queuing.  
**Evidence:** `server.py:891` (`_rate_limit`) raises an `HTTPException` with a user-visible message. There is no `track()` call inside `_rate_limit`. The cooldown and window limits (5s cooldown, 6/min, 15/5min per `server.py:4744`) are the only guardrails against runaway cost; knowing how often they fire is essential for tuning.  
**Effort:** S (<2h)  
**Sketch:** In `_rate_limit` in `server.py`, before raising the exception, call `track(user_id, "rate_limit_hit", endpoint=endpoint, reason="cooldown"|"minute_limit"|"window_limit")`. The `user_id` is already available as a parameter. This requires no schema change.  
**Counterargument:** Rate-limit hits in dev/testing environments will pollute the event stream.  
**Kill criterion:** If fewer than 1% of users ever hit a rate limit, the metric is noise; remove after 90 days if no actionable spike is ever seen.

---

### P11 — Data-in-transit transparency page
**Category:** trust, privacy and the "is this safe to run during my interview" question  
**Title:** Add a "What leaves your computer?" one-pager linked from onboarding and the FAQ  
**User value:** Users can show their employer's IT team a clear list of what data the extension transmits, making approval faster and reducing abandonment from security-conscious candidates.  
**Evidence:** `templates/onboarding.html:54` says "stays completely invisible during your interview" but gives no data-flow detail. `templates/faq.html` and `templates/support.html` exist but have no structured privacy/data section. The Chrome manifest (`extension/manifest.json:6`) requests `<all_urls>` host_permissions and `tabCapture` — both are permissions that enterprise security reviewers flag.  
**Effort:** M (half day)  
**Sketch:** Create `templates/privacy_flow.html` (a simple static page, no auth needed) reachable at `/privacy-flow`. List: (1) screenshot PNG sent to `{your server}/api/capture` over HTTPS — never stored longer than 60 seconds; (2) audio sent as WebM blob; (3) no keystrokes, clipboard, or browsing history ever read. Link from the onboarding step 1 help text and the FAQ.  
**Counterargument:** A detailed data-flow page gives phishing-kit authors a blueprint for faking legitimacy.  
**Kill criterion:** If no users cite the page in support tickets or referrals after 6 months, remove it.

---

### P12 — Narrow host_permissions in manifest
**Category:** trust, privacy and the "is this safe to run during my interview" question  
**Title:** Replace `<all_urls>` host_permissions with a specific server origin  
**User value:** IT administrators at enterprise companies can approve the extension without flagging a "reads data from all websites" policy exception.  
**Evidence:** `extension/manifest.json:7` lists `"host_permissions": ["<all_urls>"]`. The only host the extension actually POSTs to is the user's configured `server_url` — it doesn't read data from other websites except for the content-script ping/pong which uses DOM events, not fetch. `<all_urls>` is displayed by Chrome as "Read and change all your data on all websites" — the most alarming possible permission summary.  
**Effort:** M (half day)  
**Sketch:** Change `host_permissions` to `["https://*.interviewace.app/*"]` (or whatever the production domain is). In `background.js`, the `fetch()` calls already use the user-configured `server_url`; they will continue to work if that URL matches the declared host. The content-script DOM events require no host permission. Users who self-host on a different domain will need a custom build — document this in the manifest README.  
**Counterargument:** Self-hosted deployments on arbitrary domains become impossible without a custom build, which is a real barrier for technically advanced users who currently just change the server_url in the popup.  
**Kill criterion:** If self-hosted user count (measured by non-production server_urls hitting the API) is >5% of active users, hold off.

---

### P13 — Low-sessions warning email
**Category:** pricing and packaging  
**Title:** Email paid users when `sessions_remaining` drops to 1  
**User value:** Users don't discover their sessions are exhausted mid-interview when their next capture returns 403.  
**Evidence:** `User.sessions_remaining` is decremented at `server.py:4764` whenever a new `InterviewSession` is created for a paid user. The 403 `sessions_exhausted` error (`server.py:4763`) silently downgrades the user to free. There is no `track()` call or email sent when this happens. `server.py:180` already has a scheduled email loop; adding a low-sessions query there is one function call.  
**Effort:** S (<2h)  
**Sketch:** In `_account_bookkeeping()` inside `api_capture` (`server.py:4748`), after `user.sessions_remaining -= 1`, check `if user.sessions_remaining == 1: send_low_sessions_email(user)` using the existing `mailer.py` infra. Add a `low_sessions_email_sent` boolean column to `User` (or reuse the existing admin `admin_low_sessions_sent` pattern) to prevent duplicates. Also add `track(user.id, "sessions_low", remaining=1)`.  
**Counterargument:** Users who buy sessions immediately before an interview don't need a warning; it's noise for the one-session-at-a-time workflow.  
**Kill criterion:** If fewer than 10% of users who receive the email buy more sessions within 7 days, the email is ineffective → stop sending.

---

### P14 — Monthly subscription on the pricing page
**Category:** pricing and packaging  
**Title:** Surface the existing monthly subscription as the primary plan on `/pricing`  
**User value:** Users interviewing over several months can budget predictably rather than buying sessions ad hoc.  
**Evidence:** `billing.py` and `config.py` reference `STRIPE_SUB_PRICE_ID` and `STRIPE_PRICE_ID`, confirming a subscription product exists. `templates/pricing.html:69` shows the sessions pack and intro deal prominently; the subscription card exists but is rendered lower. `User.sub_cancel_at` and `User.stripe_sub_id` are full model fields, so the billing plumbing is complete.  
**Effort:** S (<2h)  
**Sketch:** In `templates/pricing.html`, reorder the plan cards so the subscription is first in the grid (hero position). Add a "Most popular" badge. The Stripe integration (`billing.py`) already handles subscription creation. No backend change needed — this is a template ordering change.  
**Counterargument:** Sessions packs generate one-time revenue without churn risk; pushing subscriptions optimises for LTV but hurts cash flow on single-interview buyers.  
**Kill criterion:** If subscription signup rate doesn't improve within 8 weeks, revert card order.

---

### P15 — Edge browser listing
**Category:** distribution channels beyond the Chrome Web Store  
**Title:** Publish the extension to the Microsoft Edge Add-ons store  
**User value:** Candidates using Edge (default on Windows in corporate environments) can install without switching browsers or using developer mode.  
**Evidence:** `extension/manifest.json` is MV3, which Edge supports natively. The extension has no Chrome-specific APIs beyond `chrome.*` which is aliased in Edge. The Web Store URL in `templates/onboarding.html:55` is hard-coded to `chrome.google.com/webstore` — Edge users see the Chrome store link, which requires a Chrome install.  
**Effort:** L (multi-day) — Edge store submission process, review wait, marketing page.  
**Sketch:** Submit the identical zip to `microsoftedge.microsoft.com/addons`. Replace the hard-coded install link in `onboarding.html` with a browser-detection snippet that serves the correct store URL. Add `EDGE_EXTENSION_ID` to `config.py` alongside `WEBSTORE_EXTENSION_ID` for the health-check polling.  
**Counterargument:** Edge's market share among software engineers is small; the submission + review overhead may not pay off relative to building features.  
**Kill criterion:** If Edge install rate is <3% of total installs after 3 months, deprioritise Edge-specific work.

---

### P16 — Referral code in the post-install email
**Category:** distribution channels beyond the Chrome Web Store  
**Title:** Include the user's referral code in the welcome email and in the `/app` dashboard  
**User value:** Users who just successfully set up the tool can immediately share it with a colleague without navigating to `/referral`.  
**Evidence:** `User.referral_code` is generated at signup (`server.py` init_db backfill). The referral programme page is at `/referral`. The welcome email (sent from `mailer.py` after signup) does not include the referral code. The `/app` dashboard (`templates/index.html`) has no referral widget. The `/referral` page is not linked from the main app navigation.  
**Effort:** S (<2h)  
**Sketch:** In `mailer.py`, add `referral_code` and `referral_url` to the welcome email template. In `templates/index.html` (the `/app` dashboard), add a small "Invite a friend" chip in the sidebar that shows the code and a copy button. No new endpoint needed — the code is already on the `User` object passed to the template.  
**Counterargument:** Showing a referral prompt immediately after signup (before the user has gotten value) feels premature and self-serving.  
**Kill criterion:** If referral link clicks from the welcome email represent <1% of total referral traffic after 90 days, remove it from the email.

---

### P17 — Support page live extension check
**Category:** self-serve support and failure recovery  
**Title:** Add a "Test your setup" widget on `/support` that pings the extension and server  
**User value:** A user troubleshooting a failed capture can immediately see whether the extension is connected and the server is reachable, rather than working through a static checklist blind.  
**Evidence:** `templates/support.html` exists as a static troubleshooting page. The ping/pong mechanism (`interview-ace:ping` / `interview-ace:pong` CustomEvents) is already implemented in `content.js` and `onboarding.html`. The popup already does a live `/api/me` fetch on open. Neither of these is reused on the support page.  
**Effort:** M (half day)  
**Sketch:** In `templates/support.html`, add a `<script>` block that dispatches `interview-ace:ping` on page load and listens for `interview-ace:pong` with a 1-second timeout. Show a green/red status badge: "Extension connected" or "Extension not detected." Also do a `fetch('/healthz')` (the existing health endpoint at `server.py:4014`) to confirm the server is up. Display both statuses visually above the static help text.  
**Counterargument:** Users on other devices (phone) who visit `/support` can't run the extension check; the widget would show red confusingly.  
**Kill criterion:** If the widget never shows "connected" for users who subsequently file support tickets (i.e. it's always accurate), it's earning its space; if it shows false positives, remove.

---

### P18 — Token regeneration confirmation flow
**Category:** self-serve support and failure recovery  
**Title:** Make token regeneration a two-step confirm that shows the new token before invalidating the old  
**User value:** Users who accidentally regenerate their token can copy the new one before the old extension connection drops, avoiding a lockout.  
**Evidence:** `POST /api/token/regenerate` at `server.py:5188` immediately writes a new token to `User.api_token` and returns it. The settings page (`templates/settings.html`) shows a "Regenerate" button with no confirmation step. If the user regenerates from a different browser tab or device and then closes the modal before copying, their extension stops working.  
**Effort:** S (<2h)  
**Sketch:** In `templates/settings.html`, add a JS confirmation modal that: (1) warns "Your extension will disconnect immediately"; (2) calls `POST /api/token/regenerate`; (3) shows the new token in a copyable `<input readonly>`; (4) shows a "Done — I've copied it" button that closes the modal. The backend endpoint requires no change. Add a 30-second clipboard copy hint before auto-dismiss.  
**Counterargument:** The extra modal step is friction for power users who know what they're doing.  
**Kill criterion:** If support tickets for "I regenerated my token and now can't connect" drop to zero after the change, the problem was real; if they never existed, the change was preventive overhead.

---

### P19 — Keyboard focus rings and skip navigation
**Category:** accessibility  
**Title:** Add visible focus indicators and a skip-to-content link on all pages  
**User value:** Keyboard-only users and screen reader users can navigate the landing page and app without a mouse.  
**Evidence:** `css/landing.css` imports fonts from Google Fonts and uses CSS custom properties but has no explicit `:focus-visible` rules for interactive elements. `templates/base.html` has no `<a href="#main" class="skip-link">Skip to content</a>` element. The landing page hero CTA (`ia-btn-primary`) is a plain `<a>` — its focus state depends on browser defaults, which are often removed by CSS resets.  
**Effort:** S (<2h)  
**Sketch:** In `css/landing.css` and the shared `base.html` `<style>` block, add: `:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }` globally. Add a skip link as the first element in `base.html` `<body>`, styled off-screen until focused. Run `axe` or `Lighthouse > Accessibility` to verify score improvement.  
**Counterargument:** The product's target demographic (software engineers) overwhelmingly uses a mouse; accessibility investment may have near-zero user impact short-term.  
**Kill criterion:** There is no practical kill criterion for legal baseline accessibility; keep it.

---

### P20 — Screen reader announcements in the response stream
**Category:** accessibility  
**Title:** Add `aria-live="polite"` to the SSE answer stream container  
**User value:** Blind candidates using a screen reader hear AI responses read out as they stream in, without having to navigate to the element manually.  
**Evidence:** `templates/index.html` (the `/app` dashboard) renders the SSE response chunks into a DOM element. The SSE handler in the page script appends text to this container. There is no `aria-live` attribute on the container, so screen readers never announce the streamed content. There is also no `role="status"` or `aria-atomic` attribute.  
**Effort:** S (<2h)  
**Sketch:** In `templates/index.html`, add `aria-live="polite" aria-relevant="additions"` to the response container element. For the "Analysing…" working indicator, add `role="status"` so screen readers announce when processing begins. Test with NVDA + Chrome.  
**Counterargument:** Screen reader users would find continuous chunk-by-chunk announcements disruptive; `polite` may still interrupt them at the wrong moment.  
**Kill criterion:** If any screen-reader-dependent user reports the live region is disruptive, switch `aria-live` to `off` and add a "Read response" button instead.

---

### P21 — Hotkey conflict detection
**Category:** core extension UX during a live interview  
**Title:** Detect and warn about hotkey conflicts at arm-time  
**User value:** Users whose default Ctrl+Shift+7 is taken by another extension or their OS see a warning before they're mid-interview pressing a hotkey that does nothing.  
**Evidence:** `background.js` registers hotkeys via `chrome.commands` (implied by manifest defaults). When the hotkey is taken, the command simply never fires — the user presses the key and nothing happens. The popup has no conflict-detection UI. `HOTKEY_DEFAULTS` in `server.py:478` lists five default bindings, all on Ctrl+Shift+[5-9].  
**Effort:** M (half day)  
**Sketch:** In `popup.js`, call `chrome.commands.getAll()` on popup open. Check if any command's `shortcut` is empty string — Chrome sets this when there's a conflict with another extension. If any assigned hotkey is `""`, show a warning badge next to the arm button: "⚠ Capture hotkey has no binding — set one in `chrome://extensions/shortcuts`." Link directly to that Chrome page.  
**Counterargument:** `chrome.commands.getAll()` reports the shortcut as defined in the manifest, not whether it's conflicted at the OS level — so the check may miss OS-level conflicts.  
**Kill criterion:** If fewer than 2% of users ever have an empty shortcut (no conflict), the check is wasted UI noise → remove.

---

### P22 — Audio hold-to-record abort on long silence
**Category:** core extension UX during a live interview  
**Title:** Auto-submit audio after 2 seconds of trailing silence instead of requiring key-up  
**User value:** Users who finish speaking but forget to release the key don't waste a full session on a dangling audio capture.  
**Evidence:** `background.js` handles `Ctrl+Shift+8` (audio hotkey): press → start recording, release → stop and submit. The offscreen document records a continuous stream. There is no silence detection (VAD) in `offscreen.js`. If a user holds the key too long, they submit a long audio file with silence at the end, wasting OpenAI transcription tokens and adding latency.  
**Effort:** L (multi-day) — requires VAD integration in `offscreen.js` (Web Audio API RMS or a WebAssembly VAD model).  
**Sketch:** In `offscreen.js`, after recording starts, create an `AnalyserNode` and compute RMS every 200ms. If RMS < threshold for 2 consecutive seconds (2s trailing silence), send a message to `background.js` (`type: 'audio-silence-detected'`). Background then calls `handleAudioStop()`. Also add a max-duration cap (e.g. 120s) to prevent runaway recordings.  
**Counterargument:** Interviewers sometimes pause for 3+ seconds while reading a question aloud; auto-submit on silence would cut off the recording prematurely and submit garbage.  
**Kill criterion:** If >5% of auto-submitted audio clips are shorter than 3 seconds (indicating premature cut-off), disable silence detection.

---

### P23 — CV context upload progress indicator
**Category:** self-serve support and failure recovery  
**Title:** Show a progress/spinner during CV extraction and return a word count on success  
**User value:** Users who upload a long CV know the compression is running and see confirmation that their context was saved.  
**Evidence:** `POST /api/settings/context/extract` at `server.py:5097` calls `_compress_context_text()` which itself calls `_stream_ai_response()` — a potentially 2–5 second Anthropic API call. The settings page (`templates/settings.html`) submits this via a form or fetch, but there is no `track()` call and no loading state specified in the template. Users who click "Extract" and see no feedback sometimes click again, submitting duplicate requests.  
**Effort:** S (<2h)  
**Sketch:** In `templates/settings.html`, on the CV extract button click handler, disable the button and show a spinner text ("Extracting…"). On the server response, re-enable and show "Saved — X words of context active." In `server.py:5097`, add `track(user.id, "cv_context_extracted", word_count=len(compressed.split()))` after the extraction completes.  
**Counterargument:** The feedback UI complexity is higher than the problem frequency; most users upload their CV once and never touch it again.  
**Kill criterion:** If duplicate extract requests drop to <1% after the change, the fix worked. If they were already <1%, the UX was good enough.

---

### P24 — Interview context slot discoverability
**Category:** activation & first-run onboarding  
**Title:** Promote the company-specific interview context feature during onboarding step 5  
**User value:** Users who are about to open a LeetCode problem can immediately add the company name and role to their context, getting more targeted AI responses.  
**Evidence:** `InterviewContext` (`models.py:87`) supports per-company context slots (`slot` 1..MAX_CONTEXTS_PER_USER). These are configured in `/settings` under the "Interview context" sidebar section. The onboarding flow (`onboarding.html` step 5) just asks the user to open a coding platform. There is no mention of the context feature during onboarding; users likely discover it much later, if at all.  
**Effort:** S (<2h)  
**Sketch:** After `obComplete(5)` in `onboarding.html`, before the "start trial" CTA, add a collapsible "Optional: add company context" panel with a text field for company name and role. On submit, POST to `/api/settings/context` with `slot=1`. If the user skips, log nothing. This surfaces the feature at the highest-intent moment — about to open a real coding platform.  
**Counterargument:** Adding a form to step 5 lengthens onboarding just before the trial CTA; users may abandon rather than fill it in.  
**Kill criterion:** If step-5 → trial-start conversion drops by >5%, collapse the panel to a "Skip" + "Add context" CTA pair.

---

### P25 — First-capture milestone event and celebration
**Category:** retention after the first successful session  
**Title:** Track and celebrate the first successful capture  
**User value:** New users get positive feedback at the exact moment the product works for the first time.  
**Evidence:** No `first_capture` PostHog event exists (confirmed by reviewing all `track()` calls in `server.py`). `UsageDaily.capture_count` is incremented at `server.py:1015` but there is no code that checks "is this their first ever?" to trigger a celebration. The `/app` dashboard has no "first time" state. The `trial_started` event (`server.py:4688`) fires when the session begins, not when the first answer streams in.  
**Effort:** S (<2h)  
**Sketch:** In `_account_bookkeeping()` inside `api_capture` (`server.py:4748`), after `_record_usage()`, query `UsageDaily` for total historical `capture_count` for this user. If the grand total is exactly 1, set a flag in the broadcast payload: `await broadcast(r, user.id, "first_capture", {})`. In `templates/index.html`, handle this SSE event with a one-time "🎉 First capture — nice!" toast. Add `track(user.id, "first_capture")` here too.  
**Counterargument:** The dashboard already streams the AI response — a toast on top of it clutters the moment of highest attention.  
**Kill criterion:** If the `first_capture` event is never used in any PostHog funnel after 90 days, remove the toast but keep the track call.

---

### P26 — Announce when trial starts from the dashboard (not just onboarding)
**Category:** activation & first-run onboarding  
**Title:** Surface the 10-minute trial clock prominently in `/app` when the session starts  
**User value:** Users who start their trial from the dashboard (not the onboarding CTA) know exactly how long they have.  
**Evidence:** `POST /api/trial/start` at `server.py:4668` broadcasts `session_started` with `expires_at` and `seconds_remaining`. The dashboard SSE handler in `templates/index.html` receives this event, but the session timer chip (in `templates/settings.html:44`) is rendered server-side based on `active_session_expires_at` — it isn't present if the page was loaded before the trial started. Users who click "Start test run" from the dashboard see no countdown.  
**Effort:** S (<2h)  
**Sketch:** In `templates/index.html`, listen for the `session_started` SSE event and inject a countdown chip into the page header dynamically (same CSS as `sidebar-session-timer`). On `trial_expired` SSE event, show a soft paywall overlay instead of a hard redirect. No server change needed.  
**Kill criterion:** If users spend more than 3 minutes on `/app` after trial expiry (indicating confusion about the paywall), the overlay approach is wrong → revert to the redirect.  
**Counterargument:** The hard redirect to `/trial-end` is more decisive; soft overlay may cause users to think there's still time remaining.

---

### P27 — Partner withdrawal ETA communication
**Category:** self-serve support and failure recovery  
**Title:** Show expected payout timeline on the partner dashboard  
**User value:** Partners who requested a withdrawal know when to expect payment without emailing support.  
**Evidence:** `Withdrawal` model (`models.py:147`) has `status` (requested/paid/rejected) and `created_at`. `/partner/dashboard` (`server.py:2453`) passes withdrawal history to the template. `partner/dashboard.html` shows withdrawal rows but there is no SLA or expected-date text. Every `requested` withdrawal requires manual admin action (`partner/admin/withdraw/{id}/approve`) with no ETA communicated.  
**Effort:** S (<2h)  
**Sketch:** In `templates/partner_dashboard.html`, for each withdrawal in `requested` status, display "Expected within 5 business days of [created_at + 5bd]." In `partner_admin.html`, add an optional "estimated payout date" field that partners can see. No DB change needed if SLA is fixed.  
**Counterargument:** Publishing an SLA creates a support obligation; if admin is on holiday and misses it, partners have grounds for complaint.  
**Kill criterion:** If partner support tickets about withdrawal status drop to zero after the ETA text is added, keep it.

---

## 3. Ranked Shortlist — Top 10 by Value ÷ Effort

1. **P1 — Onboarding step funnel tracking** (S effort, immediately actionable signal)  
   A two-hour change that turns a black-box onboarding flow into a visible funnel. If 40% of users drop at step 2, every subsequent onboarding change is informed. Highest ratio of insight per hour invested.

2. **P25 — First-capture milestone event** (S effort, retention anchor)  
   The single most important activation signal — "did they get an answer?" — is currently unmeasurable. Adding it takes an afternoon and unlocks day-1 retention analysis.

3. **P9 — Visible Claude→OpenAI failover signal** (S effort, trust + clarity)  
   Every unexplained slow response is a silent churn signal. A one-line SSE event plus a toast turns a trust-eroding mystery into a reassuring system message.

4. **P13 — Low-sessions warning email** (S effort, direct revenue protection)  
   A user who hits `sessions_exhausted` mid-interview churns. A 2-hour code change emails them at 1 remaining. The LTV impact of preventing even one churn per week justifies it.

5. **P5 — Pre-interview setup-check deep link in reminder email** (S effort, retention)  
   The reminder infrastructure already exists (`_send_due_interview_reminders`). Adding a deep link to the reminder email that auto-runs a ping check is a one-line mailer change with immediate utility.

6. **P16 — Referral code in welcome email** (S effort, distribution)  
   Users are most enthusiastic about the product immediately after it works. A referral link in the welcome email captures that moment. Zero backend work; mailer template edit only.

7. **P19 — Visible focus rings and skip link** (S effort, accessibility baseline)  
   Legal floor, two-hour fix. Doing it now avoids a rushed accessibility patch later. No kill criterion because it's a baseline, not a feature experiment.

8. **P3 — Trial-end page context recap** (M effort, conversion)  
   The trial-end page is the product's highest-leverage conversion surface. Showing usage stats takes half a day and anchors the upgrade CTA in demonstrated value, not hope.

9. **P17 — Support page live extension check** (M effort, support deflection)  
   Every support ticket about "my capture stopped working" starts with "is the extension connected?" Surfacing the answer on `/support` deflects those tickets before they're filed.

10. **P7 — Interview-mode popup focus** (M effort, core UX)  
    The popup during a live interview is noise. Collapsing config when armed takes half a day and makes the one thing that matters — arm status — the only thing on screen.

---

## 4. Cut List — 5 Things to Remove or Simplify

### C1 — Typing passthrough hotkey (Ctrl+Shift+5) and `typing_passthrough` column
**What it is:** `User.typing_passthrough` (`models.py:67`), `User.hotkey_typing` (`models.py:65`), `HOTKEY_DEFAULTS["typing"]` (`server.py:478`), and the corresponding `POST /api/settings/passthrough` endpoint.  
**Case for removal:** There is no evidence in the codebase or templates that this feature has a UI entry point visible to normal users — no settings card explains what "typing passthrough" means. It occupies a hotkey slot (Ctrl+Shift+5) that conflicts with default tab-switching shortcuts in some terminal emulators. A fifth hotkey to explain during onboarding adds cognitive overhead with unclear user value. If no user has ever changed `typing_passthrough` from the default, it's dead weight.

### C2 — Dual response-style sync (popup + settings page)
**What it is:** Response style is set via pills in both `popup.js` (which calls `POST /api/settings/style` with Bearer auth) and `templates/settings.html` (which calls `POST /api/settings/response-style` with cookie auth). The popup also writes to `chrome.storage.local` (`response_style`).  
**Case for removal:** Two sync paths mean the popup and settings page can drift out of sync (e.g. if the server call in the popup fails silently). Simplify to a single source of truth: read and write style only through the server (cookie-auth settings page), and have the popup's saved value be read-only / display-only, refreshed on open via `GET /api/me`. This removes `POST /api/settings/style` (Bearer variant) and the local-storage write.

### C3 — `intro_declined` column
**What it is:** `User.intro_declined` (`models.py:58`) is set somewhere in the billing flow when a user explicitly declines the intro deal.  
**Case for removal:** A search of the codebase shows this column is written but never read to change any behaviour — there is no branching on `intro_declined` in `server.py` or any template. It does not prevent the intro card from showing (that's `intro_redeemed`). It is never passed to PostHog. The column exists without a function. Drop it and migrate the DB.

### C4 — `partner_tier = 0` vs `partner_tier = 1` distinction
**What it is:** `User.partner_tier` (`models.py:76`) uses `0` and `1` to represent the same "implicit flat Tier 1" status, with `2` = 15% and `3` = 25%. Comments in the model acknowledge this ("0/1 = implicit flat Tier 1").  
**Case for removal:** Two values representing the same tier creates a branch in every piece of code that compares `partner_tier`. Simplify: use `1` uniformly as the base tier, write a migration that sets all `partner_tier = 0` rows to `1`, and remove the `0` case from any conditional. This is a pure refactor with no user-visible change.

### C5 — `AUTHOR_PASSWORD` / `/verify-author` auth path
**What it is:** `config.py` defines `AUTHOR_PASSWORD`; `server.py:2215` implements `_require_author` which checks a submitted password against it; `/verify-author` is a separate auth path for internal admin pages.  
**Case for removal:** The product already has an admin area gated by Django-style session auth (`get_current_user` + admin flag check). A second, password-only auth path for "author" is a parallel credential system that doesn't benefit from the same session expiry, CSRF protection, or rate limiting as the main auth. There is no `is_author` field on `User`; the check is purely password-based. If the page(s) behind it are worth protecting, gate them with the existing admin session auth. If they're not, delete them.
