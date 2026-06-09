import { jsxs as _jsxs, jsx as _jsx } from "react/jsx-runtime";
import { Text } from '@ector/ink';
import { hotnessBucket } from '../../../../lib/subagentTree.js';
import { compactPreview } from '../../../../lib/text.js';
import { heatPalette } from '../../lib/overlayConstants.js';
import { formatRowId, indentFor, statusGlyph } from '../../lib/overlayRows.js';
export function ListRow({
  active,
  index,
  node,
  peak,
  t,
  width
}) {
  const {
    color,
    glyph
  } = statusGlyph(node.item, t);
  const palette = heatPalette(t);
  const heatIdx = hotnessBucket(node.aggregate.hotness, peak, palette.length);
  const heatMarker = heatIdx >= 2 ? palette[heatIdx] : null;
  const goal = compactPreview(node.item.goal || 'subagente', width - 28 - node.item.depth * 2);
  const toolsCount = node.aggregate.totalTools > 0 ? ` ·${node.aggregate.totalTools}t` : '';
  const kids = node.children.length ? ` ·${node.children.length}↓` : '';
  const line = node.item.status === 'running' ? node.item.tools.at(-1) : undefined;
  const paren = line ? line.indexOf('(') : -1;
  const toolShort = line ? (paren > 0 ? line.slice(0, paren) : line).trim() : '';
  const trailing = toolShort ? ` · ${compactPreview(toolShort, 14)}` : '';
  const fg = active ? t.color.cyan : t.color.text;
  return _jsxs(Text, {
    bold: active,
    color: fg,
    inverse: active,
    wrap: "truncate-end",
    children: [' ', _jsxs(Text, {
      color: active ? fg : t.color.dim,
      children: [formatRowId(index), " "]
    }), indentFor(node.item.depth), heatMarker ? _jsx(Text, {
      color: heatMarker,
      children: "\u258D"
    }) : null, _jsx(Text, {
      color: active ? fg : color,
      children: glyph
    }), " ", goal, _jsxs(Text, {
      color: active ? fg : t.color.dim,
      children: [toolsCount, kids, trailing]
    })]
  });
}