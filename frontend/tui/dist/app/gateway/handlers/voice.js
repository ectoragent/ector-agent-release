export function handleVoiceStatus(ev, api) {
  const state = String(ev.payload?.state ?? '');
  if (state === 'listening') {
    api.setVoiceRecording(true);
    api.setVoiceProcessing(false);
  } else if (state === 'transcribing') {
    api.setVoiceRecording(false);
    api.setVoiceProcessing(true);
  } else {
    api.setVoiceRecording(false);
    api.setVoiceProcessing(false);
  }
}
export function handleVoiceTranscript(ev, api) {
  const p = ev.payload;
  if (p?.no_speech_limit) {
    api.setVoiceEnabled(false);
    api.setVoiceRecording(false);
    api.setVoiceProcessing(false);
    api.sys('voice: no speech detected 3 times, continuous mode stopped');
    return;
  }
  const text = String(p?.text ?? '').trim();
  if (!text) {
    return;
  }
  api.setInput('');
  setTimeout(() => api.submitRef.current(text), 0);
}