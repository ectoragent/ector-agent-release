/** Debug-mode NDJSON logger (session 9e46c8). Remove after root-cause is verified. */
import { appendFileSync } from 'node:fs';
const ENDPOINT = 'http://127.0.0.1:7942/ingest/87fa9e4b-a416-4933-9cfd-a9f0ed917b76';
const SESSION = '9e46c8';
let seq = 0;
export function debugSessionLog(payload) {
  const line = JSON.stringify({
    ...payload,
    id: `log_${Date.now()}_${++seq}`,
    sessionId: SESSION,
    timestamp: Date.now()
  });
  fetch(ENDPOINT, {
    body: line,
    headers: {
      'Content-Type': 'application/json',
      'X-Debug-Session-Id': SESSION
    },
    method: 'POST'
  }).catch(() => {});
  const path = process.env.ECTOR_DEBUG_LOG;
  if (path) {
    try {
      appendFileSync(path, `${line}\n`);
    } catch {
      // ignore
    }
  }
}