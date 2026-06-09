/**
 * Banner "ector" — ASCII + ANSI truecolor.
 */
const ESC = '\u001b';
const RESET = `${ESC}[0m`;
export const ECTOR_ASCII_LINES = ['╭─╴   ╭─╴   ╶┬╴   ╭─╮   ╭─╮', '├╴    │      │    │ │   ├┬╯', '╰─╴   ╰─╴    ╵    ╰─╯   ╵╰╴'];
function parseHex(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) {
    return null;
  }
  const n = parseInt(m[1], 16);
  return [n >> 16 & 0xff, n >> 8 & 0xff, n & 0xff];
}
function mixHex(from, to, t) {
  const a = parseHex(from);
  const b = parseHex(to);
  if (!a || !b) {
    return t < 0.5 ? from : to;
  }
  const p = Math.max(0, Math.min(1, t));
  const lerp = i => Math.round(a[i] + (b[i] - a[i]) * p);
  return `#${(1 << 24 | lerp(0) << 16 | lerp(1) << 8 | lerp(2)).toString(16).slice(1)}`;
}
function fg(hex) {
  const rgb = parseHex(hex);
  if (!rgb) {
    return '';
  }
  const [r, g, b] = rgb;
  return `${ESC}[1m${ESC}[38;2;${r};${g};${b}m`;
}
/** Reflexo suave: bordas #21ade4, centro um pouco mais claro. */
function reflectMix(edge, peak, t) {
  const mirror = 1 - Math.abs(2 * Math.max(0, Math.min(1, t)) - 1);
  const soft = mirror ** 2;
  const blueGray = mixHex(edge, peak, 0.38);
  return mixHex(edge, blueGray, soft * 0.52);
}
const RIPPLE_MS = 900;
const RIPPLE_RADIUS = 20;
const RIPPLE_RING = 2.2;
/** Onda circular que se expande a partir do clique. */
function rippleBoost(dist, ageMs) {
  if (ageMs >= RIPPLE_MS) {
    return 0;
  }
  const fade = 1 - ageMs / RIPPLE_MS;
  const wave = ageMs / RIPPLE_MS * RIPPLE_RADIUS;
  const ring = Math.abs(dist - wave);
  return fade * Math.max(0, 1 - ring / RIPPLE_RING) * 0.88;
}
/** Coluna do glifo a partir do clique numa linha centrada. */
export function logoClickCol(line, localCol, boxWidth) {
  const w = line.trimEnd().length;
  const offset = Math.max(0, Math.floor((boxWidth - w) / 2));
  return Math.max(0, Math.min(w - 1, localCol - offset));
}
export function rippleActive(ripple, now = performance.now()) {
  return ripple !== null && now - ripple.at < RIPPLE_MS;
}
/** Gradiente horizontal; clique dispara onda circular em azul. */
export function paintBannerGradient(lines, edge, peak, ripple, now = performance.now(), rippleBlue) {
  const trimmed = lines.map(line => line.trimEnd());
  const maxW = Math.max(...trimmed.map(line => line.length), 1);
  return trimmed.map((line, row) => {
    let out = '';
    for (let col = 0; col < line.length; col++) {
      const ch = line[col];
      if (ch === ' ') {
        out += ' ';
        continue;
      }
      const t = maxW <= 1 ? 0 : col / (maxW - 1);
      let color = edge === peak ? edge : reflectMix(edge, peak, t);
      if (ripple && rippleBlue) {
        const dist = Math.hypot(col - ripple.col, row - ripple.row);
        const boost = rippleBoost(dist, now - ripple.at);
        if (boost > 0) {
          color = mixHex(color, rippleBlue, boost);
        }
      }
      out += `${fg(color)}${ch}${RESET}`;
    }
    return out;
  });
}
export function formatBannerVersion(version, versionCode) {
  if (!version?.trim()) {
    return '';
  }
  const v = version.trim().replace(/^v/i, '');
  const label = `v${v}`;
  if (versionCode != null && versionCode > 0) {
    return `${label} (${versionCode})`;
  }
  return label;
}