# Handoff: InterviewAce Landing Page Redesign

## Overview
A full redesign of the InterviewAce marketing landing page. InterviewAce is a desktop tool that, during a coding interview, captures the on-screen problem (or the interviewer's spoken question) via an OS-level hotkey and streams an AI-generated solution — code, complexity analysis, explanation — to the user's **phone**, so nothing ever appears on the interview screen. The redesign replaces a generic "AI SaaS" look (gradient text, glow effects, Inter everywhere, all-centered) with a confident, intentional technical aesthetic in the quality tier of Linear / Vercel / Raycast.

The page sells: stop blanking under pressure → a silent, undetectable co-pilot → start acing.

## About the Design Files
The files in this bundle are **design references created in HTML** — a working prototype showing the intended look, layout, and behavior. They are **not production code to copy directly**. The `.dc.html` format is a self-contained prototype format (it pulls in `support.js` as a tiny runtime); do not port that runtime or the `<x-dc>`/`sc-for` template syntax into your app.

**Your task:** recreate this design in the InterviewAce codebase's existing environment. That codebase is a **Flask app using Jinja2 templates** (`templates/*.html`) with per-page CSS files in `css/` and a shared `base.html`. Rebuild the landing page as `templates/landing.html` + `css/landing.css`, following the patterns already established there (block inheritance from `base.html`, semantic class names, etc.). Use the HTML prototype purely as the source of truth for exact colors, type, spacing, and interactions.

## Fidelity
**High-fidelity (hifi).** Final colors, typography, spacing, and interactions are all specified below and present in the prototype. Recreate the UI pixel-for-pixel using the codebase's own CSS conventions. Every hex value, font size, and measurement in this README is authoritative.

## Open Decisions
- **Two complete themes exist: dark (default) and light.** The prototype switches via a `theme` prop. In production, decide whether you want both shipped (with a toggle or `prefers-color-scheme`) or just one. Both token sets are documented under Design Tokens. If you ship one only, dark is the primary direction.
- Three **alternate style directions** (Editorial / Terminal / Warm-premium) are included in `Landing Style Explorations.dc.html` for reference only. They are NOT the design to build — the design to build is `InterviewAce Landing.dc.html`. Ignore the explorations unless the team explicitly changes direction.

---

## Page Structure (top → bottom)
1. Fixed nav bar
2. Hero (two-column: copy left, device demo right)
3. Platform strip ("Works with …")
4. Pain section ("Interviews are broken")
5. How-it-works (3 steps)
6. Features (bento grid)
7. Pricing (2 plans)
8. Closing CTA
9. Footer

All sections are centered in a max-width container (`1180px`, hero `1280px`) with horizontal padding `max(28px, 4vw)`.

---

## Design Tokens

The prototype is fully tokenized via CSS custom properties on the root element, themed by a `data-theme` attribute. Reproduce these as CSS variables (e.g. `:root` for dark, `:root[data-theme="light"]` or a `.theme-light` class for light).

### Dark theme (default)
```
--bg:            #0A0A0C   /* page background */
--nav-bg:        rgba(10,10,12,0.72)  /* nav, with backdrop-filter blur(16px) saturate(160%) */
--bg-panel:      #0C0C0F   /* alternating section bg (how-it-works, pricing, platform strip) */
--card:          #111114   /* card surfaces */
--line:          rgba(255,255,255,0.07)   /* hairline borders */
--line-strong:   rgba(255,255,255,0.16)   /* hover borders, badges */
--text:          #F4F4F6   /* headings */
--text-1:        #ECECEE   /* primary text */
--text-2:        #9C9CA6   /* body / secondary */
--text-3:        #67676F   /* muted / mono labels */
--accent:        #C6F24E   /* acid green — accent text, dots, checks */
--accent-line:   rgba(198,242,78,0.28)
--accent-soft:   rgba(198,242,78,0.06)
--accent-bg:     #C6F24E   /* filled accent (featured CTA, highlight mark) */
--accent-on:     #0A0A0C   /* text on accent fill */
--dot:           #C6F24E
--dot-glow:      0 0 8px #C6F24E
--btn-bg:        #ECECEE   /* primary button (solid near-white) */
--btn-text:      #0A0A0C
--btn-shadow:    rgba(255,255,255,0.16)
--ghost-line:    rgba(255,255,255,0.14)        /* secondary/ghost button border */
--ghost-hover-line: rgba(255,255,255,0.3)
--ghost-hover-bg:   rgba(255,255,255,0.03)
--icon-line:     rgba(255,255,255,0.1)
--icon-bg:       rgba(255,255,255,0.04)
--hero-glow:     rgba(198,242,78,0.07)   /* radial glow behind device */
```

### Light theme
```
--bg:            #FBFBF9   /* warm off-white, NOT pure white */
--nav-bg:        rgba(251,251,249,0.78)
--bg-panel:      #F3F2EE
--card:          #FFFFFF
--line:          rgba(20,20,18,0.10)
--line-strong:   rgba(20,20,18,0.22)
--text:          #161614
--text-1:        #1A1A18
--text-2:        #5C5C58
--text-3:        #8A8A84
--accent:        #3F6212   /* deeper green for AA contrast on light bg */
--accent-line:   rgba(63,98,18,0.30)
--accent-soft:   rgba(63,98,18,0.07)
--accent-bg:     #C6F24E   /* the lime fill stays lime */
--accent-on:     #1A1A18
--dot:           #4D7C0F
--dot-glow:      none
--btn-bg:        #1A1A18   /* primary button is near-black on light */
--btn-text:      #FBFBF9
--btn-shadow:    rgba(0,0,0,0.20)
--ghost-line:    rgba(20,20,18,0.18)
--ghost-hover-line: rgba(20,20,18,0.35)
--ghost-hover-bg:   rgba(20,20,18,0.03)
--icon-line:     rgba(20,20,18,0.12)
--icon-bg:       rgba(20,20,18,0.03)
--hero-glow:     rgba(63,98,18,0.05)
```
> IMPORTANT: the device mockups (browser stub + phone) in the hero are **always dark**, in both themes, so they read as real screens. Their colors are hard-coded (see Hero), not themed.

### Typography
Three Google Fonts. Load: `Space Grotesk` (400,500,600,700), `Hanken Grotesk` (400,500,600), `JetBrains Mono` (400,500,600).
- **Display / headings** — `'Space Grotesk', sans-serif`, weight 600, letter-spacing `-0.03em` (hero `-0.035em`), line-height `1.0–1.1`.
- **Body / UI** — `'Hanken Grotesk', system-ui, sans-serif`, line-height `1.6`.
- **Labels, code, kickers, badges** — `'JetBrains Mono', monospace`, uppercase, letter-spacing `0.1–0.22em` for kickers.

Type scale (px):
- H1 hero: `clamp(46, 5.6vw, 80)`, line-height 1.0
- H2 section: `clamp(30, 4vw, 46)`, line-height 1.08
- H2 closing CTA: `clamp(32, 4.5vw, 52)`
- Hero body: 18 / lh 1.65
- Card body: 13.5–14.5 / lh 1.6–1.65
- Mono kicker: 12, letter-spacing 0.16em, uppercase
- Mono micro (badges, device): 7.5–11.5
- Nav links: 14
- Price figure: 40 (Space Grotesk 600)

### Spacing / radii / misc
- Section vertical padding: `120px` top/bottom (closing CTA `130px`).
- Container: max-width `1180px` (hero `1280px`, pricing `1000px`, CTA `760px`), side padding `max(28px,4vw)`.
- Card radius: `16–18px`; buttons `8–11px`; pills/badges `980px`; small chips `4–8px`.
- Nav height: `64px`, fixed, blurred translucent bg, 1px bottom border `--line`.
- Card grid gaps: `16px`; how-it-works `40px`; pricing `20px`.
- No drop shadows on content cards — depth comes from hairline borders + bg contrast. Shadows ONLY on: buttons (on hover), the device mockups, and the featured pricing CTA.

---

## Screens / Views
Single page. Components top to bottom:

### 1. Nav (fixed)
- 64px tall, `position:fixed`, full width, z-index 100. Background `--nav-bg` + `backdrop-filter: blur(16px) saturate(160%)`. Bottom border 1px `--line`.
- **Left:** logo — a 9×9px rounded-square (`border-radius:2px`) in `--dot` with `--dot-glow`, then wordmark "InterviewAce" in Space Grotesk 600, 17px, letter-spacing -0.02em.
- **Center-right links:** "How it works", "Features", "Pricing" — 14px, `--text-2`, hover → `--text-1`. Anchor to `#how`, `#features`, `#pricing`.
- **Right:** "Sign in" text link + "Try free" solid button (`--btn-bg` / `--btn-text`, 14px 600, padding 9×18, radius 8px; hover: translateY(-1px) + shadow `--btn-shadow`).

### 2. Hero
Two-column grid `1.05fr 0.95fr`, gap 64px, vertical-centered. Section padding `150px … 80px` (clears fixed nav). A soft radial glow (`--hero-glow`) sits absolutely top-right behind the device, 620×620, blurred.

**Left column (copy):**
- Eyebrow pill: bordered (`--line-strong`), radius 980px, padding 6×14. Contains a 6px pulsing dot (`--dot`, animation `ia-pulse` 2s) + mono text "Streams in under 3 seconds" (11.5px, uppercase, ls 0.12em, `--text-2`).
- H1: "Stop blanking.<br>Start acing." — Space Grotesk 600, clamp(46,5.6vw,80), `--text`. The word **"acing"** has an accent underline: an absolutely-positioned bar at the baseline (height 0.12em, `--accent-bg`, radius 2px, opacity 0.9).
- Sub-paragraph: 18px `--text-2`, max-width 480, lh 1.65. Copy: *"You know the material — but the moment someone's watching, your mind goes blank. InterviewAce streams a working solution to your phone before you've typed a line. Your silent co-pilot, off-screen and out of sight."*
- Button row: primary "Try free — no card" (solid `--btn-bg`, 15px 600, padding 14×26, radius 10; hover translateY(-2px)+shadow) and ghost "See how it works" (1px `--ghost-line`, hover border+bg). Anchors: primary → signup, ghost → `#how`.
- Trust row (mono 12px `--text-3`): "✓ OS-level capture" · "✓ Zero browser footprint" (checks in `--accent`).

**Right column (device demo) — ALWAYS DARK:**
A browser-window stub overlapped by a phone.
- **Browser stub:** 300px wide, bg `#101013`, border `rgba(255,255,255,0.08)`, radius 14, shadow `0 40px 80px rgba(0,0,0,0.5)`. Title bar `#141417`: three traffic-light dots (#ff5f57 / #febc2e / #28c840) + mono URL `leetcode.com/problems/reverse-linked-list` (10px #67676F). Body: problem title "206. Reverse Linked List" (Space Grotesk 600 13px #ECECEE) + an "Easy" chip (mono 9.5px #C6F24E, bordered). A description line, a sample-IO block (`#0A0A0C` bg), and a code block with a blinking accent caret (`ia-blink`). A "Capture" pill + `⌥ Space` kbd + mono "undetectable" tag (#C6F24E).
- **Phone:** 148px wide, overlaps the browser (`margin-left:-46px; margin-top:54px`). Dark body `#0D0D10`, 6px bezel `#1A1A20`, radius 30, big drop shadow, gentle float animation (`ia-float` 6s). Notch (46×14 pill). Status row "9:41 ●●●". Header: green dot + mono "INTERVIEWACE" (#C6F24E). A `<pre>` that **types out** the Python solution character-by-character with a blinking caret (see Interactions). Below: two mono chips "O(n) time" / "O(1) space" (#C6F24E, bordered).
  - The typed code string is:
    ```
    def reverseList(head):
        prev = None
        while head:
            nxt = head.next
            head.next = prev
            prev = head
            head = nxt
        return prev
    ```

### 3. Platform strip
Full-width band, bg `--bg-panel`, 1px top+bottom `--line`. Centered flex row: mono label "Works with" (`--text-3`, uppercase ls 0.14em) followed by platform names (mono 13px `--text-2`): **LeetCode, HackerRank, CoderPad, HireVue, Kira, Zoom, Teams, Meet**.

### 4. Pain section ("01 · Sound familiar?")
- Kicker: mono, "01" in `--accent` + "· Sound familiar?" in `--text-3`.
- H2: "Interviews are broken. Pressure kills performance." (max-width 640).
- 4-up card grid (`repeat(4,1fr)`, gap 16). Each card: `--card` bg, 1px `--line`, radius 16, padding 26; hover → border `--line-strong` + translateY(-3px). Contents: mono number (`--accent`), title (Space Grotesk 600 16px), body (13.5px `--text-2`).
- Cards:
  1. **Mind goes completely blank** — "You've solved this exact problem before. But now, with the interviewer staring, every algorithm just disappears."
  2. **Can't think while watched** — "The screen share is on, the timer's ticking, and you can feel their eyes. Anxiety takes over before you've read the question."
  3. **Forget the optimal approach** — "You know there's a better solution. But under pressure, only the naive brute-force comes to mind."
  4. **One mistake ends it** — "One bad day, one blank moment — and months of prep go to waste. The stakes are too high to leave to chance."

### 5. How it works ("02 · How it works")
- Band with `--bg-panel` bg + top/bottom borders.
- H2: "Two ways to capture. One silent result."
- 3-column grid, gap 40. Each step: a 44×44 rounded square (radius 11, border `--accent-line`, bg `--accent-soft`) with the step number in `--accent` (Space Grotesk 600 18px), beside a fading hairline rule. Title (Space Grotesk 600 18px) + body (14.5px `--text-2`).
  1. **Tap or hold a hidden hotkey** — "Tap to capture your screen instantly — intercepted at the OS level, invisible to monitoring software. Hold while the interviewer speaks to send their words to AI."
  2. **AI reads or listens** — "Claude reads the problem, detects the language, and generates a solution with complexity analysis. For voice, Whisper transcribes first — same output, hands-free."
  3. **Answer streams to your phone** — "Results appear in seconds with syntax-highlighted code and explanation. Missed something? Instant replay captures the last 15 seconds of speech."

### 6. Features (bento grid) ("03 · Features")
- H2: "Everything you need. Nothing they'll notice."
- 6-column grid (`repeat(6,1fr)`), `grid-auto-rows:1fr`, gap 16. Cards `--card` / 1px `--line` / radius 18. Tile spans:
  - **A — "Undetectable by design"** (span 3): shield icon in an accent-bordered tile; body about OS-level hotkey interception, no window switching / tabs / clipboard; footer chip "OS-level interception · Zero browser footprint". Hover border → `--accent-line`.
  - **B — "Streams to your phone"** (span 3): phone icon (neutral `--icon` tile); answer never on the interview screen; syntax-highlighted, also works on a second monitor.
  - **C/D/E small tiles** (span 2 each): mono tag + title + body —
    - *Capture* → **Screen or voice** — "Tap to screenshot the question, or hold to record the interviewer. Both stream the same Claude analysis."
    - *Replay* → **Instant replay** — "Missed what they said? Replay sends the last 15s of their question to AI after the fact."
    - *Analysis* → **Smart analysis** — "Auto language detection. Switch between optimal, intermediate, and naive on the fly."
  - **F — "Live calls & recorded tests"** (span 6, full width): video icon + title + body — "On live calls the answer goes to your phone. On recorded tests that flag tab switching — you never switch, so there's nothing to flag. Zoom, Teams, HireVue, Kira & more."
- Icons are inline SVG (Feather-style, 1.8 stroke). Icon stroke uses `currentColor` set to `--accent` (tile A) or `--text-1` (others).

### 7. Pricing ("04 · Pricing")
- Band with `--bg-panel` bg + borders, container max-width 1000, centered header.
- H2: "Start free. Pay when it matters."
- Two cards, `1fr 1fr`, gap 20, equal height (flex column, CTA pinned bottom via `margin-top:auto`).
  - **Sessions** (neutral): mono label "Sessions"; price **£2** + "/ 3 sessions"; accent note "Intro offer — normally £10"; desc "Buy sessions when you need them. No subscription."; checklist (✓ in `--accent`): "3 full 2.5-hour sessions", "Screen & voice capture", "Instant replay", "Sessions never expire". CTA: ghost button "Claim £2 intro".
  - **Unlimited** (featured): card has a faint accent top-gradient (`linear-gradient(180deg, --accent-soft, --card 42%)`) and `--accent-line` border. A "Most popular" tab badge sits on the top border (mono 10px, `--accent-bg` fill, `--accent-on` text, offset top:-11px left:32px). Mono label "Unlimited" in `--accent`; price **£20** + "/ month"; note "Free 1-week trial — no card needed"; desc "For active job seekers. Unlimited sessions, cancel anytime."; checklist: "Unlimited sessions", "Screen & voice capture", "Instant replay", "Cancel anytime". CTA: **solid accent** button "Start free week" (`--accent-bg` / `--accent-on`; hover translateY(-2px) + shadow `--lime-cta-shadow` ≈ rgba(198,242,78,0.25) dark).

### 8. Closing CTA
Centered, max-width 760. H2 "Your next interview doesn't have to be a gamble." (clamp 32–52). Sub "Join developers who stopped leaving it to chance." (17px `--text-2`). Primary button "Try free — no card" (solid `--btn-bg`, 16px, padding 16×34, radius 11).

### 9. Footer
1px top border. Flex row, space-between, wraps. Left: logo mark + "InterviewAce". Center: "© 2026 InterviewAce. All rights reserved." (13px `--text-3`). Right: links "Support", "Pricing", "Privacy" (13px `--text-2`, hover `--text-1`).

---

## Interactions & Behavior
- **Nav links** smooth-scroll to section anchors (`html { scroll-behavior:smooth }`). Nav stays fixed and translucent over content.
- **Phone code typing loop:** on load (≈900ms delay) the phone `<pre>` types the Python solution char-by-char. Per-char delay ≈ 26–48ms (random), 8ms for spaces, 60ms after newlines. When complete, hold ~4.2s, clear, and repeat. A caret (5×10px accent block) blinks continuously (`ia-blink` 1.1s step-end). In production, implement with a small JS typing function writing to a single text node (don't trigger framework re-renders per character) — or use a CSS/canvas approach. Respect `prefers-reduced-motion` by showing the full code statically.
- **Caret blink** (`ia-blink`): opacity 1→0→1, 1.1s, step-end. Used in phone, browser code block.
- **Phone float** (`ia-float`): translateY 0→-7px→0, 6s ease-in-out infinite.
- **Eyebrow dot pulse** (`ia-pulse`): scale+opacity, 2s ease-in-out infinite.
- **Card hover:** border lightens to `--line-strong` (or `--accent-line` on feature A) and pain cards lift `translateY(-3px)`. Transition ~0.25s.
- **Button hover:** `translateY(-1 to -2px)` + colored box-shadow. Transition ~0.15s.
- **Entrance reveal (optional):** the prototype originally faded sections up on scroll via IntersectionObserver (opacity 0→1, translateY 18→0, ~0.7–0.8s, cubic-bezier(.2,.7,.2,1)). This was removed for robustness but is a nice-to-have — reintroduce with IntersectionObserver if desired, ensuring content stays visible if JS fails / reduced-motion is set.
- **Theme switching:** toggling theme only swaps the CSS-variable set on the root. NOTE: do **not** put a CSS `transition` on the root element's `background` property — it traps the var-backed background on the old color during the swap. Transition individual surfaces if you want a fade, or omit.

## State Management
Minimal — this is a marketing page. Only client state:
- Typing-animation index/timer (local, self-contained).
- Active theme (if you ship the toggle): persist to `localStorage` and/or honor `prefers-color-scheme`.
No data fetching. All copy is static (good candidates for Jinja template variables if you want CMS-ability later).

## Responsive Behavior
The prototype is built at desktop width (~1280). For production add breakpoints:
- Hero `1.05fr 0.95fr` → single column under ~900px (device below copy, or hide device on small phones).
- Pain grid `repeat(4,1fr)` → 2-up then 1-up.
- Features bento: collapse spans to single column on mobile (each tile full width).
- Pricing `1fr 1fr` → stacked.
- Nav: collapse center links into a menu under ~720px.
- Section padding 120px → ~72–80px on mobile.

## Assets
- **Fonts:** Google Fonts — Space Grotesk, Hanken Grotesk, JetBrains Mono. (Self-host in production for performance/privacy.)
- **Icons:** inline SVG, Feather-style, 1.8 stroke (shield, phone, video). No icon-font dependency. Lift the SVG paths directly from the prototype.
- **Images:** none — the hero device is built entirely in HTML/CSS. No raster assets required.
- **Logo:** text wordmark + a CSS square dot. No logo image.

## Files
- `InterviewAce Landing.dc.html` — **the design to build.** Full landing page, both themes (toggle via the `theme` prop in its `<script data-dc-script data-props>`; set `data-theme="light"` on the root to preview light). Open it in a browser to inspect live; use it as the source of truth for exact values.
- `Landing Style Explorations.dc.html` — three ALTERNATE directions (Editorial / Terminal / Warm-premium), hero + first section only. **Reference / not the build target** unless the team changes direction.
- `support.js` — runtime for the `.dc.html` prototype format. **Do not port to production**; it only exists so the HTML files open standalone.

### How to inspect exact values
Open `InterviewAce Landing.dc.html` in a browser and use devtools to read computed styles, or read the file source directly — every style is inline and the token table lives in the `<style>` block at the top (the `[data-ia]` and `[data-ia][data-theme="light"]` rules). The token values in this README mirror that block.
