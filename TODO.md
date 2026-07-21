# TODO

## Now

- [ ] error 500 page (created - need reverse proxy)
- [ ] hot restart breaks on server.py changes
- [ ] light mode theme changes
- [ ] social proof improvements
 
## Soon 
- [ ] typing mode to edit question - not start new question
- [ ] google login
- [ ] shorten landing page
- [ ] dark mode text can be hard to read
- [ ] find new name 
- [ ] change AI content 
- [ ] change stop blanking, start acing tagline
- [ ] accidental session start warning for session users 



## Later

- [ ] Desktop app with invisible-to-screen-share overlay (native, not a plain extension port)
- [ ] Video demonstration for landing page
- [ ] zero downtime deploy
- [ ] privacy via termly
- [ ] terms and conditions
- [ ] refund policy
- [ ] cookie policy

## Done

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
