export const FENCE_RE = /^\s*(`{3,}|~{3,})(.*)$/;
export const FENCE_CLOSE_RE = /^\s*(`{3,}|~{3,})\s*$/;
export const HR_RE = /^ {0,3}([-*_])(?:\s*\1){2,}\s*$/;
export const HEADING_RE = /^\s{0,3}(#{1,6})\s+(.*?)(?:\s+#+\s*)?$/;
export const SETEXT_RE = /^\s{0,3}(=+|-+)\s*$/;
export const FOOTNOTE_RE = /^\[\^([^\]]+)\]:\s*(.*)$/;
export const DEF_RE = /^\s*:\s+(.+)$/;
export const BULLET_RE = /^(\s*)[-+*]\s+(.*)$/;
export const TASK_RE = /^\[( |x|X)\]\s+(.*)$/;
export const NUMBERED_RE = /^(\s*)(\d+)[.)]\s+(.*)$/;
export const QUOTE_RE = /^\s*(?:>\s*)+/;
/** Indented prose continuation for a list item (not a nested bullet/number). */
export const listContinuationLine = line => {
  if (!line.trim()) {
    return false;
  }
  if (BULLET_RE.test(line) || NUMBERED_RE.test(line)) {
    return false;
  }
  return /^\s{2,}\S/.test(line) && !/^\s*[-+*]\s+/.test(line) && !/^\s*\d+[.)]\s+/.test(line);
};
export const TABLE_DIVIDER_CELL_RE = /^:?-{3,}:?$/;
const indentDepth = s => Math.floor(s.replace(/\t/g, '  ').length / 2);
const splitRow = row => row.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim());
const isTableDivider = row => {
  const cells = splitRow(row);
  return cells.length > 1 && cells.every(c => TABLE_DIVIDER_CELL_RE.test(c));
};
export const autolinkUrl = raw => raw.startsWith('mailto:') || raw.startsWith('http') || !raw.includes('@') ? raw : `mailto:${raw}`;
export { indentDepth, isTableDivider, splitRow };