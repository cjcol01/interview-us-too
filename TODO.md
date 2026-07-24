# TODO

## Now

- [x] check mobile /welcome page. if phone takes up too much space, have it pop up when the phone is the focus and drop down half off page when its not
- [ ] after welcome, tell people they can change hotkeys at any time
- [ ] investigate postgres
- [ ] loadtest (locust, LOADTEST_RAMP=1) wedges the whole server around ~800 concurrent users even after fixing async routes that blocked the event loop (settings_page, api_capture, auth routes etc. now use run_in_threadpool). Real cause: SQLAlchemy pool_size=20+max_overflow=20=40 (database.py) and AnyIO's default thread pool (also 40) both saturate around the same point — every request holds a DB connection/thread for its full duration, so >40 concurrent DB-touching requests queue and cascade into a total stall. Raise both pool sizes (together) if we ever expect real concurrency near that.
- [ ] add different prompts for different use cases (image, typing etc)
- [ ] Paste this token into the extension popup along with your server URL
- [ ] settings mobile refresh
- [ ] proper on call esque alerts for major server issues, one api (ais) going down, failures, api credit run out etc


## Soon 
- [ ] shorten landing page
- [ ] dark mode text can be hard to read
- [ ] find new name 
- [ ] change AI content 
- [ ] change stop blanking, start acing tagline
- [ ] some kind of alert system for health checks directly to mobile
- [ ] undetectability FAQ's honest assessment
- [ ] test job in github actions
- [ ] auto top up sessions - toggle that rebuys 3 sessions when down to 1. Needs off-session card charging: current Stripe checkout never saves a reusable card (no `setup_future_usage`, no stored payment method). Would need checkout to save a card + an off-session PaymentIntent + SCA/decline handling; only works for purchases made after the change ships.



## Later

- [ ] Follow-up hotkey — let the candidate type a clarification to the AI's *previous* answer (e.g. "now do it recursively") instead of starting a fresh question. Sent to the same underlying "chat" so the reply has context of what was already said.
  - New 6th hotkey (`hotkey_followup`) — same keydown/buffer plumbing as the existing `typing` hotkey in `content.js`/`background.js`, so extension-side work is mechanical
  - Needs a DB migration: new nullable `User.hotkey_followup` column, plus entries in `HOTKEY_DEFAULTS`, `_user_hotkeys()`, `HotkeySettings`, and a settings.html row
  - Server currently has **no memory** of the last answer to build on — only `/api/capture` (screenshot) persists `analysis` to Redis, and even that has no turn/prompt structure; `/api/text-capture` and `/api/audio-capture` don't persist anything past the SSE push. Needs a short-TTL "last Q&A" Redis entry per user
  - All 3 capture endpoints currently send Claude a single-turn `messages` array — the follow-up needs `messages: [prior instruction, prior answer, new instruction]` instead
  - Cost: verified via `count_tokens` against the live model (`claude-sonnet-4-6`) — a single follow-up adds an almost negligible ~$0.0007 (re-sending the ~250-token prior text answer as context). The one hard rule: **never re-send the original screenshot** in that history — only carry forward the text answer. Doing it naively (resending images) roughly 5-6x's the cost of a multi-turn session; doing it right (text-only history, ideally + prompt caching) keeps a full session to ~1.3-2x today's cost
- [ ] Desktop app with invisible-to-screen-share overlay (native, not a plain extension port)
- [ ] Video demonstration for landing page
- [ ] zero downtime deploy
- [ ] privacy via termly
- [ ] terms and conditions
- [ ] refund policy
- [ ] cookie policy
- [ ] convert to desktop app and get code signed (PITA)
- [ ] error 500 page (created - need reverse proxy)


## Done

- [x] accidental session start warning for session users — Settings page (Shortcuts section) now shows an amber notice for `paid` account-level users explaining that pressing the capture hotkey with the extension on starts a session immediately (no confirmation popup), spending one of their remaining sessions
- [x] improve admin page with billing state, error rate, resend failures, rate limit headroom, Sideload/CDN fallback reachability — new "Metrics" section on /admin/health: DB disk usage (main + WAL/SHM), billing summary (active subs / session users / low-session users / pending cancellations), resend email failures + HTTP 5xx error rate (rolling 24h Redis counters), per-endpoint rate-limit activity vs configured limits, and a new Sideload CDN/mirror reachability deep check. Backup time data skipped — no backup mechanism exists yet to report on (see OPS_PLAN.md)
- [x] trial-end page navbar now uses the standard show_navbar layout (auth-state links) instead of its own custom header
- [x] verified trial-expiry -> "subscription required" flow end to end (server + extension popup + monitor page all already wired; full test suite green)
- [x] reworded pricing page stat so "4-6 months" reads as avg. job-search length, not an InterviewAce commitment (added "cancel anytime" framing elsewhere)
- [x] added scrolling social-proof testimonial bar to landing page (placeholder reviews, labeled "Early access feedback" — swap for real beta-tester reviews before public launch)
- [x] do i want db in new place?
- [x] get ssh working into server
- [x] set up stripe and redis if required on server
- [x] check above 2 are worth it if migrating to VPS or similar
- [x] Widen main app page (index.css 600→680px) and onboarding (onboarding.css 580→640px) on desktop
- [x] Tighten up features — bento trimmed from 6 tiles to 4, equal-width 2x2, green accent icon on "Streams to your phone"
- [x] Add "or see our full pricing page for more details" to footer pricing nudge + fixed footer Pricing link to point at /pricing
- [x] Add FAQ "How we compare" section — 3 generic competitor-comparison entries (no names)
- [x] Improve onboarding clarity — tightened step 2 copy, collapsed advanced hotkeys/callouts (replay, typing, passthrough) behind an optional toggle
- [x] Changed pricing to £15/month unlimited (landing.html, landing_prep.html hardcoded text; STRIPE_SUB_PRICE_PENCE already updated)
- [x] Investigated /settings?offer=claimed — confirmed it applied NO real discount, just a misleading "50% off applied" banner. Fixed: banner now gated on user.retention_offer_claimed (the real DB flag set only by POST /billing/offer), so typing the URL directly no longer shows a false claim.
- [x] Enlarged the landing hero demo (grid ratio + demo stage height) to fill more of the right column, as a substitute for landing-page respacing (that concern turned out to be about /app, handled above)
- [x] testing script
- [x] navbar on all pages renders conditionally for logged in/ logged out state
- [x] set up server hot reloading?
- [x] stress test site - locust/k6
- [x] create backup plans and security and reliability plans
- [x] light mode theme changes
- [x] social proof improvements
- [x] hot restart breaks (sometimes) on server.py changes — dev reloader was watching screenshots/*.db too; excluded from uvicorn's reload_excludes
- [x] hard to read social proof profile pic texts on white mode — light-mode override for .ia-proof-avatar (darker gradient + dark text)
- [x] add more user action buttons (send expiry reminder, 1 session left, etc) — new admin per-user buttons + emails for cancelling subs and low session-pack balances
- [x] set up open ai backup if claude is down, and whispr backup — Claude failures on capture/text-capture/audio-capture fail over to OpenAI vision (gpt-4o); Whisper failures fail over to Deepgram if DEEPGRAM_API_KEY is set. Added a Deepgram row to /admin/health deep checks too.
- [x] clean context - only keep x messages or purge old ones if not discussed
- [x] typing mode to edit question - not start new question
- [x] check loadtest - login/bcrypt writes should only happen once — locustfile.py now always uses a pre-minted session cookie from seed_users.py, no /auth/login POST during the ramp at all
- [x] pull onboarding4 
- [x] hotkey doesnt turn off extension
- [x] add see fix to mic and IR on support page
- [x] clear up wording on support page - detechify
- [x] investigate why server starts quckly on mac but slow on pc
- [x] google login
