const COMPLEXITY_DESC = { 1: 'Concise hint', 2: 'Full solution', 3: 'Optimal + trade-offs' };
const COMMENT_LEVEL_DESC = { 1: 'Low', 2: 'High', 3: 'Every line' };

document.addEventListener('DOMContentLoaded', async () => {
  document.getElementById('version-label').textContent = 'V' + chrome.runtime.getManifest().version;

  const { server_url, api_token, complexity, comment_level, response_style, last_capture, last_error, enabled,
          hotkey_capture, is_unlimited,
          replay_enabled, replay_seconds } =
    await chrome.storage.local.get(['server_url', 'api_token', 'complexity', 'comment_level', 'response_style',
                                    'last_capture', 'last_error', 'enabled',
                                    'hotkey_capture', 'is_unlimited',
                                    'replay_enabled', 'replay_seconds']);

  const serverInput   = document.getElementById('server_url');
  const tokenInput    = document.getElementById('api_token');
  const toggleBtn     = document.getElementById('toggle_token');
  const complexityVal = document.getElementById('complexity_val');
  const complexityDesc = document.getElementById('complexity_desc');
  const commentVal    = document.getElementById('comment_level_val');
  const commentDesc   = document.getElementById('comment_level_desc');
  const saveBtn       = document.getElementById('save');
  const statusEl      = document.getElementById('status');
  const enabledBtn      = document.getElementById('toggle_enabled');
  const armTitle        = enabledBtn.querySelector('.arm-title');
  const armSub          = enabledBtn.querySelector('.arm-sub');
  const armState        = enabledBtn.querySelector('.arm-state');
  const confirmOverlay  = document.getElementById('confirm-overlay');
  const confirmBody     = document.getElementById('confirm-body');
  const confirmOk       = document.getElementById('confirm-ok');
  const confirmCancel   = document.getElementById('confirm-cancel');

  if (server_url) serverInput.value = server_url;
  if (api_token)  tokenInput.value  = api_token;

  let isEnabled = enabled ?? false;

  function applyEnabledState() {
    enabledBtn.className = 'arm-btn ' + (isEnabled ? 'on' : 'off');
    armTitle.textContent = isEnabled ? 'Assistant armed' : 'Assistant off';
    armSub.textContent   = isEnabled ? 'LISTENING FOR HOTKEY' : 'TAP TO ARM';
    armState.textContent = isEnabled ? 'ON' : 'OFF';
  }

  applyEnabledState();

  enabledBtn.addEventListener('click', () => {
    if (!isEnabled) {
      confirmBody.textContent = is_unlimited
        ? ''
        : 'Turning this on starts using a session as soon as you use any hotkey — toggle it off between interviews to avoid using one by accident.';
      confirmOk.textContent = is_unlimited ? 'Yes' : 'Got it, turn on';
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
  complexityDesc.textContent = COMPLEXITY_DESC[comp];

  let cmt = comment_level ?? 2;
  commentVal.textContent  = cmt;
  commentDesc.textContent = COMMENT_LEVEL_DESC[cmt];

  function showStatus(msg, isError = false) {
    statusEl.textContent = msg;
    statusEl.className = 'status ' + (isError ? 'err' : 'ok');
  }

  // Re-check the server for a lingering error instead of trusting (or aging out) a
  // stale banner. Server answers → error is no longer true, clear it. Rejected/
  // unreachable → surface the real, current reason.
  async function revalidateError(url, tok, storedError) {
    try {
      const resp = await fetch(`${url}/api/me`, { headers: { 'Authorization': `Bearer ${tok}` } });
      if (resp.ok) {
        await chrome.storage.local.set({ last_error: '' });
        return; // baseline status (last capture / blank) already on screen
      }
      showStatus(resp.status === 401 || resp.status === 403
        ? 'Token invalid or expired — re-check your API token below'
        : storedError, true);
    } catch {
      showStatus('Can’t reach the server — check the URL below and your connection', true);
    }
  }

  // A persisted error describes a *past* capture attempt. Rather than trust a stale
  // banner (or guess at its age with a timeout), re-check the server on open: if it
  // answers, the error is no longer true, so clear it; if it doesn't, the problem is
  // real right now and we show an accurate connection message.
  if (last_capture) {
    showStatus(`Last capture: ${last_capture}`);
  } else if (!api_token || !server_url) {
    showStatus('Configure server URL and token below', true);
  }

  if (last_error && api_token && server_url) {
    revalidateError(server_url, api_token, last_error);
  }

  toggleBtn.addEventListener('click', () => {
    const show = tokenInput.type === 'password';
    tokenInput.type = show ? 'text' : 'password';
    toggleBtn.innerHTML = show ? '&#9673;' : '&#9678;';
  });

  document.getElementById('complexity_down').addEventListener('click', () => {
    if (comp > 1) { comp--; complexityVal.textContent = comp; complexityDesc.textContent = COMPLEXITY_DESC[comp]; }
  });

  document.getElementById('complexity_up').addEventListener('click', () => {
    if (comp < 3) { comp++; complexityVal.textContent = comp; complexityDesc.textContent = COMPLEXITY_DESC[comp]; }
  });

  document.getElementById('comment_level_down').addEventListener('click', () => {
    if (cmt > 1) { cmt--; commentVal.textContent = cmt; commentDesc.textContent = COMMENT_LEVEL_DESC[cmt]; }
  });

  document.getElementById('comment_level_up').addEventListener('click', () => {
    if (cmt < 3) { cmt++; commentVal.textContent = cmt; commentDesc.textContent = COMMENT_LEVEL_DESC[cmt]; }
  });

  saveBtn.addEventListener('click', async () => {
    const url = serverInput.value.trim().replace(/\/$/, '');
    const tok = tokenInput.value.trim();

    if (!url) { showStatus('Server URL is required', true); return; }
    if (!tok)  { showStatus('API token is required', true); return; }

    await chrome.storage.local.set({ server_url: url, api_token: tok, complexity: comp, comment_level: cmt, last_error: '' });

    const prevLabel = saveBtn.textContent;
    saveBtn.textContent = 'Saved ✓';
    setTimeout(() => { saveBtn.textContent = prevLabel; }, 1600);

    statusEl.textContent = last_capture ? `Last capture: ${last_capture}` : '';
    statusEl.className = 'status ok';

    try {
      const resp = await fetch(`${url}/api/me`, { headers: { 'Authorization': `Bearer ${tok}` } });
      if (resp.ok) {
        const data = await resp.json();
        await chrome.storage.local.set({ is_unlimited: data.account_level === 'unlimited' });
      }
    } catch {}

    // Sync complexity + comment level to the server so they apply to audio/replay too
    try {
      await fetch(`${url}/api/settings/complexity`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${tok}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: comp }),
      });
    } catch {}

    try {
      await fetch(`${url}/api/settings/comment-level`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${tok}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: cmt }),
      });
    } catch {}
  });

  // ── Response style pills ───────────────────────────────────────────────────
  const stylePills = document.querySelectorAll('.pill');
  let activeStyle  = response_style || 'conversational';

  function applyStyleUI(style) {
    stylePills.forEach(p => p.classList.toggle('active', p.dataset.style === style));
  }
  applyStyleUI(activeStyle);

  stylePills.forEach(pill => {
    pill.addEventListener('click', async () => {
      const style = pill.dataset.style;
      if (style === activeStyle) return;
      activeStyle = style;
      applyStyleUI(style);
      await chrome.storage.local.set({ response_style: style });
      const { server_url: url, api_token: tok } = await chrome.storage.local.get(['server_url', 'api_token']);
      if (!url || !tok) return;
      try {
        await fetch(`${url}/api/settings/style`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${tok}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ style }),
        });
      } catch {}
    });
  });

  const grantMicBtn  = document.getElementById('grant_mic');
  const micSelect    = document.getElementById('mic-select');
  const micMeterBar  = document.getElementById('mic-meter-bar');
  const micMeterWrap = document.getElementById('mic-meter-wrap');
  const micPermDot   = document.getElementById('mic-perm-dot');
  const micTestBtn   = document.getElementById('mic-test-btn');

  const _mic = { stream: null, animId: null, ctx: null, testing: false };
  let _meterClass = '';
  let _smoothed   = 0;

  function stopMicPreview() {
    if (_mic.animId) { cancelAnimationFrame(_mic.animId); _mic.animId = null; }
    if (_mic.stream) { _mic.stream.getTracks().forEach(t => t.stop()); _mic.stream = null; }
    if (_mic.ctx)    { _mic.ctx.close().catch(() => {}); _mic.ctx = null; }
    _mic.testing    = false;
    _smoothed       = 0;
    micMeterBar.style.width = '0%';
    if (_meterClass) { micMeterBar.className = 'mic-meter-bar'; _meterClass = ''; }
    micMeterWrap.style.display = 'none';
    micTestBtn.textContent     = 'Test';
    micTestBtn.classList.remove('testing');
  }

  async function startMicPreview(deviceId) {
    stopMicPreview();
    const audio = deviceId ? { deviceId: { ideal: deviceId } } : true;
    try {
      _mic.stream = await navigator.mediaDevices.getUserMedia({ audio, video: false });
    } catch {
      return false;
    }
    _mic.testing           = true;
    micMeterWrap.style.display = '';
    micTestBtn.textContent     = 'Listening…';
    micTestBtn.classList.add('testing');

    _mic.ctx = new AudioContext();
    const src      = _mic.ctx.createMediaStreamSource(_mic.stream);
    const analyser = _mic.ctx.createAnalyser();
    analyser.fftSize = 256;
    src.connect(analyser);
    const data = new Uint8Array(analyser.frequencyBinCount);

    function tick() {
      _mic.animId = requestAnimationFrame(tick);
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i++) sum += (data[i] - 128) ** 2;
      const raw = Math.min(1, Math.sqrt(sum / data.length) / 36);
      // Asymmetric smoothing: fast attack, slow decay
      _smoothed = raw > _smoothed
        ? raw * 0.5  + _smoothed * 0.5
        : raw * 0.08 + _smoothed * 0.92;
      micMeterBar.style.width = (_smoothed * 100).toFixed(1) + '%';
      // Only update class on threshold crossings to avoid constant repaints
      const next = _smoothed > 0.72 ? 'hot' : _smoothed > 0.22 ? 'active' : '';
      if (next !== _meterClass) {
        _meterClass = next;
        micMeterBar.className = 'mic-meter-bar' + (next ? ' ' + next : '');
      }
    }
    tick();
    return true;
  }

  // Brief stream to unlock device labels, then immediately stop
  async function enumerateDevices() {
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    } catch { return []; }
    const devices = await navigator.mediaDevices.enumerateDevices();
    stream.getTracks().forEach(t => t.stop());
    return devices.filter(d => d.kind === 'audioinput' && d.deviceId && d.deviceId !== 'default');
  }

  async function populateMicDevices(selectedId) {
    const inputs = await enumerateDevices();
    micSelect.innerHTML = '<option value="">Default microphone</option>';
    inputs.forEach((d, i) => {
      const opt = document.createElement('option');
      opt.value       = d.deviceId;
      opt.textContent = d.label || `Microphone ${i + 1}`;
      if (d.deviceId === selectedId) opt.selected = true;
      micSelect.appendChild(opt);
    });
  }

  async function initMicSection() {
    const { mic_device_id } = await chrome.storage.local.get(['mic_device_id']);
    let permState = 'prompt';
    try {
      const perm = await navigator.permissions.query({ name: 'microphone' });
      permState = perm.state;
    } catch {}

    grantMicBtn.style.display = '';
    if (permState === 'granted') {
      await populateMicDevices(mic_device_id || '');
      micTestBtn.disabled        = false;
      micPermDot.className       = 'status-dot ok';
      grantMicBtn.textContent    = 'Microphone connected';
      grantMicBtn.className      = 'btn ghost small full connected';
      grantMicBtn.disabled       = true;
    } else {
      micTestBtn.disabled        = true;
      micPermDot.className       = permState === 'denied' ? 'status-dot err' : 'status-dot';
      grantMicBtn.textContent    = 'Grant mic permission';
      grantMicBtn.className      = 'btn ghost small full';
      grantMicBtn.disabled       = false;
    }
  }

  micTestBtn.addEventListener('click', async () => {
    if (_mic.testing) {
      stopMicPreview();
    } else {
      const { mic_device_id } = await chrome.storage.local.get(['mic_device_id']);
      await startMicPreview(mic_device_id || null);
    }
  });

  micSelect.addEventListener('change', async () => {
    const deviceId = micSelect.value || '';
    await chrome.storage.local.set({ mic_device_id: deviceId });
    if (_mic.testing) await startMicPreview(deviceId || null);
  });

  grantMicBtn.addEventListener('click', () => {
    chrome.tabs.create({ url: chrome.runtime.getURL('grant-mic.html') });
  });

  window.addEventListener('unload', stopMicPreview);

  initMicSection();

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
  const replaySection   = document.getElementById('replay-section');
  const replayPill      = document.getElementById('replay-pill');
  const replayWinReadout = document.getElementById('replay-window-readout');
  const replaySlider    = document.getElementById('replay-window-slider');
  const lockRow         = document.getElementById('replay-lock-row');
  const lockedRow       = document.getElementById('replay-locked-row');
  const lockedTabEl     = document.getElementById('replay-locked-tab');
  const lockBtn         = document.getElementById('replay-lock-btn');
  const unlockBtn       = document.getElementById('replay-unlock-btn');

  function updateReplayWindowUI(secs) {
    replaySlider.value = secs;
    const clamped = Number(replaySlider.value); // native range input clamps to min/max
    replayWinReadout.textContent = `${clamped}s`;
    return clamped;
  }

  // The popup only has a Bearer token, not the cookie session /api/settings/replay needs, so
  // it syncs the window seconds through the Bearer-authed counterpart instead — otherwise this
  // change would live only in chrome.storage.local and get clobbered the next time anything
  // (e.g. opening Settings) re-syncs account settings down from the server.
  function syncReplayWindowToServer(secs) {
    chrome.storage.local.get(['server_url', 'api_token'], ({ server_url: url, api_token: tok }) => {
      if (!url || !tok) return;
      fetch(`${url}/api/settings/replay-window`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${tok}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ seconds: secs }),
      }).catch(() => {});
    });
  }

  // Unset means the settings sync hasn't landed yet (fresh install, or a service worker
  // that hasn't run fetchAccountLevel since). The server default is on, so match it —
  // otherwise the replay card is invisible on a new install until the first sync, which
  // reads as "instant replay isn't available" rather than "not loaded yet".
  if (replay_enabled !== false) {
    replaySection.style.display = 'flex';
    updateReplayWindowUI(replay_seconds || 15);
  }

  // Live-update if the setting changes while the popup happens to be open
  // (e.g. toggled on Settings in another tab) — otherwise this only ever
  // reflects whatever was true the moment the popup was opened.
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local') return;
    if (changes.replay_enabled) {
      replaySection.style.display = changes.replay_enabled.newValue ? 'flex' : 'none';
    }
    if (changes.replay_seconds) {
      updateReplayWindowUI(changes.replay_seconds.newValue || 15);
    }
  });

  // 'input' fires continuously while dragging — keep local storage current (background.js
  // reads it fresh whenever the lock button is pressed) without hammering the server.
  replaySlider.addEventListener('input', () => {
    const clamped = updateReplayWindowUI(replaySlider.value);
    chrome.storage.local.set({ replay_seconds: clamped });
  });

  // 'change' fires once the drag settles — that's when it's worth a network round trip.
  replaySlider.addEventListener('change', () => {
    const clamped = updateReplayWindowUI(replaySlider.value);
    syncReplayWindowToServer(clamped);
  });

  function applyReplayStatus(status) {
    if (!status) return;
    const { state, tabTitle } = status;
    replayPill.className = 'badge ' + state;
    if (state === 'idle') {
      replayPill.textContent = 'Idle';
      lockBtn.textContent    = 'Lock to this tab';
      lockRow.style.display   = '';
      lockedRow.style.display = 'none';
    } else if (state === 'arming') {
      replayPill.textContent  = 'Filling buffer…';
      lockedTabEl.textContent = tabTitle || 'this tab';
      lockRow.style.display   = 'none';
      lockedRow.style.display = 'flex';
    } else if (state === 'armed') {
      replayPill.textContent  = 'Buffer ready';
      lockedTabEl.textContent = tabTitle || 'Unknown tab';
      lockRow.style.display   = 'none';
      lockedRow.style.display = 'flex';
    } else if (state === 'stream-ended') {
      replayPill.textContent = 'Stream lost';
      lockBtn.textContent    = 'Re-lock to a tab';
      lockRow.style.display   = '';
      lockedRow.style.display = 'none';
    } else if (state === 'error') {
      replayPill.textContent = 'Error — re-lock';
      lockBtn.textContent    = 'Lock to this tab';
      lockRow.style.display   = '';
      lockedRow.style.display = 'none';
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
    const { replay_seconds: secs } = await chrome.storage.local.get(['replay_seconds']);
    chrome.runtime.sendMessage({ type: 'replay-lock', tabId: tab.id, windowSec: secs || 10 });
  });

  unlockBtn.addEventListener('click', () => {
    chrome.runtime.sendMessage({ type: 'replay-unlock' });
  });
});
