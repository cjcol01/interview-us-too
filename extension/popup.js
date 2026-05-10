document.addEventListener('DOMContentLoaded', async () => {
  const { server_url, api_token, complexity, last_capture, last_error, enabled,
          hotkey_capture, hotkey_audio, hotkey_toggle, hotkey_replay,
          replay_enabled, replay_seconds } =
    await chrome.storage.local.get(['server_url', 'api_token', 'complexity', 'last_capture', 'last_error', 'enabled',
                                    'hotkey_capture', 'hotkey_audio', 'hotkey_toggle', 'hotkey_replay',
                                    'replay_enabled', 'replay_seconds']);

  const serverInput   = document.getElementById('server_url');
  const tokenInput    = document.getElementById('api_token');
  const toggleBtn     = document.getElementById('toggle_token');
  const complexityVal = document.getElementById('complexity_val');
  const saveBtn       = document.getElementById('save');
  const statusEl      = document.getElementById('status');
  const enabledBtn      = document.getElementById('toggle_enabled');
  const confirmOverlay  = document.getElementById('confirm-overlay');
  const confirmOk       = document.getElementById('confirm-ok');
  const confirmCancel   = document.getElementById('confirm-cancel');

  if (server_url) serverInput.value = server_url;
  if (api_token)  tokenInput.value  = api_token;

  document.getElementById('hint-capture').textContent     = hotkey_capture || 'Ctrl+Shift+7';
  document.getElementById('hint-audio').textContent       = hotkey_audio   || 'Ctrl+Shift+8';
  document.getElementById('hint-toggle').textContent      = hotkey_toggle  || 'Ctrl+Shift+9';
  document.getElementById('hint-replay').textContent      = hotkey_replay  || 'Ctrl+Shift+6';
  document.getElementById('confirm-capture-key').textContent = hotkey_capture || 'Ctrl+Shift+7';

  let isEnabled = enabled ?? false;

  function applyEnabledState() {
    enabledBtn.textContent = isEnabled ? 'ON' : 'OFF';
    enabledBtn.className = 'toggle-btn ' + (isEnabled ? 'on' : 'off');
  }

  applyEnabledState();

  enabledBtn.addEventListener('click', () => {
    if (!isEnabled) {
      confirmOverlay.classList.remove('hidden');
    } else {
      isEnabled = false;
      chrome.storage.local.set({ enabled: false });
      applyEnabledState();
    }
  });

  confirmOk.addEventListener('click', async () => {
    confirmOverlay.classList.add('hidden');
    isEnabled = true;
    await chrome.storage.local.set({ enabled: true });
    applyEnabledState();
  });

  confirmCancel.addEventListener('click', () => {
    confirmOverlay.classList.add('hidden');
  });

  let comp = complexity ?? 2;
  complexityVal.textContent = comp;

  function showStatus(msg, isError = false) {
    statusEl.textContent = msg;
    statusEl.className = 'status ' + (isError ? 'err' : 'ok');
  }

  if (last_error) {
    showStatus(last_error, true);
  } else if (last_capture) {
    showStatus(`Last capture: ${last_capture}`);
  } else if (!api_token || !server_url) {
    showStatus('Configure server URL and token below', true);
  }

  toggleBtn.addEventListener('click', () => {
    const show = tokenInput.type === 'password';
    tokenInput.type = show ? 'text' : 'password';
    toggleBtn.textContent = show ? '🚫' : '👁';
  });

  document.getElementById('complexity_down').addEventListener('click', () => {
    if (comp > 1) { comp--; complexityVal.textContent = comp; }
  });

  document.getElementById('complexity_up').addEventListener('click', () => {
    if (comp < 3) { comp++; complexityVal.textContent = comp; }
  });

  saveBtn.addEventListener('click', async () => {
    const url = serverInput.value.trim().replace(/\/$/, '');
    const tok = tokenInput.value.trim();

    if (!url) { showStatus('Server URL is required', true); return; }
    if (!tok)  { showStatus('API token is required', true); return; }

    await chrome.storage.local.set({ server_url: url, api_token: tok, complexity: comp, last_error: '' });
    showStatus('Saved!');
    setTimeout(() => {
      statusEl.textContent = last_capture ? `Last capture: ${last_capture}` : '';
      statusEl.className = 'status ok';
    }, 1500);

    try {
      const resp = await fetch(`${url}/api/me`, { headers: { 'Authorization': `Bearer ${tok}` } });
      if (resp.ok) {
        const { account_level } = await resp.json();
        await chrome.storage.local.set({ is_unlimited: account_level === 'unlimited' });
      }
    } catch {}
  });

  const grantMicBtn = document.getElementById('grant_mic');
  const micStatusEl = document.getElementById('mic_status');

  async function checkMicPermission() {
    try {
      const result = await navigator.permissions.query({ name: 'microphone' });
      if (result.state === 'granted') {
        micStatusEl.textContent = 'Mic permission granted';
        micStatusEl.className = 'status ok';
        grantMicBtn.textContent = 'Re-test mic';
      }
    } catch {}
  }
  checkMicPermission();

  grantMicBtn.addEventListener('click', () => {
    chrome.tabs.create({ url: chrome.runtime.getURL('grant-mic.html') });
  });

  chrome.storage.onChanged.addListener((changes) => {
    if (changes.last_capture) showStatus(`Last capture: ${changes.last_capture.newValue}`);
    if (changes.last_error?.newValue) showStatus(changes.last_error.newValue, true);
    if (changes.enabled !== undefined) {
      isEnabled = changes.enabled.newValue ?? false;
      applyEnabledState();
      if (isEnabled) {
        statusEl.textContent = '';
        statusEl.className = 'status';
      }
    }
    if (changes.last_disabled_press) {
      chrome.storage.local.get(['hotkey_toggle', 'hotkey_capture'], (r) => {
        const toggle  = r.hotkey_toggle  || 'Ctrl+Shift+9';
        const capture = r.hotkey_capture || 'Ctrl+Shift+7';
        showStatus(`Interview assistant not started. Press ${toggle} to start, then ${capture} to capture.`, true);
      });
    }
  });

  // ── Replay section ────────────────────────────────────────────────────────
  const replaySection  = document.getElementById('replay-section');
  const replayPill     = document.getElementById('replay-pill');
  const replayWinLabel = document.getElementById('replay-window-label');
  const lockBtn        = document.getElementById('replay-lock-btn');
  const unlockBtn      = document.getElementById('replay-unlock-btn');

  if (replay_enabled) {
    replaySection.style.display = 'block';
    replayWinLabel.textContent  = `Window: ${replay_seconds || 10}s`;
  }

  function applyReplayStatus(status) {
    if (!status) return;
    const { state, tabTitle } = status;
    replayPill.className = 'replay-pill ' + state;
    if (state === 'idle') {
      replayPill.textContent  = 'Idle';
      lockBtn.textContent     = 'Lock to this tab';
      lockBtn.style.display   = '';
      unlockBtn.style.display = 'none';
    } else if (state === 'arming') {
      replayPill.textContent  = 'Arming…';
      lockBtn.style.display   = 'none';
      unlockBtn.style.display = '';
    } else if (state === 'armed') {
      replayPill.textContent  = tabTitle ? `Armed: ${tabTitle.slice(0, 24)}` : 'Armed';
      lockBtn.style.display   = 'none';
      unlockBtn.style.display = '';
    } else if (state === 'stream-ended') {
      replayPill.textContent  = 'Stream lost';
      lockBtn.textContent     = 'Re-lock to a tab';
      lockBtn.style.display   = '';
      unlockBtn.style.display = 'none';
    } else if (state === 'error') {
      replayPill.textContent  = 'Error — re-lock';
      lockBtn.textContent     = 'Lock to this tab';
      lockBtn.style.display   = '';
      unlockBtn.style.display = 'none';
    }
  }

  // Restore persisted status (local is accessible from both popup and content scripts)
  chrome.storage.local.get(['replay_status'], ({ replay_status }) => {
    applyReplayStatus(replay_status);
  });

  // Live updates from background
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === 'replay-status') applyReplayStatus(msg);
  });

  lockBtn.addEventListener('click', async () => {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) return;
    const windowSec = replay_seconds || 10;
    chrome.runtime.sendMessage({ type: 'replay-lock', tabId: tab.id, windowSec });
  });

  unlockBtn.addEventListener('click', () => {
    chrome.runtime.sendMessage({ type: 'replay-unlock' });
  });
});
