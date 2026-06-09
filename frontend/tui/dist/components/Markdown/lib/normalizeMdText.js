import { isHighlightable } from '../../../lib/syntax.js';
/** Unicode and “smart” quote variants models often emit instead of ASCII backticks. */
const UNICODE_BACKTICK_RE = /[\u0060\u02CB\u02F4\u2018\u2019\u201A\u2032\u2035\uFF40]|\u0300|\u0301/g;
/** Fenced code open/close lines — must not run odd-backtick repair (3 backticks is valid). */
const FENCE_LINE_RE = /^\s*(?:`{3,}|~{3,})/;
/** Modelos às vezes emitem `- json` em vez de ` ```json ` antes de `{` / `[`. */
const BROKEN_FENCE_LANG_RE = /^\s*-\s+([a-z][\w+#.-]*)\s*$/i;
/** Lista com abridor de fence na mesma linha: `- ```json`. */
const LIST_PREFIXED_FENCE_RE = /^\s*[-+*]\s+(`{3,}.*)$/;
const EXTRA_FENCE_LANGS = new Set(['diff', 'md', 'markdown', 'text', 'txt', 'plaintext', 'console', 'output']);
const isFenceLangToken = lang => isHighlightable(lang) || EXTRA_FENCE_LANGS.has(lang.toLowerCase());
const looksLikeCodeBlockBody = line => {
  const next = (line ?? '').trim();
  return next.startsWith('{') || next.startsWith('[') || next.startsWith('(') || next.startsWith('<') || next.startsWith('#!') || FENCE_LINE_RE.test(next);
};
/** `- json` + linha `{` → ` ```json `; `- ```ts` → ` ```ts `. */
const repairFenceOpeners = (line, nextLine) => {
  const listFence = line.match(LIST_PREFIXED_FENCE_RE);
  if (listFence) {
    return listFence[1];
  }
  const broken = line.match(BROKEN_FENCE_LANG_RE);
  if (broken && isFenceLangToken(broken[1]) && looksLikeCodeBlockBody(nextLine)) {
    return `\`\`\`${broken[1]}`;
  }
  return line;
};
/** Close an odd number of backticks at end-of-line (streaming / incomplete inline code). */
const closeOddBackticksPerLine = line => {
  if (FENCE_LINE_RE.test(line)) {
    return line;
  }
  const count = (line.match(/`/g) ?? []).length;
  return count % 2 === 1 ? `${line}\`` : line;
};
export const normalizeMdText = text => {
  const raw = text.replace(UNICODE_BACKTICK_RE, '`').split('\n');
  const repaired = raw.map((line, i) => repairFenceOpeners(line, raw[i + 1]));
  return repaired.map(closeOddBackticksPerLine).join('\n');
};