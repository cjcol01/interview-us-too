// Map server wire codes / details to human-readable messages. Never surface raw enums.
const ERROR_MESSAGES = {
  sessions_exhausted:       'No sessions remaining — visit InterviewWise to top up.',
  trial_expired:            'Trial expired — visit InterviewWise to continue.',
  'Subscription required':  'Your plan has ended — visit InterviewWise to upgrade.',
};

function friendlyError(status, detail) {
  if (detail && ERROR_MESSAGES[detail]) return ERROR_MESSAGES[detail];
  if (detail) return detail;  // server already sends human-friendly text (e.g. rate-limit messages)
  return `Something went wrong (error ${status}). Please try again.`;
}


async function fetchAccountLevel() {
  const { server_url, api_token } = await chrome.storage.local.get(['server_url', 'api_token']);
  if (!server_url || !api_token) return;
  try {
    const resp = await fetch(`${server_url}/api/me`, {
      headers: { 'Authorization': `Bearer ${api_token}` },
    });
    if (resp.ok) {
      const data = await resp.json();
      await chrome.storage.local.set({ is_unlimited: data.account_level === 'unlimited' });
      // Hotkeys are now managed via chrome://extensions/shortcuts (manifest commands).
      // We no longer sync them from the server.
      if (data.typing_passthrough != null) await chrome.storage.local.set({ typing_passthrough: data.typing_passthrough });
      if (data.typing_preview != null) await chrome.storage.local.set({ typing_preview: data.typing_preview });
      if (data.replay) {
        await chrome.storage.local.set({
          replay_enabled: data.replay.enabled,
          replay_seconds: data.replay.seconds,
        });
      }
      if (data.complexity != null)    await chrome.storage.local.set({ complexity: data.complexity });
      if (data.comment_level != null) await chrome.storage.local.set({ comment_level: data.comment_level });
      if (data.response_style != null) await chrome.storage.local.set({ response_style: data.response_style });
    }
  } catch {}
}


async function doCapture() {
  const { server_url, api_token, complexity } = await chrome.storage.local.get([
    'server_url', 'api_token', 'complexity',
  ]);

  if (!api_token || !server_url) {
    chrome.action.openPopup().catch(() => {});
    return;
  }

  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!tab) return;

  let dataUrl;
  try {
    dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' });
  } catch (e) {
    console.error('[capture] screenshot failed:', e.message);
    return;
  }

  try {
    const resp = await fetch(`${server_url}/api/capture`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${api_token}`,
      },
      body: JSON.stringify({
        image: dataUrl,
        monitor: 'browser',
      }),
    });

    if (resp.ok) {
      await chrome.storage.local.set({ last_capture: new Date().toLocaleTimeString(), last_error: '' });
    } else {
      const body = await resp.text();
      let detail = body;
      try { detail = JSON.parse(body).detail ?? body; } catch {}
      await chrome.storage.local.set({ last_error: friendlyError(resp.status, detail) });
    }
  } catch (e) {
    await chrome.storage.local.set({ last_error: `Network error: ${e.message}` });
  }
}

async function flashDisabled() {
  const { server_url, api_token } = await chrome.storage.local.get(['server_url', 'api_token']);
  if (!server_url || !api_token) return;
  await fetch(`${server_url}/api/notify/disabled`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${api_token}` },
  }).catch(() => {});
}

async function notifyEnabled() {
  const { server_url, api_token } = await chrome.storage.local.get(['server_url', 'api_token']);
  if (!server_url || !api_token) return;
  await fetch(`${server_url}/api/notify/enabled`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${api_token}` },
  }).catch(() => {});
}

async function forceEnable() {
  const { enabled } = await chrome.storage.local.get(['enabled']);
  if (enabled) return;
  await chrome.storage.local.set({ enabled: true });
  await notifyEnabled();
}

// Opens (or refocuses) grant-mic.html — a real tab, unlike the offscreen document, so it can
// actually show the native mic-permission prompt. Reuses an existing tab instead of stacking
// up duplicates if the hotkey gets pressed more than once while still unresolved.
async function openGrantMicTab() {
  const url = chrome.runtime.getURL('grant-mic.html');
  let existing = [];
  try {
    existing = await chrome.tabs.query({ url });
  } catch {}
  if (existing.length) {
    const tab = existing[0];
    chrome.tabs.update(tab.id, { active: true }).catch(function fallbackCreateGrantTab() {
      chrome.tabs.create({ url }).catch(() => {});
    });
    if (tab.windowId) chrome.windows.update(tab.windowId, { focused: true }).catch(() => {});
  } else {
    chrome.tabs.create({ url }).catch(function logGrantTabCreateError(e) {
      console.error('[scap] openGrantMicTab: tabs.create failed', e);
    });
  }
}

async function handleCapture() {
  const { enabled } = await chrome.storage.local.get(['enabled']);
  if (!enabled) {
    await chrome.storage.local.set({ last_disabled_press: Date.now() });
    await flashDisabled();
    return;
  }
  doCapture();
}

async function handleToggle(senderTabId) {
  const { enabled } = await chrome.storage.local.get(['enabled']);
  const next = !enabled;
  _extEnabled = next;
  await chrome.storage.local.set({ enabled: next });
  // Push immediately. Same-browser pages hear this via storage.onChanged, but the phone
  // dashboard only knows what the server knows — without this it shows the old state until
  // the next 30s heartbeat tick.
  sendExtStatus();
  // Re-probe the mic too. Reading mic_status from storage only helps if something ever
  // wrote it — a device that has never run a check reports 'unknown' forever, and the
  // phone has no extension of its own to ask. This is the passive permissions query, so
  // it never prompts; its result writes storage and sends a fresh status by itself.
  checkMicPermission();
  if (next) await notifyEnabled();
  if (senderTabId) {
    chrome.tabs.sendMessage(senderTabId, { type: 'toggled', enabled: next }).catch(() => {});
  }
}

function updateIcon(enabled) {
  const s = enabled ? 'on' : 'off';
  chrome.action.setIcon({
    path: {
      16: `icons/16-${s}.png`,
      32: `icons/32-${s}.png`,
    },
  }).catch(() => {});
}

function handleEnabledStorageChange(changes) {
  if (changes.enabled !== undefined) {
    updateIcon(changes.enabled.newValue ?? false);
  }
}
chrome.storage.onChanged.addListener(handleEnabledStorageChange);

const initializeIcon = ({ enabled }) => updateIcon(enabled ?? false);
chrome.storage.local.get(['enabled']).then(initializeIcon);

// ---------------------------------------------------------------------------
// Audio capture (hold the audio hotkey to record, release to send)
// ---------------------------------------------------------------------------

let _audioActive = false;
let _stopPending = false;
let _offscreenReadyResolve = null;
let _micHoldTimer = null;  // timer ID for hold-to-talk release detection (see mic command handler)

// Shared deferred-promise executor: stores the resolve fn so the 'offscreen-ready'
// message handler can fulfill the promise once the document signals it is ready.
function captureOffscreenReady(resolve) { _offscreenReadyResolve = resolve; }

let _micState    = 'unknown';
let _replayState = 'idle';
let _extEnabled  = false;

async function sendExtStatus() {
  // Read mic/replay from storage rather than trusting the in-memory copies. Those are
  // reset to 'unknown'/'idle' every time MV3 evicts the service worker and only rehydrated
  // inside an async .then() at startup — so any send that races that (a toggle waking the
  // worker, say) would tell the dashboard the mic is unknown when it isn't. Storage is
  // already the normalized truth: stale 'armed'/'arming' is scrubbed on startup while
  // terminal 'stream-ended'/'error' is deliberately preserved.
  const { server_url, api_token, mic_status, replay_status } = await chrome.storage.local.get(
    ['server_url', 'api_token', 'mic_status', 'replay_status'],
  );
  if (!server_url || !api_token) return;
  await fetch(`${server_url}/api/ext/status`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${api_token}`,
    },
    body: JSON.stringify({
      ext: true,
      ext_enabled: _extEnabled,
      mic: mic_status?.state || _micState,
      replay: replay_status?.state || _replayState,
    }),
  }).catch(() => {});
}

// ---------------------------------------------------------------------------
// Instant replay state
// ---------------------------------------------------------------------------

let _replayArmed     = false;
let _replayTabId     = null;
let _replayTabOrigin = null;
let _replayWindowSec = 15;
const _replayPending = {};   // requestId → resolve fn

// Clear any stale *armed* status from a previous SW lifetime — a lock never
// survives an SW restart, so 'armed'/'arming' left in storage would be a lie.
// But preserve terminal 'stream-ended'/'error' states: those drive the "replay
// lost" warning that tells the user to re-lock from the extension popup.
function clearStaleReplayStatus({ replay_status }) {
  const state = replay_status?.state;
  if (state === 'stream-ended' || state === 'error') return;
  chrome.storage.local.set({ replay_status: { state: 'idle' } }).catch(() => {});
}
function resetReplayStatusOnReadError() {
  chrome.storage.local.set({ replay_status: { state: 'idle' } }).catch(() => {});
}
chrome.storage.local.get(['replay_status']).then(clearStaleReplayStatus).catch(resetReplayStatusOnReadError);

function maybeCloseOffscreen() {
  if (!_replayArmed && !_audioActive) {
    chrome.offscreen.closeDocument().catch(() => {});
  }
}

function broadcastReplayStatus(state, extra = {}) {
  _replayState = state;
  const payload = { state, ...extra };
  // local is readable by content scripts; session is not — write both
  chrome.storage.local.set({ replay_status: payload }).catch(() => {});
  chrome.storage.session?.set({ replay_status: payload }).catch(() => {});
  chrome.runtime.sendMessage({ type: 'replay-status', ...payload }).catch(() => {});
  sendExtStatus();
}

function handleStreamDeath() {
  if (!_replayArmed && _replayTabId === null) return; // already disarmed
  _replayArmed     = false;
  _replayTabId     = null;
  _replayTabOrigin = null;
  chrome.runtime.sendMessage({ type: 'replay-disarm' }).catch(() => {});
  broadcastReplayStatus('stream-ended');
  maybeCloseOffscreen();
}

// ---------------------------------------------------------------------------
// Message router
// ---------------------------------------------------------------------------

function routeMessage(msg, sender, sendResponse) {
  if (msg.type === 'get-commands') {
    const onCommandsFetched = (cmds) => sendResponse(cmds);
    const sendEmptyCommandsOnError = () => sendResponse([]);
    chrome.commands.getAll().then(onCommandsFetched).catch(sendEmptyCommandsOnError);
    return true; // keep channel open for async response
  } else if (msg.type === 'capture') {
    handleCapture();
  } else if (msg.type === 'toggle') {
    handleToggle(sender.tab?.id);
  } else if (msg.type === 'force-enable') {
    forceEnable();
  } else if (msg.type === 'audio-start') {
    handleAudioStart();
  } else if (msg.type === 'audio-stop') {
    handleAudioStop();
  } else if (msg.type === 'audio-data') {
    handleAudioData(msg.base64, msg.mimeType);
  } else if (msg.type === 'typing-start') {
    handleTypingStart();
  } else if (msg.type === 'typing-preview') {
    queueTypingPreview(msg.text);
  } else if (msg.type === 'typing-submit') {
    handleTypingSubmit(msg.text);
  } else if (msg.type === 'typing-cancel') {
    handleTypingCancel();
  } else if (msg.type === 'audio-error') {
    _micState = 'error';
    _audioActive = false;
    _stopPending = false;
    chrome.action.setBadgeText({ text: 'ERR' });
    chrome.action.setBadgeBackgroundColor({ color: '#c0392b' });
    setTimeout(function clearErrorBadge() { chrome.action.setBadgeText({ text: '' }); }, 2000);
    chrome.storage.local.set({ mic_status: { state: 'error', message: msg.error } }).catch(() => {});
    if (msg.errorName === 'NotAllowedError') openGrantMicTab();
    maybeCloseOffscreen();
    sendExtStatus();
  } else if (msg.type === 'check-mic-permission') {
    checkMicPermission();
  } else if (msg.type === 'open-mic-grant') {
    openGrantMicTab();
  } else if (msg.type === 'mic-permission-result') {
    _micState = msg.state;
    chrome.storage.local.set({ mic_status: { state: msg.state } }).catch(() => {});
    maybeCloseOffscreen();
    sendExtStatus();
  } else if (msg.type === 'offscreen-ready') {
    _offscreenReadyResolve?.();
    _offscreenReadyResolve = null;
  } else if (msg.type === 'replay-lock') {
    handleReplayLock(msg.tabId, msg.windowSec);
  } else if (msg.type === 'replay-unlock') {
    handleReplayUnlock();
  } else if (msg.type === 'replay-trigger') {
    handleReplayTrigger(sender.tab?.id);
  } else if (msg.type === 'replay-armed') {
    _replayArmed = true;
    if (_replayTabId) {
      const onReplayTabFetched = (tab) => {
        broadcastReplayStatus('armed', { tabTitle: tab?.title || 'Unknown tab' });
      };
      chrome.tabs.get(_replayTabId, onReplayTabFetched);
    } else {
      broadcastReplayStatus('armed');
    }
  } else if (msg.type === 'replay-slice-result') {
    _replayPending[msg.requestId]?.({ base64: msg.base64, mimeType: msg.mimeType });
    delete _replayPending[msg.requestId];
  } else if (msg.type === 'replay-stream-error') {
    _replayArmed = false;
    broadcastReplayStatus('error', { errorMsg: msg.error || 'Tab audio capture failed' });
    maybeCloseOffscreen();
  } else if (msg.type === 'replay-stream-ended') {
    handleStreamDeath();
  } else if (msg.type === 'sync-account') {
    fetchAccountLevel();
  }
  return false;
}
chrome.runtime.onMessage.addListener(routeMessage);

// ---------------------------------------------------------------------------
// Mic recording handlers (unchanged logic, maybeCloseOffscreen replaces unconditional close)
// ---------------------------------------------------------------------------

async function handleAudioStart() {
  if (_audioActive) return;
  _stopPending = false;

  const { enabled } = await chrome.storage.local.get(['enabled']);
  if (!enabled) {
    await chrome.storage.local.set({ last_disabled_press: Date.now() });
    await flashDisabled();
    return;
  }

  if (_stopPending) { _stopPending = false; return; }
  _audioActive = true;

  const existing = await chrome.runtime.getContexts({
    contextTypes: ['OFFSCREEN_DOCUMENT'],
    documentUrls: [chrome.runtime.getURL('offscreen.html')],
  });

  if (existing.length === 0) {
    const readyPromise = new Promise(captureOffscreenReady);
    await chrome.offscreen.createDocument({
      url: 'offscreen.html',
      reasons: ['USER_MEDIA'],
      justification: 'Microphone access for audio transcription',
    });
    await readyPromise;
  }

  // Guard against a race where handleAudioStop fired while the offscreen doc was
  // being created: it takes the main path (clears _audioActive, sends stop — which
  // is dropped because there was no offscreen yet) without setting _stopPending.
  // Checking !_audioActive catches that case; _stopPending catches the inverse
  // (stop fired before _audioActive was set, i.e. the very-fast-release path).
  if (_stopPending || !_audioActive) {
    _stopPending = false;
    _audioActive = false;
    maybeCloseOffscreen();
    return;
  }

  const { mic_device_id } = await chrome.storage.local.get(['mic_device_id']);
  chrome.runtime.sendMessage({ type: 'start-recording', deviceId: mic_device_id || null }).catch(() => {});
  chrome.action.setBadgeText({ text: 'REC' });
  chrome.action.setBadgeBackgroundColor({ color: '#c0392b' });
}

async function handleAudioStop() {
  if (!_audioActive) { _stopPending = true; return; }
  _audioActive = false;
  chrome.action.setBadgeText({ text: '' });
  chrome.runtime.sendMessage({ type: 'stop-recording' }).catch(() => {});
}

// ── Passive mic-permission check (for the /app status dot) ─────────────────────
let _micCheckInProgress = false;
async function checkMicPermission() {
  // The onboarding page retries this event several times while waiting for the service
  // worker to wake up. Guard against concurrent calls so we don't try to create a second
  // offscreen document (which throws) before the first one is ready.
  if (_micCheckInProgress) return;
  _micCheckInProgress = true;
  try {
  const existing = await chrome.runtime.getContexts({
    contextTypes: ['OFFSCREEN_DOCUMENT'],
    documentUrls: [chrome.runtime.getURL('offscreen.html')],
  });
  if (existing.length === 0) {
    const readyPromise = new Promise(captureOffscreenReady);
    await chrome.offscreen.createDocument({
      url: 'offscreen.html',
      reasons: ['USER_MEDIA'],
      justification: 'Check microphone permission status',
    });
    await readyPromise;
  }
  chrome.runtime.sendMessage({ type: 'query-mic-permission' }).catch(() => {});
  } finally {
    _micCheckInProgress = false;
  }
}

async function handleAudioData(base64, mimeType) {
  _micState = 'granted';
  chrome.storage.local.set({ mic_status: { state: 'granted' } }).catch(() => {});
  sendExtStatus();
  const { server_url, api_token } = await chrome.storage.local.get(['server_url', 'api_token']);
  if (server_url && api_token) {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    const form = new FormData();
    form.append('audio', new Blob([bytes], { type: mimeType }), 'recording.webm');
    // Both audio paths hit the same endpoint; this is what tells the server which prompt
    // to use — a deliberate mic recording, not a retroactive replay slice.
    form.append('source', 'mic');
    try {
      const resp = await fetch(`${server_url}/api/audio-capture`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${api_token}` },
        body: form,
      });
      if (!resp.ok) {
        let detail = null;
        try { detail = (await resp.json()).detail; } catch {}
        await chrome.storage.local.set({ last_error: friendlyError(resp.status, detail) });
      }
    } catch (e) {
      console.error('[audio] upload failed:', e.message);
    }
  }
  maybeCloseOffscreen();
}

// ---------------------------------------------------------------------------
// Typing-mode handlers
// ---------------------------------------------------------------------------

async function handleTypingStart() {
  const { enabled } = await chrome.storage.local.get(['enabled']);
  if (!enabled) {
    await chrome.storage.local.set({ last_disabled_press: Date.now() });
    await flashDisabled();
    return;
  }
  chrome.action.setBadgeText({ text: 'TYPE' });
  chrome.action.setBadgeBackgroundColor({ color: '#2563eb' });
  queueTypingPreview('');  // clears any leftover preview from the last round
}

// Live preview of the typing buffer, throttled to one request per TYPING_PREVIEW_MS.
// Always sends the WHOLE buffer rather than a delta: a dropped or out-of-order request
// then costs one stale frame instead of corrupting the text, and no sequencing is needed.
// Trailing edge, so the last keystroke of a burst always lands.
const TYPING_PREVIEW_MS = 250;
let _previewText = null;
let _previewTimer = null;
let _previewLastSent = 0;

function queueTypingPreview(text) {
  _previewText = text;
  if (_previewTimer) return;
  const wait = Math.max(0, TYPING_PREVIEW_MS - (Date.now() - _previewLastSent));
  function flushTypingPreview() {
    _previewTimer = null;
    const pending = _previewText;
    _previewText = null;
    _previewLastSent = Date.now();
    sendTypingPreview(pending);
  }
  _previewTimer = setTimeout(flushTypingPreview, wait);
}

async function sendTypingPreview(text) {
  const { server_url, api_token, enabled, typing_preview } = await chrome.storage.local.get([
    'server_url', 'api_token', 'enabled', 'typing_preview',
  ]);
  // Unset means the settings sync hasn't run yet — the server default is on, so match it.
  if (typing_preview === false) return;
  if (!enabled || !api_token || !server_url) return;
  try {
    await fetch(`${server_url}/api/typing-preview`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${api_token}`,
      },
      body: JSON.stringify({ text }),
    });
  } catch {
    // A dropped preview frame is not worth surfacing — the next keystroke resends the
    // full buffer, and the submit itself goes through /api/text-capture regardless.
  }
}

function cancelTypingPreview() {
  if (_previewTimer) { clearTimeout(_previewTimer); _previewTimer = null; }
  _previewText = null;
}

// Escape in typing mode: drop the buffer without sending it anywhere.
function handleTypingCancel() {
  chrome.action.setBadgeText({ text: '' });
  cancelTypingPreview();
  // Clear the dashboard's live preview too — a half-typed question left on the phone would
  // read as "still waiting to send" when nothing is coming.
  sendTypingPreview('');
}

async function handleTypingSubmit(text) {
  chrome.action.setBadgeText({ text: '' });
  // Drop any queued preview — otherwise a trailing frame lands after the submit and
  // repaints the dashboard's preview over the "thinking…" state.
  cancelTypingPreview();
  if (!text || !text.trim()) return;

  const { server_url, api_token, enabled } = await chrome.storage.local.get(['server_url', 'api_token', 'enabled']);
  if (!enabled) return;
  if (!api_token || !server_url) {
    chrome.action.openPopup().catch(() => {});
    return;
  }

  try {
    const resp = await fetch(`${server_url}/api/text-capture`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${api_token}`,
      },
      body: JSON.stringify({ text, monitor: 'browser' }),
    });

    if (resp.ok) {
      await chrome.storage.local.set({ last_capture: new Date().toLocaleTimeString(), last_error: '' });
    } else {
      const body = await resp.text();
      let detail = body;
      try { detail = JSON.parse(body).detail ?? body; } catch {}
      await chrome.storage.local.set({ last_error: friendlyError(resp.status, detail) });
    }
  } catch (e) {
    await chrome.storage.local.set({ last_error: `Network error: ${e.message}` });
  }
}

// ---------------------------------------------------------------------------
// Replay handlers
// ---------------------------------------------------------------------------

async function handleReplayLock(tabId, windowSec) {
  _replayTabId     = tabId;
  _replayWindowSec = windowSec;

  // Remember origin so we can detect cross-origin navigation later
  let tabTitle = 'Unknown tab';
  try {
    const tab = await chrome.tabs.get(tabId);
    _replayTabOrigin = tab.url ? new URL(tab.url).origin : null;
    tabTitle = tab.title || tabTitle;
  } catch { _replayTabOrigin = null; }

  broadcastReplayStatus('arming', { tabTitle });

  // Ensure a clean offscreen doc — close any stale one first (awaited so we
  // don't race between close and create), then create fresh unless the mic
  // path is already holding the doc open.
  const existing = await chrome.runtime.getContexts({
    contextTypes: ['OFFSCREEN_DOCUMENT'],
    documentUrls: [chrome.runtime.getURL('offscreen.html')],
  });

  let needCreate = existing.length === 0;
  if (existing.length > 0 && !_audioActive) {
    await chrome.offscreen.closeDocument().catch(() => {});
    needCreate = true;
  }

  if (needCreate) {
    const readyPromise = new Promise(captureOffscreenReady);
    await chrome.offscreen.createDocument({
      url: 'offscreen.html',
      reasons: ['USER_MEDIA'],
      justification: 'Tab audio capture for instant replay',
    });
    await readyPromise;
  }

  let streamId;
  try {
    // Omit consumerTabId — offscreen docs don't have a tab ID
    streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tabId });
  } catch (e) {
    console.error('[replay] getMediaStreamId failed:', e.message);
    broadcastReplayStatus('error', { errorMsg: 'Could not capture tab audio — try re-locking' });
    maybeCloseOffscreen();
    return;
  }

  chrome.runtime.sendMessage({ type: 'replay-stream-id', streamId, windowSec, epochMs: 60_000 }).catch(() => {});
}

async function handleReplayUnlock() {
  if (!_replayArmed && _replayTabId === null) return;
  _replayArmed = false;
  _replayTabId = null;
  chrome.runtime.sendMessage({ type: 'replay-disarm' }).catch(() => {});
  broadcastReplayStatus('idle');
  maybeCloseOffscreen();
}

async function handleReplayTrigger(senderTabId) {
  const { enabled } = await chrome.storage.local.get(['enabled']);
  if (!enabled) {
    await chrome.storage.local.set({ last_disabled_press: Date.now() });
    await flashDisabled();
    return;
  }
  if (!_replayArmed) return;

  // Always read the current setting — user may have changed it since locking
  const { replay_seconds } = await chrome.storage.local.get(['replay_seconds']);
  const windowSec = replay_seconds || _replayWindowSec;

  const requestId = Math.random().toString(36).slice(2);
  function captureReplaySliceResolve(resolve) { _replayPending[requestId] = resolve; }
  const dataPromise = new Promise(captureReplaySliceResolve);

  chrome.runtime.sendMessage({ type: 'replay-slice', requestId, windowSec }).catch(() => {});

  const { base64, mimeType } = await dataPromise;
  if (!base64) {
    if (senderTabId) {
      chrome.tabs.sendMessage(senderTabId, { type: 'replay-buffer-empty' }).catch(() => {});
    }
    return;
  }

  const { server_url, api_token } = await chrome.storage.local.get(['server_url', 'api_token']);
  if (!server_url || !api_token) return;

  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  const form = new FormData();
  form.append('audio', new Blob([bytes], { type: mimeType }), 'recording.webm');
  // Marks this as a retroactive tab-audio slice rather than a mic recording, so the server
  // uses the appropriate prompt for truncated, multi-speaker audio.
  form.append('source', 'replay');
  try {
    await fetch(`${server_url}/api/audio-capture`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${api_token}` },
      body: form,
    });
  } catch (e) {
    console.error('[replay] upload failed:', e.message);
  }
}

// Hold the SW alive while the offscreen doc has an open port
function onKeepalivePortDisconnect() {}
function handlePortConnect(port) {
  if (port.name === 'replay-keepalive') {
    port.onDisconnect.addListener(onKeepalivePortDisconnect);
  }
}
chrome.runtime.onConnect.addListener(handlePortConnect);

// Detect locked tab being closed
function handleTabRemoved(tabId) {
  if (tabId === _replayTabId) handleStreamDeath();
}
chrome.tabs.onRemoved.addListener(handleTabRemoved);

// Detect locked tab navigating to a different origin (privacy guard)
function handleTabUpdated(tabId, changeInfo, tab) {
  if (tabId !== _replayTabId || !_replayArmed) return;
  if (changeInfo.status !== 'loading') return;
  try {
    const currentUrl = tab.url || changeInfo.url;
    if (!currentUrl) return;
    const newOrigin = new URL(currentUrl).origin;
    if (_replayTabOrigin && newOrigin !== _replayTabOrigin) handleStreamDeath();
  } catch {}
}
chrome.tabs.onUpdated.addListener(handleTabUpdated);

// Storage-based trigger for opening the mic-grant tab from content scripts.
// More reliable than sendMessage because storage writes always wake the service worker,
// whereas sendMessage can be silently dropped during a sleep/wake transition.
function handleMicGrantStorageSignal(changes, area) {
  if (area === 'local' && changes._open_mic_grant_ts) openGrantMicTab();
}
chrome.storage.onChanged.addListener(handleMicGrantStorageSignal);


// One-time migration: v4 removes server-synced hotkeys (now managed via manifest commands /
// chrome://extensions/shortcuts). Clear any stale hotkey_* keys left over from v1-v3.
const HOTKEY_VERSION = 4;
async function migrateHotkeys() {
  const { hotkey_version } = await chrome.storage.local.get(['hotkey_version']);
  if (hotkey_version === HOTKEY_VERSION) return;
  await chrome.storage.local.remove([
    'hotkey_capture', 'hotkey_audio', 'hotkey_toggle', 'hotkey_replay', 'hotkey_typing',
  ]);
  await chrome.storage.local.set({ hotkey_version: HOTKEY_VERSION });
}

// ---------------------------------------------------------------------------
// Manifest command listener — replaces content-script keydown detection.
// Hotkeys are defined in manifest.json and configured by users at
// chrome://extensions/shortcuts. Commands grant activeTab on press, so
// captureVisibleTab works without <all_urls> host permission.
// ---------------------------------------------------------------------------

// _execute_action is handled by Chrome itself — it opens the popup (clicking the icon).
// All hotkey commands are intercepted here; toggle now has its own named command so
// Ctrl+Shift+1 toggles directly without opening the popup.
function clearMicDebounce() { _micHoldTimer = null; handleAudioStop(); }
async function handleCommand(command) {
  if (command === 'arm') {
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    handleToggle(tab?.id);
  } else if (command === 'capture') {
    handleCapture();
  } else if (command === 'mic') {
    // Hold-to-talk: hold the key to record, release to send.
    // chrome.commands has no keyup event, so release is inferred from the key-repeat
    // stream: Chrome fires onCommand ~10×/sec while the key is held. Each fire resets
    // a 300ms timer; when the fires stop (key released), the timer expires and stops
    // recording. First fire starts recording and arms the timer.
    if (_audioActive) {
      // Key still held — push the release timer forward.
      clearTimeout(_micHoldTimer);
      _micHoldTimer = setTimeout(clearMicDebounce, 300);
    } else {
      // First press — arm the release timer then start recording.
      _micHoldTimer = setTimeout(clearMicDebounce, 300);
      handleAudioStart();
    }
  } else if (command === 'replay') {
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    handleReplayTrigger(tab?.id);
  } else if (command === 'typing') {
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (tab?.id) {
      // Content script (interview-wise.com only) owns the typing buffer — tell it to toggle.
      chrome.tabs.sendMessage(tab.id, { type: 'typing-command' }).catch(() => {});
    }
  }
}
chrome.commands.onCommand.addListener(handleCommand);

// Seed the server URL on first install.
// Dev builds (manifest.dev.json sets "_dev": true) seed the local dev server.
// Prod builds seed the production URL.
// If you already have the dev extension installed with a stale URL, clear it once:
//   chrome.storage.local.set({ server_url: 'http://127.0.0.1:8080' })
const _IS_DEV = !!chrome.runtime.getManifest()._dev;
function seedServerUrl({ server_url }) {
  if (!server_url) {
    chrome.storage.local.set({
      server_url: _IS_DEV ? 'http://127.0.0.1:8080' : 'https://interview-wise.com',
    });
  }
}
chrome.storage.local.get(['server_url'], seedServerUrl);

const onHotkeysMigrated = () => fetchAccountLevel();
migrateHotkeys().then(onHotkeysMigrated);

// Broadcast initial ext status to the server so all connected devices (e.g. mobile)
// see the correct dot states immediately on load, then keep it fresh via heartbeat.
// Heartbeat only starts when credentials are configured — no pings before the user
// has set up the extension.
let _heartbeatId = null;
function ensureHeartbeat() {
  if (_heartbeatId) return;
  function startHeartbeatIfConfigured({ server_url, api_token }) {
    if (server_url && api_token && !_heartbeatId) {
      _heartbeatId = setInterval(sendExtStatus, 30_000);
    }
  }
  chrome.storage.local.get(['server_url', 'api_token'], startHeartbeatIfConfigured);
}

function onInitialStateLoaded({ enabled, mic_status }) {
  _extEnabled = !!enabled;
  if (mic_status?.state) _micState = mic_status.state;
  sendExtStatus();
  // Nothing has ever established a mic state on this device, so no amount of reading
  // storage will produce one — ask once, or the dashboard shows "unknown" indefinitely.
  if (!mic_status?.state || mic_status.state === 'unknown') checkMicPermission();
  ensureHeartbeat();
}
chrome.storage.local.get(['enabled', 'mic_status']).then(onInitialStateLoaded);

// Also start the heartbeat when the token is saved for the first time after install
function handleApiTokenStorageChange(changes) {
  if (changes.api_token) ensureHeartbeat();
}
chrome.storage.onChanged.addListener(handleApiTokenStorageChange);
