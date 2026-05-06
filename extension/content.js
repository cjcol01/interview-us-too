document.addEventListener('interview-ace:connect', (e) => {
  const { token, serverUrl } = e.detail;
  chrome.storage.local.set({ api_token: token, server_url: serverUrl }, () => {
    document.dispatchEvent(new CustomEvent('interview-ace:connected'));
  });
});
