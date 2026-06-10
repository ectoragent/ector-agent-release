// #region agent log
export function debugSessionLog(location, message, data, hypothesisId, runId = 'pre-fix') {
  fetch('http://127.0.0.1:7942/ingest/87fa9e4b-a416-4933-9cfd-a9f0ed917b76', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Debug-Session-Id': '9e46c8'
    },
    body: JSON.stringify({
      sessionId: '9e46c8',
      location,
      message,
      data,
      hypothesisId,
      runId,
      timestamp: Date.now()
    })
  }).catch(() => {});
}
// #endregion