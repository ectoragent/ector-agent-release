import { hotnessBucket } from '../../../lib/subagentTree.js';
export function heatColor(node, peak, theme) {
  const palette = [theme.color.border, theme.color.cyan, theme.color.title, theme.color.warn, theme.color.error];
  const idx = hotnessBucket(node.aggregate.hotness, peak, palette.length);
  if (idx < 2) {
    return undefined;
  }
  return palette[idx];
}