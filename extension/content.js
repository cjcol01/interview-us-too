// Screen capture + AI analysis content script
// Runs only on https://interview-wise.com/* (see manifest.json).
// Hotkey detection has moved to manifest commands (background.js).
// This script handles the DOM-event bridge and typing-mode character buffering.

if (window._scapCtrl) window._scapCtrl.abort();
const ac = new AbortController();
window._scapCtrl = ac;

// If the extension context has been invalidated (e.g. after an extension update while
// this tab was open), every chrome.* call below would throw synchronously, meaning no
// listeners would ever be registered and the page would silently stop working.
// Signal the page first so it can show a "reload to reconnect" prompt, then abort.
try {
  void chrome.runtime.id;
} catch {
  document.dispatchEvent(new CustomEvent('scap:ext-stale'));
  throw new Error('[scap] Extension context invalidated — reload the page to reconnect.');
}

function _checkExtContext() {
  try { void chrome.runtime.id; } catch {
    document.dispatchEvent(new CustomEvent('scap:ext-stale'));
  }
}

// Wrappers for chrome.* calls that silences both synchronous throws (invalidated
// extension context) and async rejections (port closed / no listener / storage error).
function _safeSend(msg) {
  try { chrome.runtime.sendMessage(msg).catch(() => {}); } catch {}
}
function _safeGet(keys) {
  try { return chrome.storage.local.get(keys).catch(() => ({})); } catch { return Promise.resolve({}); }
}
function _safeSet(obj) {
  try { chrome.storage.local.set(obj).catch(() => {}); } catch {}
}
const handleVisibilityChange = () => { if (!document.hidden) _checkExtContext(); };
document.addEventListener('visibilitychange', handleVisibilityChange, { signal: ac.signal });
window.addEventListener('focus', _checkExtContext, { signal: ac.signal });

function showDisabledToast() {
  if (!window.location.pathname.startsWith('/app')) return;
  document.getElementById('_scap_disabled_toast')?.remove();
  const el = document.createElement('div');
  el.id = '_scap_disabled_toast';
  el.textContent = 'Extension is disabled — use the toggle shortcut (Ctrl+Shift+1 by default) or the popup to enable';
  Object.assign(el.style, {
    position: 'fixed', bottom: '24px', right: '24px', zIndex: '2147483647',
    background: '#1e1e1e', color: '#fff', padding: '10px 16px', borderRadius: '8px',
    fontSize: '14px', fontFamily: 'sans-serif', boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
    opacity: '1', transition: 'opacity 0.3s',
  });
  document.body.appendChild(el);
  const removeDisabledToastEl = () => el.remove();
  const fadeOutDisabledToast = () => { el.style.opacity = '0'; setTimeout(removeDisabledToastEl, 300); };
  setTimeout(fadeOutDisabledToast, 3000);
}

function showRateLimitToast(message) {
  if (!window.location.pathname.startsWith('/app')) return;
  const id = '_scap_ratelimit_toast';
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
  const removeRateLimitToastEl = () => el.remove();
  const fadeOutRateLimitToast = () => { el.style.opacity = '0'; setTimeout(removeRateLimitToastEl, 300); };
  setTimeout(fadeOutRateLimitToast, 4000);
}

const _onMessage = (msg) => {
  if (msg.type === 'toggled') {
    document.dispatchEvent(new CustomEvent('scap:toggled', { detail: { enabled: msg.enabled } }));
  } else if (msg.type === 'show-disabled') {
    showDisabledToast();
  } else if (msg.type === 'show-rate-limit') {
    showRateLimitToast(msg.message);
  } else if (msg.type === 'replay-buffer-empty') {
    showRateLimitToast('Replay buffer warming up — wait a moment and try again.');
  } else if (msg.type === 'typing-command') {
    // Background forwarded the manifest command — toggle typing mode.
    if (_typingActive) {
      _typingActive = false;
      const text = _typingBuffer;
      _typingBuffer = '';
      _safeSend({ type: 'typing-submit', text });
    } else {
      _typingActive = true;
      _typingBuffer = '';
      _safeSend({ type: 'typing-start' });
    }
  }
};
chrome.runtime.onMessage.addListener(_onMessage);
const cleanupOnMessageListener = () => { try { chrome.runtime.onMessage.removeListener(_onMessage); } catch {} };
ac.signal.addEventListener('abort', cleanupOnMessageListener);

const handlePassthroughChange = (e) => {
  _safeSet({ typing_passthrough: e.detail.enabled });
};
document.addEventListener('scap:passthrough', handlePassthroughChange, { signal: ac.signal });

const handleTypingPreviewChange = (e) => {
  _safeSet({ typing_preview: e.detail.enabled });
};
document.addEventListener('scap:typing-preview', handleTypingPreviewChange, { signal: ac.signal });

const handleReplaySettingsChange = (e) => {
  const { enabled, seconds } = e.detail;
  _safeSet({ replay_enabled: enabled, replay_seconds: seconds });
};
document.addEventListener('scap:replay', handleReplaySettingsChange, { signal: ac.signal });

// On /app and /support: push replay + mic + enabled status changes into the page as custom
// events. Unlike the 'toggled' message (sent only to whichever tab issued the toggle), this
// covers every tab showing these pages regardless of where the extension was actually
// toggled — hotkey, popup, or another tab entirely — since it's driven by storage.onChanged.
// /onboarding is in this list because its audio step shows live mic and instant-replay state
// while the user grants permission and locks a tab — without it those pushes never reach the
// page and the step can't tell whether anything worked.
if (window.location.pathname.startsWith('/app') || window.location.pathname.startsWith('/support')
    || window.location.pathname.startsWith('/onboarding')) {
  const onInitialStatusLoaded = ({ replay_status, mic_status, enabled }) => {
    if (replay_status) {
      document.dispatchEvent(new CustomEvent('scap:replay-status', { detail: replay_status }));
    }
    if (mic_status) {
      document.dispatchEvent(new CustomEvent('scap:mic-status', { detail: mic_status }));
    }
    document.dispatchEvent(new CustomEvent('scap:enabled-status', { detail: { enabled: enabled ?? false } }));
  };
  _safeGet(['replay_status', 'mic_status', 'enabled']).then(onInitialStatusLoaded).catch(() => {});
  const handleStorageChangedForPage = (changes, area) => {
    try {
      if (area !== 'local') return;
      if (changes.replay_status?.newValue) {
        document.dispatchEvent(new CustomEvent('scap:replay-status', {
          detail: changes.replay_status.newValue,
        }));
      }
      if (changes.mic_status?.newValue) {
        document.dispatchEvent(new CustomEvent('scap:mic-status', {
          detail: changes.mic_status.newValue,
        }));
      }
      if (changes.enabled?.newValue !== undefined) {
        document.dispatchEvent(new CustomEvent('scap:enabled-status', {
          detail: { enabled: changes.enabled.newValue },
        }));
      }
    } catch {}
  };
  chrome.storage.onChanged.addListener(handleStorageChangedForPage);
}

// Read-only presence/link check — unlike scap:connect, never writes to storage,
// so it's safe to fire from any page without risking clobbering a real stored token.
const handlePing = () => {
  try {
    const onPingStorageLoaded = ({ server_url, api_token }) => {
      // Deliberately not checking server_url === window.location.origin: captures always
      // go to the stored server_url regardless of which host the current tab is on (e.g.
      // 127.0.0.1 vs localhost are different origins but the same server), so requiring
      // an exact match here just produced false "not connected" reports.
      const linked = !!(server_url && api_token);
      let version;
      try { version = chrome.runtime.getManifest().version; } catch {}
      document.dispatchEvent(new CustomEvent('scap:pong', { detail: { linked, version } }));
    };
    _safeGet(['server_url', 'api_token']).then(onPingStorageLoaded).catch(() => {});
  } catch {}
};
document.addEventListener('scap:ping', handlePing, { signal: ac.signal });

// Retrieve the actual Chrome-assigned keyboard shortcuts and broadcast them to the page.
// Called on load (so settings/app pages populate immediately) and on explicit request.
function _sendHotkeysToPPage() {
  try {
    const onCommandsReceived = (cmds) => {
      if (!cmds) return;
      document.dispatchEvent(new CustomEvent('scap:hotkeys', { detail: cmds }));
    };
    chrome.runtime.sendMessage({ type: 'get-commands' })
      .then(onCommandsReceived)
      .catch(() => {});
  } catch {}
}
_sendHotkeysToPPage();
document.addEventListener('scap:get-hotkeys', _sendHotkeysToPPage, { signal: ac.signal });

const handleMicCheck = () => {
  _safeSend({ type: 'check-mic-permission' });
};
document.addEventListener('scap:mic-check', handleMicCheck, { signal: ac.signal });

// Distinct from mic-check, which only *queries* — the offscreen document is headless and can't
// show a permission prompt, so asking for the permission means opening grant-mic.html as a real
// tab. Until this existed the only way to reach that prompt was to fail a real capture, i.e. to
// find out your mic was blocked by pressing the hotkey during active use.
const handleMicGrant = () => {
  _safeSet({ _open_mic_grant_ts: Date.now() });
};
document.addEventListener('scap:mic-grant', handleMicGrant, { signal: ac.signal });

// The extension's mic permission lives at its own chrome-extension://<id> origin, which only
// this content script can look up (chrome.runtime.id isn't available to a regular page) — used
// by the support page's "Mic silent" card to link straight to the right settings entry instead
// of the generic microphone list, where it'd show up as an unlabeled chrome-extension:// origin
// among ordinary websites.
const handleMicSettingsLink = () => {
  try {
    const url = 'chrome://settings/content/siteDetails?site='
      + encodeURIComponent('chrome-extension://' + chrome.runtime.id + '/');
    document.dispatchEvent(new CustomEvent('scap:mic-settings-link-result', { detail: { url } }));
  } catch {}
};
document.addEventListener('scap:mic-settings-link', handleMicSettingsLink, { signal: ac.signal });

const handleEnable = () => {
  // Only honour enable requests from the stored server's own origin — any arbitrary
  // page can dispatch DOM events, so without this check a malicious site could
  // silently arm the extension while the user is browsing elsewhere.
  const onEnableStorageLoaded = ({ server_url }) => {
    if (!server_url) return;
    try { if (new URL(server_url).origin !== window.location.origin) return; } catch { return; }
    _safeSend({ type: 'force-enable' });
  };
  _safeGet(['server_url']).then(onEnableStorageLoaded).catch(() => {});
};
document.addEventListener('scap:enable', handleEnable, { signal: ac.signal });

const handleConnect = (e) => {
  const { token, serverUrl } = e.detail;
  // Origin guard: if a server is already stored, only the page at that origin may
  // update credentials. First-time installs (nothing stored yet) are allowed through
  // so the onboarding flow can set the token without the user already being connected.
  // Exception: 127.0.0.1 and localhost are local dev addresses — unreachable from
  // the public internet — so they may always override even if prod is already stored.
  const onCredentialsSaved = () => {
    _safeSend({ type: 'sync-account' });
    document.dispatchEvent(new CustomEvent('scap:connected'));
  };
  const onConnectStorageLoaded = ({ server_url }) => {
    if (server_url) {
      try {
        const isLocalDev = /^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(window.location.origin);
        if (!isLocalDev && new URL(server_url).origin !== window.location.origin) return;
      } catch { return; }
    }
    // The background service worker only pulls account settings (replay,
    // complexity, etc.) from the server once, at its own startup —
    // which happens before a fresh install has a token to sync with. Ask it
    // to sync now that one actually exists, or those settings stay empty
    // until the service worker happens to restart for an unrelated reason.
    try {
      chrome.storage.local.set({ api_token: token, server_url: serverUrl })
        .then(onCredentialsSaved)
        .catch(() => {});
    } catch {}
  };
  _safeGet(['server_url']).then(onConnectStorageLoaded).catch(() => {});
};
document.addEventListener('scap:connect', handleConnect, { signal: ac.signal });

// ---------------------------------------------------------------------------
// Typing mode — character buffering, initiated by the 'typing-command' message
// from background.js (manifest command). The actual start/stop toggle lives in
// the _onMessage handler above; this listener only runs while typing is active.
// ---------------------------------------------------------------------------

let _typingActive = false;
let _typingBuffer = '';
let _passthrough = true;

const onPassthroughLoaded = (r) => {
  if (r.typing_passthrough !== undefined) _passthrough = r.typing_passthrough;
};
_safeGet(['typing_passthrough']).then(onPassthroughLoaded).catch(() => {});

const handlePassthroughStorageChange = (changes) => {
  try {
    if (changes.typing_passthrough?.newValue !== undefined) _passthrough = changes.typing_passthrough.newValue;
  } catch {}
};
chrome.storage.onChanged.addListener(handlePassthroughStorageChange);

// Is the keystroke going somewhere that will actually consume it (a text box, a code editor)?
// Only used to decide whether a Space in typing mode would scroll the page instead of typing.
function typesIntoTarget(el) {
  // Walk into shadow roots: editors like Monaco/CodeMirror retarget the event to their host
  // element, so the real focused text box is one (or more) shadow boundaries down.
  while (el) {
    const tag = el.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable === true) return true;
    el = el.shadowRoot?.activeElement;
  }
  return false;
}

// TYPING MODE NOTE: this listener intercepts keystrokes only when the user has manually
// activated typing mode via the typing hotkey (_typingActive === true). In all other
// states every keystroke passes through completely unobserved.
const handleTypingModeKeydown = (e) => {
  if (!_typingActive) return;

  // Enter ends capture and submits — it never appears in the buffer or on the page.
  if (e.key === 'Enter') {
    e.preventDefault();
    e.stopPropagation();
    _typingActive = false;
    const text = _typingBuffer;
    _typingBuffer = '';
    _safeSend({ type: 'typing-submit', text });
    return;
  }
  // Escape abandons the capture — buffer discarded, nothing sent.
  if (e.key === 'Escape') {
    e.preventDefault();
    e.stopPropagation();
    _typingActive = false;
    _typingBuffer = '';
    _safeSend({ type: 'typing-cancel' });
    return;
  }
  if (e.key === 'Backspace') {
    _typingBuffer = _typingBuffer.slice(0, -1);
  } else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
    _typingBuffer += e.key;
  } else {
    return;  // navigation/modifier keys: ignore and let them pass through
  }
  // .catch: the router answers nothing, so MV3 rejects the send promise with "message port
  // closed". Harmless, but unhandled it floods the page console on every keystroke.
  _safeSend({ type: 'typing-preview', text: _typingBuffer });
  if (!_passthrough) { e.preventDefault(); e.stopPropagation(); }
  // Passthrough deliberately lets keystrokes reach the page, but Space's page default is
  // "scroll down a screen" whenever focus isn't in a text field — so typing with
  // the editor unfocused would scroll the page down a paragraph per word.
  // Swallow only that default; the character is already in the buffer either way.
  else if (e.code === 'Space' && !typesIntoTarget(e.target) && !typesIntoTarget(document.activeElement)) e.preventDefault();
};
document.addEventListener('keydown', handleTypingModeKeydown, { capture: true, signal: ac.signal });

const handleTypingModePaste = (e) => {
  if (!_typingActive) return;
  const pasted = (e.clipboardData || window.clipboardData)?.getData('text') || '';
  if (!pasted) return;
  _typingBuffer += pasted;
  // .catch: see above.
  _safeSend({ type: 'typing-preview', text: _typingBuffer });
  if (!_passthrough) { e.preventDefault(); e.stopPropagation(); }
};
document.addEventListener('paste', handleTypingModePaste, { capture: true, signal: ac.signal });
