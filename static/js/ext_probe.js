/* Shared extension probe.
 *
 * One detection layer for every page that reports extension state: the check rows on
 * /support, the status dots on /app, and the connection row in Settings. Lifted from
 * /support, which was the only one that got this right — the others each rolled their own
 * and drifted (Settings detected presence with a *write*, and never re-checked; /app only
 * asked once at page load).
 *
 * What it does NOT do: render. Pages subscribe and draw their own UI from the state, since
 * a dot, a check row and a connection banner want different words for the same facts.
 *
 * Transport is the content script's read-only DOM events — `scap:ping` answered by
 * `scap:pong`. Never `scap:connect`: that one WRITES the token into
 * extension storage, so using it as a presence check silently repoints the extension at
 * whatever origin the page happens to be served from.
 *
 * State fields:
 *   detected  true | false | null   extension's content script answered (null = still asking)
 *   linked    true | false | null   ...and has a stored account token
 *   enabled   true | false | null   armed (pushed live via storage.onChanged)
 *   version   string | null         manifest version from the pong
 *   mic       'granted' | 'denied' | 'prompt' | 'error' | 'unknown' | null
 *   replay    'armed' | 'arming' | 'error' | 'stream-ended' | 'idle' | null
 */
(function () {
  'use strict';

  // The content script injects at document_idle, which can land *after* an inline page
  // script has already run — a single dispatch is lost with no answer ever coming back.
  const RETRY_MS   = 200;
  const RETRY_MAX  = 6;
  const ANSWER_MS  = 1500;   // no pong by now → treat as not detected
  const RECHECK_MS = 10000;  // periodic re-ask, so a dot can't keep lying after a change

  const state = {
    detected: null, linked: null, enabled: null,
    version: null, mic: null, replay: null,
  };

  const subscribers = [];
  let pongSeen = false;
  let micSeen = false;
  let extTimer = null;
  let micTimer = null;
  let started = false;

  function emit() {
    const snapshot = Object.assign({}, state);
    subscribers.forEach((fn) => {
      // One page's rendering bug must not stop the others from updating.
      try { fn(snapshot); } catch (err) { console.error('[ext-probe] subscriber failed', err); }
    });
  }

  function retryDispatch(eventName, isSeen) {
    let attempts = 0;
    document.dispatchEvent(new CustomEvent(eventName));
    const timer = setInterval(() => {
      if (isSeen() || ++attempts >= RETRY_MAX) { clearInterval(timer); return; }
      document.dispatchEvent(new CustomEvent(eventName));
    }, RETRY_MS);
    return timer;
  }

  document.addEventListener('scap:pong', (e) => {
    pongSeen = true;
    clearTimeout(extTimer);
    state.detected = true;
    state.linked  = !!(e.detail && e.detail.linked);
    state.version = (e.detail && e.detail.version) || null;
    emit();
  });

  document.addEventListener('scap:enabled-status', (e) => {
    state.enabled = !!(e.detail && e.detail.enabled);
    emit();
  });

  document.addEventListener('scap:mic-status', (e) => {
    micSeen = true;
    clearTimeout(micTimer);
    state.mic = (e.detail && e.detail.state) || 'unknown';
    emit();
  });

  document.addEventListener('scap:replay-status', (e) => {
    state.replay = (e.detail && e.detail.state) || null;
    emit();
  });

  // Extension reloaded/updated while this tab was open: the content script's context is
  // dead, so nothing here can reach it until the page is reloaded. Report it rather than
  // waiting for a probe to time out.
  document.addEventListener('scap:ext-stale', () => {
    state.detected = false;
    state.linked = false;
    emit();
  });

  function probe() {
    pongSeen = false;
    micSeen = false;
    clearTimeout(extTimer);
    clearTimeout(micTimer);
    extTimer = setTimeout(() => {
      if (pongSeen) return;
      state.detected = false;
      state.linked = false;
      state.version = null;
      emit();
    }, ANSWER_MS);
    micTimer = setTimeout(() => {
      if (micSeen) return;
      state.mic = 'unknown';
      emit();
    }, ANSWER_MS);
    retryDispatch('scap:ping', () => pongSeen);
    // Mic permission is never pushed on its own — unlike ext/enabled state, nothing writes
    // to storage when the browser-level permission changes. It only ever arrives in answer
    // to an explicit ask, which is why a page that asks once shows a stale value forever.
    retryDispatch('scap:mic-check', () => micSeen);
  }

  window.IAExtProbe = {
    /** Register a render callback. Fires immediately with the current state if already started. */
    subscribe(fn) {
      subscribers.push(fn);
      if (started) fn(Object.assign({}, state));
    },
    /** Re-ask now (page focus, a "Run diagnostics" button, after connecting). */
    probe,
    /** The document_idle workaround on its own, for one-off asks like the mic-settings link. */
    retryDispatch,
    /** Begin probing. `autoRecheck: false` for pages that drive their own cadence. */
    start(opts) {
      if (started) return;
      started = true;
      probe();
      if (opts && opts.autoRecheck === false) return;
      setInterval(() => { if (!document.hidden) probe(); }, RECHECK_MS);
      document.addEventListener('visibilitychange', () => { if (!document.hidden) probe(); });
      window.addEventListener('focus', probe);
    },
    get state() { return Object.assign({}, state); },
  };
})();
