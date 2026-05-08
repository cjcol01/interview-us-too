document.addEventListener('interview-ace:connect', (e) => {
  const { token, serverUrl } = e.detail;
  chrome.storage.local.set({ api_token: token, server_url: serverUrl }, () => {
    document.dispatchEvent(new CustomEvent('interview-ace:connected'));
  });
});

let _audioRecording = false;

document.addEventListener('keydown', (e) => {
  const trigger = (e.ctrlKey || e.metaKey) && e.shiftKey && e.code === 'Digit8';
  if (trigger && !e.repeat && !_audioRecording) {
    _audioRecording = true;
    chrome.runtime.sendMessage({ type: 'audio-start' });
  }
}, true);

document.addEventListener('keyup', (e) => {
  if (!_audioRecording) return;
  const released = e.code === 'Digit8'
    || e.code === 'MetaLeft' || e.code === 'MetaRight'
    || e.code === 'ShiftLeft' || e.code === 'ShiftRight'
    || e.code === 'ControlLeft' || e.code === 'ControlRight';
  if (released) {
    _audioRecording = false;
    chrome.runtime.sendMessage({ type: 'audio-stop' });
  }
}, true);
