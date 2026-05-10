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
      if (data.hotkeys) {
        await chrome.storage.local.set({
          hotkey_capture: data.hotkeys.capture,
          hotkey_audio:   data.hotkeys.audio,
          hotkey_toggle:  data.hotkeys.toggle,
          hotkey_replay:  data.hotkeys.replay,
        });
      }
      if (data.replay) {
        await chrome.storage.local.set({
          replay_enabled: data.replay.enabled,
          replay_seconds: data.replay.seconds,
        });
      }
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
        complexity: complexity ?? 2,
        monitor: 'browser',
      }),
    });

    if (resp.ok) {
      await chrome.storage.local.set({ last_capture: new Date().toLocaleTimeString(), last_error: '' });
    } else {
      const body = await resp.text();
      let msg;
      try {
        const json = JSON.parse(body);
        if (json.detail === 'sessions_exhausted') {
          msg = 'No sessions remaining — visit InterviewAce to top up.';
        } else if (json.detail === 'trial_expired') {
          msg = 'Trial expired — visit InterviewAce to continue.';
        } else {
          msg = `Error ${resp.status}: ${json.detail ?? body}`;
        }
      } catch {
        msg = `Error ${resp.status}: ${body}`;
      }
      await chrome.storage.local.set({ last_error: msg });
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
  await chrome.storage.local.set({ enabled: next });
  if (next) await notifyEnabled();
  else await flashDisabled();
  if (senderTabId) {
    chrome.tabs.sendMessage(senderTabId, { type: 'toggled', enabled: next }).catch(() => {});
  }
}

function makeIconImageData(size, enabled) {
  const canvas = new OffscreenCanvas(size, size);
  const ctx = canvas.getContext('2d');
  const r = Math.round(size * 0.2);
  ctx.fillStyle = '#1e1e1e';
  ctx.beginPath();
  ctx.roundRect(0, 0, size, size, r);
  ctx.fill();
  ctx.beginPath();
  ctx.arc(size / 2, size / 2, Math.round(size * 0.3), 0, Math.PI * 2);
  ctx.fillStyle = enabled ? '#4a8c55' : '#8c4a4a';
  ctx.fill();
  return ctx.getImageData(0, 0, size, size);
}

function updateIcon(enabled) {
  chrome.action.setIcon({
    imageData: {
      16: makeIconImageData(16, enabled),
      32: makeIconImageData(32, enabled),
    },
  }).catch(() => {});
}

chrome.storage.onChanged.addListener((changes) => {
  if (changes.enabled !== undefined) {
    updateIcon(changes.enabled.newValue ?? false);
  }
});

chrome.storage.local.get(['enabled']).then(({ enabled }) => updateIcon(enabled ?? false));

// ---------------------------------------------------------------------------
// Audio capture (hold Ctrl+Shift+8 to record, release to send)
// ---------------------------------------------------------------------------

let _audioActive = false;
let _stopPending = false;
let _offscreenReadyResolve = null;

// ---------------------------------------------------------------------------
// Instant replay state
// ---------------------------------------------------------------------------

let _replayArmed     = false;
let _replayTabId     = null;
let _replayTabOrigin = null;
let _lastReplayTabId = null;
let _replayWindowSec = 10;
const _replayPending = {};   // requestId → resolve fn

// Clear any stale armed status from a previous SW lifetime
chrome.storage.local.set({ replay_status: { state: 'idle' } }).catch(() => {});

function maybeCloseOffscreen() {
  if (!_replayArmed && !_audioActive) {
    chrome.offscreen.closeDocument().catch(() => {});
  }
}

function broadcastReplayStatus(state, extra = {}) {
  const payload = { state, ...extra };
  // local is readable by content scripts; session is not — write both
  chrome.storage.local.set({ replay_status: payload }).catch(() => {});
  chrome.storage.session?.set({ replay_status: payload }).catch(() => {});
  chrome.runtime.sendMessage({ type: 'replay-status', ...payload }).catch(() => {});
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

chrome.runtime.onMessage.addListener((msg, sender) => {
  if (msg.type === 'capture') {
    handleCapture();
  } else if (msg.type === 'toggle') {
    handleToggle(sender.tab?.id);
  } else if (msg.type === 'audio-start') {
    handleAudioStart();
  } else if (msg.type === 'audio-stop') {
    handleAudioStop();
  } else if (msg.type === 'audio-data') {
    handleAudioData(msg.base64, msg.mimeType);
  } else if (msg.type === 'audio-error') {
    _audioActive = false;
    _stopPending = false;
    chrome.action.setBadgeText({ text: 'ERR' });
    chrome.action.setBadgeBackgroundColor({ color: '#c0392b' });
    setTimeout(() => chrome.action.setBadgeText({ text: '' }), 2000);
    maybeCloseOffscreen();
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
      chrome.tabs.get(_replayTabId, (tab) => {
        broadcastReplayStatus('armed', { tabTitle: tab?.title || 'Unknown tab' });
      });
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
  } else if (msg.type === 'replay-relock') {
    handleReplayRelock();
  }
  return false;
});

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
    const readyPromise = new Promise(resolve => { _offscreenReadyResolve = resolve; });
    await chrome.offscreen.createDocument({
      url: 'offscreen.html',
      reasons: ['USER_MEDIA'],
      justification: 'Microphone access for audio transcription',
    });
    await readyPromise;
  }

  if (_stopPending) {
    _stopPending = false;
    _audioActive = false;
    maybeCloseOffscreen();
    return;
  }

  const { mic_device_id } = await chrome.storage.local.get(['mic_device_id']);
  chrome.runtime.sendMessage({ type: 'start-recording', deviceId: mic_device_id || null });
  chrome.action.setBadgeText({ text: 'REC' });
  chrome.action.setBadgeBackgroundColor({ color: '#c0392b' });
}

async function handleAudioStop() {
  if (!_audioActive) { _stopPending = true; return; }
  _audioActive = false;
  chrome.action.setBadgeText({ text: '' });
  chrome.runtime.sendMessage({ type: 'stop-recording' });
}

async function handleAudioData(base64, mimeType) {
  const { server_url, api_token } = await chrome.storage.local.get(['server_url', 'api_token']);
  if (server_url && api_token) {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    const form = new FormData();
    form.append('audio', new Blob([bytes], { type: mimeType }), 'recording.webm');
    try {
      const resp = await fetch(`${server_url}/api/audio-capture`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${api_token}` },
        body: form,
      });
      if (!resp.ok) {
        let msg = `Audio error ${resp.status}`;
        try { const json = await resp.json(); msg = json.detail ?? msg; } catch {}
      }
    } catch (e) {
      console.error('[audio] upload failed:', e.message);
    }
  }
  maybeCloseOffscreen();
}

// ---------------------------------------------------------------------------
// Replay handlers
// ---------------------------------------------------------------------------

async function handleReplayLock(tabId, windowSec) {
  _replayTabId     = tabId;
  _lastReplayTabId = tabId;
  _replayWindowSec = windowSec;

  // Remember origin so we can detect cross-origin navigation later
  try {
    const tab = await chrome.tabs.get(tabId);
    _replayTabOrigin = tab.url ? new URL(tab.url).origin : null;
  } catch { _replayTabOrigin = null; }

  broadcastReplayStatus('arming');

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
    const readyPromise = new Promise(resolve => { _offscreenReadyResolve = resolve; });
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

  chrome.runtime.sendMessage({ type: 'replay-stream-id', streamId, windowSec, epochMs: 60_000 });
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
  if (!_replayArmed) return;

  // Always read the current setting — user may have changed it since locking
  const { replay_seconds } = await chrome.storage.local.get(['replay_seconds']);
  const windowSec = replay_seconds || _replayWindowSec;

  const requestId = Math.random().toString(36).slice(2);
  const dataPromise = new Promise(resolve => { _replayPending[requestId] = resolve; });

  chrome.runtime.sendMessage({ type: 'replay-slice', requestId, windowSec });

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

// ---------------------------------------------------------------------------

async function handleReplayRelock() {
  if (!_lastReplayTabId) return;
  const { replay_seconds } = await chrome.storage.local.get(['replay_seconds']);
  handleReplayLock(_lastReplayTabId, replay_seconds || _replayWindowSec);
}

// Hold the SW alive while the offscreen doc has an open port
chrome.runtime.onConnect.addListener((port) => {
  if (port.name === 'replay-keepalive') {
    port.onDisconnect.addListener(() => {});
  }
});

// Detect locked tab being closed
chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabId === _replayTabId) handleStreamDeath();
});

// Detect locked tab navigating to a different origin (privacy guard)
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (tabId !== _replayTabId || !_replayArmed) return;
  if (changeInfo.status !== 'loading') return;
  try {
    const currentUrl = tab.url || changeInfo.url;
    if (!currentUrl) return;
    const newOrigin = new URL(currentUrl).origin;
    if (_replayTabOrigin && newOrigin !== _replayTabOrigin) handleStreamDeath();
  } catch {}
});

chrome.runtime.onInstalled.addListener(async ({ reason }) => {
  if (reason === 'install' || reason === 'update') {
    const tabs = await chrome.tabs.query({});
    for (const tab of tabs) {
      if (!tab.url || tab.url.startsWith('chrome://') || tab.url.startsWith('chrome-extension://')) continue;
      chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['content.js'] }).catch(() => {});
    }
  }
});

fetchAccountLevel();
