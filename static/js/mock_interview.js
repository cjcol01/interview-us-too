// Mock interview: full-screen "Split cockpit" practice call. Shared by /welcome (first-run) and
// /app ("How it works" replay). Host pages must set `window.MI_HOTKEYS` ({capture, audio, toggle,
// replay, typing}) and may set `window.MI_ON_FIRST_RUN_FINISH` (called from miClose() after a
// first-run demo closes) and `window.MI_FIRST_RUN_CTA_LABEL` (button text shown on the "Done"
// screen during a first run) before this script runs.

// Pausable timers: every delay in this file goes through miAfter (rather than raw
// setTimeout) so miPauseTimers/miResumeTimers — used while the leave-confirmation dialog is
// open — can freeze the whole call (dialogue, streaming text, beat transitions) and pick up
// exactly where it left off, instead of losing time or racing ahead while paused.
let _miPendingTimers = [];
let _miPaused = false;
let _miSpeedLevel = 0; // -2..2 — one press of the tortoise/hare buttons = 20% off default per step

function miSpeedMultiplier() { return 1 - _miSpeedLevel * 0.2; }

function miScheduleTimer(scaled, fn) {
  const timer = { fn, remaining: scaled, startedAt: Date.now(), handle: null };
  if (!_miPaused) {
    timer.handle = setTimeout(() => {
      _miPendingTimers = _miPendingTimers.filter((t) => t !== timer);
      fn();
    }, scaled);
  }
  _miPendingTimers.push(timer);
  return timer;
}

// First-run comprehension: the opening round throws a lot at someone at once — interviewer
// question, hotkey press, then an answer streaming into two areas of the screen — and testers
// couldn't absorb it live. On a second pass, with context, the same pace felt fine. So the first
// two rounds run slower and the rest of the call is unchanged. Indexed by _miIndex, which is -1
// during the intro (unslowed) and 0-based once questions start.
const MI_ROUND_PACING = [1.25, 1.1];

function miRoundMultiplier() { return MI_ROUND_PACING[_miIndex] || 1; }

// Stacks with miSpeedMultiplier rather than replacing it, so the tortoise/hare buttons still
// work during the slowed rounds.
function miAfter(ms, fn) { return miScheduleTimer(ms * miSpeedMultiplier() * miRoundMultiplier(), fn); }

// Unscaled version of miAfter — used for the things neither the tortoise/hare buttons nor the
// first-round slowdown should touch: how long the AI takes to start responding, and the
// typing/streaming speed. Those already read well at full speed; slowing them just makes the
// demo feel sluggish rather than comprehensible.
function miAfterFixed(ms, fn) { return miScheduleTimer(ms, fn); }

function miUpdateSpeedBtns() {
  const slowBtn = document.getElementById('mi-slow-btn');
  const fastBtn = document.getElementById('mi-fast-btn');
  const slowBar = document.getElementById('mi-slow-bar');
  const fastBar = document.getElementById('mi-fast-bar');
  const slowLevel = _miSpeedLevel < 0 ? -_miSpeedLevel : 0;
  const fastLevel = _miSpeedLevel > 0 ? _miSpeedLevel : 0;
  [[slowBtn, slowBar, slowLevel], [fastBtn, fastBar, fastLevel]].forEach(([btn, bar, level]) => {
    if (btn) {
      btn.classList.toggle('active', level > 0);
      btn.classList.toggle('level-1', level === 1);
      btn.classList.toggle('level-2', level >= 2);
    }
    if (bar) {
      bar.classList.remove('level-1', 'level-2');
      if (level === 1) bar.classList.add('level-1');
      else if (level >= 2) bar.classList.add('level-2');
    }
  });
}

function miSlowDown() {
  _miSpeedLevel = Math.max(-2, _miSpeedLevel - 1);
  miUpdateSpeedBtns();
}

function miSpeedUp() {
  _miSpeedLevel = Math.min(2, _miSpeedLevel + 1);
  miUpdateSpeedBtns();
}

function miClearTimers() {
  _miPendingTimers.forEach((t) => { if (t.handle) clearTimeout(t.handle); });
  _miPendingTimers = [];
}

// Cancels a single timer returned by miAfter/miAfterFixed — used to reschedule the
// "continue the call" countdown when the visitor switches response style mid-read,
// without needing to touch any other in-flight timer.
function miCancelTimer(timer) {
  if (!timer) return;
  if (timer.handle) clearTimeout(timer.handle);
  _miPendingTimers = _miPendingTimers.filter((t) => t !== timer);
}

function miPauseTimers() {
  if (_miPaused) return;
  _miPaused = true;
  const now = Date.now();
  _miPendingTimers.forEach((t) => {
    if (!t.handle) return;
    clearTimeout(t.handle);
    t.remaining = Math.max(0, t.remaining - (now - t.startedAt));
    t.handle = null;
  });
}

function miResumeTimers() {
  if (!_miPaused) return;
  _miPaused = false;
  _miPendingTimers.forEach((t) => {
    t.startedAt = Date.now();
    t.handle = setTimeout(() => {
      _miPendingTimers = _miPendingTimers.filter((x) => x !== t);
      t.fn();
    }, t.remaining);
  });
}

const MI_PREFERS_REDUCED_MOTION = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function miStreamText(el, text, done) {
  if (MI_PREFERS_REDUCED_MOTION) { el.textContent = text; if (done) miAfterFixed(150, done); return; }
  let i = 0;
  function tick() {
    if (i >= text.length) { if (done) done(); return; }
    el.textContent = text.slice(0, i + 1);
    const ch = text[i];
    const delay = ch === '\n' ? 70 + Math.random() * 50 : ch === ' ' ? 9 : 20 + Math.random() * 18;
    i++;
    miAfterFixed(delay, tick);
  }
  tick();
}

// Syntax-highlights the <pre><code> blocks marked just rendered, so the demo's answers look
// like the real /app ones instead of a flat wall of monospace. Optional by design: hljs is a
// CDN script, and a demo that renders unhighlighted code is far better than one that throws
// mid-stream, so every call site goes through here rather than touching hljs directly.
function miHighlightCode(el) {
  if (!window.hljs) return;
  el.querySelectorAll('pre code').forEach((block) => {
    const m = block.className.match(/language-(\S+)/);   // marked's default langPrefix
    if (m && !hljs.getLanguage(m[1])) block.className = ''; // not in the bundle → let hljs auto-detect
    try { hljs.highlightElement(block); } catch {}
  });
}

// The single place markdown gets written into an answer body — both the streaming path and the
// response-style pills go through it, so the highlight pass can't be dropped on one of them.
function miRenderMarkdown(el, text) {
  el.innerHTML = marked.parse(text);
  miHighlightCode(el);
}

function miStreamMarkdown(el, text, done) {
  if (MI_PREFERS_REDUCED_MOTION) { miRenderMarkdown(el, text); if (done) miAfterFixed(150, done); return; }
  let i = 0;
  function tick() {
    if (i >= text.length) { miRenderMarkdown(el, text); if (done) done(); return; }
    i = Math.min(i + 3, text.length);
    // Highlighting each frame (not just the finished block) is the point: an unclosed ``` fence
    // still parses as a code block, so the colour arrives with the characters the way it does on
    // a real streamed response. The blocks are ~10 lines, so re-highlighting per tick is cheap.
    miRenderMarkdown(el, text.slice(0, i));
    miAfterFixed(26 + Math.random() * 26, tick);
  }
  tick();
}

// Animates typing into a (read-only, demo-only) text display — never sends real keystrokes.
// The field is a plain div (not an <input>) so long questions wrap onto multiple lines
// instead of scrolling off the edge of a single-line box.
function miTypeIntoField(field, text, done) {
  if (MI_PREFERS_REDUCED_MOTION) { field.textContent = text; if (done) miAfterFixed(150, done); return; }
  let i = 0;
  function tick() {
    if (i >= text.length) { if (done) done(); return; }
    field.textContent = text.slice(0, i + 1);
    const ch = text[i];
    const delay = ch === ' ' ? 9 : 20 + Math.random() * 18;
    i++;
    miAfterFixed(delay, tick);
  }
  tick();
}

// Streams a line into the speaker's own tile — the interviewer's caption sits inside his video
// tile, the candidate's speech (both the live relay-back and any future recording UI) appears
// beside the small PiP tile. `who` is 'interviewer' or 'you'.
function miSpeak(text, who, done) {
  const tile = document.getElementById(who === 'you' ? 'mi-you-tile' : 'mi-interviewer-tile');
  tile.classList.add('speaking');

  if (who === 'you') {
    const status = document.getElementById('mi-you-status');
    const liveText = document.getElementById('mi-you-live-text');
    status.classList.add('live');
    liveText.textContent = '';
    miStreamText(liveText, text, () => {
      tile.classList.remove('speaking');
      // Keep 'live' until miResetTileUI on the next beat so the text stays
      // visible through the pause and the interviewer's reply, not just for
      // the instant the streaming finishes.
      if (done) done();
    });
    return;
  }

  const captionText = document.getElementById('mi-caption-text');
  const cursor = document.getElementById('mi-cursor');
  captionText.textContent = '';
  cursor.style.display = 'inline-block';
  miStreamText(captionText, text, () => {
    cursor.style.display = 'none';
    tile.classList.remove('speaking');
    if (done) done();
  });
}

function miHotkeys() { return window.MI_HOTKEYS || {}; }

function miMatchHotkey(e, hotkeyStr) {
  if (!hotkeyStr) return false;
  const isMac = /Mac/.test(navigator.platform);
  const parts = hotkeyStr.split('+');
  const main = parts[parts.length - 1];
  for (const m of parts.slice(0, -1)) {
    if (m === 'Ctrl' && !(isMac ? e.metaKey : e.ctrlKey)) return false;
    if (m === 'Shift' && !e.shiftKey) return false;
    if (m === 'Alt' && !e.altKey) return false;
  }
  return e.key.toUpperCase() === main.toUpperCase() || e.code === `Digit${main}` || e.code === `Key${main.toUpperCase()}`;
}

function miRenderHotkey(hotkey) {
  if (!hotkey) return '';
  const isMac = /Mac/.test(navigator.platform);
  return hotkey.split('+').map(part => {
    const display = isMac && part === 'Ctrl' ? 'Cmd' : part;
    return `<kbd>${display}</kbd>`;
  }).join(' + ');
}

// window.MI_FIRST_NAME (set by the host page — see welcome.html/index.html) is read here
// rather than baked into static consts, since it's only known once the host template renders.
function miFirstName() { return window.MI_FIRST_NAME || ''; }

function miIntroLine() {
  const name = miFirstName();
  return name
    ? `Hi, I'm Alex — nice to meet you, ${name}! Let's get straight into it.`
    : "Hi, I'm Alex — nice to meet you! Let's get straight into it.";
}

// Each beat: interviewer asks -> you press the hotkey -> the AI answers privately -> you relay
// `youReply` back to the interviewer -> interviewer moves on. `hotkeyLabel`/`via`/`sendingText`/
// `recap` are short real descriptions of that beat's mode, used in the phone UI and done-screen
// recap — not additional invented functionality.
const MI_BEATS = [
  {
    hotkeyKey: 'capture',
    hotkeyLabel: 'Send screen',
    via: 'screen capture',
    sendingText: 'Reading your shared screen…',
    line: "Let's start with a coding question — could you share your screen and pull up Two Sum for me?",
    screenshot: true,
    followup: "Great, thanks. Given an array of integers and a target, how would you find two numbers that add up to it?",
    popup: 'Press the hotkey to send your screen to the AI.',
    answer: "Use a hash map to track numbers you've seen:\n\n```python\ndef two_sum(nums, target):\n    seen = {}\n    for i, n in enumerate(nums):\n        if target - n in seen:\n            return [seen[target - n], i]\n        seen[n] = i\n```\n\n**O(n) time, O(n) space** — one pass.",
    answerVariants: {
      one_liner: "Hash map of seen numbers, checking `target - n` as you go — O(n) time, one pass.",
      bullets: "- Walk the array once, tracking seen numbers in a hash map\n- At each index, check if `target - n` is already in the map\n- If yes, return the two indices\n- Otherwise store `n` and keep going\n- **O(n) time, O(n) space**",
      summary: "A single-pass hash-map approach: track each number you've seen, and check whether its complement (target minus the current number) already exists. This avoids the O(n²) brute-force scan and finds the pair in O(n) time using O(n) extra space for the map.",
    },
    youReply: "I'd use a hash map to track numbers I've already seen — that gets it done in one pass, O(n) time.",
    recap: 'Send your shared screen to the AI',
  },
  {
    hotkeyKey: 'audio',
    hotkeyLabel: 'Hold to talk',
    via: 'voice',
    sendingPhases: [
      { text: 'Sending to AI…', wave: false, ms: 500 },
    ],
    line: "Now how would you solve it recursively instead?",
    popup: 'Hold the hotkey to talk, then release to send.',
    answerDwellMs: 6500,   // the comment stepper lands on this beat — see miScheduleContinueAfterAnswer
    transcription: 'Hmm, let me think, how would I do this recursively',
    answer: "Here's a recursive version:\n\n```python\ndef two_sum(nums, target, i=0, seen=None):\n    # Fresh dict per top-level call — a `{}` default would be shared between calls\n    seen = seen if seen is not None else {}\n\n    # Base case: walked the whole array without finding a pair\n    if i == len(nums):\n        return None\n\n    # An earlier call already stored the complement, so those two indices are the answer\n    if target - nums[i] in seen:\n        return [seen[target - nums[i]], i]\n\n    # Otherwise record where this value lives and let the next call handle the rest\n    seen[nums[i]] = i\n    return two_sum(nums, target, i + 1, seen)\n```\n\nSame **O(n) time**, but it trades the loop for call-stack depth — fine here, but I'd go back to the loop for very large inputs to avoid hitting the recursion limit.",
    // Comment-level variants — level 2 ("High") is `answer` above, so only 1 and 3 live here.
    // Same code either way: the stepper changes how much the AI explains, never the solution.
    answerCommentVariants: {
      1: "Here's a recursive version:\n\n```python\ndef two_sum(nums, target, i=0, seen=None):\n    seen = seen if seen is not None else {}   # avoids the mutable-default trap\n    if i == len(nums):\n        return None\n    if target - nums[i] in seen:\n        return [seen[target - nums[i]], i]\n    seen[nums[i]] = i\n    return two_sum(nums, target, i + 1, seen)\n```\n\nSame **O(n) time**, but it trades the loop for call-stack depth — fine here, but I'd go back to the loop for very large inputs to avoid hitting the recursion limit.",
      3: "Here's a recursive version:\n\n```python\ndef two_sum(nums, target, i=0, seen=None):     # i and seen carry state down the recursion\n    seen = seen if seen is not None else {}    # fresh dict per top-level call, never a shared default\n    if i == len(nums):                         # base case: ran off the end of the array\n        return None                            # nothing left to pair, so hand back nothing\n    if target - nums[i] in seen:               # has the complement been recorded already?\n        return [seen[target - nums[i]], i]     # yes — that earlier index plus this one is the pair\n    seen[nums[i]] = i                          # no — remember where this value lives\n    return two_sum(nums, target, i + 1, seen)  # recurse on the rest, threading seen along\n```\n\nSame **O(n) time**, but it trades the loop for call-stack depth — fine here, but I'd go back to the loop for very large inputs to avoid hitting the recursion limit.",
    },
    answerVariants: {
      one_liner: "Same hash-map check, just done recursively one element at a time — still O(n) time.",
      bullets: "- Recurse one element at a time instead of looping\n- Same hash map check at each call: is `target - n` already seen?\n- Base case: ran out of elements, return nothing\n- **O(n) time** — trades the loop for stack depth",
      summary: "It's the identical hash-map technique, just expressed recursively — each call handles one element, checks the map for its complement, then recurses on the rest. Time complexity stays O(n); the trade-off is call-stack depth instead of a loop, which matters for very large inputs.",
    },
    youReply: "I'd peel off one element at a time, checking the same hash map at each call until I hit a match or run out of numbers — same idea as the loop, just recursive.",
    recap: 'Speak the question out loud',
  },
  {
    hotkeyKey: 'replay',
    hotkeyLabel: 'Replay 30s',
    via: 'replay',
    sendingPhases: [
      { text: 'Grabbing the last 30 seconds…', wave: true, ms: 900 },
      { text: 'Sending to AI…', wave: false, ms: 500 },
    ],
    line: "One more — tell me about a time you demonstrated leadership.",
    popup: "Press the hotkey — it grabs the last 30 seconds of everyone's audio and sends it to the AI.",
    transcription: "(replayed) Tell me about a time you demonstrated leadership.",
    contextNote: '📎 Drawing from your uploaded information',
    answer: "**Situation:** Our release process was manual and slow, and nobody had really owned fixing it.\n\n**Task:** I wanted to cut deploy time without waiting for a formal mandate to do it.\n\n**Action:** I built a small CI pipeline on a side branch, demoed it to the team, then paired with two teammates to roll it into our actual workflow.\n\n**Result:** Deploys went from about 40 minutes to under 5, and the team adopted it as the standard within a month.",
    answerVariants: {
      one_liner: "Built a CI pipeline solo, demoed it, then paired it in — deploys went from 40 minutes to under 5.",
      bullets: "- **Situation:** manual, slow release process nobody owned\n- **Task:** cut deploy time without waiting for a mandate\n- **Action:** built a CI pipeline solo, demoed it, paired it into the real workflow\n- **Result:** 40 minutes → under 5, adopted team-wide within a month",
      summary: "A concise STAR answer: recognizing an unowned, slow release process, building and demoing a CI pipeline independently, then pairing with teammates to roll it into the real workflow — cutting deploy time from 40 minutes to under 5 and getting it adopted as the standard.",
    },
    youReply: "There was a stretch where our deploys were slow and manual, so I built a CI pipeline on my own time, demoed it, and paired with the team to roll it in — deploys went from 40 minutes to under 5.",
    recap: 'Replay the last 30 seconds of the call',
  },
  {
    hotkeyKey: 'typing',
    hotkeyLabel: 'Type privately',
    via: 'typing',
    sendingText: 'Thinking…',
    line: "Last one — how would you design a rate limiter for a public API?",
    popup: "Press the hotkey to type your question to the AI — it shows up here, and doesn't go to your interviewer.",
    autoType: "How do I design a rate limiter for a public API?",
    answer: "Key angles: token bucket vs. sliding window, per-user vs. global limits, and whether it needs to work across multiple servers (shared store like Redis) or just one.",
    answerVariants: {
      one_liner: "Token bucket vs sliding window, per-user vs global, and whether state needs to be shared (e.g. Redis) across servers.",
      bullets: "- Choose an algorithm: token bucket vs sliding window\n- Decide scope: per-user vs global limits\n- Decide storage: in-memory (one server) vs a shared store like Redis (many servers)",
      summary: "The core decisions are the limiting algorithm (token bucket vs sliding window), the scope of each limit (per-user vs global), and where state lives — in-memory if it's a single server, or a shared store like Redis if the API runs across many.",
    },
    youReply: "I'd weigh token bucket versus sliding window, decide on per-user versus global limits, and think about whether it needs a shared store like Redis across multiple servers.",
    recap: 'Type it privately — never seen',
  },
];

// Short teaching nudge shown the moment a beat becomes armed — points at the phone so a
// first-time viewer knows which hotkey to press and where the answer will land.
const MI_NUDGES = {
  capture: { eyebrow: 'Stuck?', body: 'Send your screen — the answer shows up here.' },
  audio:   { eyebrow: 'One linked conversation', body: "Want to tweak an answer? Just ask or type a clarifying question — unlike competitors, it remembers everything so far" },
  replay:  { eyebrow: 'Missed the question?', body: "Replay the last 30 seconds of audio. You can also upload context about yourself or the company ahead of time for the AI to draw from." },
  typing:  { eyebrow: 'Not sure where to start?', body: 'Type it, or paste it privately — the answer shows up here.' },
};

let _miIndex = -1;
let _miAwaitingBeat = null;
let _miAudioHeld = false;
let _miListening = false;      // audio beat: the waveform panel is up, working toward the 1.2s minimum
let _miListeningStartedAt = 0;
let _miCallEnded = false; // last question answered — waiting for the user to click Leave
let _miIsFirstRun = false;
let _miCallInterval = null;
let _miCallSecs = 0;

// Response-style switcher (mirrors the real ResponseStyle setting in Settings): the
// selection persists across beats, same as it would for a real account, and only resets
// when the whole call restarts — see miResetCallState.
const MI_DEFAULT_STYLE = 'conversational';
let _miSelectedStyle = MI_DEFAULT_STYLE;
let _miCurrentAnswerBeat = null; // the beat whose answer is currently on screen, if any
let _miContinueTimer = null;     // the pending "wrap up this answer and move on" timer
let _miStyleToastShown = false;  // only explain the switcher once per call
let _miDemoToastShown = false;   // only explain the laptop/phone split once per call

// Comment-level stepper (mirrors the real Comments setting — same 1..3 range, same names, same
// default as COMMENT_LEVEL_* in server.py and the extension popup). Only beats that answer with
// code carry answerCommentVariants, so the stepper appears exactly where moving it would change
// something; on the others it stays hidden rather than sitting there doing nothing.
const MI_COMMENT_LEVEL_NAMES = { 1: 'Low', 2: 'High', 3: 'Every line' };
const MI_COMMENT_LEVEL_MIN = 1;
const MI_COMMENT_LEVEL_MAX = 3;
const MI_DEFAULT_COMMENT_LEVEL = 2;
let _miCommentLevel = MI_DEFAULT_COMMENT_LEVEL;
let _miCommentToastShown = false;

function miAnswerTextFor(beat) {
  if (_miSelectedStyle !== MI_DEFAULT_STYLE) {
    return (beat.answerVariants && beat.answerVariants[_miSelectedStyle]) || beat.answer;
  }
  return (beat.answerCommentVariants && beat.answerCommentVariants[_miCommentLevel]) || beat.answer;
}

// The stepper only makes sense against the full conversational answer: the one-liner, bullet and
// summary variants carry no code block for comments to attach to, so picking one of those hides
// it rather than leaving a control that silently does nothing.
function miCommentSwitchApplies(beat) {
  return !!(beat && beat.answerCommentVariants && _miSelectedStyle === MI_DEFAULT_STYLE);
}

function miSyncCommentSwitch(beat) {
  document.getElementById('mi-comment-switch').style.display = miCommentSwitchApplies(beat) ? '' : 'none';
  document.getElementById('mi-comment-level').textContent = MI_COMMENT_LEVEL_NAMES[_miCommentLevel];
  document.getElementById('mi-comment-down').disabled = _miCommentLevel <= MI_COMMENT_LEVEL_MIN;
  document.getElementById('mi-comment-up').disabled   = _miCommentLevel >= MI_COMMENT_LEVEL_MAX;
}

function miChangeCommentLevel(delta) {
  if (!miCommentSwitchApplies(_miCurrentAnswerBeat)) return;
  const next = Math.min(MI_COMMENT_LEVEL_MAX, Math.max(MI_COMMENT_LEVEL_MIN, _miCommentLevel + delta));
  if (next === _miCommentLevel) return;
  _miCommentLevel = next;
  miSyncCommentSwitch(_miCurrentAnswerBeat);
  miDismissCommentToast();
  miRenderMarkdown(document.getElementById('mi-answer-body'), miAnswerTextFor(_miCurrentAnswerBeat));
  miScheduleContinueAfterAnswer(_miCurrentAnswerBeat);
}

function miShowCommentToast(beat) {
  if (_miCommentToastShown || !miCommentSwitchApplies(beat)) return;
  _miCommentToastShown = true;
  document.getElementById('mi-comment-toast').classList.add('active');
  miAfterFixed(6000, miDismissCommentToast);
}

function miDismissCommentToast() {
  document.getElementById('mi-comment-toast').classList.remove('active');
}

function miSyncStylePills() {
  document.querySelectorAll('.mi-style-pill').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.style === _miSelectedStyle);
  });
}

function miShowStyleToast() {
  if (_miStyleToastShown) return;
  _miStyleToastShown = true;
  document.getElementById('mi-style-toast').classList.add('active');
  miAfterFixed(6000, miDismissStyleToast);
}

function miDismissStyleToast() {
  document.getElementById('mi-style-toast').classList.remove('active');
}

// Mobile-only, once per call: the hotkey nudge that normally explains this is desktop-only
// (it points across a gap the stacked layout doesn't have), so on a phone nothing otherwise
// says that the real interaction is a keypress on your laptop and the phone is just where
// the answer lands. Fires with the first phone pop-up; CSS keeps it hidden above 900px. No
// timer and no dismiss on the phone dropping — it's the one explainer a phone visitor gets,
// so it rides with the rail for the rest of the call and only clears on a replay.
function miShowDemoToast() {
  if (_miDemoToastShown) return;
  _miDemoToastShown = true;
  document.getElementById('mi-demo-toast').classList.add('active');
}

function miDismissDemoToast() {
  document.getElementById('mi-demo-toast').classList.remove('active');
}

// Both answer controls (style pills, comment stepper) are only meaningful while this answer is
// still the thing on screen being read. Once miScheduleContinueAfterAnswer's countdown commits —
// the phone's about to drop and the reply's about to be spoken — a late click must not be able to
// re-fire that whole sequence on top of itself, so lock (and visually grey out) both right at that
// moment rather than waiting for the next beat's reset to get around to it.
function miAnswerControls() {
  return [document.getElementById('mi-style-switch'), document.getElementById('mi-comment-switch')];
}

function miLockAnswerControls() {
  _miCurrentAnswerBeat = null;
  miDismissStyleToast();
  miDismissCommentToast();
  miAnswerControls().forEach(el => el.classList.add('mi-answer-locked'));
}

function miUnlockAnswerControls(beat) {
  _miCurrentAnswerBeat = beat;
  miAnswerControls().forEach(el => el.classList.remove('mi-answer-locked'));
}

// Bound directly (not on DOMContentLoaded) — this script tag is placed after
// _mock_interview.html's markup in every host template, so these elements already exist.
document.querySelectorAll('.mi-style-pill').forEach((btn) => {
  btn.addEventListener('click', () => {
    if (!_miCurrentAnswerBeat || btn.dataset.style === _miSelectedStyle) return;
    _miSelectedStyle = btn.dataset.style;
    miSyncStylePills();
    miDismissStyleToast();
    // Style is chosen after the stepper may already be on screen, and it decides whether the
    // stepper applies at all — so re-sync it here, not just when the answer first lands.
    miSyncCommentSwitch(_miCurrentAnswerBeat);
    miRenderMarkdown(document.getElementById('mi-answer-body'), miAnswerTextFor(_miCurrentAnswerBeat));
    miScheduleContinueAfterAnswer(_miCurrentAnswerBeat);
  });
});

// Stays up until the user acts on it (hotkey/click) or the next beat replaces it — see
// miTrigger and miShowNeedHelp, the only two callers of miDismissHotkeyNudge/miShowHotkeyNudge.
function miShowHotkeyNudge(beat) {
  miDismissHotkeyNudge();
  const nudge = MI_NUDGES[beat.hotkeyKey];
  if (!nudge) return;
  document.getElementById('mi-hotkey-nudge-eyebrow-text').textContent = nudge.eyebrow;
  document.getElementById('mi-hotkey-nudge-body').textContent = nudge.body;
  document.getElementById('mi-hotkey-nudge-keys').innerHTML = miRenderHotkey(miHotkeys()[beat.hotkeyKey]);
  document.getElementById('mi-hotkey-nudge').classList.add('active');
}

function miDismissHotkeyNudge() {
  document.getElementById('mi-hotkey-nudge').classList.remove('active');
}

function openMockInterview(isFirstRun) {
  miClearTimers();
  miResetCallState();
  _miIsFirstRun = !!isFirstRun;
  const closeBtn = document.getElementById('mi-done-close-btn');
  if (closeBtn) closeBtn.textContent = _miIsFirstRun ? (window.MI_FIRST_RUN_CTA_LABEL || 'Continue →') : 'Close';
  miBuildRecap();
  miShowScreen('mi-greenroom');
  document.getElementById('mock-interview-overlay').classList.add('visible');
}

function miBuildRecap() {
  const el = document.getElementById('mi-recap');
  el.innerHTML = MI_BEATS.map(beat => `
    <div class="mi-recap-row">
      <div class="mi-recap-keys">${miRenderHotkey(miHotkeys()[beat.hotkeyKey])}</div>
      <span class="mi-recap-label">${beat.recap}</span>
    </div>
  `).join('');
}

function miShowScreen(id) {
  document.querySelectorAll('#mock-interview-overlay .mi-screen').forEach(el => el.classList.remove('active'));
  document.getElementById(id).classList.add('active');
}

function miShowScreenshot() {
  document.getElementById('mi-screenshot').classList.add('active');
  document.getElementById('mi-call-left').classList.add('sharing');
  document.getElementById('mi-share-btn').classList.add('sharing');
}

function miHideScreenshot() {
  document.getElementById('mi-screenshot').classList.remove('active');
  document.getElementById('mi-call-left').classList.remove('sharing');
  document.getElementById('mi-share-btn').classList.remove('sharing');
}

function miShowPhonePanel(id) {
  document.querySelectorAll('#mi-phone-body .mi-phone-panel').forEach(el => el.classList.remove('active'));
  if (id) document.getElementById(id).classList.add('active');
}

// Small screens: raise the phone to "take focus" (rises to cover) or drop it to a peek.
// No-op on desktop — the transform rules only exist under @media (max-width: 899px).
// Focus is driven explicitly (not from the panel id) so we can control exactly when the
// phone pops up (a beat after "Need help?" appears) and drops (after the user has had a
// moment to read the finished answer, and before the spoken reply fires).
function miPhoneFocus(on) {
  const right = document.querySelector('#mock-interview-overlay .mi-call-right');
  if (right) right.classList.toggle('mi-phone-focus', !!on);
}


function miStartCallTimer() {
  clearInterval(_miCallInterval);
  _miCallSecs = 0;
  miUpdateCallTimer();
  _miCallInterval = setInterval(() => { _miCallSecs++; miUpdateCallTimer(); }, 1000);
}

function miStopCallTimer() {
  clearInterval(_miCallInterval);
  _miCallInterval = null;
}

// Unlike miStopCallTimer, this doesn't reset _miCallSecs — resuming picks up where it froze.
function miPauseCallTimer() {
  clearInterval(_miCallInterval);
  _miCallInterval = null;
}

function miResumeCallTimer() {
  if (_miCallInterval) return;
  _miCallInterval = setInterval(() => { _miCallSecs++; miUpdateCallTimer(); }, 1000);
}

function miUpdateCallTimer() {
  const mm = String(Math.floor(_miCallSecs / 60)).padStart(2, '0');
  const ss = String(_miCallSecs % 60).padStart(2, '0');
  document.getElementById('mi-timer').textContent = `${mm}:${ss}`;
}

// Shared by miJoinCall and miRestart so re-entering the call (e.g. via the
// "How it works" button after a previous run) never leaves stale state —
// an old answer card, a "sent" typing field, etc. — visible behind the intro.
function miResetCallState() {
  _miAwaitingBeat = null;
  _miAudioHeld = false;
  _miListening = false;
  _miCallEnded = false;
  _miPaused = false;
  document.getElementById('mi-leave-btn').classList.remove('mi-leave-jump');
  document.getElementById('mi-leave-confirm').classList.remove('active');
  miDismissHotkeyNudge();
  miShowPhonePanel('mi-phone-idle');
  miPhoneFocus(false);
  document.getElementById('mi-interviewer-tile').classList.remove('speaking');
  document.getElementById('mi-you-tile').classList.remove('speaking');
  document.getElementById('mi-you-status').classList.remove('live');
  document.getElementById('mi-back-btn').disabled = true;
  const typingField = document.getElementById('mi-typing-field');
  typingField.classList.remove('sent');
  typingField.textContent = '';
  miHideScreenshot();
  miStopCallTimer();
  _miSelectedStyle = MI_DEFAULT_STYLE;
  _miCurrentAnswerBeat = null;
  _miStyleToastShown = false;
  miDismissStyleToast();
  _miCommentLevel = MI_DEFAULT_COMMENT_LEVEL;
  _miCommentToastShown = false;
  miDismissCommentToast();
  _miDemoToastShown = false;
  miDismissDemoToast();
  miSyncStylePills();
  miSyncCommentSwitch(null);
  miAnswerControls().forEach(el => el.classList.remove('mi-answer-locked'));
}

// A real InterviewAce extension installed in this browser listens for the same hotkeys the
// demo uses. Rather than force it disabled (which left no normal way to turn it back on
// mid-demo), the call blocks those specific keystrokes from ever reaching its content-script
// listener in the first place — see the window-capture keydown/keyup listeners below. The
// extension itself is left completely alone: still fully on/off-able, nothing about it changes.
let _miCallLive = false;

function miSpeakIntro() {
  miAfter(1500, () => {
    miSpeak(miIntroLine(), 'interviewer', () => miAfter(2200, miNextBeat));
  });
}

function miJoinCall() {
  miClearTimers();
  miResetCallState();
  miShowScreen('mi-call');
  miStartCallTimer();
  _miIndex = -1;
  _miCallLive = true;
  miSpeakIntro();
}

function miRestart() {
  miClearTimers();
  miResetCallState();
  miShowScreen('mi-call');
  miStartCallTimer();
  _miIndex = -1;
  _miCallLive = true;
  miSpeakIntro();
}

// Shared UI reset used before (re-)rendering any beat or the introduction — always drops the
// screenshot first, even for a beat that uses one, so re-entering that beat (going back) is a
// clean unshare-then-reshare rather than leaving a stale share visible underneath.
function miResetTileUI() {
  _miCallEnded = false;
  document.getElementById('mi-leave-btn').classList.remove('mi-leave-jump');
  miShowPhonePanel('mi-phone-idle');
  miPhoneFocus(false);
  document.getElementById('mi-interviewer-tile').classList.remove('speaking');
  document.getElementById('mi-you-tile').classList.remove('speaking');
  document.getElementById('mi-you-status').classList.remove('live');
  document.getElementById('mi-cursor').style.display = 'none';
  miHideScreenshot();
  _miCurrentAnswerBeat = null; // last beat's card is going away — its style pills go inert until the next reveal
}

// Renders beat `index` from the start (interviewer asks it again) — shared by miNextBeat
// (advancing forward) and miGoBack (rewinding to replay a question).
function miRenderBeat(index) {
  const beat = MI_BEATS[index];
  miResetTileUI();
  document.getElementById('mi-back-btn').disabled = false;

  miSpeak(beat.line, 'interviewer', () => {
    if (beat.screenshot) {
      miAfter(2000, () => {
        miShowScreenshot();
        miAfter(1000, () => {
          miSpeak(beat.followup, 'interviewer', () => miAfter(2300, () => miShowNeedHelp(beat)));
        });
      });
    } else {
      miAfter(2300, () => miShowNeedHelp(beat));
    }
  });
}

function miNextBeat() {
  _miIndex++;
  if (_miIndex >= MI_BEATS.length) { miFinish(); return; }
  miRenderBeat(_miIndex);
}

// Replays the introduction, then lets the normal flow carry on into Q1 — same path miJoinCall
// takes. Nothing precedes the introduction, so the back button is disabled again from here.
function miGoToIntro() {
  _miIndex = -1;
  miResetTileUI();
  document.getElementById('mi-back-btn').disabled = true;
  miSpeakIntro();
}

// Rewinds to the previous question (or the introduction, once Q1 is current) —
// clearing any in-flight speech/timers first.
function miGoBack() {
  if (_miIndex < 0) return; // already at the introduction — nothing earlier

  miClearTimers();
  _miAwaitingBeat = null;
  _miAudioHeld = false;
  _miListening = false;
  miDismissHotkeyNudge();

  if (_miIndex === 0) {
    miGoToIntro();
    return;
  }
  _miIndex--;
  miRenderBeat(_miIndex);
}

// Dev-build-only shortcut (button gated server-side on config.DEV_BUILD) — jumps straight to
// the next question from wherever the current one is, skipping its remaining wait/hotkey
// steps. miNextBeat already handles every starting point correctly: from the introduction
// (_miIndex -1) it lands on Q1, and from the last question it finishes the call.
function miDevSkipQuestion() {
  miClearTimers();
  _miAwaitingBeat = null;
  _miAudioHeld = false;
  _miListening = false;
  miDismissHotkeyNudge();
  miNextBeat();
}

function miShowNeedHelp(beat) {
  document.getElementById('mi-nh-text').textContent = beat.popup;
  const btnEl = document.getElementById('mi-nh-btn');
  const row = document.getElementById('mi-typing-row');
  const field = document.getElementById('mi-typing-field');

  btnEl.style.display = '';
  btnEl.textContent = 'Send to AI';
  btnEl.classList.remove('mi-nh-jump');
  row.classList.remove('active');
  field.textContent = '';
  field.classList.remove('sent');
  _miAwaitingBeat = beat;
  miShowPhonePanel('mi-need-help');
  miShowHotkeyNudge(beat);
  // Let the phone sit at a peek for a beat first, then pop up to take focus.
  miAfter(1000, () => {
    miPhoneFocus(true);
    miShowDemoToast();
  });
  // Shortly after that the button starts hopping — but only if this beat is still waiting
  // on it, so a press inside that window doesn't leave it twitching.
  miAfter(1500, () => { if (_miAwaitingBeat === beat) btnEl.classList.add('mi-nh-jump'); });
}

// Typing beat: pressing the hotkey (or the button) opens the typing box and autotypes the
// demo question, then sends it automatically once the text finishes appearing — no second
// press needed.
function miStartTyping(beat) {
  const btnEl = document.getElementById('mi-nh-btn');
  const row = document.getElementById('mi-typing-row');
  const field = document.getElementById('mi-typing-field');

  btnEl.style.display = 'none';
  row.classList.add('active');
  field.textContent = '';
  field.classList.remove('sent');

  miAfter(300, () => {
    miTypeIntoField(field, beat.autoType, () => {
      // Text stays full-color while it's still sitting there; only greys out right as it sends.
      miAfter(2000, () => {
        field.classList.add('sent');
        miAfter(350, () => miRevealAnswer(beat, beat.autoType));
      });
    });
  });
}

// Purely in-page — never arms the real extension or calls a capture endpoint on its own.
// The audio beat is hold-to-talk: keydown just arms "listening" (shows the waveform panel),
// the send only fires on keyup — mirroring how the real hotkey behaves.
//
// Registered on window with capture:true, rather than document uncaptured, so it runs before
// the real extension's content-script listener — which sits on document with capture:true —
// since the capture phase visits window before document. Content scripts share the page's DOM
// event dispatch despite running in an isolated JS world, so calling stopPropagation here for
// the extension's own action hotkeys (capture/audio/replay/typing) genuinely keeps its listener
// from ever seeing that keystroke, rather than just telling it to ignore one it already got.
// The toggle hotkey is deliberately left alone — the real extension stays fully on/off-able
// through the whole call, only its actions are kept from firing.
const MI_LISTEN_MIN_MS = 1200;

function miIsExtensionActionHotkey(e) {
  const hk = miHotkeys();
  return miMatchHotkey(e, hk.capture) || miMatchHotkey(e, hk.audio) || miMatchHotkey(e, hk.replay) || miMatchHotkey(e, hk.typing);
}

// Shows the waveform and starts timing it — shared by a real key hold (keydown, below) and a
// button tap (miTrigger, since a tap has no "hold" of its own to time against).
function miBeginListening() {
  _miListening = true;
  _miListeningStartedAt = Date.now();
  miDismissHotkeyNudge();
  miShowPhonePanel('mi-listening');
}

window.addEventListener('keydown', (e) => {
  if (_miCallLive && miIsExtensionActionHotkey(e)) e.stopPropagation();
  if (_miPaused) return; // leave-confirmation dialog is open
  if (!_miAwaitingBeat) return;
  if (!miMatchHotkey(e, miHotkeys()[_miAwaitingBeat.hotkeyKey])) return;
  e.preventDefault();
  if (_miAwaitingBeat.hotkeyKey === 'audio') {
    if (_miAudioHeld) return; // key-repeat while already held
    _miAudioHeld = true;
    miBeginListening();
  } else {
    miTrigger();
  }
}, { capture: true });

window.addEventListener('keyup', (e) => {
  if (_miCallLive && miIsExtensionActionHotkey(e)) e.stopPropagation();
  if (_miPaused) return; // leave-confirmation dialog is open
  if (!_miAudioHeld || !_miAwaitingBeat) return;
  if (!miMatchHotkey(e, miHotkeys()[_miAwaitingBeat.hotkeyKey])) return;
  e.preventDefault();
  _miAudioHeld = false;
  miTrigger();
}, { capture: true });

// Triggered by a real hotkey release, the "Send to AI" button, or (for audio) a real keyup.
// For the typing beat this opens the typing box (which sends itself once the autotype
// finishes); every other beat sends straight away. The audio beat always shows at least
// MI_LISTEN_MIN_MS of waveform before sending — a tap starts it fresh, a real hold that
// already ran that long sends immediately since the minimum's already been met.
function miTrigger(typedText) {
  if (!_miAwaitingBeat) return;
  const beat = _miAwaitingBeat;
  _miAwaitingBeat = null;
  miDismissHotkeyNudge();
  document.getElementById('mi-nh-btn').classList.remove('mi-nh-jump');

  if (beat.hotkeyKey === 'typing') {
    miStartTyping(beat);
    return;
  }

  if (beat.hotkeyKey === 'audio') {
    if (!_miListening) miBeginListening(); // tapped the button — no real hold happened
    const wait = Math.max(0, MI_LISTEN_MIN_MS - (Date.now() - _miListeningStartedAt));
    miAfter(wait, () => {
      _miListening = false;
      miRevealAnswer(beat, typedText);
    });
    return;
  }

  miRevealAnswer(beat, typedText);
}

// Steps through a beat's "sending" phases (e.g. "Listening to your voice…" then "Sending to
// AI…") before handing off to `done`. Beats without `sendingPhases` fall back to a single
// `sendingText` phase, so capture/typing beats don't need to define one.
function miRenderSendingPhases(beat, done) {
  const body = document.getElementById('mi-answer-body');
  const phases = beat.sendingPhases || [{ text: beat.sendingText, ms: 1200 }];
  let i = 0;
  function step() {
    if (i >= phases.length) { done(); return; }
    const phase = phases[i++];
    const wave = phase.wave ? '<span class="mi-sending-wave" aria-hidden="true"><i></i><i></i><i></i><i></i></span>' : '';
    body.innerHTML = `<div class="mi-sending"><span class="mi-sending-dot"></span><span class="mi-sending-text">${phase.text}</span>${wave}</div>`;
    miAfterFixed(phase.ms, step);
  }
  step();
}

function miRevealAnswer(beat, typedText) {
  miShowPhonePanel('mi-answer-card');

  const body = document.getElementById('mi-answer-body');
  const transcription = document.getElementById('mi-answer-transcription');
  const transcriptionLabel = document.getElementById('mi-answer-transcription-label');
  const transcriptionText = document.getElementById('mi-answer-transcription-text');

  document.getElementById('mi-answer-via').textContent = beat.via;

  const spokenText = typedText || beat.transcription;
  if (spokenText) {
    transcription.style.display = '';
    transcriptionLabel.textContent = typedText ? 'You typed' : 'You said';
    transcriptionText.textContent = spokenText;
  } else {
    transcription.style.display = 'none';
  }

  const contextNote = document.getElementById('mi-answer-context-note');
  miRenderSendingPhases(beat, () => {
    body.innerHTML = '';
    if (beat.contextNote) {
      contextNote.textContent = beat.contextNote;
      contextNote.style.display = '';
    } else {
      contextNote.style.display = 'none';
    }
    miUnlockAnswerControls(beat);
    miSyncStylePills();
    miSyncCommentSwitch(beat);
    miStreamMarkdown(body, miAnswerTextFor(beat), () => {
      // At most one explainer per answer: the style toast fires on the first beat, so by the time
      // a code beat with a stepper comes round it's spent and the comment toast gets the slot.
      miShowStyleToast();
      miShowCommentToast(beat);
      miScheduleContinueAfterAnswer(beat);
    });
  });
}

// Give the visitor a moment to read the finished answer (or to try a different response
// style — see the .mi-style-pill click handler above), then drop the phone out of focus.
// Only once it's dropped do you relay the answer back to the interviewer, so attention has
// clearly left the phone before the spoken reply fires. Re-callable: switching style mid-read
// cancels and restarts this countdown instead of stacking a second one on top.
function miScheduleContinueAfterAnswer(beat) {
  miCancelTimer(_miContinueTimer);
  // 2.5s is enough to read an answer you weren't invited to touch, but not to notice a control,
  // read the toast explaining it, and press it. Beats that put a knob in front of the viewer set
  // answerDwellMs to buy that time — and every press restarts this countdown, so trying it twice
  // doesn't get cut off either.
  _miContinueTimer = miAfter(beat.answerDwellMs || 2500, () => {
    _miContinueTimer = null;
    miLockAnswerControls();
    miPhoneFocus(false);
    miAfter(600, () => {                 // let the drop animation settle first
      miSpeak(beat.youReply, 'you', () => {
        // 900ms of natural gap once the candidate's relay finishes streaming, plus a 750ms
        // beat on top so the interviewer doesn't come in on the tail of their answer.
        miAfter(1650, () => {
          const hasNext = _miIndex + 1 < MI_BEATS.length;
          if (hasNext) {
            miSpeak('Great — next question…', 'interviewer', () => miAfter(2100, miNextBeat));
          } else {
            miSpeak("That's everything — nice work.", 'interviewer', miEnterCallEnd);
          }
        });
      });
    });
  });
}

// Last question's answered — rather than auto-advancing to the Done/recap screen, wait for
// the user to click Leave themselves (it jumps to draw the eye). A couple of nudges keep it
// from feeling stuck: a plain reminder, then — if they still haven't — a little easter egg.
function miEnterCallEnd() {
  _miCallEnded = true;
  document.getElementById('mi-leave-btn').classList.add('mi-leave-jump');
  miAfter(3000, () => {
    miSpeak("That wraps up the interview — go ahead and click Leave whenever you're ready.", 'interviewer', () => {
      miAfter(3000, () => {
        const name = miFirstName();
        miSpeak(name
          ? `Wow, ${name} — I can see you're a keen bean! Honestly, that went so well I want to make you an offer on the spot.`
          : "Wow — I can see you're a keen bean! Honestly, that went so well I want to make you an offer on the spot.", 'interviewer', () => {
          miAfter(600, () => {
            miSpeak("Fully remote, £1,000,000 a year, full benefits, subsidised lunch, free parking — and a company dog called Steve. Just click Leave and it's yours.", 'interviewer', () => {});
          });
        });
      });
    });
  });
}

// Leave button: mid-call this confirms first (pausing everything while it's open) since
// leaving loses the rest of the walkthrough. Once the call has actually ended, the warning
// is unnecessary — it just goes straight to the Done/recap screen.
function miRequestLeave() {
  if (_miCallEnded) {
    miFinish();
    return;
  }
  miPauseTimers();
  miPauseCallTimer();
  document.getElementById('mi-leave-confirm').classList.add('active');
}

function miCancelLeave() {
  document.getElementById('mi-leave-confirm').classList.remove('active');
  miResumeCallTimer();
  miResumeTimers();
}

function miConfirmLeave() {
  document.getElementById('mi-leave-confirm').classList.remove('active');
  miClose();
}

function miFinish() {
  miClearTimers();
  miStopCallTimer();
  _miCallLive = false;
  if (_miIsFirstRun && window.MI_SKIP_DONE_SCREEN) {
    // /welcome's first run skips the recap card and hands off straight to
    // MI_ON_FIRST_RUN_FINISH — see welcome.html. Deliberately does NOT go through
    // miClose(): the callback navigates to /welcome/next, and leaving the demo
    // overlay up keeps it covering the bare /welcome intro until the new page
    // paints, otherwise that intro flashes up during navigation. The /app fallback
    // replay (first visit without having gone through /welcome) doesn't set this
    // flag, so it still gets the recap card as before.
    _miIsFirstRun = false;
    if (window.MI_ON_FIRST_RUN_FINISH) window.MI_ON_FIRST_RUN_FINISH();
    return;
  }
  miShowScreen('mi-done');
}

function miClose() {
  miClearTimers();
  miStopCallTimer();
  _miCallLive = false;
  _miAwaitingBeat = null;
  _miAudioHeld = false;
  _miListening = false;
  document.getElementById('mock-interview-overlay').classList.remove('visible');
  if (_miIsFirstRun) {
    _miIsFirstRun = false;
    if (window.MI_ON_FIRST_RUN_FINISH) window.MI_ON_FIRST_RUN_FINISH();
  }
}
