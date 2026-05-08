const statusEl = document.getElementById('status');

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
  });
