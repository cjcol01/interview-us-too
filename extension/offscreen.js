let mediaRecorder = null;
let chunks = [];
let stream = null;

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === 'start-recording') {
    startRecording();
  } else if (msg.type === 'stop-recording') {
    stopRecording();
  }
});

async function startRecording() {
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
  } catch (e) {
    chrome.runtime.sendMessage({ type: 'audio-error', error: e.message });
    return;
  }

  chunks = [];
  mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });

  mediaRecorder.ondataavailable = (e) => {
    if (e.data.size > 0) chunks.push(e.data);
  };

  mediaRecorder.onstop = () => {
    const blob = new Blob(chunks, { type: 'audio/webm' });
    const reader = new FileReader();
    reader.onloadend = () => {
      const base64 = reader.result.split(',')[1];
      chrome.runtime.sendMessage({ type: 'audio-data', base64, mimeType: 'audio/webm' });
    };
    reader.readAsDataURL(blob);
    stream.getTracks().forEach(t => t.stop());
    stream = null;
    mediaRecorder = null;
    chunks = [];
  };

  mediaRecorder.start();
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();
  }
}
