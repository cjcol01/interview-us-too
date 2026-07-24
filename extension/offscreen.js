// ── Mic state (hold-to-record) ───────────────────────────────────────────────
const _mic = { stream: null, recorder: null, chunks: [] };

// ── Replay state (rolling tab-audio buffer) ───────────────────────────────────
let _keepAlivePort = null;

const _replay = {
  stream:      null,
  recorder:    null,
  // Ring of last 2 epochs: { initBlob, chunks:[{blob,t}], startedAt }
  epochs:      [],
  windowSec:   10,
  epochMs:     60_000,
  ctx:         null,   // AudioContext — held to keep track alive
  src:         null,   // MediaStreamAudioSourceNode (intentionally unconnected)
  rotateTimer: null,
  disarming:   false,
};

// ── Message router ────────────────────────────────────────────────────────────
chrome.runtime.onMessage.addListener((msg) => {
  if      (msg.type === 'start-recording')      startMicRecording(msg.deviceId);
  else if (msg.type === 'stop-recording')       stopMicRecording();
  else if (msg.type === 'replay-stream-id')     startReplay(msg.streamId, msg.windowSec, msg.epochMs);
  else if (msg.type === 'replay-slice')         handleReplaySlice(msg.requestId, msg.windowSec);
  else if (msg.type === 'replay-disarm')        disarmReplay();
  else if (msg.type === 'query-mic-permission') queryMicPermission();
});

// ── Mic permission check (passive — never prompts) ────────────────────────────
async function queryMicPermission() {
  let state = 'prompt';
  try {
    const status = await navigator.permissions.query({ name: 'microphone' });
    state = status.state;
  } catch {}
  chrome.runtime.sendMessage({ type: 'mic-permission-result', state });
}

// ── Mic recording ─────────────────────────────────────────────────────────────
async function startMicRecording(deviceId) {
  try {
    const audio = deviceId ? { deviceId: { ideal: deviceId } } : true;
    _mic.stream = await navigator.mediaDevices.getUserMedia({ audio, video: false });
  } catch (e) {
    // e.name is 'NotAllowedError' when mic permission was never granted — offscreen documents
    // are headless and can't show the native permission prompt themselves (background.js opens
    // grant-mic.html, a real tab, to get one), so this always fails silently on a first-ever
    // hotkey press rather than prompting.
    chrome.runtime.sendMessage({ type: 'audio-error', error: e.message, errorName: e.name });
    return;
  }

  _mic.chunks = [];
  _mic.recorder = new MediaRecorder(_mic.stream, { mimeType: 'audio/webm;codecs=opus' });

  _mic.recorder.ondataavailable = (e) => {
    if (e.data.size > 0) _mic.chunks.push(e.data);
  };

  _mic.recorder.onstop = () => {
    const blob = new Blob(_mic.chunks, { type: 'audio/webm' });
    const reader = new FileReader();
    reader.onloadend = () => {
      const base64 = reader.result.split(',')[1];
      chrome.runtime.sendMessage({ type: 'audio-data', base64, mimeType: 'audio/webm' });
    };
    reader.readAsDataURL(blob);
    _mic.stream.getTracks().forEach(t => t.stop());
    _mic.stream   = null;
    _mic.recorder = null;
    _mic.chunks   = [];
  };

  _mic.recorder.start();
}

function stopMicRecording() {
  if (_mic.recorder && _mic.recorder.state !== 'inactive') {
    _mic.recorder.stop();
  }
}

// ── Replay tab-audio capture ──────────────────────────────────────────────────
async function startReplay(streamId, windowSec, epochMs) {
  _replay.windowSec = windowSec;
  _replay.epochMs   = epochMs;
  _replay.disarming = false;
  _replay.epochs    = [];

  try {
    _replay.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        mandatory: {
          chromeMediaSource:   'tab',
          chromeMediaSourceId: streamId,
        },
      },
      video: false,
    });
  } catch (e) {
    chrome.runtime.sendMessage({ type: 'replay-stream-error', error: e.message });
    return;
  }

  // Route captured audio back to speakers — Chrome mutes the source tab when
  // captured via an offscreen doc, so we must explicitly pass it through.
  _replay.ctx = new AudioContext();
  _replay.src = _replay.ctx.createMediaStreamSource(_replay.stream);
  _replay.src.connect(_replay.ctx.destination);

  // Detect stream death (tab refresh, close, or navigation)
  const track = _replay.stream.getAudioTracks()[0];
  if (track) {
    track.addEventListener('ended', () => {
      chrome.runtime.sendMessage({ type: 'replay-stream-ended' }).catch(() => {});
    });
  }

  // Keep the service worker alive while replay is armed
  _keepAlivePort = chrome.runtime.connect({ name: 'replay-keepalive' });
  _keepAlivePort.onDisconnect.addListener(() => { _keepAlivePort = null; });

  _startReplayEpoch();
  chrome.runtime.sendMessage({ type: 'replay-armed' });
}

function _startReplayEpoch() {
  const epoch = { initBlob: null, chunks: [], startedAt: performance.now() };
  _replay.epochs.push(epoch);
  if (_replay.epochs.length > 2) _replay.epochs.shift();

  _replay.recorder = new MediaRecorder(_replay.stream, { mimeType: 'audio/webm;codecs=opus' });
  let isFirst = true;

  _replay.recorder.ondataavailable = (e) => {
    if (e.data.size === 0) return;
    if (isFirst) {
      // First chunk = WebM init segment + first timeslice — store as epoch header
      epoch.initBlob = e.data;
      isFirst = false;
    } else {
      epoch.chunks.push({ blob: e.data, t: performance.now() });
    }
  };

  _replay.recorder.onstop = () => {
    clearTimeout(_replay.rotateTimer);
    _replay.rotateTimer = null;
    if (_replay.disarming) {
      _replayCleanup();
    } else {
      _startReplayEpoch();
    }
  };

  _replay.recorder.start(250);

  // Rotate epoch every epochMs to keep epochs self-contained
  _replay.rotateTimer = setTimeout(() => {
    if (_replay.recorder && _replay.recorder.state !== 'inactive') {
      _replay.recorder.stop();
    }
  }, _replay.epochMs);
}

function handleReplaySlice(requestId, windowSec) {
  if (!_replay.recorder || _replay.epochs.length === 0) {
    chrome.runtime.sendMessage({ type: 'replay-slice-result', requestId, base64: null });
    return;
  }

  const now    = performance.now();
  const cutoff = now - windowSec * 1000;
  const cur    = _replay.epochs.at(-1);

  let blobs;
  const curAge = now - cur.startedAt;

  if (curAge >= windowSec * 1000 || _replay.epochs.length === 1) {
    // Current epoch is old enough — slice from it alone
    const relevant = cur.chunks.filter(c => c.t >= cutoff);
    blobs = cur.initBlob
      ? [cur.initBlob, ...relevant.map(c => c.blob)]
      : relevant.map(c => c.blob);
  } else {
    // Current epoch younger than window — reach into the previous epoch
    const prev = _replay.epochs.at(-2);
    const prevRelevant = prev ? prev.chunks.filter(c => c.t >= cutoff) : [];
    blobs = [
      ...(prev?.initBlob ? [prev.initBlob] : []),
      ...prevRelevant.map(c => c.blob),
      ...(cur.initBlob  ? [cur.initBlob]  : []),
      ...cur.chunks.map(c => c.blob),
    ];
  }

  const blob = new Blob(blobs, { type: 'audio/webm' });
  const reader = new FileReader();
  reader.onloadend = () => {
    const base64 = reader.result.split(',')[1];
    chrome.runtime.sendMessage({ type: 'replay-slice-result', requestId, base64, mimeType: 'audio/webm' });
  };
  reader.readAsDataURL(blob);
}

function disarmReplay() {
  if (!_replay.recorder) return;
  clearTimeout(_replay.rotateTimer);
  _replay.disarming = true;
  if (_replay.recorder.state !== 'inactive') {
    _replay.recorder.stop(); // _replayCleanup called in onstop
  } else {
    _replayCleanup();
  }
}

function _replayCleanup() {
  _keepAlivePort?.disconnect();
  _keepAlivePort      = null;
  _replay.recorder    = null;
  _replay.epochs      = [];
  _replay.rotateTimer = null;
  _replay.disarming   = false;
  if (_replay.src)    { _replay.src.disconnect(); _replay.src = null; }
  if (_replay.ctx)    { _replay.ctx.close().catch(() => {}); _replay.ctx = null; }
  if (_replay.stream) { _replay.stream.getTracks().forEach(t => t.stop()); _replay.stream = null; }
}

// Signal to background that this document is loaded and ready to receive messages
chrome.runtime.sendMessage({ type: 'offscreen-ready' });
