import { stringWidth } from '@ector/ink';
let _seg = null;
const seg = () => _seg ??= new Intl.Segmenter(undefined, {
  granularity: 'grapheme'
});
/**
 * Mirrors the char-wrap behavior used by the composer TextInput.
 * Returns the zero-based visual line and column of the cursor cell.
 */
export function cursorLayout(value, cursor, cols) {
  const pos = Math.max(0, Math.min(cursor, value.length));
  const w = Math.max(1, cols);
  let col = 0,
    line = 0;
  for (const {
    segment,
    index
  } of seg().segment(value)) {
    if (index >= pos) {
      break;
    }
    if (segment === '\n') {
      line++;
      col = 0;
      continue;
    }
    const sw = stringWidth(segment);
    if (!sw) {
      continue;
    }
    if (col + sw > w) {
      line++;
      col = 0;
    }
    col += sw;
  }
  // trailing cursor-cell overflows to the next row at the wrap column
  if (col >= w) {
    line++;
    col = 0;
  }
  return {
    column: col,
    line
  };
}
export function inputVisualHeight(value, columns) {
  return cursorLayout(value, value.length, columns).line + 1;
}
/** Colunas entre prefixo ($ / continuação) e o texto — `columnGap` do `Box` da linha. */
export const COMPOSER_PROMPT_GAP = 2;
/** `ComposerPane` outer `NoSelect` horizontal padding (`padding={1}` × 2). */
export const COMPOSER_OUTER_PAD_X = 2;
/** `NoSelect` (2) + `paddingX` interno do cartão (2). */
const COMPOSER_INNER_PAD_X = COMPOSER_OUTER_PAD_X + 2;
/** Largura do cartão do composer — cabe dentro do `NoSelect` com `padding={1}`. */
export function composerCardWidth(totalCols) {
  return Math.max(1, totalCols - COMPOSER_OUTER_PAD_X);
}
export function stableComposerColumns(totalCols, promptWidth) {
  // Physical render/wrap width. Reserve inner horizontal padding, prompt prefix,
  // gap between gutter and field, and (on wide panes) transcript scrollbar gutter.
  return Math.max(1, totalCols - promptWidth - COMPOSER_PROMPT_GAP - COMPOSER_INNER_PAD_X - (totalCols - promptWidth >= 24 ? 2 : 0));
}