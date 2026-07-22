# Handoff: Practice Interview — Demo Call (full-screen)

## Overview
A full-screen, self-running "practice interview" experience used to demo InterviewAce on sales/investor calls. The user joins a simulated video call with an AI interviewer ("Alex"), who asks four questions. When the candidate gets stuck, they press a hotkey (or click) and the AI answer appears **privately on their phone** — invisible to the interviewer. It walks through the product's four help modes in one flow: **screen capture, voice, replay, and private typing**.

This replaces the old cramped centered-modal demo with a real-video-call layout that fills the screen and reads clearly on a shared screen.

## About the Design Files
The files in this bundle are **design references created in HTML** (a prototype showing the intended look and behavior) — **not production code to copy directly**. The task is to **recreate this design in the target codebase's existing environment**.

Per project memory, the product is a **Flask app with Jinja2 templates** (`templates/`, shared `base.html`), a global stylesheet `css/global.css`, and per-page CSS. Implement this as a new page/route in that stack: add the markup to a Jinja template, drive state/interaction with vanilla JS (or whatever the app already uses), and style via `global.css` tokens + a per-page stylesheet. **Do not paste the `.dc.html` prototype or its `support.js` runtime into production** — they are prototype-only. Recreate the structure using the app's own patterns.

## Fidelity
**High-fidelity (hifi).** Colors, typography, spacing, radii, and interactions are final. Recreate pixel-accurately using the values in this doc. The design follows the existing InterviewAce design system (see `design_handoff_landing/README.md` in the project and `CLAUDE.md`).

## Chosen direction
Three directions were explored (Gallery / Split cockpit / Cinematic). **The approved design is "Split cockpit" (option 1b), with these refinements:**
- The AI answer surface is a **phone mockup** on the right rail (not a flat side panel).
- The **interviewer's speech** appears as a caption **inside his video tile**.
- The **candidate's speech** (live transcript while recording) appears **beside their tile**, which is a **small non-focused PiP box** (~224×132).

The other two directions (`gallery`, `cinematic`) still exist in the prototype behind a `layout` prop but are **out of scope** for production unless requested.

---

## Canvas / stage
The whole experience renders inside a fixed **1440 × 900** stage (`position:relative; overflow:hidden`). Background `#0A0A0C`. In production this should be a full-viewport page (`100vw × 100vh`), with the internal proportions below preserved. All device mockups (screen-share window, phone) stay dark in both themes.

There are three top-level phases: **Lobby → Live call → Done**.

---

## Screen 1 — Lobby (green room)
**Purpose:** Pre-call setup screen; user reviews their camera and joins.

**Layout:** Full-stage flex row, centered, `gap:40px`, `padding:56px`, background `radial-gradient(1200px 700px at 50% -10%, #111117, #0A0A0C)`.
- **Left (flex:0 0 620px):** camera preview tile, `aspect-ratio:16/9`, `border-radius:18px`, `1px solid rgba(255,255,255,0.09)`, striped placeholder background `repeating-linear-gradient(135deg,#111116 0 11px,#0d0d12 11px 22px)`.
  - Centered avatar: 96px circle, bg `#17323a`, initial "Y" in `#7fe0c8`, Space Grotesk 600 34px.
  - Bottom-left label chip "You · camera on" — JetBrains Mono 12px, bg `rgba(10,10,12,0.6)`, `border-radius:8px`, padding `6px 11px`.
  - Top-right: two 40px circular control buttons (mic, video icons), `border:1px solid rgba(255,255,255,0.14)`.
- **Right (flex:1, max-width:360px):**
  - Kicker: `01 · Practice interview` — JetBrains Mono 12px, uppercase, letter-spacing 0.16em, `#67676F`, the `01` in `#C6F24E`.
  - H1 "Ready to join?" — Space Grotesk 600, 38px, line-height 1.02, letter-spacing −0.03em, `#F4F4F6`.
  - Sub: 15px `#9C9CA6` — "A short simulated call — see exactly how InterviewAce works in a real interview. Nothing is recorded, and it won't touch your trial time."
  - Tip box: bg `#0e0e12`, `1px solid rgba(255,255,255,0.08)`, `border-radius:14px`, padding `15px 16px`. Line 1 (with music/pin icon) "Pin the extension so it's one click away." Line 2 "Arm it with `⌃` `⇧` `9`" (keycaps).
  - Primary button "Join call →" — full width, bg `#C6F24E`, text `#0A0A0C`, Hanken 600 15px, `border-radius:12px`, padding 14px. Hover: `translateY(-2px)` + `box-shadow:0 14px 34px rgba(198,242,78,0.22)`.
  - Presence row: 26px avatar (initials "A", bg `#2a2320`, `#E0A96A`) with a `#C6F24E` online dot, text "Alex is already in the call" `#67676F` 13px.

**Keycap style (used throughout):** JetBrains Mono 11–13px, color `#F4F4F6`, bg `#0A0A0C`, `border:1px solid rgba(255,255,255,0.16–0.18)`, **`border-bottom-width:2px`**, `border-radius:5–7px`, padding `~4–6px 7–11px`, min-width ~26–30px, centered.

---

## Screen 2 — Live call (Split cockpit)
**Purpose:** The interview itself. Runs 4 "beats" (questions). Interviewer on the left, AI answers on the phone at right.

**Layout:** Full-stage flex row.
- **Left column (flex:1):** vertical flex — top bar (58px) · content (padding 18px, `gap:14px`) · control bar (70px).
- **Right rail (width:428px, flex-shrink:0):** `border-left:1px solid rgba(255,255,255,0.08)`, bg `radial-gradient(700px 500px at 60% 20%, #111117, #0A0A0C)`, centers a phone mockup.

### Top bar (left column)
Height 58px, `border-bottom:1px solid rgba(255,255,255,0.07)`, bg `#0C0C0F`, padding `0 24px`, space-between.
- Left: brand lockup — 8px `#C6F24E` rounded square with `box-shadow:0 0 8px #C6F24E` + "InterviewAce" (Space Grotesk 600 15px) · 1px divider · "Practice Interview · Technical Screen" (13px `#9C9CA6`).
- Right: timer chip `mm:ss` (JetBrains Mono 12px, bg `#141417`, `1px solid rgba(255,255,255,0.08)`, radius 8px, padding `5px 10px`). Counts up from 00:00 at join.

### Interviewer tile (content, flex:1)
`border-radius:16px`, `overflow:hidden`, bg `#0d0d10`. Border is **state-driven**: `rgba(198,242,78,0.5)` while Alex is speaking, else `rgba(255,255,255,0.09)` (0.2s transition).
- **Not sharing (verbal beats):** centered avatar — 118px wrapper containing a 104px circle (bg `#2a2320`, initials `#E0A96A`, Space Grotesk 600 36px). While speaking, a 2px `#C6F24E` ring animates outward (`ia-ring`). Background `radial-gradient(circle at 50% 38%, #1b1b22, #0d0d10)`.
  - Name chip bottom-left: "Alex" + (while speaking) small animated waveform bars. JetBrains Mono 11px chip on `rgba(10,10,12,0.62)`.
- **Sharing (capture beat only):** the shared-screen window fills the tile (see below). Name chip becomes a compact **top-right** badge "Alex · sharing screen" (JetBrains Mono 10px) so it never overlaps the shared content.
- **Interviewer speech caption** (both states): centered near the bottom (`left:16 right:16 bottom:16`), a bubble — max-width 640px, font 16px `#F4F4F6`, line-height 1.5, bg `rgba(8,8,10,0.82)`, `1px solid rgba(255,255,255,0.09)`, `border-radius:12px`, padding `11px 18px`, `backdrop-filter:blur(4px)`. Shows the interviewer's current line, then the full question.

### Shared-screen window (capture beat)
A fake LeetCode "Two Sum" browser window. Column layout on `#0d0d10`.
- Title bar: 3 traffic-light dots (`#ff5f57`, `#febc2e`, `#28c840`) + URL pill "leetcode.com/problems/two-sum" (JetBrains Mono 10px, bg `#0A0A0C`), bg `#141417`, bottom border.
- Body split: left 40% problem panel ("1. Two Sum" heading Space Grotesk 600 13px + gray skeleton bars); right editor on `#0a0a0c`, JetBrains Mono 11.5px, syntax colors — comment `#6A9955`, keyword `#C586C0`, function name `#DCDCAA`, text `#D4D4D4`, plus a blinking `#C6F24E` caret block.

### Candidate ("You") tile — small PiP
A bottom row: `display:flex; align-items:flex-end; gap:16px`.
- **Tile: 224 × 132**, `border-radius:14px`, bg `radial-gradient(circle at 50% 40%, #141a1c, #0d0d10)`. Border state-driven: `rgba(198,242,78,0.5)` while recording else `rgba(255,255,255,0.09)`.
  - Centered avatar: 54px circle (bg `#17323a`, "Y" `#7fe0c8`, Space Grotesk 600 20px), with animated `#C6F24E` ring while recording.
  - "You" chip bottom-left.
- **Beside the tile (flex:1):**
  - While recording: uppercase JetBrains Mono 9.5px `#C6F24E` label "● You're speaking" (pulsing dot), then the live transcript in italic 15px `#ECECEE` wrapped in quotes, typed out character by character.
  - Otherwise: faint hint "Your mic is live — speak when you're ready." (JetBrains Mono 11.5px `#5b5b63`).

### Control bar (left column)
Height 70px, top border, bg `#0C0C0F`, centered `gap:11px`.
- 3 circular 44px buttons: mic, video, **present/share**. Share button is highlighted during the capture beat: color `#C6F24E`, bg `rgba(198,242,78,0.1)`, border `rgba(198,242,78,0.4)`; otherwise color `#ECECEE`, bg `#17171b`, border `rgba(255,255,255,0.12)`.
- Red "Leave" pill: bg `#E5484D`, white text, Hanken 600 13.5px, `border-radius:22px`, height 44px, padding `0 18px`. → returns to Lobby.

### Phone mockup (right rail) — the AI surface
Bezel: 326 × 668, `border-radius:48px`, padding 11px, bg `#1a1a1e`, `1px solid rgba(255,255,255,0.14)`, `box-shadow:0 40px 90px rgba(0,0,0,0.6)`. Inner screen: `border-radius:38px`, bg `#0A0A0C`, with a black notch (100×25) at top.
- **Phone header:** brand lockup "InterviewAce" + an **armed pill** (see states) on the right; below, "Private · Question N of 4" (JetBrains Mono 9.5px uppercase `#67676F`).
- **Phone body (scrollable):** renders the current **panel state** (below).

The phone body is the only place AI content appears — reinforcing "the interviewer never sees this."

#### Panel states (inside the phone)
1. **Idle / listening** (before a hotkey is pressed): pulsing `#67676F` dot + "Listening for your cue", sub "When you get stuck, press the hotkey — the answer only shows up here."
2. **Armed (help prompt):** `● Need help?` (JetBrains Mono 10px `#C6F24E`), the beat's popup text (13.5px `#ECECEE`), a keycap row (e.g. `⌃ + ⇧ + 1`) + label, and a ghost-accent button "or click to run →" (color/border `#C6F24E`, bg `rgba(198,242,78,0.06)`).
3. **Recording** (voice beat, while key held): "● Listening" label + animated waveform bars, and the live partial transcript in italic quotes.
4. **Sending (~1s):** optional "You asked" + transcript, then a pulsing amber `#E0A96A` dot with italic status — "Reading your shared screen…" (capture) / "Processing audio…" (voice, replay) / "Thinking…" (typing).
5. **Typing** (typing beat): "Typing privately · hidden from interviewer" label + an input row (accent border, `›` prompt, "Ask" button) that auto-types the question; Enter or "Ask" sends.
6. **Answer:** "Answer · via {mode}" label + the rendered answer (fades in), then a light "Next question →" / "Finish →" button (bg `#ECECEE`, text `#0A0A0C`).

---

## The four beats (script + answers)
Order is fixed. Each beat = one question + one help mode.

| # | Mode | Hotkey | Interviewer line | Answer summary |
|---|------|--------|------------------|----------------|
| 1 | **capture** (screen) | `⌃⇧1` | "First up — let me share my screen." → *Given an array of integers and a target, how would you find two numbers that add up to it?* | "Use a hash map…" + Python `two_sum` code block + tags `O(n) time` / `O(n) space` · one pass. |
| 2 | **audio** (voice, hold) | `⌃⇧2` | "Let's switch gears — tell me about a time you disagreed with a teammate on a technical decision." | STAR paragraph (message-queue-vs-API-calls spike, caught a real outage). |
| 3 | **replay** (last 30s) | `⌃⇧3` | "Quick one — what's the difference between a process and a thread?" | Two short paragraphs; **process** and **thread** bolded. |
| 4 | **typing** (private) | `⌃⇧4` | "Last one — how would you design a rate limiter for a public API?" | "Key angles:" bulleted list (token bucket vs sliding window; per-user vs global; multi-server Redis vs single). |

Exact answer copy and code live in the prototype's `answerBody(kind)` method — reproduce verbatim. Transcripts: beat 2 = "Tell me about a time you disagreed with a teammate on a technical decision."; beat 3 = "(replayed) What's the difference between a process and a thread?"; beat 4 auto-types "How should I approach designing a rate limiter for a public API?".

---

## Screen 3 — Done overlay
Shown after beat 4 finishes. Full-stage scrim `rgba(6,6,8,0.9)` + `backdrop-filter:blur(8px)`, centered card (560px, bg `#0e0e12`, `1px solid rgba(255,255,255,0.1)`, `border-radius:20px`, padding 34px), fades/rises in.
- Header: 40px `#C6F24E` check circle + "That's the whole loop." (Space Grotesk 600 22px) + sub "Four ways to get an answer — private, instant, and invisible to the interviewer."
- Recap list: 4 rows (bg `#111114`), each = keycaps + label: `⌃⇧1` Send your shared screen to the AI · `⌃⇧2` Speak the question out loud · `⌃⇧3` Replay the last 30 seconds · `⌃⇧4` Type it privately — never seen.
- Actions: primary "↻ Replay demo" (accent, restarts) + ghost "Back to lobby".

---

## Interactions & Behavior
- **Arming:** Hotkeys only fire when the stage is **hovered/focused** (mirrors the real extension being armed). Header pill shows "Hover to arm" (`#67676F`) → "Armed" (`#C6F24E`) on hover. In production, tie "armed" to whatever focus model the real page uses; keep the visible armed indicator.
- **Hotkeys:** global `keydown` for `Ctrl+Shift+{1..4}` (match on `event.code === 'Digit'+n`, `preventDefault`). Each beat only responds to its own key while in the `armed` state.
  - capture/replay: key → `sending` → answer.
  - audio: **keydown** starts recording (transcript types out live); **keyup** sends. Click fallback auto-stops after ~1.3s.
  - typing: key opens the input and auto-types the question; Enter/"Ask" sends.
- **Timing:** after a beat starts, interviewer "line" shows, then the full question at ~1.5s, then `armed` (help prompt appears) at ~2.4s. "Sending" lasts **~1000ms** before the answer (per request — answers are not instant). Transcript/typing auto-type at ~26ms/char.
- **Animations** (respect `prefers-reduced-motion`, all disabled under it):
  - `ia-ring`: speaking/recording ring, `scale(1)→scale(1.5)`, opacity `.55→0`, ~1.5–1.7s ease-out infinite.
  - `ia-pulse`: dots, opacity/scale, ~0.9–2s.
  - `ia-wave`: waveform bars, `scaleY(.35)→1`, 0.9s, staggered delays.
  - `ia-pop`: panels/popups rise+scale in, 0.3s cubic-bezier(.2,.8,.2,1).
  - `ia-fade`: answers/overlay, 0.3s.
  - Button hovers: `translateY(-1/-2px)` + soft shadow, 0.15s.
- **Navigation:** "Join call" → Live; "Leave" → Lobby; "Finish" → Done; "Replay demo" → restart at beat 1; "Back to lobby" → Lobby.

## State Management
Single state object:
- `phase`: `'lobby' | 'live' | 'done'`
- `beat`: `0..3`
- `step`: `'question' | 'armed' | 'recording' | 'sending' | 'typing' | 'answer'`
- `said`: bool (line → question swap)
- `hovered`: bool (armed gating)
- `typed`, `partial`: strings (typing box / live transcript)
- `secs`: call timer (interval, +1/s while live)
Transitions are timer-driven as described under Timing; clear beat timers on each beat change; clear the clock on done/leave.

## Design Tokens
**Color**
- bg `#0A0A0C` · panel `#0C0C0F` · card/tile `#0d0d10` / `#0e0e12` / `#111114` / `#141417` · control `#17171b`
- lines `rgba(255,255,255,0.07)` / `0.08` / `0.09` · strong `rgba(255,255,255,0.16–0.18)`
- text `#F4F4F6` / `#ECECEE` / `#9C9CA6` / `#67676F` / `#5b5b63`
- accent `#C6F24E` · accent-soft `rgba(198,242,78,0.06)` · accent-line `rgba(198,242,78,0.28)` · accent-ring `rgba(198,242,78,0.5)`
- amber (thinking) `#E0A96A` · destructive `#E5484D`
- Alex avatar `#2a2320` / `#E0A96A`; You avatar `#17323a` / `#7fe0c8`
- Code: comment `#6A9955`, keyword `#C586C0`, fn `#DCDCAA`, body `#D4D4D4`; traffic lights `#ff5f57`/`#febc2e`/`#28c840`

**Type**
- Display/headings: **Space Grotesk** 600, letter-spacing −0.02 to −0.03em (H1 38px, done 22px, tile initials 20–36px).
- Body/UI: **Hanken Grotesk** 400–600, line-height ~1.5–1.6 (buttons 13–15px, captions 15–16px).
- Mono/labels/code: **JetBrains Mono** — labels uppercase 9.5–12px letter-spacing 0.1–0.16em; code 11.5–12px.

**Radius:** tiles 14–16px · phone screen 38 / bezel 48px · buttons 8–12px · pills/chips 6–8px · circular controls 50%.
**Spacing:** stage padding 18–56px · content gap 14px · card padding 34px. **Shadows:** phone `0 40px 90px rgba(0,0,0,0.6)`; frame `0 30px 80px rgba(0,0,0,0.5)`; button hover `0 14px 34px rgba(198,242,78,0.22)`.

## Assets
None external. Camera preview is a CSS striped placeholder; the shared screen and phone are pure HTML/CSS mockups; icons are inline SVGs (mic, video, present, users, chart, check, eye). Fonts via Google Fonts (Space Grotesk, Hanken Grotesk, JetBrains Mono). In the real interview, replace the fake camera/shared-screen with the actual video streams.

## Files
- `Demo Call.dc.html` — the interactive prototype (the approved **Split cockpit** is `layout="cockpit"`; the engine, four beats, answer bodies, and all states live here). `layout="gallery"` and `layout="cinematic"` are alternate directions, out of scope.
- `Demo Call Explorations.dc.html` — the side-by-side canvas comparing all three directions.
- Reference for tokens/patterns: `CLAUDE.md` and `design_handoff_landing/README.md` in the project root.
