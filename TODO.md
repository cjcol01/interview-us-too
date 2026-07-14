# TODO

## Now

- [ ] trial-end page needs updating and navbar
- [ ] navbar on all pages renders conditionally for logged in/ logged out state
- [ ] do i want db in new place?

## Later

- [ ] Desktop app with invisible-to-screen-share overlay (native, not a plain extension port)
- [ ] Video demonstration for landing page
## Done

- [x] Widen main app page (index.css 600→680px) and onboarding (onboarding.css 580→640px) on desktop
- [x] Tighten up features — bento trimmed from 6 tiles to 4, equal-width 2x2, green accent icon on "Streams to your phone"
- [x] Add "or see our full pricing page for more details" to footer pricing nudge + fixed footer Pricing link to point at /pricing
- [x] Add FAQ "How we compare" section — 3 generic competitor-comparison entries (no names)
- [x] Improve onboarding clarity — tightened step 2 copy, collapsed advanced hotkeys/callouts (replay, typing, passthrough) behind an optional toggle
- [x] Changed pricing to £15/month unlimited (landing.html, landing_prep.html hardcoded text; STRIPE_SUB_PRICE_PENCE already updated)
- [x] Investigated /settings?offer=claimed — confirmed it applied NO real discount, just a misleading "50% off applied" banner. Fixed: banner now gated on user.retention_offer_claimed (the real DB flag set only by POST /billing/offer), so typing the URL directly no longer shows a false claim.
- [x] Enlarged the landing hero demo (grid ratio + demo stage height) to fill more of the right column, as a substitute for landing-page respacing (that concern turned out to be about /app, handled above)
