# Handoff: Cancel Subscription Flow (InterviewAce)

## Overview
A single-page cancellation flow that replaces the previous "Cancel?" confirm page. It does three jobs, in order:

1. Reassures the user about what cancelling actually does (nothing is lost immediately).
2. Presents one retention offer (50% off next month) that can be declined and later re-opened.
3. Collects a cancellation reason and shows a reason-specific response — congratulations, a pricing alternative, troubleshooting help, or a direct note from the founder.

The primary action throughout is **keeping** the subscription. Cancelling is available but visually secondary and gated behind selecting a reason.

Route in the product: reached from Settings → Subscription → Cancel. Back arrow returns to Settings.

## About the Design Files
`Cancel Confirm v2.dc.html` in this bundle is a **design reference built in HTML** — a prototype that shows the intended look, copy, and behavior. It is not production code and should not be pasted into the app.

Per this project's production context, the target stack is a **Flask app with Jinja2 templates** (`templates/`, shared `base.html`) plus `css/global.css` and per-page CSS. Recreate this design as:

- `templates/cancel_confirm.html` (extends `base.html`)
- `css/cancel_confirm.css` for page-specific rules, using the existing `global.css` custom properties
- a small vanilla-JS block for the reason selection, offer collapse/expand, textarea state, and confetti

Do **not** port `support.js` or the `.dc.html` wrapper — they are prototype runtime only. `support.js` is included solely so the HTML file opens in a browser for reference.

## Fidelity
**High fidelity.** Colors, typography, spacing, radii, and interaction timings below are final and should be matched. Where a value maps to an existing `global.css` token, use the token rather than the literal hex.

## Screen: Cancel subscription

Single scrolling page, dark theme only (matches the rest of the authenticated app).

### Page frame
- Root: `background #0A0A0C`, `color #ECECEE`, `font-family 'Hanken Grotesk'`, `line-height 1.6`, `min-height 100vh`, antialiased.
- **Header**: flex row, `gap 14px`, `padding 18px max(28px, 4vw)`, bottom border `1px solid rgba(255,255,255,.07)`.
  - Back button: 32×32, `radius 8px`, `1px solid rgba(255,255,255,.12)`, chevron-left icon 17px, color `#9C9CA6`. Hover → border `rgba(255,255,255,.16)`, color `#ECECEE`. Links to Settings.
  - Wordmark: 9×9 square `#C6F24E` with `box-shadow 0 0 8px #C6F24E`, then "InterviewAce" in Space Grotesk 600 / 17px / `-0.02em` / `#F4F4F6`. `gap 9px`.
- **Main column**: `max-width 600px`, centered, `padding 56px max(28px,4vw) 96px`, `display flex; flex-direction column; gap 16px`.
- **Confetti canvas**: `position fixed; inset 0; pointer-events none; z-index 60`.

### 1. Page heading
- H1 "Before you go" — Space Grotesk 600, 34px, `line-height 1.12`, `letter-spacing -0.03em`, `#F4F4F6`, `margin-bottom 10px`.
- Sub "We're sorry to see you leave. Here's what happens when you cancel." — 16px, `#9C9CA6`, `max-width 44ch`, `text-wrap pretty`.
- Block has `margin-bottom 14px` (so the gap to the first card is 30px total).

### 2. "What happens when you cancel" card
- Card: `background #111114`, `1px solid rgba(255,255,255,.07)`, `radius 16px`, `padding 24px 26px`.
- Kicker: JetBrains Mono, 11px, `letter-spacing .16em`, uppercase, `#67676F`, `margin-bottom 18px`. Text: "What happens when you cancel".
- Two rows in a `flex column; gap 16px`, separated by a `1px` `rgba(255,255,255,.07)` divider.
- Each row: `flex; gap 14px; align-items flex-start`. Numeral `01`/`02` in JetBrains Mono 11px `#C6F24E`, `padding-top 3px`, `flex-shrink 0`. Body 14.5px `#9C9CA6` with `<strong>` at `#ECECEE` / 600.
- Copy (verbatim):
  - 01 — "Your subscription will remain **active until the end of your current billing period**. Nothing changes right away."
  - 02 — "Any unused sessions will remain in your account."

### 3. Retention offer card (visible while `offerOpen`)
- Card: `background rgba(198,242,78,.045)`, `1px solid rgba(198,242,78,.28)`, `radius 18px`, `padding 30px 32px`. Carries `data-offer-card` for the scroll target.
- Flash ring on re-open: `box-shadow 0 0 0 3px rgba(198,242,78,.22)` with `transition box-shadow .4s ease`, cleared after 1100ms.
- Kicker "A quick offer" — mono 11px `.16em` uppercase `#C6F24E`, `margin-bottom 14px`.
- H2 "Stay for 50% off next month" — Space Grotesk 600, 26px, `line-height 1.2`, `-0.03em`, `#F4F4F6`, `margin-bottom 10px`.
- Body — 14.5px `#9C9CA6`, `max-width 48ch`, `margin-bottom 24px`: "Since you've been with us, we'd like to offer you half price on your next month. No commitment beyond that — cancel any time."
- Actions row: `flex; flex-wrap wrap; gap 16px; align-items center`.
  - **Claim offer** — solid accent: `background #C6F24E`, `color #0A0A0C`, 15px/600, `padding 12px 22px`, `radius 10px`. Hover `translateY(-2px)` + `box-shadow 0 6px 18px rgba(198,242,78,.16)`. (Wire to the discount endpoint.)
  - **No thanks, continue cancelling** — bare text button, 13.5px/500, `#67676F`, hover `#ECECEE`. Sets `phase = feedback`, `offerOpen = false`.

### 4. Offer recall bar (visible when offer declined and `phase = feedback`)
Replaces the offer card in the same position so nothing jumps.
- Bar: `background #0C0C0F`, `1px solid rgba(198,242,78,.28)`, `radius 12px`, `padding 13px 16px`, `flex; wrap; gap 12px; align-items center`.
- 7px accent dot; mono 11px `.16em` uppercase `#67676F` "Offer still available"; 13.5px `#9C9CA6` "50% off next month".
- **View** button, `margin-left auto`: solid `#C6F24E`, `color #0A0A0C`, mono 11px `.12em` uppercase, `padding 7px 13px`, `radius 8px`, hover `translateY(-1px)`. Re-opens the offer card **and scrolls it into view** (see Interactions).

### 5. Feedback section (visible when `phase = feedback`)
Wrapper `flex column; gap 16px`, enters with `ia-in .25s ease` (`opacity 0 → 1`, `translateY(6px) → 0`).

**Reason card** — same card style as §2. Kicker: "Before you cancel — why are you leaving?". Options in a `role="radiogroup"`, `flex column; gap 8px`.

Each option is a button, `flex; gap 12px; align-items center`, text left, 14.5px/500, `padding 13px 16px`, `radius 10px`, transitions `border-color/background/color .15s`:
- unselected — `background #0A0A0C`, `border 1px solid rgba(255,255,255,.07)`, text `#9C9CA6`, dot ring `1.5px rgba(255,255,255,.25)`, dot fill transparent
- selected — `background rgba(198,242,78,.06)`, `border 1px solid rgba(198,242,78,.28)`, text `#F4F4F6`, dot ring `#C6F24E`, dot fill `#C6F24E`
- dot: 16×16 circle, inner fill inset 3px

Options (value → label, in order):
`got_job` → "I got the job!" · `too_expensive` → "Too expensive" · `not_used_enough` → "Didn't use it enough" · `had_issues` → "It was buggy / I had issues" · `missing_feature` → "Missing a feature I need" · `other` → "Other"

**Reason-specific panels** (exactly one shows, `ia-in .2s ease`):

*a. `got_job` — accent card* (`rgba(198,242,78,.045)` bg, `rgba(198,242,78,.28)` border, `radius 16px`, `padding 26px`)
- Kicker "Congratulations" in accent.
- Space Grotesk 500 / 19px / `-0.02em` / `#F4F4F6`: "That's literally the whole point of this. Good luck in the new role."
- CTA **Leave us a review on Trustpilot ↗** — solid `#C6F24E`, `#0A0A0C` text, 13.5px/600, `padding 10px 18px`, `radius 9px`, hover `translateY(-1px)` + accent shadow. Opens Trustpilot in a new tab (`rel="noopener"`). Replace the placeholder URL with the real review link.
- Also triggers confetti (see Interactions).

*b. `too_expensive` and offer still eligible* — `#0C0C0F` card, accent border, `radius 16px`, `padding 24px 26px`
- "The **50% offer above still stands** — half price for next month, no commitment beyond that. Worth a look before you go."
- CTA **See the offer** — solid accent, 13.5px/600, `padding 10px 18px`, `radius 9px`. Same behavior as the recall bar's View.

*c. `not_used_enough`, or `too_expensive` when not offer-eligible* — `#0C0C0F` card, `rgba(255,255,255,.07)` border
- Copy is assembled from two halves so it fits both entry points:
  - `not_used_enough` → "If timing is the issue, **session packs might suit you better**. Each session lasts 1.5 hours and **never expires** — use them when you actually have an interview, not on a monthly clock."
  - `too_expensive` (no offer) → same sentence with "If cost is the issue," and "…pay only when you actually have an interview, not on a monthly clock."
- CTA **See session packs →** — solid accent, `#0A0A0C` text, `padding 10px 18px`, `radius 9px`. Links to Pricing.

*d. `had_issues` — troubleshooting card* (`#0C0C0F`, `rgba(255,255,255,.07)` border, `padding 24px 26px`)
- Intro 14.5px `#9C9CA6`: "Sorry to hear that. A few things that catch people out:"
- Four items in a hairline grid: `display grid; gap 1px; background rgba(255,255,255,.07); border 1px solid rgba(255,255,255,.07); radius 12px; overflow hidden`; each cell `background #0A0A0C; padding 15px 17px`. Item title mono 10.5px `.14em` uppercase `#ECECEE`; body 13.5px `#9C9CA6`.
  1. **Extension not pinned** — "Click the puzzle piece in Chrome's toolbar, find *Interview Assistant* and pin it. The icon going green means it's active." Followed by the Chrome mock (below).
  2. **Hotkeys not firing** — "Capture & analyse is `Ctrl+Shift+7`. Toggle on/off is `Ctrl+Shift+9`. Another app may be claiming the same shortcut — try the popup buttons instead."
  3. **Not connected / signed out** — "Open the extension popup and check it shows your account. If not, sign out and back in — the token may have expired."
  4. **Overlay not showing** — "The overlay only appears after a capture. Toggle off then on again with `Ctrl+Shift+9` if it seems stuck."
  - `<kbd>` style: JetBrains Mono 11.5px, `#ECECEE`, `1px solid rgba(255,255,255,.14)` with `border-bottom-width 2px`, `radius 4px`, `padding 1px 5px`.
- **Chrome mock** (pure CSS, no image), `max-width 330px`, `background #0C0C0F`, `1px solid rgba(255,255,255,.09)`, `radius 10px`, `overflow hidden`, `margin-top 14px`:
  - Toolbar strip (`padding 8px 9px`, bottom hairline): fake URL field `#0A0A0C` / hairline border / `radius 6px` / mono 9.5px `#54545C` "leetcode.com"; 22×22 puzzle-slot button with accent border `rgba(198,242,78,.45)`, `rgba(198,242,78,.08)` fill and a 2×2 grid of 4px `#C6F24E` squares; 22×22 solid `#C6F24E` badge with mono 9px `#0A0A0C` "IA".
  - Dropdown body (`padding 9px 9px 10px`): mono 9px `.16em` uppercase `#54545C` "Extensions"; highlighted row (`rgba(198,242,78,.06)` bg, accent border, `radius 7px`, `padding 7px 8px`) with 18×18 `#C6F24E` "IA" tile, 12px `#ECECEE` "Interview Assistant", and a **filled** accent pin icon; a second dimmed row (`opacity .35`) with grey placeholder bars and an outline pin.
  - Caption under the mock: 5px accent dot + mono 9.5px `.12em` uppercase `#54545C` "Pinned & active".
- Founder note: 36×36 `radius 9px` avatar tile (`rgba(198,242,78,.06)` bg, accent border, mono 12px `#C6F24E` "CJ") beside 13.5px `#9C9CA6` copy, lead sentence in `#ECECEE`: "**If none of that helps, I want to know.** Hi, I'm CJ, I built InterviewAce. I check these messages every day. Tell me what happened and I'll look into it within 1 day."
- Textarea, placeholder "What went wrong? (optional)".

*e. `missing_feature` / `other` — founder note card* (`#0C0C0F`, hairline border)
- Same CJ avatar tile + note:
  - `missing_feature` — "Hi, I'm CJ — I built InterviewAce. I check these messages every day. If something would've made this work for you, let me know. If it makes sense for everyone, I'll ship it in the next 5 days." Placeholder: "What were you looking for? (optional)"
  - `other` — "Hi, I'm CJ — I built InterviewAce. I check these messages every day. Feel free to share anything — I read every message." Placeholder: "Anything you'd like to share? (optional)"

**Textarea style** (both cases): full width, `min-height 92px`, `resize vertical`, 14px Hanken Grotesk, `line-height 1.6`, `color #ECECEE`, `background #0A0A0C`, `1px solid rgba(255,255,255,.07)`, `radius 10px`, `padding 12px 14px`, `outline none`; focus border `rgba(198,242,78,.28)`; placeholder `#67676F`.

### 6. Action footer
`flex column; gap 12px`, `margin-top 8px`, `padding-top 20px`, top border `1px solid rgba(255,255,255,.07)`.
- **Keep my subscription** (primary, full width): solid `#C6F24E`, `color #0A0A0C`, 15px/600, `padding 14px`, `radius 11px`, hover `translateY(-2px)` + `box-shadow 0 6px 20px rgba(198,242,78,.18)`. Label becomes **"Keep my subscription and send developer message"** when the textarea has content.
- **Cancel subscription** (destructive ghost, full width): transparent, 14px/600, `padding 13px`, `radius 11px`.
  - enabled — `color #E06A6A`, `border 1px solid rgba(224,106,106,.35)`, `cursor pointer`
  - disabled (no reason chosen) — `color #54545C`, `border 1px solid rgba(255,255,255,.07)`, `cursor not-allowed`
- Disabled hint (only while disabled): mono 10.5px `.14em` uppercase `#67676F`, centered — "Select a reason above to continue".

## Interactions & Behavior

**Phases.** `phase` starts at `offer` (or `feedback` directly if the user isn't offer-eligible). "No thanks, continue cancelling" → `phase = feedback`, `offerOpen = false`. The feedback section is additive: the reassurance card stays visible above it.

**Offer collapse / re-open.** Declining collapses the offer into the recall bar in the same slot. **View** (recall bar) and **See the offer** (`too_expensive` panel) both set `offerOpen = true`, flash the accent ring for 1100ms, and scroll the offer card into view.

*Scroll implementation note (this bit was fiddly in the prototype):* the offer card only exists in the DOM after re-open, and expanding it changes document height, so a naive `scrollTo` right after the state change either finds no node or gets absorbed by the browser's scroll anchoring. What works: a `requestAnimationFrame` retry loop (up to ~20 frames) that waits until the card exists and has a non-zero height, then `window.scrollTo({top: rect.top + scrollY - 28, behavior:'smooth'})`, re-asserting once at 180ms if the position drifted more than 40px; plus `overflow-anchor: none` on the document and page subtree. Do not rely on `scrollIntoView`. Target: the card's `rect.top` ends up between 0 and viewport height.

**Reason selection.** Single-select radio behavior. Selecting a reason reveals its panel, enables Cancel subscription, and resets the "has text" flag (so the Keep label reverts).

**Confetti.** Selecting `got_job` fires a one-shot canvas confetti burst (once per page load): 90 rectangles, 4–9 × 8–15px, colors `#C6F24E #ECECEE #9C9CA6 #A8CF3E #F4F4F6`, spawned above the viewport, `vy 1.6–5`, `vx ±1.2`, gravity `+0.07/frame`, rotation `±0.09/frame`, fade begins at 1600ms (`-0.014` alpha/frame), canvas cleared when all particles are gone. DPR-scaled. Skipped entirely under `prefers-reduced-motion: reduce`.

**Keep button label.** Watch textarea input; non-empty (trimmed) → "Keep my subscription and send developer message". Submitting Keep with text should also POST the message to the founder inbox.

**Motion.** Hover transitions `.15s`; panel entry `ia-in .2–.25s ease`; flash ring `.4s`. All animation suppressed under `prefers-reduced-motion`.

**Responsive.** Single 600px column; side padding `max(28px,4vw)`. Action rows use `flex-wrap: wrap`. No separate mobile layout needed.

## State Management
| State | Type | Notes |
|---|---|---|
| `phase` | `'offer' \| 'feedback'` | initial `offer`; `feedback` immediately if not offer-eligible |
| `offerOpen` | boolean | offer card expanded vs. collapsed recall bar |
| `reason` | one of the six values or `null` | gates the Cancel button and the panels |
| `hasText` | boolean | textarea non-empty → Keep button label swap |
| `flash` | boolean | 1100ms accent ring on the offer card |

Server-side inputs: whether the user is eligible for the 50% offer (never offered before, active paid sub), and the current period end date if you want to name it in copy row 01.

Endpoints to wire: claim discount, cancel subscription, submit reason + optional message.

## Design Tokens
Colors — bg `#0A0A0C` · panel `#0C0C0F` · card `#111114` · line `rgba(255,255,255,.07)` · line-strong `rgba(255,255,255,.16)` · text `#F4F4F6` / `#ECECEE` / `#9C9CA6` / `#67676F` / `#54545C` · accent `#C6F24E` · accent-soft `rgba(198,242,78,.045–.08)` · accent-line `rgba(198,242,78,.28)` · danger `#E06A6A` / `rgba(224,106,106,.35)`.

Type — Space Grotesk 500/600 (headings, `-0.02` to `-0.03em`); Hanken Grotesk 400/500/600 (body, `line-height 1.6`); JetBrains Mono 400–600 (kickers, kbd, micro labels, `.12–.16em` uppercase). Sizes: 34 / 26 / 19 / 16 / 14.5 / 13.5 / 12 / 11 / 10.5 / 9.5 / 9.

Spacing — 6 · 8 · 10 · 12 · 14 · 16 · 18 · 20 · 24 · 26 · 30 · 32 · 56 · 96. Column `max-width 600px`.

Radius — 4 (kbd) · 5–7 (mock rows) · 8–11 (buttons) · 12 (list, recall bar) · 16 (cards) · 18 (offer card) · 980px (pills) · 50% (dots).

Shadows — only two: `0 6px 18–20px rgba(198,242,78,.16–.18)` on accent-button hover, `0 0 8px #C6F24E` on the wordmark dot. Cards have no shadow; depth comes from hairline borders.

## Assets
None external. All icons are inline SVG (chevron-left, pin) or CSS shapes (puzzle grid, dots, bars). Fonts load from Google Fonts — swap to the app's self-hosted faces if `global.css` already provides them. The Trustpilot link is a placeholder.

## Files
- `Cancel Confirm v2.dc.html` — the design reference (open in a browser)
- `support.js` — prototype runtime only; do not port
- Project root `CLAUDE.md` and `design_handoff_landing/README.md` — the wider InterviewAce design system this page follows
