import { normalizeMdText } from './normalizeMdText.js';
/** Private-use sentinels — must not use \\u0000 (stripped by terminal) or bare ASCII (matches INLINE_RE). */
const PH_OPEN = '\uE100';
const PH_CLOSE = '\uE101';
const codePh = idx => `${PH_OPEN}c${idx}${PH_CLOSE}`;
const boldPh = idx => `${PH_OPEN}b${idx}${PH_CLOSE}`;
export const PH_RE = new RegExp(`${PH_OPEN}([cb])(\\d+)${PH_CLOSE}`, 'g');
/** Short HTML tags in prose (`<br />`, `<hr>`) — styled like inline code. */
const HTML_TAG_RE = /<[A-Za-z][A-Za-z0-9-]*(?:\s[^<>\n]{0,48})?\s*\/?>/g;
const protectHtmlTag = (text, codes) => text.replace(HTML_TAG_RE, match => {
  const idx = codes.length;
  codes.push(match);
  return codePh(idx);
});
const protectCode = (text, codes) => text.replace(/`([^`\\]+)`/g, (_, inner) => {
  const idx = codes.length;
  codes.push(inner);
  return codePh(idx);
});
const protectBold = (text, bolds) => {
  let out = text.replace(/\*\*(.+?)\*\*/g, (_, inner) => {
    const idx = bolds.length;
    bolds.push(inner);
    return boldPh(idx);
  });
  return out.replace(/(?<!\w)__(.+?)__(?!\w)/g, (_, inner) => {
    const idx = bolds.length;
    bolds.push(inner);
    return boldPh(idx);
  });
};
/** Extract inline code and bold spans before INLINE_RE runs (avoids orphaned backticks). */
export const protectInlineSpans = raw => {
  const codes = [];
  const bolds = [];
  const normalized = normalizeMdText(raw);
  const withCode = protectCode(normalized, codes);
  const text = protectBold(protectHtmlTag(withCode, codes), bolds);
  return {
    bolds,
    codes,
    text
  };
};
const expandPh = (value, kind, values) => value.replace(new RegExp(`${PH_OPEN}${kind}(\\d+)${PH_CLOSE}`, 'g'), (_, n) => values[Number(n)] ?? '');
/** Expand placeholder marks to plain text (for stripInlineMarkup / table sizing). */
export const expandInlinePlaceholders = (value, {
  bolds,
  codes
}) => {
  const expandedBolds = bolds.map(b => expandPh(b, 'c', codes));
  return expandPh(expandPh(value, 'c', codes), 'b', expandedBolds);
};
/** Split protected text into plain runs and placeholder tokens for inline layout. */
export const splitProtectedText = text => {
  const segments = [];
  let last = 0;
  for (const m of text.matchAll(PH_RE)) {
    const i = m.index ?? 0;
    if (i > last) {
      segments.push({
        kind: 'plain',
        text: text.slice(last, i)
      });
    }
    segments.push({
      kind: m[1] === 'c' ? 'code' : 'bold',
      index: Number(m[2])
    });
    last = i + m[0].length;
  }
  if (last < text.length) {
    segments.push({
      kind: 'plain',
      text: text.slice(last)
    });
  }
  return segments;
};
/** Normalize + protect; feed result.text to INLINE_RE. */
export const prepareInlineText = raw => protectInlineSpans(raw);