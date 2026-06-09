const ESC = '\x1b';
const BEL = '\x07';
const ST = `${ESC}\\`;
export const OSC52_CLIPBOARD_QUERY = `${ESC}]52;c;?${BEL}`;
function wrapForMultiplexer(sequence) {
  if (process.env['TMUX']) {
    return `${ESC}Ptmux;${sequence.split(ESC).join(ESC + ESC)}${ST}`;
  }
  if (process.env['STY']) {
    return `${ESC}P${sequence}${ST}`;
  }
  return sequence;
}
export function buildOsc52ClipboardQuery() {
  return wrapForMultiplexer(OSC52_CLIPBOARD_QUERY);
}
export function parseOsc52ClipboardData(data) {
  const firstSep = data.indexOf(';');
  if (firstSep === -1) {
    return null;
  }
  const selection = data.slice(0, firstSep);
  const payload = data.slice(firstSep + 1);
  if (selection !== 'c' && selection !== 'p' || !payload || payload === '?') {
    return null;
  }
  try {
    return Buffer.from(payload, 'base64').toString('utf8');
  } catch {
    return null;
  }
}
export async function readOsc52Clipboard(querier, timeoutMs = 500) {
  if (!querier) {
    return null;
  }
  const timeout = new Promise(resolve => setTimeout(resolve, timeoutMs));
  const query = querier.send({
    request: buildOsc52ClipboardQuery(),
    match: r => {
      return !!r && typeof r === 'object' && r.type === 'osc' && r.code === 52;
    }
  });
  const response = await Promise.race([query, timeout]);
  await querier.flush();
  return response ? parseOsc52ClipboardData(response.data) : null;
}
export { writeOsc52Clipboard } from '@ector/ink';