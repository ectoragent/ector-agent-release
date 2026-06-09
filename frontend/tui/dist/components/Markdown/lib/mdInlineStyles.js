import { jsx as _jsx } from "react/jsx-runtime";
import { Text } from '@ector/ink';
const PATH_EXT_RE = /\.(?:tsx?|jsx?|py|md|json|ya?ml|rs|go|sh|css|toml|lock)\b/i;
const HASH_RE = /^[0-9a-f]{7,40}$/i;
export const classifyBacktick = text => {
  const s = text.trim();
  if (HASH_RE.test(s)) {
    return 'hash';
  }
  if ((s.includes('/') || PATH_EXT_RE.test(s)) && !/\s/.test(s)) {
    return 'path';
  }
  return 'code';
};
/** Rótulos de secção em negrito no corpo (`**Modificados:**`, `**Novos:**`). */
export const isSectionLabelBold = text => {
  const s = text.trim();
  if (!s.endsWith(':') || s.includes('\n') || s.length > 96) {
    return false;
  }
  if (HASH_RE.test(s)) {
    return false;
  }
  if ((s.includes('/') || PATH_EXT_RE.test(s)) && s.length >= 8) {
    return false;
  }
  return true;
};
export const classifyBold = text => {
  const s = text.trim();
  if (HASH_RE.test(s)) {
    return 'hash';
  }
  if ((s.includes('/') || PATH_EXT_RE.test(s)) && s.length >= 8) {
    return 'path';
  }
  if (isSectionLabelBold(s)) {
    return 'label';
  }
  return 'emphasis';
};
/** Accent — hashes, links, block headings only. */
export const mdAccent = (t, children, bold = false) => _jsx(Text, {
  bold: bold,
  color: t.color.cyan,
  children: children
});
/** Paths / filenames — readable but not accent. */
export const mdPath = (t, children, bold = false) => _jsx(Text, {
  bold: bold,
  color: t.color.label,
  children: children
});
/** Inline code, identifiers, regex — subtle surface. */
export const mdCode = (t, children) => _jsx(Text, {
  backgroundColor: t.color.completionBg,
  color: t.color.label,
  children: children
});
/** Ênfase no corpo — primário quando é rótulo curto; caso contrário título. */
export const mdEmphasis = (t, children) => isSectionLabelBold(children) ? mdAccent(t, children, true) : _jsx(Text, {
  bold: true,
  color: t.color.title,
  children: children
});
export const renderBacktick = (t, inner, inBold = false) => {
  switch (classifyBacktick(inner)) {
    case 'hash':
      return mdAccent(t, inner);
    case 'path':
      return mdPath(t, inner, inBold);
    default:
      return mdCode(t, inner);
  }
};
export const renderBoldSpan = (t, inner, tone = 'body') => {
  switch (classifyBold(inner)) {
    case 'hash':
      return mdAccent(t, inner);
    case 'path':
      return mdPath(t, inner, true);
    case 'label':
      return mdAccent(t, inner, true);
    default:
      return tone === 'heading' ? mdAccent(t, inner, true) : mdEmphasis(t, inner);
  }
};