// Mock interview: full-screen "Split cockpit" practice call. Shared by /welcome (first-run) and
// /app ("How it works" replay). Host pages must set `window.MI_HOTKEYS` ({capture, audio, toggle,
// replay, typing}) and may set `window.MI_ON_FIRST_RUN_FINISH` (called from miClose() after a
// first-run demo closes) and `window.MI_FIRST_RUN_CTA_LABEL` (button text shown on the "Done"
// screen during a first run) before this script runs.

let _miTimers = [];
function miAfter(ms, fn) { _miTimers.push(setTimeout(fn, ms)); }
function miClearTimers() { _miTimers.forEach(clearTimeout); _miTimers = []; }
const MI_PREFERS_REDUCED_MOTION = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function miStreamText(el, text, done) {
  if (MI_PREFERS_REDUCED_MOTION) { el.textContent = text; if (done) miAfter(150, done); return; }
  let i = 0;
  function tick() {
    if (i >= text.length) { if (done) done(); return; }
    el.textContent = text.slice(0, i + 1);
    const ch = text[i];
    const delay = ch === '\n' ? 70 + Math.random() * 50 : ch === ' ' ? 9 : 20 + Math.random() * 18;
    i++;
    _miTimers.push(setTimeout(tick, delay));
  }
  tick();
}

function miStreamMarkdown(el, text, done) {
  if (MI_PREFERS_REDUCED_MOTION) { el.innerHTML = marked.parse(text); if (done) miAfter(150, done); return; }
  let i = 0;
  function tick() {
    if (i >= text.length) { el.innerHTML = marked.parse(text); if (done) done(); return; }
    i = Math.min(i + 3, text.length);
    el.innerHTML = marked.parse(text.slice(0, i));
    _miTimers.push(setTimeout(tick, 26 + Math.random() * 26));
  }
  tick();
}

// Animates typing into a (read-only, demo-only) text display — never sends real keystrokes.
// The field is a plain div (not an <input>) so long questions wrap onto multiple lines
// instead of scrolling off the edge of a single-line box.
function miTypeIntoField(field, text, done) {
  if (MI_PREFERS_REDUCED_MOTION) { field.textContent = text; if (done) miAfter(150, done); return; }
  let i = 0;
  function tick() {
    if (i >= text.length) { if (done) done(); return; }
    field.textContent = text.slice(0, i + 1);
    const ch = text[i];
    const delay = ch === ' ' ? 9 : 20 + Math.random() * 18;
    i++;
    _miTimers.push(setTimeout(tick, delay));
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

const MI_INTRO_LINE = "Hi, I'm Alex — nice to meet you! Let's get straight into it.";

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
    youReply: "I'd use a hash map to track numbers I've already seen — that gets it done in one pass, O(n) time.",
    recap: 'Send your shared screen to the AI',
  },
  {
    hotkeyKey: 'audio',
    hotkeyLabel: 'Hold to talk',
    via: 'voice',
    sendingPhases: [
      { text: 'Listening to your voice…', wave: true, ms: 700 },
      { text: 'Sending to AI…', wave: false, ms: 500 },
    ],
    line: "Now how would you solve it recursively instead?",
    popup: 'Hold the hotkey to talk, then release to send.',
    transcription: 'uh, how would I do this one recursively?',
    answer: "Here's a recursive version:\n\n```python\ndef two_sum(nums, target, i=0, seen=None):\n    seen = seen if seen is not None else {}\n    if i == len(nums):\n        return None\n    if target - nums[i] in seen:\n        return [seen[target - nums[i]], i]\n    seen[nums[i]] = i\n    return two_sum(nums, target, i + 1, seen)\n```\n\nSame **O(n) time**, but it trades the loop for call-stack depth — fine here, but I'd go back to the loop for very large inputs to avoid hitting the recursion limit.",
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
    answer: "**Situation:** Our release process was manual and slow, and nobody had really owned fixing it.\n\n**Task:** I wanted to cut deploy time without waiting for a formal mandate to do it.\n\n**Action:** I built a small CI pipeline on a side branch, demoed it to the team, then paired with two teammates to roll it into our actual workflow.\n\n**Result:** Deploys went from about 40 minutes to under 5, and the team adopted it as the standard within a month.",
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
    youReply: "I'd weigh token bucket versus sliding window, decide on per-user versus global limits, and think about whether it needs a shared store like Redis across multiple servers.",
    recap: 'Type it privately — never seen',
  },
];

// Short teaching nudge shown the moment a beat becomes armed — points at the phone so a
// first-time viewer knows which hotkey to press and where the answer will land.
const MI_NUDGES = {
  capture: { eyebrow: 'Stuck?', body: 'Send your screen — the answer shows up here.' },
  audio:   { eyebrow: 'One linked conversation', body: "Want to tweak an answer? Just ask a clarifying question — it remembers everything so far, not four separate chats." },
  replay:  { eyebrow: 'Missed the question?', body: "Replay the last 30 seconds — it also folds in whatever context you've saved (company, role, style) automatically." },
  typing:  { eyebrow: 'Not sure where to start?', body: 'Type it privately — the answer shows up here.' },
};

let _miIndex = -1;
let _miAwaitingBeat = null;
let _miIsFirstRun = false;
let _miCallInterval = null;
let _miCallSecs = 0;

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
  miDismissHotkeyNudge();
  miShowPhonePanel('mi-phone-idle');
  document.getElementById('mi-interviewer-tile').classList.remove('speaking');
  document.getElementById('mi-you-tile').classList.remove('speaking');
  document.getElementById('mi-you-status').classList.remove('live');
  document.getElementById('mi-phone-progress').textContent = 'Private · Question 1 of 4';
  const typingField = document.getElementById('mi-typing-field');
  typingField.classList.remove('sent');
  typingField.textContent = '';
  miHideScreenshot();
  miStopCallTimer();
}

function miJoinCall() {
  miClearTimers();
  miResetCallState();
  miShowScreen('mi-call');
  miStartCallTimer();
  _miIndex = -1;
  miSpeak(MI_INTRO_LINE, 'interviewer', () => miAfter(1000, miNextBeat));
}

function miRestart() {
  miClearTimers();
  miResetCallState();
  miShowScreen('mi-call');
  miStartCallTimer();
  _miIndex = -1;
  miSpeak(MI_INTRO_LINE, 'interviewer', () => miAfter(1000, miNextBeat));
}

function miNextBeat() {
  _miIndex++;
  if (_miIndex >= MI_BEATS.length) { miFinish(); return; }
  const beat = MI_BEATS[_miIndex];

  document.getElementById('mi-phone-progress').textContent = `Private · Question ${_miIndex + 1} of ${MI_BEATS.length}`;
  miShowPhonePanel('mi-phone-idle');
  document.getElementById('mi-you-status').classList.remove('live');
  if (!beat.screenshot) miHideScreenshot();

  miSpeak(beat.line, 'interviewer', () => {
    if (beat.screenshot) {
      miAfter(500, () => {
        miShowScreenshot();
        miAfter(1000, () => {
          miSpeak(beat.followup, 'interviewer', () => miAfter(1100, () => miShowNeedHelp(beat)));
        });
      });
    } else {
      miAfter(1100, () => miShowNeedHelp(beat));
    }
  });
}

function miShowNeedHelp(beat) {
  document.getElementById('mi-nh-text').textContent = beat.popup;
  document.getElementById('mi-nh-hotkey-label').textContent = beat.hotkeyLabel;
  const keyEl = document.getElementById('mi-nh-key');
  const btnEl = document.getElementById('mi-nh-btn');
  const hotkeyRow = document.getElementById('mi-nh-hotkey-row');
  const row = document.getElementById('mi-typing-row');
  const field = document.getElementById('mi-typing-field');

  hotkeyRow.style.display = '';
  btnEl.style.display = '';
  btnEl.textContent = 'Send to AI';
  keyEl.innerHTML = miRenderHotkey(miHotkeys()[beat.hotkeyKey]);
  row.classList.remove('active');
  field.textContent = '';
  field.classList.remove('sent');
  _miAwaitingBeat = beat;
  miShowPhonePanel('mi-need-help');
  miShowHotkeyNudge(beat);
}

// Typing beat: pressing the hotkey (or the button) opens the typing box and autotypes the
// demo question, then sends it automatically once the text finishes appearing — no second
// press needed.
function miStartTyping(beat) {
  const hotkeyRow = document.getElementById('mi-nh-hotkey-row');
  const btnEl = document.getElementById('mi-nh-btn');
  const row = document.getElementById('mi-typing-row');
  const field = document.getElementById('mi-typing-field');

  hotkeyRow.style.display = 'none';
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

// Purely in-page: never arms the real extension or calls a capture endpoint.
// Real hotkeys are intercepted by the extension at the OS/browser level, separate from this listener.
document.addEventListener('keydown', (e) => {
  if (!_miAwaitingBeat) return;
  if (miMatchHotkey(e, miHotkeys()[_miAwaitingBeat.hotkeyKey])) {
    e.preventDefault();
    miTrigger();
  }
});

// Triggered by a real hotkey press or the "Send to AI" button. For the typing beat this
// opens the typing box (which sends itself once the autotype finishes); every other beat
// sends straight away.
function miTrigger(typedText) {
  if (!_miAwaitingBeat) return;
  const beat = _miAwaitingBeat;
  _miAwaitingBeat = null;
  miDismissHotkeyNudge();

  if (beat.hotkeyKey === 'typing') {
    miStartTyping(beat);
    return;
  }

  if (beat.hotkeyKey === 'audio') {
    // A beat of "still talking" before the question actually goes out, rather than sending
    // the instant the hotkey is pressed.
    miAfter(1000, () => miRevealAnswer(beat, typedText));
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
    miAfter(phase.ms, step);
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

  miRenderSendingPhases(beat, () => {
    body.innerHTML = '';
    miStreamMarkdown(body, beat.answer, () => {
      // The AI's answer is private — now you relay it back to the interviewer out loud.
      miAfter(1400, () => {
        miSpeak(beat.youReply, 'you', () => {
          miAfter(900, () => {
            const hasNext = _miIndex + 1 < MI_BEATS.length;
            const line = hasNext ? 'Great — next question…' : "That's everything — nice work.";
            miSpeak(line, 'interviewer', () => miAfter(hasNext ? 900 : 2400, miNextBeat));
          });
        });
      });
    });
  });
}

function miFinish() {
  miStopCallTimer();
  miShowScreen('mi-done');
}

function miClose() {
  miClearTimers();
  miStopCallTimer();
  _miAwaitingBeat = null;
  document.getElementById('mock-interview-overlay').classList.remove('visible');
  if (_miIsFirstRun) {
    _miIsFirstRun = false;
    if (window.MI_ON_FIRST_RUN_FINISH) window.MI_ON_FIRST_RUN_FINISH();
  }
}
