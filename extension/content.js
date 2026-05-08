document.addEventListener('interview-ace:connect', (e) => {
  const { token, serverUrl } = e.detail;
  chrome.storage.local.set({ api_token: token, server_url: serverUrl }, () => {
    document.dispatchEvent(new CustomEvent('interview-ace:connected'));
  });
});

// Hold Ctrl+Shift+U to record audio; release to send
let _audioRecording = false;

document.addEventListener('keydown', (e) => {
  if (e.ctrlKey && e.shiftKey && e.code === 'KeyU' && !e.repeat && !_audioRecording) {
    _audioRecording = true;
    chrome.runtime.sendMessage({ type: 'audio-start' });
  }
}, true);

document.addEventListener('keyup', (e) => {
  if (e.code === 'KeyU' && _audioRecording) {
    _audioRecording = false;
    chrome.runtime.sendMessage({ type: 'audio-stop' });
  }
}, true);
