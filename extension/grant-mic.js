const statusEl   = document.getElementById('status');
const deniedHelp = document.getElementById('denied-help');
const copyBtn    = document.getElementById('copy-settings-link');
const retryBtn   = document.getElementById('retry-btn');

// Re-runs the permission check — used for the first load, the manual "Refresh" button, and
// the automatic re-check when the user switches back to this tab after fixing the setting
// in chrome://settings (see the visibilitychange listener below). A fresh getUserMedia() call
// picks up a just-granted permission immediately — no actual page reload is needed.
let _checkingMic = false;
function requestMic() {
  if (_checkingMic) return;
  _checkingMic = true;
  retryBtn.disabled = true;
  statusEl.textContent = 'Checking...';
  statusEl.className = 'status';

  navigator.mediaDevices.getUserMedia({ audio: true, video: false })
    .then(function onMicGranted(stream) {
      stream.getTracks().forEach(t => t.stop());
      deniedHelp.classList.add('hidden');
      statusEl.textContent = 'Permission granted — you can close this tab.';
      statusEl.className = 'status ok';
      // Tell the background worker directly rather than leaving it to re-query later: this
      // reuses the handler that keeps _micState, storage and the server's ext-status in step,
      // and it means any open /onboarding or /app tab flips to "granted" while this tab is
      // still on screen instead of only once it regains focus.
      chrome.runtime.sendMessage({ type: 'mic-permission-result', state: 'granted' });
      setTimeout(function closeTabAfterDelay() { window.close(); }, 1500);
    })
    .catch(function onMicDenied(e) {
      statusEl.textContent = 'Denied: ' + e.message;
      statusEl.className = 'status err';
      // Blocked outright (vs. e.g. no mic device found) — this is almost always because the
      // extension's own chrome-extension:// origin got blocked on a past prompt, not a normal
      // per-website setting, so point straight at the one settings page that actually fixes it.
      if (e.name === 'NotAllowedError') deniedHelp.classList.remove('hidden');
      _checkingMic = false;
      retryBtn.disabled = false;
    });
}

requestMic();

retryBtn.addEventListener('click', requestMic);

// Auto re-check as soon as the user switches back to this tab, so they don't have to
// remember to click "Refresh" after fixing the setting in chrome://settings. Scoped to only
// fire while the denied-help flow is showing, so it doesn't re-prompt after success (the tab
// is already closing) or spam getUserMedia on every tab switch for unrelated error types.
function handleVisibilityChange() {
  if (document.visibilityState === 'visible' && !deniedHelp.classList.contains('hidden')) {
    requestMic();
  }
}
document.addEventListener('visibilitychange', handleVisibilityChange);

// chrome:// URLs can't be linked to directly from a page — Chrome silently refuses to
// navigate to them — so this is copy-to-clipboard instead of a real <a href>.
const settingsUrl = 'chrome://settings/content/siteDetails?site='
  + encodeURIComponent('chrome-extension://' + chrome.runtime.id + '/');

function handleCopyClick() {
  navigator.clipboard.writeText(settingsUrl).then(function onCopySuccess() {
    const original = copyBtn.textContent;
    copyBtn.textContent = '✓ Copied — paste into a new tab';
    copyBtn.classList.add('copied');
    setTimeout(function restoreCopyButton() { copyBtn.textContent = original; copyBtn.classList.remove('copied'); }, 2000);
  });
}
copyBtn.addEventListener('click', handleCopyClick);

// server_url is only known once the extension's been connected to an account — if this fires
// before that (unlikely, but possible on a very fresh install) the link just stays hidden.
chrome.storage.local.get(['server_url'], function onServerUrlLoaded({ server_url }) {
  if (!server_url) return;
  const supportLink = document.getElementById('support-link');
  supportLink.href = server_url.replace(/\/$/, '') + '/support#issue-1';
  supportLink.classList.remove('hidden');
});
