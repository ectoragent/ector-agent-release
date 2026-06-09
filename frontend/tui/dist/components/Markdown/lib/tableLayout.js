import { stripInlineMarkup } from '../regex.js';
const MIN_COL_WIDTH = 3;
const DEFAULT_TABLE_MAX_WIDTH = 88;
/** Espaços internos em `│ conteúdo │`. */
const CELL_PAD = 1;
const plainCell = cell => stripInlineMarkup(cell).replace(/\s+/g, ' ').trim();
export const tableFrameWidth = widths => widths.reduce((sum, w) => sum + w + 2 * CELL_PAD, 0) + widths.length + 1;
/** Distribui espaço extra proporcionalmente ao conteúdo de cada coluna. */
const expandColumnWidths = (widths, slack) => {
  if (slack <= 0 || !widths.length) {
    return widths;
  }
  const next = [...widths];
  const total = next.reduce((sum, w) => sum + w, 0);
  if (total <= 0) {
    const base = Math.floor(slack / next.length);
    let rem = slack - base * next.length;
    for (let i = 0; i < next.length; i++) {
      next[i] += base + (rem > 0 ? 1 : 0);
      if (rem > 0) {
        rem--;
      }
    }
    return next;
  }
  const order = next.map((w, ci) => ({
    ci,
    frac: slack * w / total % 1,
    share: Math.floor(slack * w / total)
  })).sort((a, b) => b.frac - a.frac || next[b.ci] - next[a.ci]);
  let allocated = 0;
  for (const {
    ci,
    share
  } of order) {
    next[ci] += share;
    allocated += share;
  }
  let rem = slack - allocated;
  for (let i = 0; i < rem; i++) {
    next[order[i % order.length].ci]++;
  }
  return next;
};
/** Larguras de conteúdo (sem contar bordas │ ─ ┌). */
export const computeTableColumnWidths = (rows, maxWidth = DEFAULT_TABLE_MAX_WIDTH) => {
  const colCount = Math.max(0, ...rows.map(r => r.length));
  if (!colCount) {
    return [];
  }
  const widths = Array.from({
    length: colCount
  }, (_, ci) => Math.max(MIN_COL_WIDTH, ...rows.map(r => plainCell(r[ci] ?? '').length)));
  const shrinkToFit = () => {
    let next = [...widths];
    let excess = tableFrameWidth(next) - maxWidth;
    while (excess > 0) {
      const maxCol = Math.max(...next);
      if (maxCol <= 1) {
        break;
      }
      const ci = next.indexOf(maxCol);
      next[ci]--;
      excess = tableFrameWidth(next) - maxWidth;
    }
    return next;
  };
  let result = tableFrameWidth(widths) <= maxWidth ? widths : shrinkToFit();
  const slack = maxWidth - tableFrameWidth(result);
  if (slack > 0) {
    result = expandColumnWidths(result, slack);
  }
  return result;
};
export const formatTableCell = (cell, width) => {
  const plain = plainCell(cell);
  if (plain.length <= width) {
    return plain.padEnd(width);
  }
  return width < 2 ? plain.slice(0, width) : `${plain.slice(0, width - 1)}…`;
};
export const tableHorizontalRule = (widths, join) => widths.map(w => '─'.repeat(w + 2 * CELL_PAD)).join(join);
const formatDataRow = (row, widths) => `│${row.map((cell, ci) => ` ${formatTableCell(cell, widths[ci] ?? MIN_COL_WIDTH)} `).join('│')}│`;
/** Linhas completas da tabela com bordas (┌ ┬ ┐ │ ├ ┼ ┤ └ ┴ ┘). */
export const buildTableLines = (rows, maxWidth = DEFAULT_TABLE_MAX_WIDTH) => {
  if (!rows.length) {
    return [];
  }
  const widths = computeTableColumnWidths(rows, maxWidth);
  const seg = join => tableHorizontalRule(widths, join);
  const lines = [{
    kind: 'border',
    text: `┌${seg('┬')}┐`
  }];
  for (const [ri, row] of rows.entries()) {
    lines.push({
      kind: ri === 0 ? 'header' : 'body',
      text: formatDataRow(row, widths)
    });
    if (ri < rows.length - 1) {
      lines.push({
        kind: 'border',
        text: `├${seg('┼')}┤`
      });
    }
  }
  lines.push({
    kind: 'border',
    text: `└${seg('┴')}┘`
  });
  return lines;
};
/** @deprecated Use {@link buildTableLines} — mantido para testes de alinhamento. */
export const formatTableRow = (row, widths) => formatDataRow(row, widths);