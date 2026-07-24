const statusEl   = document.getElementById('status');
const deniedHelp = document.getElementById('denied-help');
const copyBtn    = document.getElementById('copy-settings-link');

navigator.mediaDevices.getUserMedia({ audio: true, video: false })
  .then(stream => {
    stream.getTracks().forEach(t => t.stop());
    statusEl.textContent = 'Permission granted — you can close this tab.';
    statusEl.className = 'status ok';
    setTimeout(() => window.close(), 1500);
  })
  .catch(e => {
    statusEl.textContent = 'Denied: ' + e.message;
    statusEl.className = 'status err';
    // Blocked outright (vs. e.g. no mic device found) — this is almost always because the
    // extension's own chrome-extension:// origin got blocked on a past prompt, not a normal
    // per-website setting, so point straight at the one settings page that actually fixes it.
    if (e.name === 'NotAllowedError') deniedHelp.classList.remove('hidden');
  });

// chrome:// URLs can't be linked to directly from a page — Chrome silently refuses to
// navigate to them — so this is copy-to-clipboard instead of a real <a href>.
const settingsUrl = 'chrome://settings/content/siteDetails?site='
  + encodeURIComponent('chrome-extension://' + chrome.runtime.id + '/');

copyBtn.addEventListener('click', () => {
  navigator.clipboard.writeText(settingsUrl).then(() => {
    const original = copyBtn.textContent;
    copyBtn.textContent = '✓ Copied — paste into a new tab';
    copyBtn.classList.add('copied');
    setTimeout(() => { copyBtn.textContent = original; copyBtn.classList.remove('copied'); }, 2000);
  });
});

// server_url is only known once the extension's been connected to an account — if this fires
// before that (unlikely, but possible on a very fresh install) the link just stays hidden.
chrome.storage.local.get(['server_url'], ({ server_url }) => {
  if (!server_url) return;
  const supportLink = document.getElementById('support-link');
  supportLink.href = server_url.replace(/\/$/, '') + '/support#issue-1';
  supportLink.classList.remove('hidden');
});
