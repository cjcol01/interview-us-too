# InterviewWise — Pre-Deployment Roadmap

> Work top-to-bottom. Blockers and security must be done before going live.
> Use `[x]` when done, `[!]` if it needs a note.

---

## ⚠️ VERIFY BEFORE LAUNCH — Subscription referral credit

> Subscription credit (referral_credit_pence) deducts from the DB via `invoice.paid` by reading
> the Stripe customer balance delta. This was NOT end-to-end tested because manual DB edits don't
> mirror to Stripe balance. **Must test the full flow:** earn credit via real referral → referee
> subscribes → check that (a) Stripe auto-applies the balance to the first invoice and (b)
> `referral_credit_pence` is deducted in the DB after `invoice.paid` fires.
> Key code: `billing.py _credit_referrer`, `_handle_invoice_paid`.

---

## 🔴 Blockers (must fix before launch)

### Security
- [ ] Tighten CORS: change `allow_origins=["*"]` to your actual domain (`server.py:48`)
- [ ] Enable card fingerprinting for the £2 intro deal — currently toggled off in dev (`billing.py:142-183`)

### Config
- [ ] Update `BASE_URL` — currently hardcoded to LAN IP `192.168.4.21:8000` (`config.py:31`)
- [ ] Set all required env vars in production (see list below)


### Bugs


---

## 🟡 Infrastructure & Hosting

- [ ] Choose a host: Railway / Render / Fly.io / VPS
- [ ] Deploy app and verify it starts cleanly
- [ ] Set environment variables on host:
- [ ] Configure Stripe webhook endpoint → `POST /billing/webhook` on the live domain
- [ ] Set up SSL / HTTPS (most hosts do this automatically)

---

## 🌐 Domain & Email

- [ ] Buy a domain (e.g. `interview-wise.co`)
- [ ] Point domain DNS to host
- [ ] Set up professional support email (e.g. `support@interview-wise.co`) via Resend, Cloudflare, or Google Workspace
- [ ] Update `BASE_URL` and `FROM_EMAIL` in `.env` once live

---

## 🔧 Features & Polish

### ⌨️ Typing Mode (backend + extension + dashboard DONE — docs/UX remaining)
- [ ] Landing page — add "Typing mode" to the feature list alongside screen capture + audio (`templates/landing.html`, `templates/landing_prep.html`, `landing.md`)
- [ ] Tutorial overlay on `/app` — add a step explaining the typing hotkey, Enter-to-send, and passthrough
- [ ] `/onboarding` — show the typing hotkey alongside the others (`templates/onboarding.html`)
- [ ] Extension popup — add typing hotkey hint + passthrough state (was skipped during impl; `extension/popup.html` / `popup.js`)
- [ ] `features.md` — document typing mode
- [ ] README — document the typing hotkey + passthrough (folds into the stale-shortcuts fix below)
- [ ] Decide passthrough default (currently ON) and whether OFF needs a clearer "your typing is invisible" warning in settings
- [ ] Known limitation: Enter submits, so no multi-line typed input (paste still handles multi-line) — confirm acceptable or add a separate send key
- [ ] Known limitation: typed results aren't persisted to the capture hash, so they don't reappear on dashboard reload (same as audio) — confirm acceptable
- [ ] `/api/text-capture` shares the `/api/capture` rate-limit bucket (6/min, 5s cooldown) and deducts a paid session — confirm intended

- [ ] Add a contact form or `mailto` link on landing page footer / settings / pricing
- [ ] Improve site navigation — navbar consistency across pages
- [ ] Add mic settings and mic test
- [ ] Fix audio keyup edge case — any modifier release stops recording (`content.js:85-97`)
- [ ] Show "Trial (expired)" label for expired trial users in settings (not just "Trial")
- [ ] Fix README keyboard shortcut docs — stale (wrong keys, missing audio shortcut)
- [ ] "Buy me a coffee" link / tip jar
- [ ] check mac mic recording symbol - do we need to spoof a mic
- [ ] upload a paragraph before hand of core company info

---

## 🧪 Manual Testing Checklist

> Full browser + Stripe test mode required. See `post_refactor_checklist.txt` for detail.

### Chrome Extension (E2E)
- [ ] Capture hotkey fires and streams analysis into dashboard
- [ ] Audio hold-to-record — REC badge appears, analysis streams on release
- [ ] Typing hotkey starts capture (TYPE badge appears); pressing it again sends buffered text
- [ ] Enter while typing sends the text and ends capture; Enter alone does NOT start capture
- [ ] Passthrough ON — typed text appears in the page field; OFF — nothing appears in the page
- [ ] Typed text shows in the "You typed" box on the dashboard; analysis streams below
- [ ] Typing-mode UI is invisible during screen share (no in-page overlay; badge on toolbar only)
- [ ] Toggle hotkey disables captures; dashboard receives `disabled` event
- [ ] Hotkey changes in `/settings` propagate to extension within ~5 seconds
- [ ] Mic permission: "Grant microphone" button opens tab, requests mic, closes itself
- [ ] Extension reloads correctly without refreshing the tab (`background.js:258-266`)

### Web Pages
- [ ] Landing — signed out and signed in states
- [ ] Login — sign in tab and register tab
- [ ] `/verify-pending` — correct email shown
- [ ] `/onboarding` — API token visible, hotkeys shown, `BASE_URL` correct
- [ ] `/app` — tutorial overlays on first visit; streaming dashboard works
- [ ] `/pricing` — both plan cards render; intro-redeemed state hides sessions plan
- [ ] `/settings` — account level, all four hotkeys (incl. typing), passthrough toggle, API token, billing section
- [ ] `/referral` — referral code shown, referee table renders
- [ ] `/billing/cancel` — confetti + reason form
- [ ] `/billing/success` — polls `/api/billing/status` until account upgrades
- [ ] `/trial-end` — renders without error
- [ ] All pages — no CSS regressions (especially login + app dashboard, changed in `14db733`)

### Auth Flows
- [ ] Register → email verification → land on `/onboarding`
- [ ] Login → session cookie → `/app` reachable
- [ ] `GET /auth/logout` clears cookie, redirects to `/login`
- [ ] `/api/token/regenerate` — old token immediately returns 401

### Billing (Stripe test mode — card `4242 4242 4242 4242`)
- [ ] Sessions plan checkout → `account_level = paid`, `sessions_remaining > 0`
- [ ] Subscription checkout → `account_level = unlimited`
- [ ] In-app cancel → subscription set to cancel at period end → feedback email arrives at `NOTIFY_EMAIL`
- [ ] `customer.subscription.deleted` webhook flips account to `free`
- [ ] Card-fingerprint anti-abuse: second account with same card auto-refunded (prod key only)

### Referrals
- [ ] `/r/{code}` sets ref cookie; registering with it creates a `Referral` row
- [ ] Referee buys intro → referrer gets £2 Stripe credit (note: known broken — verify status)
- [ ] Self-referral blocked at register
- [ ] `/referral/apply` works retroactively if user has no referrer

### Streaming
- [ ] Screenshot analysis chunks stream in word-by-word (not dumped all at once)
- [ ] Audio analysis streams the same way
- [ ] Typed-input analysis streams the same way
- [ ] Whisper transcription for a 5-second clip completes in < ~5 seconds
- [ ] SSE connection stays alive > 30 seconds (important if behind a proxy/nginx)

### Database
- [ ] Delete `users.db`, restart server — `init_db` creates all tables cleanly with no errors

---

## 📦 Chrome Extension Distribution

- [ ] Decide: publish to Chrome Web Store or keep sideloaded
  - Web Store: requires $5 developer account, review process (1–3 days)
  - Sideloaded: write clear install instructions for users
- [ ] If publishing: prepare store listing (screenshots, description, privacy policy)

---

## 📣 Marketing & Launch

- [ ] LinkedIn post / outreach
- [ ] Discord communities (coding, interview prep)
- [ ] Reddit (r/cscareerquestions, r/leetcode, r/programming)
- [ ] TikTok / Instagram demos
- [ ] Direct ads (Google / Meta)
- [ ] Trustpilot — set up profile and request early reviews
- [ ] "Sticker on hand" (lol, noted from plan.txt)

---

## ✅ Already Done