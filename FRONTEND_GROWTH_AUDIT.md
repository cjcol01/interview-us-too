# InterviewAce — Front-End & Growth Audit

_Five parallel read-only audits (visual design, copy, UX/flow, feature opportunities, monetization). Goal: look better, read better, work better, earn more. Nothing was changed._

Date: 2026-05-28

---

## Product & business context (established before auditing)

- **What it is:** A real-time coding-interview assistant. A Chrome MV3 extension captures the interview screen (`Ctrl+Shift+7`), audio question (`Ctrl+Shift+8`), or typed text; a FastAPI server sends it to Claude (sonnet), which returns a solution at a chosen complexity (1–3) / response style, streamed via SSE to a **separate** web dashboard meant for a phone or second screen (so it's off the shared screen).
- **User:** Job-seeking software engineers in remote coding interviews (LeetCode, HackerRank, CoderPad, HireVue, Zoom/Teams/Meet) who want discreet real-time help. **Aha moment** = first capture streams a usable answer to their dashboard.
- **Business model (freemium ladder):** free 10-min trial → **£2 intro** (2 sessions × 2.5h, one-time, card-fingerprint anti-abuse) → **£15 sessions pack** (3 sessions) → **£25/mo unlimited** (7-day free trial). Referral program pays the referrer Stripe credit (£2 on referee's intro, £3–5 on subscribe) and gives the referee £5 off.
- **Tech stack:** FastAPI + Jinja2 server-rendered templates; **hand-written vanilla CSS** (no component library, ~11k LOC, per-page stylesheets); light vanilla JS; dark/light theme via `data-theme` + localStorage. No JS framework.
- **Live landing page:** `landing.html` (confirmed — `LANDING_PROD` defaults to `"1"`, `config.py:43`; `landing_prep.html` is not live).
- **Assumption flagged:** I have **no analytics/conversion/cost data** (PostHog is wired but not readable here). Every "loss-leader / cannibalization / drop-off" claim is inferred from the product structure, not measured — validate against funnel data before acting on revenue cuts.

---

## Executive summary

**As a paying user would see it:** the product has genuine craft in patches — the landing page's animated demo and the cancel/retention flow are premium-grade — but it reads as **built page-by-page, not as a system.** Buttons, cards, and `kbd` styles are redefined on every page; light mode silently breaks the moment you leave the homepage; and the conversion-critical fine print (the "£10 regular" anchor, "no card saved" reassurance, referral payout terms) is styled at near-invisible contrast. More fundamentally, the **path to the first answer is ~15 steps across two devices with two logins and a broken install link**, the **trial clock burns on a button click rather than the first capture**, and there's **almost nothing that brings a user back between interviews** — a structural churn problem the £25/mo tier depends on solving. On revenue, several leaks give away margin (audio captures aren't session-gated, the £2 intro buys ~5h of unlimited AI, the 7-day sub trial is uncapped, referrers get paid on the £2 intro).

### Top 5 highest-leverage changes

1. **Fix the path to "aha."** Replace the placeholder Web Store link (`onboarding.html:35`), start the trial timer on **first capture** not button click (`server.py:663`), and add a QR/short-code so the phone logs in by scanning instead of re-typing a password. This is the difference between users reaching the answer and bouncing.
2. **Plug the revenue leaks.** Session-gate audio capture (`server.py:816` — currently free for out-of-credit paid users), cut the intro to 1 session, cap the 7-day sub trial, and stop paying referrers on the £2 intro. Pure margin, mostly small effort.
3. **Make it a system, not 12 pages.** Promote one `.btn-primary`, `.card`, `.kbd`, `.copy-btn` into `global.css`; fix light mode app-wide (or drop the landing toggle); add a global `:focus-visible` ring. Kills the "template-y / unfinished" feel.
4. **Fix the invisible value copy + price contradiction.** Landing says intro is "usually £15"; checkout says "£10 regular" — reconcile. Lift all near-invisible muted/fine-print text (strikethrough price, "no card saved", referral terms, dashboard empty state) to a legible token.
5. **Attack one-and-done churn.** Persist capture history server-side (today it's overwritten), then build the retention layer: post-interview review, prep-context upload, and a "Pause subscription" option for the structural "I got the job" churn.

### Cross-cutting themes
- **No design system** → component drift + accessibility gaps (no focus states, contrast failures on conversion copy).
- **Heavy aha path** → setup friction is the biggest conversion risk, ahead of pricing.
- **Amnesiac product** → nothing persists, so nothing brings users back; retention features are all blocked on server-side history.
- **Margin leaks** in gating + trial + referral that compound with already-thin first-month economics.
- **Bright spots to replicate:** the cancel/retention flow and landing demo show the team *can* build premium UX — the rest of the app should match them.

---

## Findings — sorted by impact (deduplicated across the 5 audits)

Impact: **H** high · **M** medium · **L** low. Dim = Visual / Copy / UX / Feature / Money. Effort: S/M/L. · **[x]** in the # column = implemented (as of 2026-05-29).

| # | Imp | Dim | Location | Current state | Suggested change | Eff |
|---|-----|-----|----------|---------------|------------------|-----|
| 1 | H | UX | `onboarding.html:35` | "Add to Chrome" links to `.../interviewace/placeholder` — 404; only real install is dev-mode unpacked, never mentioned | Point to real Web Store URL, or show inline sideload steps until published. Never ship a placeholder in the primary CTA | S |
| 2 | H | UX | `server.py:663` `/api/trial/start` | 10-min trial clock starts on button click regardless of setup → the one trial gets burned doing nothing | Start the timer on the **first successful capture**; until then show "trial ready — make your first capture" | M |
| 3 | H | UX | `onboarding.html:117` | Phone/2nd-screen requires a **second manual login** (type password on phone) right before the payoff | Generate a one-time QR/short-code on the "move to your phone" step → one scan logs the phone in | M |
| 4 | H | Money | `server.py:816` `api_audio_capture` | No paid-session gating block (unlike capture/text-capture) → out-of-credit paid users get free Whisper+Claude audio | Add the same `account_level==paid` session check/deduction; share one `_consume_paid_session` helper | S |
| 5 | H | Money | `server.py:663-671` + `billing.py:228` | Free 10-min trial (per email) + £2 intro = ~5h unlimited AI; intro likely sold below cost | Cut intro to **1 session** (keep £2 price); add disposable-email block at register | S |
| 6 | H | Money | `billing.py:101,155` | 7-day sub trial grants uncapped `unlimited`; user runs full interviews then cancels day 6 for £0 | Cap trial (N captures / 1 session-equiv / 3 days), or require intro purchase before offering sub trial | M |
| 7 | H | Money | `billing.py:238` `_credit_referrer(...,200,...)` | Referrer paid £2 credit when referee buys the £2 (≈cost) intro → net-negative acquisition; no lifetime cap | Credit referrer **only on referee's first paid sub-month/pack**, not intro; cap lifetime credit per user (£15–25) | M |
| 8 | H | Visual | `css/global.css` (dark-only) vs `css/landing.css` (light+dark) | Light toggle on landing persists `theme:light`, but every other page is hard-dark → user's choice silently ignored | Promote landing's token system into `global.css` (`:root`=light, `[data-theme=dark]`), refactor pages to tokens, add toggle to `base.html` — **or** remove the landing toggle | M |
| 9 | H | Visual/UX | `index.html:137-148` (empty dashboard) | First-run paid user sees a 90px grey box "waiting for capture…" twice, no guidance, empty-state text at ~1.3:1 contrast (invisible) | Proper empty state: larger icon + "Press [capture hotkey] on your computer — the answer lands here" + live armed status; text to `var(--muted)` | M |
| 10 [x] | H | Visual/Copy | `landing.html:845` vs `pricing.html:41` | Landing: intro "usually **£15 for 3 sessions**"; checkout: "£2 for 2 sessions, **£10 regular**" — contradictory anchors | Single source of truth: landing → "normally £10" (same 2-session SKU) | S |
| 11 | H | Feature/Money | `models.py:82`, `server.py:760` | No capture content ever persisted (Redis hash overwritten; 3-item client buffer wiped on reload) → product is amnesiac, blocks all retention | Add a `Capture` table (transcription+analysis+ts per session) + `GET /api/history`; unlocks review/saved/progress | S–M |
| 12 | H | Feature | new (prompt) `server.py:123` `RESPONSE_STYLE_SUFFIX` | No "talk track" — pasting correct code silently fails the "explain your thinking" bar interviewers grade | Add a talk-track response style ("I'd start brute-force O(n²)… then optimise with a hash map because…") — one suffix | S |
| 13 | H | Feature | new (prompt) + `settings.html` | No language/framework selector — Claude guesses; mismatched language makes answers useless mid-interview | Add `User.preferred_language`, a settings/popup pill, append to prompt (mirror complexity plumbing) | S |
| 14 | H | UX | `index` route `server.py:410` | After trial, free users are hard-bounced from `/app` to `/pricing` — can't even re-read last answer | Let free users reach a **read-only** `/app` (last capture + upgrade banner) — keeps value visible at the buy moment | M |
| 15 | H | UX | `onboarding.html:139` + `content.js:87` | "Connect Extension" shows "Connected!" without verifying token/server against the server; 2s timeout false-negatives | Have content.js call `/api/me` and emit `connected` only on 200 → "Connected and verified" (also the missing "test it works") | M |
| 16 | H | UX | onboarding flow (no step) | No low-stakes "do one capture now and watch it appear" — first real capture is live under pressure | Add final onboarding step: "Press [capture] now — answer appears on your phone in seconds"; detect server-side, auto-advance | M |
| 17 | H | Money | `trial_end.html:96` | Four how-to tip cards sit **above** the upgrade CTA at peak intent (trial just expired) | Put £2 intro CTA + value pitch **first**; collapse tips below | S |
| 18 | H | Money | `index.html` (paid users) | No in-app "1 session left" / "session expiring in 15 min" upsell; user hits the wall mid-interview as an error toast | Dashboard banner: sessions remaining + "Go Unlimited" at ≤1; "last 15 min — extend?" nudge | M |
| 19 | H | Money/Feature | `cancel_confirm.html` + `billing.py:39` | Cancel save-offer is good but no **pause** option; churn here is structural ("got the job / not interviewing now") | Add "Pause subscription 1–3 months" (Stripe pause) → converts hire-churn into reactivation | M |
| 20 | H | Money | `pricing.html` + `cancel_confirm.html:103` | Never-expiring one-time packs cannibalize MRR; cancel flow even pushes packs over sub | Keep packs but price per-session above sub's effective value; add low-session pack→sub upgrade nudge with session credit | M |
| 21 [x] | M | Copy | `landing.html:51,33` + funnel | 6 different labels for "sign up / pay" (Start for free / Get started / Start unlimited / Create your free account…) | Two CTA families: free = **"Try free — no card"** everywhere; paid = price-in-label ("Claim £2 intro", "Start free week") | S |
| 22 [x] | M | Copy | `index.html:2` | App `<title>` = "Screen Monitor" — off-brand, and a visible tell during screen-share | → "InterviewAce" / "Dashboard"; rename "monitor" everywhere in user copy | S |
| 23 [x] | M | Copy | `landing.html:46` | Hero subhead drifts into mechanism ("captures your screen or listens"); never pays off the "silent co-pilot" title | "…streams a working solution to your phone before you've typed a line. **Your silent co-pilot, off-screen and out of sight.**" | S |
| 24 [x] | M | Visual | `css/` (whole tree) | No `:focus-visible` anywhere; buttons/links/tabs have no keyboard focus state | Add `:where(a,button,input,[tabindex]):focus-visible{outline:2px solid var(--accent);outline-offset:2px}` to global.css | S |
| 25 [x] | M | Visual | `pricing.css:378`, `:486`; `referral.css:435`; `onboarding.css:48`; `trial_end.css:48` | Conversion/reassurance copy at near-invisible contrast (`.price-was` ~1.7:1, fine print opacity 0.5, referral footer ~1.4:1, body #444–#666) | Lift all to `var(--muted)` (#6b6b8a ~4.5:1); never use #444/#555 for real text | S |
| 26 | M | Visual | `base.html:20` + `pricing.css:5` | Shared sticky navbar + pricing's own in-content sticky header can stack; onboarding/trial-end/verify have **no** nav (marooned users) | One nav strategy: give all authed pages the navbar, delete per-page `header`/`.logo` CSS; verify pricing isn't double-stacking | M |
| 27 | M | Visual | global.css vs login/index/pricing/cancel | `.btn-primary` / `.card` / `.kbd` / `.copy-btn` redefined per page with drifting radii/padding/colour | Promote one canonical each into `global.css`, delete per-page copies | M |
| 28 | M | Visual | onboarding/trial_end/verify/billing_success CSS | Hardcoded hex (`#0d0d0d`/`#141414`) ≠ tokens (`--bg:#080810`) → these pages are literally a different shade than the app | Replace literals with existing `var(--*)`; also unblocks theming (#8) | S |
| 29 [x] | M | Visual | `verify_pending.css:25` | The only blue primary button in the product (steel-blue), hit right after register — off-brand first impression | Use `.btn-primary`; tokens for body/logout text | S |
| 30 | M | UX | `login.html:27` + `server.py:271` | Register asks full_name + username + email + password (4 fields); username-login invites "which username?" tickets | Drop full_name from signup; consider email-as-login → 2 fields | M |
| 31 [x] | M | UX/Copy | `onboarding.html:52`, `trial_end.html:21`, `cancel_confirm.html:120` | Tells users to find "**Interview Assistant**" in Chrome but brand is "**InterviewAce**" — they won't find it; also typos ("dont", "its") | Standardize on real Web Store name everywhere; fix apostrophes | S |
| 32 | M | UX | `manifest.json` (no `commands`) + `content.js:138` | Hotkeys are in-page keydown only → do nothing if the coding screen is a non-Chrome app/window (Zoom, native IDE) — silent no-op | Register true global `commands`, or clearly set expectation "coding screen must be a focused Chrome tab" | M |
| 33 | M | UX | `index.html` overlays + complexity controls | Dashboard needs mid-interview taps (complexity/style) and overlays can block the answer on the phone | Make overlays one-tap, never re-show during a running trial; answer text dominant; push complexity/style to the popup so phone stays read-only | M |
| 34 [x] | M | Copy | `server.py:189,233` + `background.js:80` | `Subscription required` has no friendly extension mapping → surfaces as "Error 403: Subscription required"; raw enum codes can leak | Map all wire codes to human strings in the extension; never show enums verbatim | S |
| 35 [x] | M | Copy | `mailer.py:22-31` | Verification email is bland, dark-bg HTML (spam/deliverability risk), no "ignore if not you" line | "Welcome to InterviewAce. Tap to confirm your email and unlock your free 10-min trial. If you didn't sign up, ignore this." + light bg | S |
| 36 | M | UX | `/verify-pending` (`server.py:408`) | Hard email gate blocks even the onboarding instructions; dead-end if email is slow (no support link, no spam hint) | Let unverified users see onboarding (gate only capture endpoints), or add support link + "check spam" + send status | M |
| 37 | M | UX | `onboarding.html:57` + popup | Token+server-URL setup = expand hidden toggle, two copies, two pastes — error-prone | Single "copy setup" blob (`token@serverUrl`) that the popup splits on one paste; or deep-link pre-filled popup | M |
| 38 | M | Feature | roadmap item; `models.py` + dashboard | No pre-interview company/role/resume context upload → answers aren't tailored; no reason to open app before interview | `prep_context` field + "Prep" card, prepend to prompts — first before-interview engagement hook | M |
| 39 | M | Feature | new `/session/{id}/review` (needs #11) | No post-interview surface → no reason to return after the interview | "Performance review": problems seen, gaps vs optimal, study list — first after-interview return reason | M |
| 40 | M | Feature | new `/practice` (needs #11) | 10-min trial says "practice only" but there's nothing to practise on; no between-interview engagement | Mock/practice mode with a seed question bank + coach prompt — the core answer to one-and-done | M–L |
| 41 | M | Money | `pricing.html:132` + `config.py:21` | Sub card headlines "Free first week"; £25/mo barely shown and vanishes if `STRIPE_SUB_PRICE_PENCE=0` (the default) | Show "£25/mo after trial" explicitly; set the env var so price/credit math doesn't silently break | S |
| 42 | M | Money | `pricing.html` (3 SKUs) | No cheap single-interview SKU, no time-boxed "job-search pass" | Add ~£5–7 single-session SKU (higher margin than intro) and a flat "3-month job-search pass" (front-loads revenue) | S–M |
| 43 | M | Money | `cancel_confirm.html:92` got-job path | Happiest churn (got the job) only offers a "buy me a coffee" link — wasted advocacy | Replace with referral CTA + testimonial ask — your best advocates at peak goodwill | S |
| 44 | M | Money | `billing.py:135` subscription deleted | No win-back for lapsed subs (churn is event-driven; they search again later) | 30/90-day win-back email ("interviewing again? a session on us") via existing Resend | M |
| 45 | M | Visual | `pricing.css:1` `@import Inter` | Pricing uses Inter; dashboard/settings use system stack → the two key post-signup pages don't match; `@import` blocks render | Pick one font app-wide (`<link preload>` in base.html) or drop the pricing import | S |
| 46 | M | Visual | `settings.html` (~20 inline styles) | Settings is the most inline-styled file; ad-hoc spacing, complexity stepper styled inline | Extract `.setting-desc`/`.save-status`/`.stepper` to CSS; share one stepper with the dashboard | M |
| 47 | M | Visual | `css/` (most pages) | `prefers-reduced-motion` honoured only on landing+pricing; cancel confetti (120 particles) unguarded | Wrap non-essential animations in `@media (prefers-reduced-motion:no-preference)`; guard `launchConfetti()` | S |
| 48 | L | UX | `index.html:490` | `tsConfirmStart` treats HTTP 400 ("trial already used") as success → overlay closes, nothing happens | On 400 show "Trial already used — upgrade to continue" + pricing link | S |
| 49 | L | UX | `trial_end.html:99` + route | "Back to monitor" → `/app` → bounces to `/pricing` (loop); paid users can see irrelevant trial-end content | Secondary link → `/pricing` for free users; redirect non-free away from `/trial-end` | S |
| 50 | L | Feature | `server.py:741` complexity dial | Manual 1–3 complexity is fiddly to change mid-interview under watch | Add "auto" — let Claude infer depth from the question | S–M |
| 51 | L | Feature | new (needs #11) | No saved/starred problems → no personal library, no switching cost | Star button + `Capture.starred` + "Saved" page | M |
| 52 | L | Feature | system-design / behavioural rounds unsupported | Coding-only coverage leaves half the loop (system design, behavioural) unhelped; seniors underserved | System-design mode (structured design + talk track) and STAR behavioural mode (reuse audio) | L |
| 53 [x] | L | Copy | `index.html:152`, `:120` | "AI Analysis" feature-led; lowercase status fragments inconsistent with Title-Case modals; `...` not `…` | "AI Analysis" → "Your answer"; pick one casing system; use real ellipsis | S |
| 54 | L | Money | `/billing/checkout` | Every plan is a full Stripe redirect; no one-click in-app upgrade for card-on-file users | Use saved customer for near-one-click pack→sub upgrade | M |
| 55 [x] | L | Visual | `referral.css` / `settings.css` dead `header`/`.logo`; `onboarding.css:195` dead `.start-section` | Half-done refactor left unused CSS blocks across pages | Delete dead CSS | S |

---

## Prioritized plan

### Quick wins (copy, spacing, labels, small fixes — hours to a day each)
- **Copy/trust:** reconcile the £10/£15 price contradiction (#10); unify CTAs into two families (#21); fix app `<title>` "Screen Monitor" (#22); rewrite hero subhead (#23); fix "Interview Assistant"→"InterviewAce" + typos (#31); map `Subscription required` error (#34); warmer verification email (#35); "AI Analysis"→"Your answer" (#53).
- **Visual:** global `:focus-visible` ring (#24); lift invisible conversion copy to `var(--muted)` (#25); replace hardcoded hex with tokens (#28); fix off-brand blue verify button (#29); reduced-motion guards (#47); delete dead CSS (#55); set/show £25/mo (#41).
- **UX:** trial-end CTA first (#17); fix placeholder install link or show sideload steps (#1); HTTP-400 trial handling (#48); fix trial-end "back to monitor" loop (#49); got-job referral CTA (#43).
- **Money/leaks:** session-gate audio capture (#4); cut intro to 1 session (#5).

### Medium changes (new components / flow rework — days each)
- **Design system:** consolidate buttons/cards/kbd/copy-btn into `global.css` (#27); de-inline settings + shared stepper (#46); single font (#45); one nav strategy across authed pages (#26).
- **Light mode:** fix app-wide or drop the toggle (#8).
- **Aha-path rework:** trial starts on first capture (#2); QR/short-code phone login (#3); verified extension connect + test-capture step (#15, #16); read-only `/app` for free users (#14); slimmer signup (#30); single-paste token setup (#37); global hotkey commands or clear expectation (#32); verify-pending escape hatch (#36); glanceable phone dashboard (#33).
- **Dashboard:** proper empty/first-run state (#9).
- **Revenue:** in-app low-session upsell (#18); pause-subscription (#19); pack→sub nudge (#20); referral credit timing/caps + disposable-email block (#7); single-interview SKU (#42); win-back emails (#44).

### Bigger bets (new features / pricing — weeks)
- **Retention engine (do in order):** persist capture history (#11) → post-interview review (#39) → mock/practice mode (#40) → prep-context upload (#38) → progress/streaks home + reminder emails. This is the structural fix for one-and-done churn and what justifies £25/mo.
- **AI surface expansion:** talk-track mode (#12) and language selector (#13) are *small* effort but high value — do them early; system-design + behavioural modes (#52) expand TAM to higher-paying seniors.
- **Pricing/packaging:** cap the 7-day sub trial (#6); time-boxed "job-search pass" SKU (#42); premium tier; rework referral economics (#7).
- **Light-mode + design-system** (#8, #27) if treated as a full pass rather than incremental.

---

## Revenue ideas ranked by expected return vs effort

**Do now (high return, small effort):**
1. **Session-gate audio capture (#4)** — closes a direct API-cost leak (pure bug). H / S
2. **Cut intro to 1 session (#5)** — ~halves CAC cost exposure, same hook. H / S
3. **Stop crediting referrers on the £2 intro; credit on first paid sub/pack (#7)** — removes net-negative payouts. H / S–M
4. **Trial-end: buy CTA first, tips below (#17)** — lifts trial→paid at peak intent. M / S
5. **Show £25/mo + set `STRIPE_SUB_PRICE_PENCE` (#41)** — fixes silent price breakage, anchors the sub. M / S

**Do next (high return, medium effort):**
6. **Cap the 7-day sub trial (#6)** — stops free-riders draining the whole product value for £0. H / M
7. **In-app low-session / expiring upsell (#18)** — converts pack→MRR at peak need. H / M
8. **Pause subscription (#19)** — converts structural hire-churn into reactivation. H / M
9. **Cap referral credit per user + disposable-email block (#7, #5)** — bounds liability + multi-account abuse. M–H / M
10. **Read-only `/app` for free users (#14)** — keeps value visible at the conversion moment. M / M

**Backlog / speculative:**
11. Single-interview SKU + 3-month job-search pass (#42); win-back emails (#44); got-job referral/testimonial CTA (#43); post-capture "go unlimited" nudge; one-click pack→sub (#54); premium tier.

> Note: every revenue figure here is inferred from the offer structure, not measured. Pull the PostHog funnel (intro→pack→sub conversion, trial-abuse rate, per-capture cost) before acting on the cost-cutting items (#5, #6) — if intro→sub conversion is strong, the loss-leader intro may be worth keeping as-is.

---

## What I couldn't assess (and why)
- **No analytics/cost/conversion data** — PostHog is wired (`analytics.py`) but not readable here; all funnel, churn, abuse-rate, and unit-economics claims are inferred from code/structure.
- **Couldn't run the extension or render pages** — auto-connect handshake (#15), cross-window hotkey capture (#32), phone overlay behaviour (#33), and all contrast ratios (#25) are inferred from code/hex, not observed in a browser. Verify the pricing double-header (#26) and contrast fixes in a real browser.
- **Couldn't test email deliverability** (Resend) or exercise live Stripe checkout — the verify-pending dead-end (#36) and billing-success poll timing depend on real latency.
- **Stripe-side values** (exact prices, coupon amounts, whether live key triggers fingerprinting) live in Stripe env config, not the repo — inferred from template copy.
- **Real Chrome Web Store extension name** — install link is a placeholder, so the "Interview Assistant" vs "InterviewAce" fix (#31) needs the actual listing name.
- **Legal/ToS dimension** of an interview-assist tool — out of scope of this audit, but it's the elephant behind the detectability/trust features (#4-feature).
- **Landing-page funnel friction** (pre-signup CTA clarity) — lightly covered; the UX agent started at "Create account" per its brief.

---

**Progress (2026-05-29):** Implemented the copy/trust and visual quick-win batches — items #10, #21, #22, #23, #24, #25, #29, #31, #34, #35, #53, #55 (marked `[x]` above). Separately, a pricing change was made outside the audit's recommendations: the £2 intro now grants **3 sessions** (was 2), the sessions pack is **£10** (was £15), and the unlimited sub is **£20/mo** (was £25) — these require matching new prices in Stripe to take effect.

Next up (not yet done): the UX quick wins (#1, #17, #48, #49, #43), then the revenue leaks (#4, #5, #7), then the aha-path rework (#1, #2, #3) and design-system pass (#8, #26, #27, #28, #45, #46).
