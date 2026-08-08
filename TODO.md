# TODO

## immediately
- [x] add syntax highlighting to demo
- [ ] onboarding skip setup button - you cant come back here from settings
- [x] relax password rate limiting (2 passwords in 5 seconds is allowed)
- [ ] stop space bar scrolling in typing mode
- [ ] if instant replay or audio is empty, dont send anything, (currently sends gobbledegook)
- [ ] pricing page, ensure cancel anytime is clear
- [ ] undetectability work needs doing (can we change id dynamically, change name, change icon)
- [ ] https://claude.ai/code/artifact/24206334-f8e7-4fcd-9120-15ccd8634eb8 implement 2C
- [ ] change all input selector types to show code (bullets, one liner - maybe exclude that dk)
- [ ] check all spacing on settings page.
- [ ] typing preview, in the same note style as others
- [ ] extension connected/ reconnect in settings could be made more reliable
- [ ] buy alternate domains similar to interview-wise?

## Now
- [ ] cancel page revamp, text and maybe some visual. (mostly done - check)
- [ ] create videos for support, install, sideload, landing
- [ ] setup check before real interview without starting session. 
- [ ] I got the job, referral system, pause instead of cancel
- [ ] Let the mobile demo run free and ask for the email at the end as "where should I send your install link?" - https://claude.ai/share/c8563073-4545-43fe-a1a9-4019f586da9f
- [ ] light mode visual check (settings, cancel page navbar, text hard to read)
- [ ] exit button on mobile takes to landing, probably should take to settings
- [ ] footer links blcoked
- [ ] non links on CWS
- [ ] non links on privacy and TCs
- [ ] navbar gap
- [ ] low contrast text
- [ ] 1,2,3 on homepage
- [ ] clear up instant replay wording
- [ ] can we detect phone scan via qr code?
- [ ] unlimited allows setup test and practise with friend

## Soon 
- [ ] dark mode text can be hard to read
- [ ] find new name 
- [ ] change AI content 
- [ ] change stop blanking, start acing tagline
- [ ] some kind of alert system for health checks directly to mobile
- [ ] undetectability FAQ's try fhonest assessment
- [ ] test job in github actions
- [ ] auto top up sessions - toggle that rebuys 3 sessions when down to 1. Needs off-session card charging: current Stripe checkout never saves a reusable card (no `setup_future_usage`, no stored payment method). Would need checkout to save a card + an off-session PaymentIntent + SCA/decline handling; only works for purchases made after the change ships.
- [ ] investigate postgres
- [ ] proper on call esque alerts for major server issues, one api (ais) going down, failures, api credit run out etc
- [ ] loadtest (locust, LOADTEST_RAMP=1) wedges the whole server around ~800 concurrent users even after fixing async routes that blocked the event loop (settings_page, api_capture, auth routes etc. now use run_in_threadpool). Real cause: SQLAlchemy pool_size=20+max_overflow=20=40 (database.py) and AnyIO's default thread pool (also 40) both saturate around the same point — every request holds a DB connection/thread for its full duration, so >40 concurrent DB-touching requests queue and cascade into a total stall. Raise both pool sizes (together) if we ever expect real concurrency near that.
- [ ] make a reel get something free
- [ ] target salesman
- [ ] investigate cluely features and competitors + reviews


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

- [x] center pricing info on landing when user is trial or sessions — pure CSS: `.ia-plan:only-child` in landing.css makes a lone pricing card span both grid columns and centre (max-width 480px, auto margins) instead of sitting in the left column. Both cards still show for trial (kept intentionally); only the single-card case (sessions user sees Unlimited only) is affected.
- [x] add another status light on /app for anything stopping the product from working — new generic "Alert" light in the Ext/Mic/Replay row, hidden until there's a problem, hover/tap for detail, most-severe alert sets the LED colour. A central `ALERT_CONFIG` map in index.html toggles each alert on/off individually. Alerts: no_plan / no_sessions / low_sessions / sub_cancelling (on); session_ending / rate_limited / approaching_limit (off by default, since the first two already have their own bar/toast). Server seeds account state via `_compute_account_alert()`; live JS hooks cover session-ending, rate-limit, and nearing the per-window capture cap. `.hk-status-dot[hidden]` CSS added so the hidden attribute actually hides it.
- [x] syntax highlighted code on /app — was doubly broken: (1) the page loaded highlight.js's CommonJS build (`highlight.js@11/lib/*`, `module.exports=…`) which never defines a browser `hljs` global, so every highlight call silently threw; (2) a `#analysis code { color: var(--danger) }` rule meant for inline code out-specified `.hljs` and painted block-code text red ("all red"). Fixes: switched to the browser bundle `@highlightjs/cdn-assets@11/highlight.min.js` (global hljs, ~40 langs), pinned marked to `@15`, scoped the red rule to `#analysis :not(pre) > code`, and replaced marked's removed `highlight` option with a post-parse `hljs.highlightElement` pass. Also added live highlighting during streaming (chunk handler re-highlights the growing buffer, throttled to one pass per animation frame).
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
- [x] after create account, welcome message
- [x] github sign in
- [x] check mobile /welcome page. if phone takes up too much space, have it pop up when the phone is the focus and drop down half off page when its not
- [x] simplify landing page
- [x] upload cv and shorten to 2000 chars via haiku (is 2k the right limit?)
- [x] copy buttons broken in support page (on mac)
- [x] how'd the interview go question and feedback
- [x] email me a link at login (for conversion from mobile)
- [x] improve status indicators
- [x] interview date on sign up for follow up email.
- [x] add a next interview date in settings
- [x] after welcome, tell people they can change hotkeys at any time
- [x] de case sensitive username  
- [x] show password button on login and create account so users can see what they typed.
- [x] welcome already done page can surface after demo call - unformatted and flashes up. looks bad
- [x] settings page, check horizontal dividing line on shortcuts/ spacing
- [x] settings mobile refresh (nearly done, a bit wider then the phone) - check first
- [x] cancel page revamp, text and maybe some visual.
- [x] shorten landing page
- [x] skip buttons now confirm before skipping - welcome, welcome_next, onboarding setup (not the low-stakes per-step skips)
- [x] back to the demo link on onboarding - the page didn't load the demo at all before, so that got wired up too
- [x] prop your phone up tip promoted from a plain line to a bordered callout on onboarding
- [x] removed the hotkey list from onboarding - kept the instant replay and typing explainers, only the key combos went
- [x] arm/disarm - turn on/turn off in every user-visible string, site and extension (code identifiers left alone)
- [x] light/dark toggle on onboarding, same control as landing
- [x] first demo round slowed 25% and second 10% so the first hotkey run is readable - response delay and typing speed unchanged
- [x] history nav on /app always shows now, disabled until there's an older answer, instead of hiding until 2+ answers
- [x] new default hotkeys - ctrl+shift+6 screen, 7 voice, 8 instant replay, 9 typing, 0 on/off (updated in all five places)
- [x] removed the context and hotkey links from trial-end so users don't wander mid-funnel, with a line saying they're set up later
- [x] run a system check on trial-end is now an outline button instead of a text link buried in a footer
- [x] testimonial scroll speed is time-based now, so it's the same on 60/120Hz instead of literally 2x on a ProMotion screen
