if (window._iaceAbort) window._iaceAbort.abort();
const ac = new AbortController();
window._iaceAbort = ac;

function showDisabledToast() {
  if (document.getElementById('_iace_disabled_toast')) return;
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

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === 'toggled') {
    document.dispatchEvent(new CustomEvent('interview-ace:toggled', { detail: { enabled: msg.enabled } }));
  } else if (msg.type === 'show-disabled') {
    showDisabledToast();
  }
});

document.addEventListener('interview-ace:hotkeys', (e) => {
  const { capture, audio, toggle } = e.detail;
  chrome.storage.local.set({ hotkey_capture: capture, hotkey_audio: audio, hotkey_toggle: toggle });
});

document.addEventListener('interview-ace:connect', (e) => {
  const { token, serverUrl } = e.detail;
  chrome.storage.local.set({ api_token: token, server_url: serverUrl }, () => {
    document.dispatchEvent(new CustomEvent('interview-ace:connected'));
  });
});

const _hotkeys = { capture: 'Ctrl+Shift+7', audio: 'Ctrl+Shift+8', toggle: 'Ctrl+Shift+9' };
let _audioRecording = false;

chrome.storage.local.get(['hotkey_capture', 'hotkey_audio', 'hotkey_toggle'], (r) => {
  if (r.hotkey_capture) _hotkeys.capture = r.hotkey_capture;
  if (r.hotkey_audio)   _hotkeys.audio   = r.hotkey_audio;
  if (r.hotkey_toggle)  _hotkeys.toggle  = r.hotkey_toggle;
});

chrome.storage.onChanged.addListener((changes) => {
  if (changes.hotkey_capture?.newValue) _hotkeys.capture = changes.hotkey_capture.newValue;
  if (changes.hotkey_audio?.newValue)   _hotkeys.audio   = changes.hotkey_audio.newValue;
  if (changes.hotkey_toggle?.newValue)  _hotkeys.toggle  = changes.hotkey_toggle.newValue;
});

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
  if (e.repeat) return;
  if (matchesHotkey(e, _hotkeys.audio) && !_audioRecording) {
    _audioRecording = true;
    chrome.runtime.sendMessage({ type: 'audio-start' });
  } else if (matchesHotkey(e, _hotkeys.capture)) {
    chrome.runtime.sendMessage({ type: 'capture' });
  } else if (matchesHotkey(e, _hotkeys.toggle)) {
    chrome.runtime.sendMessage({ type: 'toggle' });
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
