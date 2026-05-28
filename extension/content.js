if (window._iaceAbort) window._iaceAbort.abort();
const ac = new AbortController();
window._iaceAbort = ac;

function showDisabledToast() {
  if (!window.location.pathname.startsWith('/app')) return;
  document.getElementById('_iace_disabled_toast')?.remove();
  const el = document.createElement('div');
  el.id = '_iace_disabled_toast';
  el.textContent = `Extension is disabled — press ${_hotkeys.toggle} to enable`;
  Object.assign(el.style, {
    position: 'fixed', bottom: '24px', right: '24px', zIndex: '2147483647',
    background: '#1e1e1e', color: '#fff', padding: '10px 16px', borderRadius: '8px',
    fontSize: '14px', fontFamily: 'sans-serif', boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
    opacity: '1', transition: 'opacity 0.3s',
  });
  document.body.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }, 3000);
}

function showRateLimitToast(message) {
  if (!window.location.pathname.startsWith('/app')) return;
  const id = '_iace_ratelimit_toast';
  const existing = document.getElementById(id);
  if (existing) { existing.textContent = message; return; }
  const el = document.createElement('div');
  el.id = id;
  el.textContent = message;
  Object.assign(el.style, {
    position: 'fixed', bottom: '24px', right: '24px', zIndex: '2147483647',
    background: '#b45309', color: '#fff', padding: '10px 16px', borderRadius: '8px',
    fontSize: '14px', fontFamily: 'sans-serif', boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
    opacity: '1', transition: 'opacity 0.3s',
  });
  document.body.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }, 4000);
}

const _onMessage = (msg) => {
  if (msg.type === 'toggled') {
    document.dispatchEvent(new CustomEvent('interview-ace:toggled', { detail: { enabled: msg.enabled } }));
  } else if (msg.type === 'show-disabled') {
    showDisabledToast();
  } else if (msg.type === 'show-rate-limit') {
    showRateLimitToast(msg.message);
  } else if (msg.type === 'replay-buffer-empty') {
    showRateLimitToast('Replay buffer warming up — wait a moment and try again.');
  }
};
chrome.runtime.onMessage.addListener(_onMessage);
ac.signal.addEventListener('abort', () => chrome.runtime.onMessage.removeListener(_onMessage));

document.addEventListener('interview-ace:hotkeys', (e) => {
  const { capture, audio, toggle, replay, typing } = e.detail;
  chrome.storage.local.set({ hotkey_capture: capture, hotkey_audio: audio, hotkey_toggle: toggle, hotkey_replay: replay, hotkey_typing: typing });
}, { signal: ac.signal });

document.addEventListener('interview-ace:passthrough', (e) => {
  chrome.storage.local.set({ typing_passthrough: e.detail.enabled });
}, { signal: ac.signal });

document.addEventListener('interview-ace:replay', (e) => {
  const { enabled, seconds } = e.detail;
  chrome.storage.local.set({ replay_enabled: enabled, replay_seconds: seconds });
}, { signal: ac.signal });

document.addEventListener('interview-ace:replay-relock', () => {
  chrome.runtime.sendMessage({ type: 'replay-relock' });
}, { signal: ac.signal });

// On /app: push replay status changes into the page as custom events
if (window.location.pathname.startsWith('/app')) {
  chrome.storage.local.get(['replay_status'], ({ replay_status }) => {
    if (replay_status) {
      document.dispatchEvent(new CustomEvent('interview-ace:replay-status', { detail: replay_status }));
    }
  });
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && changes.replay_status?.newValue) {
      document.dispatchEvent(new CustomEvent('interview-ace:replay-status', {
        detail: changes.replay_status.newValue,
      }));
    }
  });
}

document.addEventListener('interview-ace:connect', (e) => {
  const { token, serverUrl } = e.detail;
  chrome.storage.local.set({ api_token: token, server_url: serverUrl }, () => {
    document.dispatchEvent(new CustomEvent('interview-ace:connected'));
  });
}, { signal: ac.signal });

const _hotkeys = { capture: 'Ctrl+Shift+7', audio: 'Ctrl+Shift+8', toggle: 'Ctrl+Shift+9', replay: 'Ctrl+Shift+6', typing: 'Ctrl+Shift+5' };
let _audioRecording = false;
let _typingActive = false;
let _typingBuffer = '';
let _passthrough = true;

chrome.storage.local.get(['hotkey_capture', 'hotkey_audio', 'hotkey_toggle', 'hotkey_replay', 'hotkey_typing', 'typing_passthrough'], (r) => {
  if (r.hotkey_capture) _hotkeys.capture = r.hotkey_capture;
  if (r.hotkey_audio)   _hotkeys.audio   = r.hotkey_audio;
  if (r.hotkey_toggle)  _hotkeys.toggle  = r.hotkey_toggle;
  if (r.hotkey_replay)  _hotkeys.replay  = r.hotkey_replay;
  if (r.hotkey_typing)  _hotkeys.typing  = r.hotkey_typing;
  if (r.typing_passthrough !== undefined) _passthrough = r.typing_passthrough;
});

const _onStorageChanged = (changes) => {
  if (changes.hotkey_capture?.newValue) _hotkeys.capture = changes.hotkey_capture.newValue;
  if (changes.hotkey_audio?.newValue)   _hotkeys.audio   = changes.hotkey_audio.newValue;
  if (changes.hotkey_toggle?.newValue)  _hotkeys.toggle  = changes.hotkey_toggle.newValue;
  if (changes.hotkey_replay?.newValue)  _hotkeys.replay  = changes.hotkey_replay.newValue;
  if (changes.hotkey_typing?.newValue)  _hotkeys.typing  = changes.hotkey_typing.newValue;
  if (changes.typing_passthrough?.newValue !== undefined) _passthrough = changes.typing_passthrough.newValue;
};
chrome.storage.onChanged.addListener(_onStorageChanged);
ac.signal.addEventListener('abort', () => chrome.storage.onChanged.removeListener(_onStorageChanged));

function parseHotkey(hotkey) {
  const parts = hotkey.toLowerCase().split('+').map(p => p.trim());
  const key = parts.find(p => !['ctrl', 'shift', 'alt'].includes(p)) || '';
  let code;
  if (/^\d$/.test(key))       code = 'Digit' + key;
  else if (/^[a-z]$/.test(key)) code = 'Key' + key.toUpperCase();
  else                           code = key;
  return { ctrl: parts.includes('ctrl'), shift: parts.includes('shift'), alt: parts.includes('alt'), code };
}

function matchesHotkey(e, hotkey) {
  const h = parseHotkey(hotkey);
  return (e.ctrlKey || e.metaKey) === h.ctrl
    && e.shiftKey === h.shift
    && e.altKey   === h.alt
    && e.code     === h.code;
}

document.addEventListener('keydown', (e) => {
  // Typing-mode toggle — checked first so it always stops capture, even mid-typing.
  if (matchesHotkey(e, _hotkeys.typing)) {
    if (e.repeat) return;
    e.preventDefault();
    e.stopPropagation();
    if (_typingActive) {
      _typingActive = false;
      const text = _typingBuffer;
      _typingBuffer = '';
      chrome.runtime.sendMessage({ type: 'typing-submit', text });
    } else {
      _typingActive = true;
      _typingBuffer = '';
      chrome.runtime.sendMessage({ type: 'typing-start' });
    }
    return;
  }

  // While typing mode is active, buffer keystrokes (basic fidelity: printable + Backspace).
  if (_typingActive) {
    // Enter ends capture and submits — it never appears in the buffer or on the page.
    if (e.key === 'Enter') {
      e.preventDefault();
      e.stopPropagation();
      _typingActive = false;
      const text = _typingBuffer;
      _typingBuffer = '';
      chrome.runtime.sendMessage({ type: 'typing-submit', text });
      return;
    }
    if (e.key === 'Backspace') {
      _typingBuffer = _typingBuffer.slice(0, -1);
    } else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      _typingBuffer += e.key;
    } else {
      return;  // navigation/modifier keys: ignore and let them pass through
    }
    if (!_passthrough) { e.preventDefault(); e.stopPropagation(); }
    return;
  }

  if (e.repeat) return;
  if (matchesHotkey(e, _hotkeys.audio) && !_audioRecording) {
    _audioRecording = true;
    chrome.runtime.sendMessage({ type: 'audio-start' });
  } else if (matchesHotkey(e, _hotkeys.capture)) {
    chrome.runtime.sendMessage({ type: 'capture' });
  } else if (matchesHotkey(e, _hotkeys.toggle)) {
    chrome.runtime.sendMessage({ type: 'toggle' });
  } else if (matchesHotkey(e, _hotkeys.replay)) {
    chrome.runtime.sendMessage({ type: 'replay-trigger' });
  }
}, { capture: true, signal: ac.signal });

document.addEventListener('keyup', (e) => {
  if (!_audioRecording) return;
  const h = parseHotkey(_hotkeys.audio);
  const released = e.code === h.code
    || e.code === 'MetaLeft'    || e.code === 'MetaRight'
    || e.code === 'ShiftLeft'   || e.code === 'ShiftRight'
    || e.code === 'ControlLeft' || e.code === 'ControlRight'
    || e.code === 'AltLeft'     || e.code === 'AltRight';
  if (released) {
    _audioRecording = false;
    chrome.runtime.sendMessage({ type: 'audio-stop' });
  }
}, { capture: true, signal: ac.signal });

document.addEventListener('paste', (e) => {
  if (!_typingActive) return;
  const pasted = (e.clipboardData || window.clipboardData)?.getData('text') || '';
  if (!pasted) return;
  _typingBuffer += pasted;
  if (!_passthrough) { e.preventDefault(); e.stopPropagation(); }
}, { capture: true, signal: ac.signal });
