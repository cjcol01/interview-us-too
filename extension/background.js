async function fetchAccountLevel() {
  const { server_url, api_token } = await chrome.storage.local.get(['server_url', 'api_token']);
  if (!server_url || !api_token) return;
  try {
    const resp = await fetch(`${server_url}/api/me`, {
      headers: { 'Authorization': `Bearer ${api_token}` },
    });
    if (resp.ok) {
      const { account_level } = await resp.json();
      await chrome.storage.local.set({ is_unlimited: account_level === 'unlimited' });
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

chrome.commands.onCommand.addListener(async (command) => {
  if (command === 'capture') {
    const { enabled, is_unlimited } = await chrome.storage.local.get(['enabled', 'is_unlimited']);
    if (!enabled) {
      await chrome.storage.local.set({ last_disabled_press: Date.now() });
      if (!is_unlimited) await flashDisabled();
      return;
    }
    doCapture();
  } else if (command === 'toggle') {
    const { enabled } = await chrome.storage.local.get(['enabled']);
    const next = !enabled;
    await chrome.storage.local.set({ enabled: next });
    if (next) await notifyEnabled();
  }
});

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

chrome.runtime.onInstalled.addListener(async ({ reason }) => {
  if (reason === 'install') {
    const tabs = await chrome.tabs.query({});
    for (const tab of tabs) {
      if (!tab.url || tab.url.startsWith('chrome://') || tab.url.startsWith('chrome-extension://')) continue;
      chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['content.js'] }).catch(() => {});
    }
  }
});

fetchAccountLevel();
