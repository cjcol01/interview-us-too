document.addEventListener('DOMContentLoaded', async () => {
  const { server_url, api_token, complexity, last_capture, last_error } =
    await chrome.storage.local.get(['server_url', 'api_token', 'complexity', 'last_capture', 'last_error']);

  const serverInput   = document.getElementById('server_url');
  const tokenInput    = document.getElementById('api_token');
  const toggleBtn     = document.getElementById('toggle_token');
  const complexityVal = document.getElementById('complexity_val');
  const saveBtn       = document.getElementById('save');
  const statusEl      = document.getElementById('status');

  if (server_url) serverInput.value = server_url;
  if (api_token)  tokenInput.value  = api_token;

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
  });

  chrome.storage.onChanged.addListener((changes) => {
    if (changes.last_capture) showStatus(`Last capture: ${changes.last_capture.newValue}`);
    if (changes.last_error?.newValue) showStatus(changes.last_error.newValue, true);
  });
});
