# Landing Page — Improvements & Ideas

---

## Missing Sections (conversion impact)

- [ ] **FAQ section** — place above the CTA banner. Addresses the objections every visitor has before buying:
  - Is this detectable?
  - Does it work on recorded tests (HireVue, Kira)?
  - What platforms does it support?
  - Do I need to install anything on my phone?
  - What happens when my trial ends?
  - Is there a refund policy?

- [ ] **Platform compatibility strip** — a row of logos/names between the hero and stats strip. Visitors scan for "does this work for my setup" in the first 3 seconds. Currently they have to read paragraphs to find out.
  - LeetCode, HackerRank, CoderPad, HireVue, Kira
  - Zoom, Teams, Google Meet
  - Could be text labels with subtle icons, not full brand logos

- [ ] **Testimonials / social proof section** — zero social proof anywhere on the page right now. Even 2–3 placeholder cards to swap for real ones when early users come in. Place between features and referral.
  - Name, role, quote, company (or just "Software Engineer at [FAANG]")
  - Star rating optional

- [ ] **Contact / support link in footer** — a `mailto:` or small "support" link so visitors know there's a human behind the product

---

## Nav & UX

- [ ] **Sticky nav** — nav scrolls away, taking the "Get started" CTA with it. Add `position: sticky; top: 0; backdrop-filter: blur(14px)` so it stays visible throughout the page
- [ ] **Mobile hamburger menu** — 5+ nav links will overflow on smaller screens. A toggle menu for mobile prevents layout breakage
- [ ] **Active nav highlight** — highlight the current section in the nav as the user scrolls (IntersectionObserver on each section, update nav link class)

---

## Hero

- [ ] **Hero visual** — text-only above the fold. Options:
  - Bring the phone mockup up into the hero (right side, two-column layout on desktop)
  - Add a subtle animated background (see Animations section)
- [ ] **Social proof line under CTA** — e.g. "Trusted by 200+ developers" or "Used in Google, Meta, and Amazon interviews" (once true)

---

## Animations

### Already present
- Scroll reveal (`.reveal` → `.visible` via IntersectionObserver)
- Cursor-tracking spotlight on pain cards and feature cards
- Count-up on stats strip
- Interactive demo (streaming text, phone state transitions)

### High impact, not annoying

- [ ] **Aurora / mesh gradient in hero background** — 2–3 large blurred radial gradients in accent colours, slowly drifting with a CSS `@keyframes` animation. Very subtle opacity (0.08–0.12). Makes the hero feel alive without moving content. Best effect: `mix-blend-mode: screen` on a dark background.

- [ ] **Animated gradient on the hero headline span** — the `<span>Start acing.</span>` gradient currently sits still. Animating `background-position` on a wider gradient gives a slow colour-shift effect. One `@keyframes` rule, zero JS.

- [ ] **3D card tilt on hover** — pain cards and feature cards already track the cursor for a spotlight effect. Adding a `perspective` + `rotateX/Y` transform on `mousemove` (capped at ±6°) gives a subtle depth feel. Pairs naturally with the spotlight.

- [ ] **Staggered card entrance** — feature bento cards currently all reveal at once. Adding `transition-delay: calc(var(--i) * 80ms)` (set `--i` via inline style) staggers them in left-to-right. One line of CSS per card.

- [ ] **Pricing card shimmer / glow pulse** — the "Most popular" featured card could have a slow pulsing glow on its border (`box-shadow` animated between two accent colours). Draws the eye without moving anything.

- [ ] **How-it-works connector line draw** — add a vertical line between steps that "draws down" as the section enters the viewport. CSS `height` transition from `0` to `100%` triggered by IntersectionObserver. Classic SaaS landing page effect.

- [ ] **Hotkey `<kbd>` press animation** — the demo hotkey badges could play a quick scale-down → scale-up "keypress" animation when the demo scenario triggers a capture. Reinforces the hotkey concept visually.

### Lower priority

- [ ] Smooth scroll progress bar at top of page (thin 2px line, accent colour)
- [ ] Referral reward amounts flip in like a ticker when the section scrolls into view
- [ ] CTA banner background beam / spotlight sweep (a single light streak across the gradient, looping every ~6s)
- [ ] Floating subtle dot/particle field in hero (canvas-based, very low opacity — only worth it if the aurora gradient isn't enough)
- [ ] Scroll-linked parallax on hero badge or headline (subtle translate on `scroll` event)

---

## Copy / Content

- [ ] Add a "Works on" or "Supported platforms" note somewhere near the features — currently unclear without reading
- [ ] Referral section: the `£5 credit per referral` card and the reward rows show different numbers (£2 + £3 rewards vs £5 credit card). Worth reconciling or adding a note explaining the accumulation
- [ ] Footer: add a `mailto:` or support link

---

## Technical polish

- [ ] `<meta name="description">` for SEO
- [ ] `og:image` and `og:title` for social share previews
- [ ] Favicon (if not already set in base.html)
- [ ] Lazy-load any images added in future
