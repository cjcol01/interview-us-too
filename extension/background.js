async function fetchAccountLevel() {
  const { server_url, api_token } = await chrome.storage.local.get(['server_url', 'api_token']);
  if (!server_url || !api_token) return;
  try {
    const resp = await fetch(`${server_url}/api/me`, {
      headers: { 'Authorization': `Bearer ${api_token}` },
    });
    if (resp.ok) {
      const { account_level, hotkeys } = await resp.json();
      await chrome.storage.local.set({ is_unlimited: account_level === 'unlimited' });
      if (hotkeys) {
        await chrome.storage.local.set({
          hotkey_capture: hotkeys.capture,
          hotkey_audio:   hotkeys.audio,
          hotkey_toggle:  hotkeys.toggle,
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
    chrome.offscreen.closeDocument().catch(() => {});
  } else if (msg.type === 'offscreen-ready') {
    _offscreenReadyResolve?.();
    _offscreenReadyResolve = null;
  }
  return false;
});

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
    chrome.offscreen.closeDocument().catch(() => {});
    return;
  }

  chrome.runtime.sendMessage({ type: 'start-recording' });
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
  chrome.offscreen.closeDocument().catch(() => {});
}

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
