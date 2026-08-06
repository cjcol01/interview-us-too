# Video production scripts

Shot-by-shot recording plans for the videos in `TODO.md` ("create videos for support, install,
sideload, landing"), plus two the codebase clearly warrants.

This is **not** a voiceover script. Each section says what state to put the app in, what to click,
what must appear on screen, and what to verify before you hit record. Everything below was derived
from the actual routes and templates — file references are included so you can re-check a step if
the UI moves.

---

## 0. Blockers — fix or work around these BEFORE filming

Every one of these is visible on camera. Filming over them means re-shooting later.

| # | Issue | Where | What to do |
|---|-------|-------|------------|
| B1 | Chrome Web Store link is a placeholder: `.../webstore/detail/interviewace/placeholder` | `templates/onboarding.html:55` | Either publish and swap the real URL, or film the install video on the sideload path only (V3) and shoot V2 from step 2 onward |
| B2 | Extension's display name is **"Interview Assistant"**, but onboarding/support tell the user to look for **"InterviewAce"** | `extension/manifest.json` name vs `templates/onboarding.html:105`, `templates/cancel_confirm.html` chrome mock | Rename in the manifest, or accept it and make sure narration/captions say what Chrome actually shows. Chrome's puzzle menu is on screen in V2, V3 and V5 |
| B3 | ~~Landing claims "replay the last **15 seconds**"; the DB default is **10s**~~ — no longer true: `models.py:70` now defaults `replay_seconds` to **15**, matching the copy. Older accounts may still sit at 10 | `templates/landing.html:384` & `:217` vs `models.py:70` | Nothing to fix. Just confirm the recording account reads 15s in Settings → Capture & replay (the seeded accounts are set to 15) |
| B4 | FAQ tells users to "click **Start session**" — no such button exists. Paid sessions start automatically on the first capture | `templates/faq.html:135` vs `server.py:4781` (`_account_bookkeeping`) | Fix the FAQ copy first. Do not demo a button that isn't there |
| B5 | Trustpilot link is `trustpilot.com/review/interviewace.example` | `templates/cancel_confirm.html` (got-job panel) | Swap for the real review URL before the cancel video (V6) shows that panel |
| B6 | Landing already embeds a YouTube video (`WhBbMlNWlnU`) | `templates/landing.html:409` | Confirm whether that's a placeholder. V1 is what replaces it |
| B7 | `/install-manual` 404s unless `SIDELOAD_ENABLED=1` | `server.py:2458` | Set `SIDELOAD_ENABLED=1` in the recording env, or V3 can't be filmed at all |

---

## 1. Recording environment

### Machine / rig

- **Two devices, both on camera at some point.** Computer (Chrome) + phone. The whole product
  premise is that the answer never appears on the interview machine — a video that only shows one
  screen fails to make the point.
- Phone: film physically (propped in front of the monitor, as onboarding step 6 tells users to do),
  not as a screen recording. The physical shot is the proof.
- Screen record at 1920×1080 minimum, 60fps for anything with a hotkey press or a stream.
- **Zoom the browser to 125%** for all screen recordings — the settings/support pages have small
  secondary text that dies on a phone-sized viewport.
- Clean Chrome profile: no other extensions in the toolbar, no bookmarks bar, no personal tabs, no
  profile avatar. Chrome's puzzle-piece menu appears in V2/V3/V5 and will show every extension you
  have installed.
- Use a real second Chrome profile for anything showing the "not connected" state — the token lives
  in extension local storage per profile (`templates/support.html` issue 05).

### Server / env vars

```bash
SIDELOAD_ENABLED=1        # required for /install-manual (V3)
SKIP_EMAIL_VERIFICATION=1 # skips the /verify-pending detour in V2 — see caveat below
DEV_BUILD=0               # keep dev affordances off; they render on-page
BASE_URL=<the real domain, or a clean local IP>
```

`BASE_URL` is on screen twice in V2 — in the manual-token block (`templates/onboarding.html:123`)
and as the phone URL under the QR code (`:280`). A `127.0.0.1` there makes the video look like a
dev demo, and the QR won't work from a phone. Use a LAN IP or the real domain.

**Caveat on `SKIP_EMAIL_VERIFICATION`:** it makes signup fast to film, but the real user flow goes
through `/verify-pending`. Decide per video — V2 (install) should show the real flow if you want it
to be an accurate support asset; a landing video (V1) shouldn't waste seconds on an inbox.

### Accounts to prepare

`python scripts/seed_dummy_users.py` creates all five below (plus the wider spread of states used
for admin-page testing) without going through Stripe. Password for every one: `DummyPass123!`.
Re-running tops up anything missing rather than duplicating.

| Account | Username | State | Used by |
|---------|----------|-------|---------|
| A | `dummy_rec_a_new` | Brand new, never signed in, no extension, trial unused | V2 (install), V3 (sideload) |
| B | `dummy_rec_b_ready` | Trial, onboarding complete, extension connected, replay on at 15s | V1 (landing), V5 (replay/voice) |
| C | `dummy_rec_c_sessions` | Session packs, 3 sessions remaining | V4 (support), session-timer inserts, V6 companion insert |
| D | `dummy_rec_d_sub` | Unlimited **with** a Stripe sub, retention offer unclaimed | V6 (cancel) — required, `/billing/cancel` redirects anyone who is neither unlimited nor holding a `stripe_sub_id` (`server.py:5340`) |
| E | `dummy_rec_e_disconnected` | Set up but no API token, so the extension can't authenticate | V4 — the "Not connected" system-check row |

The seeded state is server-side only. Three things still have to be done by hand on the day:
**arming replay** on account B (extension popup → Lock to this tab), **installing the extension**
in the recording profile, and — for V6 — **giving account D a real Stripe test-mode subscription**.

> **The seeded Stripe ids are fake** (`sub_dummy_rec_d`). Everything up to the last click of V6
> films fine, but the actions that call Stripe for real — *Claim offer* (`/billing/offer`),
> *Cancel subscription* (`/billing/cancel/confirm`, which 500s on a Stripe error), and *Manage
> billing* (`/billing/portal`) — will fail on a seeded account. For V6, subscribe a real test-mode
> customer in Stripe test mode and film that account instead, or accept that the final click can't
> be shown. Same for the cancellation email in V6 step 7: `dummy.rec.d@example.test` receives
> nothing — point account D at a real inbox before filming if you want that beat.

For A and E you'll want to reset between takes. Clearing the extension's stored token (popup →
clear the API Token field → Save) reproduces "Not connected" without reinstalling or reseeding.

### Redaction checklist — check every frame before publishing

- **API token** — shown in full in onboarding step 2's manual block and Settings → Extension
  (`templates/settings.html`, `#extension`). Blur it, or regenerate the token after filming
  (Settings → Extension → Regenerate token).
- **QR code in onboarding step 6** — it encodes a real signed login link (`/api/onboarding/mobile-link`
  → `/mobile-login`). It expires, but blur it anyway.
- Email address in the navbar / Settings → Account.
- Real interview content, real company names, real CV text if you demo Settings → Interview context.
- The Stripe portal in V6 — order history, card last-4.

---

## 2. Shot conventions (apply to all videos)

- **No talking head, no intro card, no logo sting.** Cut straight to the screen.
- Every hotkey press gets a **key-cap overlay** in the corner (`Ctrl+Shift+7` etc.) added in post.
  On screen the hotkey does nothing visible on the computer — that's the whole design — so without
  the overlay the viewer can't tell anything happened.
- **Never cut during a stream.** The answer arriving on the phone is the payoff shot; let it render
  in real time. If it's slow, that's a product problem to fix, not an edit problem to hide.
- Mouse: slow down deliberate clicks, no jitter, no hunting for targets. Rehearse each take.
- Captions burned in, since these will autoplay muted on the landing page and in support panels.
- Default hotkeys (`server.py:481`) — use these, don't rebind, so the video matches a fresh account:

  | Action | Key |
  |--------|-----|
  | Capture screen | `Ctrl+Shift+7` |
  | Voice (hold) | `Ctrl+Shift+8` |
  | Toggle on/off | `Ctrl+Shift+9` |
  | Instant replay | `Ctrl+Shift+6` |
  | Typing mode | `Ctrl+Shift+5` |

  On macOS the UI renders `Ctrl` as `Cmd` (`templates/onboarding.html:206`). Pick one OS per video
  and stay on it.

---

## V1 — Landing: "See it in action"

**Placement:** replaces/fills the embed at `templates/landing.html:409` (the `.ia-video-wrap`
iframe, sitting under the three how-it-works steps).
**Length:** 60–75s. No longer — it's above the pricing fold.
**Account:** B (trial, fully set up, replay armed, replay window set to 15s per B3).
**Goal:** prove the three capture modes and the phone delivery are real. It must land the claim the
steps above it make: *"Three ways to capture. One silent result."*

### Pre-roll setup (off camera)

1. Sign in as B on the computer; open `/app` on the phone and leave it in the foreground.
2. Open a LeetCode problem (`Two Sum` — it's already the Settings preview problem, so it's
   on-brand) in a normal tab.
3. Open a second tab playing a short clip of someone speaking (this stands in for the meeting tab),
   and **lock replay to it** via the extension popup → "Lock to this tab"
   (`extension/popup.html:109`). Verify the popup pill flips from `Idle` to armed.
4. Confirm the extension is armed: popup arm button reads **ON** / "Assistant on".
5. Set complexity and response style to whatever produces the tightest answer — `Bullets` or
   `Summary` reads better on a phone than `Conversational` for a 60s video
   (`templates/settings.html`, `#response`).

### Shot list

| # | Shot | On screen | Verify |
|---|------|-----------|--------|
| 1 | Wide, static: monitor with a coding problem, phone propped in front of it showing an idle `/app` | 0:00–0:04 | Phone dashboard shows the idle placeholder, not a stale answer. Clear it first (`Clear` button, `templates/index.html:227`) |
| 2 | Screen: the LeetCode problem. Press `Ctrl+Shift+7` | Key-cap overlay | **Nothing changes on the computer screen.** This is the shot that sells it. Do not cut away |
| 3 | Cut to phone (physical shot): "working" state → answer streams in | Live, uncut | Syntax highlighting renders; the code isn't red (that regression is fixed, but confirm on the day). Complexity dots visible |
| 4 | Back to computer. Hold `Ctrl+Shift+8`, speak a question ("what's the time complexity of a hashmap lookup?"), release | Key-cap overlay held, then released | Phone shows the **"You said"** transcription box (`templates/index.html:239`) before the answer — that box is the proof it heard you |
| 5 | Switch to the meeting tab (person speaking). Let 5–10s of speech play, then press `Ctrl+Shift+6` | Key-cap overlay | Phone shows the transcription of what was *just said* — no recording gesture happened. This is the least understood feature and the most impressive one |
| 6 | Final: hand picks up the phone from in front of the monitor; monitor is still on the plain problem page | 0:55–1:05 | Nothing on the computer screen shows the product at any point |

### Do not include

- Signup, onboarding, or the extension popup. This video is the outcome, not the setup.
- Any UI chrome that reads as "dev" — the navbar version chip, admin links.

### Failure modes to rehearse

- Replay says "buffer warming up" — the locked tab needs a few seconds of actual audio first
  (`templates/support.html` issue 02). Play audio for ~15s before shot 5.
- Rate limit: captures are throttled to one per 5s, 6/min, 15 per 5min (`server.py:4772`). Six takes
  in a row will hit it and produce an amber toast on `/app`. Pace the takes.

---

## V2 — Install & setup (Web Store path)

**Placement:** `/onboarding` (inline, top of step 1), post-signup email, `/support` issue 03.
**Length:** 2:30–3:30. This one is allowed to be long; people watch it while doing it.
**Account:** A (brand new). **Blocked on B1** unless the listing is live.
**Goal:** a new user gets from signup to a working capture without contacting support.

Mirror the real stepper exactly — `templates/onboarding.html` has six steps and the video should
have six chapters with the same numbers and the same headings. Chapter markers in the description.

### Chapter 0 — signup (0:00–0:20)

- `/` → **Start free trial** → register. Show the password show/hide toggle working.
- If filming the real flow: `/verify-pending`, then the email, then back. Cut the wait.
- Land on `/welcome`. The simulated interview demo auto-opens here
  (`templates/welcome.html:59`, `openMockInterview(true)`). **Let it play or skip it — decide
  once and be consistent.** Recommendation: skip it in V2 (it's covered by V1's material) and cut
  straight to `/welcome/next` → `/onboarding`.

### Chapter 1 — install the extension (0:20–0:50)

- Step 1 card is open. Click **Add to Chrome**.
- Show the Chrome Web Store page, the install confirm dialog, and the "Added to Chrome" toast.
- Return to the tab. Show the "Waiting for you to come back from the Web Store…" line
  (`onboarding.html:64`) resolving to the completed state.
- **Pin it.** Puzzle-piece icon → find the extension → click the pin. Callout: this is what B2
  affects — say the name Chrome actually shows.
- Show the escape hatch: "I've already installed it →" (`:70`) for people who already have it.

### Chapter 2 — connect to your account (0:50–1:15)

- Step 2 opens on its own and runs the connect rail: *Looking for the extension → Linking it to
  your account → Ready to capture* (`onboarding.html:89–103`). It's deliberately paced; don't
  speed-ramp it, the pacing is the reassurance.
- **Insert (film separately):** the manual fallback. Click "Set up manually instead", show the API
  token and Server URL rows, copy each, paste into the extension popup's two fields, Save. This
  insert doubles as the fix clip for support issue 05. **Blur the token.**

### Chapter 3 — microphone (1:15–1:45)

- Step 3, click **Allow microphone access**. A separate "Meeting Microphone Access" tab opens
  (`extension/grant-mic.html`) — Chrome's permission prompt appears there. Click **Allow**.
- Cut back: the LED next to "Checking microphone…" goes green.
- **Insert (film separately, needs a deliberately denied mic):** click "Never allow", show the
  denied help appearing (`onboarding.html:153`), the "Copy settings link" button, pasting
  `chrome-extension://…` into a new tab, setting Microphone to Allow, and the auto-recheck when you
  switch back to the tab. This insert is the fix clip for support issue 01 — the single highest
  support-volume issue in the accordion.

### Chapter 4 — arm instant replay (1:45–2:15)

- Read the three steps from the card on camera: switch to the tab you want to lock to (**in the
  browser, not the Zoom/Teams desktop app** — say this explicitly, it's the most common
  misunderstanding), open the popup, press **Lock to tab**.
- Practise on a YouTube video, as the card suggests (`onboarding.html:175`).
- Show the LED flipping from "Not armed yet." to armed, and the popup's `Idle` pill changing.
- Note on camera: a lock follows one tab and drops when it closes.

### Chapter 5 — open a problem (2:15–2:30)

- Click a platform link (LeetCode), open a problem.
- On the way past, show the hotkey list and expand **Show details** to reveal the two callouts:
  instant replay, and typing mode + passthrough (`onboarding.html:218–232`).

### Chapter 6 — move to your phone (2:30–3:00)

- Show the QR code (blurred in post), the countdown timer, and the copyable URL.
- **Physical shot:** phone scans the code, `/app` opens already signed in.
- Prop the phone in front of the monitor.
- Tap **Start 10-minute test run** on the phone (`templates/index.html:24`) — show the confirm
  overlay, then the trial countdown bar appearing.
- Final beat: press the capture hotkey on the computer, answer lands on the phone. Full loop closed.

### Verify before recording

- Step 2's rail actually resolves — if the extension is installed in a *different* Chrome profile
  than the one showing the page, it will sit at "Looking for the extension" forever.
- Trial has not already been used on account A: `/api/trial/start` refuses a second one
  ("Trial already used", `server.py:4706`).

---

## V3 — Manual install / sideload

**Placement:** `/install-manual` (top of page), linked from onboarding step 1's "Web Store
unavailable?" link and support issue 03.
**Length:** 1:30–2:00.
**Account:** A. **Requires `SIDELOAD_ENABLED=1`.**
**Goal:** get someone through an unpacked install without them thinking they're doing something
dangerous. Chrome's developer-mode warning is the emotional obstacle; address it head on.

### Shot list

Follow the five cards on `templates/install_manual.html` exactly, in order.

| # | Shot | Notes |
|---|------|-------|
| 1 | `/install-manual` hero, then click **Download .zip** | Show the download landing in the tray. Also point at "Trouble downloading? Try the mirror" — the primary is a CDN, the mirror is same-origin (`server.py:2465`) |
| 2 | Unzip it | Show the `interviewace-extension` folder appearing. **Say the folder must stay put** — Chrome loads from that path (card 1) |
| 3 | Copy `chrome://extensions` from the copy-chip, paste into the address bar | The page explains Chrome blocks direct links to it — show the click-to-copy working |
| 4 | Toggle **Developer mode** on (top right) | **Hold on Chrome's yellow warning banner for a full 2 seconds.** Caption it with the page's own line: Chrome shows this for every extension installed outside the Web Store. Skipping past this is what makes it look shady |
| 5 | **Load unpacked** → select the folder | Extension appears in the list immediately, no restart |
| 6 | Pin via the puzzle icon | Same shot as V2 chapter 1 — can reuse |
| 7 | Click **Continue to onboarding →** (`/onboarding?fresh=1`) | Hand off to V2 chapter 2. Say so explicitly: "the rest is the same as the normal install" |
| 8 | End on the footer note about Chrome disabling unpacked extensions after a browser update, and how to re-enable | This is a real recurring support ticket for sideloaders |

---

## V4 — Support: diagnose it yourself

**Placement:** `/support` hero, above the system check.
**Length:** 1:30–2:00 for the main video, plus short inserts embedded per accordion item.
**Accounts:** C (healthy) and E (extension present, token cleared).
**Goal:** teach the system check → fix-link loop, so the "Contact support" button is a last resort.

### Main video shot list

| # | Shot | Verify |
|---|------|--------|
| 1 | Open `/support` as account E. The four check rows resolve from "Checking…" | Rows: Browser extension, Phone link, Microphone, Instant replay (`templates/support.html:29–89`) |
| 2 | Extension row lands on **"Not connected"** and an inline **Connect →** button appears | This is the not-connected branch, distinct from "Not detected" (`_setExtFixState`) — the page routes to a *different* fix depending on which it is. Call this distinction out; it's the single most confusing thing in support |
| 3 | Click **Connect →**, show "✓ Connected!" and the row flipping green | The subline updates to "all clear" |
| 4 | Click **Run diagnostics** to re-run | Subline: "Last checked just now · all clear" |
| 5 | Show the filter pills (All / Audio / Extension / Delivery / Capture) narrowing the 9 articles | |
| 6 | Open issue 08 (Hotkeys not firing) and walk the fix list | Mention the "refresh the page after installing" rule — the content script does not inject into already-open tabs (`extension/content.js`) |
| 7 | Scroll to **Still stuck?** and click **Contact support** | Show the mail client opening with the **diagnostics snapshot pre-filled in the body** (`_updateStuckMailto`). This is the beat that makes the video worth watching — most people never notice it happens |

### Inserts to film alongside (10–25s each, silent, loopable)

Embed these next to the matching accordion item. Each needs the fault genuinely reproduced, not
mimed:

| Insert | Issue | How to reproduce the fault |
|--------|-------|----------------------------|
| Mic silent | 01 | Deny mic permission, press voice hotkey, show the grant-mic tab opening. Reuse V2 chapter 3's denied insert |
| Replay empty | 02 | Press replay with nothing locked; then lock, wait, press again |
| Can't install | 03 | Puzzle-piece → pin. Plus the pointer to `/install-manual` |
| Not detected | 04 | Toggle the extension off at `chrome://extensions`, run the check, toggle back on, **hard reload the tab**, re-run. The reload is the step everyone misses |
| Not connected | 05 | Clear the token in the popup, run the check, click Connect |
| Not reaching phone | 06 | Phone signed into a *different* account; show the same-account fix. (No pairing exists — the phone is just the same dashboard) |
| Blank capture | 07 | Capture a DRM-protected video tab, show the black frame |
| Hotkeys not firing | 08 | Press a hotkey on a tab that was open before install → nothing. Reload → works |
| Slow streaming | 09 | Hard to stage honestly. Instead, film the **fix**: trimming an over-stuffed context box in Settings → Interview context and the answer starting faster. Do not fake a stall |

---

## V5 — Voice, replay and typing mode

**Placement:** `/settings#capture`, support issues 01/02, onboarding step 4, and as a standalone
"getting the most out of it" email.
**Length:** 2:00.
**Account:** B.
**Goal:** these three features drive most of the "it doesn't work" tickets, and all three fail the
same way — the user didn't do the setup gesture. Show the gesture, then the payoff.

### Segment 1 — voice capture (0:00–0:40)

- Hold `Ctrl+Shift+8` while a question is spoken; release.
- Phone: **"You said"** box appears with the transcription, then the answer.
- Point out: hold, don't tap. Release sends.

### Segment 2 — instant replay (0:40–1:20)

- The setup: popup → **Lock to this tab**. Show the "Locked to: <tab name>" row and the Unlock
  button (`extension/popup.html:111`).
- Show the window slider (10–30s) and set it to match whatever the marketing copy says (see B3).
- Let audio play. Press `Ctrl+Shift+6`. Transcript + answer land on the phone.
- Show the failure: close the locked tab → the lock drops → replay produces nothing. Then re-lock.
  Showing the failure and the recovery is more useful than showing only the success.

### Segment 3 — typing mode + passthrough (1:20–2:00)

- Press `Ctrl+Shift+5`. **Nothing appears on the computer screen** — keystrokes are buffered by the
  content script (`extension/content.js:270`).
- Type a question. Press `Ctrl+Shift+5` again (or Enter) to submit.
- Phone shows the typed question and the answer.
- Show passthrough on vs off: with passthrough **on**, the keystrokes also reach the page — demo
  this in an online IDE so the viewer sees the text land in the editor too, which is exactly the
  scenario the setting exists for (`templates/settings.html`, `#capture`). With it off, the page
  sees nothing.

---

## V6 — Cancelling (backs the "3-click cancel" claim)

**Placement:** `/settings#billing`, the cancel page itself, and — worth considering — the landing
page next to the new "3-click cancel" trust-row item (`templates/landing.html:43`).
**Length:** 45–60s.
**Account:** D (`dummy_rec_d_sub`) — unlimited **with** a `stripe_sub_id`. Free/trial/session-pack
accounts get redirected to `/settings#billing` (`server.py:5340`), and an unlimited account without
a sub id reaches the page but can't complete the cancel (the confirm POST 400s).
**Goal:** the landing page now makes a falsifiable claim. This video is the proof. Film it in one
unbroken take with a click counter overlay.

### Shot list

1. `/settings` → scroll to Billing → click **Cancel subscription**. *(click 1)*
2. `/billing/cancel` loads. Show "What happens when you cancel" — subscription stays active to the
   end of the billing period.
3. The retention offer card appears (only if `sub_invoice_paid` and the offer isn't already
   claimed). Click **No thanks, continue cancelling**. *(click 2)*
4. The offer collapses into the persistent recall bar ("Offer still available · 50% off next month
   · Claim") and the feedback section reveals.
5. Pick a reason. Show one context panel opening — **"I got the job!"** is the best one to show
   (congratulations panel, review link; check B5 first).
6. Confirm cancellation. *(click 3)*
7. Land on the confirmation and show the cancellation email arriving.

**Honesty check:** count the clicks in the actual recording. If it's four, either fix the flow or
fix the landing copy — do not edit the video to make the number work. A support video that
overstates is worse than no video.

### Worth filming as a companion insert

The session-pack case: account C (paid, no sub) clicks around Billing and sees *"Nothing to cancel
— session packs are one-off purchases"* (`templates/settings.html:553`) instead of a cancel page.
15 seconds, kills a whole class of "how do I stop being charged?" tickets.

---

## 3. Pre-flight test pass

Run this the day of filming, on the exact machine and account you'll record with. Every item has
broken a take before.

**Server / environment**

- [ ] `python run_tests.py` passes.
- [ ] `SIDELOAD_ENABLED=1` and `/install-manual` returns 200, not 404.
- [ ] `BASE_URL` resolves from the phone on the same network (curl it from the phone browser).
- [ ] Redis is up — SSE streaming and capture state both depend on it; without it `/app` sits on
      "connecting...".
- [ ] `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` are live and have credit. A mid-take failover to
      OpenAI changes the answer's voice partway through a shot.
- [ ] `/admin/health` is all green.
- [ ] `python scripts/build_extension_zip.py` has been run if `extension/` changed — the sideload
      zip must be current for V3.

**Account state**

- [ ] Recording account's trial is unused (V2) / already set up (V1, V5).
- [ ] Account D genuinely has a `stripe_sub_id` (V6).
- [ ] Replay window reads 15s on the recording account (B3).
- [ ] Response style and complexity produce a phone-readable answer.
- [ ] No leftover capture on the dashboard — hit **Clear**.
- [ ] No announcement banner is active (`/admin/announcements`) — it renders across the top of every
      page.

**Browser**

- [ ] Only the InterviewAce extension installed, and it's pinned.
- [ ] Extension **armed** (popup reads ON) — otherwise every hotkey silently does nothing and you
      won't notice until playback.
- [ ] All tabs you'll capture on were opened **after** the extension was installed/updated (content
      script doesn't retro-inject).
- [ ] Zoom at 125%, bookmarks bar hidden, no profile avatar.
- [ ] Notifications silenced at the OS level.

**Rate limits**

- [ ] Fewer than 15 captures in the last 5 minutes before the take that matters (`server.py:4772`).
      Do your rehearsals, then wait five minutes before the real take.

---

## 4. Delivery spec

| Video | Where it embeds | Format | Notes |
|-------|-----------------|--------|-------|
| V1 Landing | `templates/landing.html` `.ia-video-wrap` | YouTube embed (existing iframe) | Also export a muted, captioned, ≤15s cut for paid social |
| V2 Install | `/onboarding` step 1, welcome email | Self-hosted or YouTube, chaptered | Chapters must match the six step numbers |
| V3 Sideload | `/install-manual` hero | Self-hosted | Short enough to be inline |
| V4 Support | `/support` hero | Self-hosted | Plus 9 silent looping inserts, one per accordion item |
| V5 Features | `/settings#capture`, support 01/02 | Self-hosted | Three separable segments — export individually too |
| V6 Cancel | `/settings#billing`, landing trust row | Self-hosted | One unbroken take, click counter overlay |

**Inserts** (the per-issue clips in V4, and V2's manual-token/denied-mic clips): export as muted,
looping, captioned MP4s under ~2MB so they can sit inline in an accordion without hurting page
load. They carry no audio, so they need on-screen text for every step.

Naming: `ia-v{n}-{slug}-{yyyymmdd}.mp4`, e.g. `ia-v4-support-diagnose-20260806.mp4`. Keep the
project files — B1–B6 will change the UI and force partial re-shoots.

---

## 5. Filming order (recommended)

1. **V3 (sideload)** — no Web Store dependency, so it's unblocked today.
2. **V4 (support) + inserts** — highest ticket-deflection value per minute of work.
3. **V6 (cancel)** — the page was just redesigned and the landing claim is live now.
4. **V5 (features)** — reuses the rig from V4's inserts.
5. **V2 (install)** — blocked on B1; several of its inserts are already shot by then.
6. **V1 (landing)** — shoot last, once you know which shots read best on the smaller ones.
