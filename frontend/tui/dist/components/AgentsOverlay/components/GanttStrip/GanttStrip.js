import { jsxs as _jsxs, jsx as _jsx } from "react/jsx-runtime";
import { Box, Text } from '@ector/ink';
import { displayElapsedSeconds, fmtElapsedLabel, formatRowId, statusGlyph } from '../../lib/overlayRows.js';
export function GanttStrip({
  cols,
  cursor,
  flatNodes,
  maxRows,
  now,
  t
}) {
  const spans = flatNodes.map((node, idx) => {
    const started = node.item.startedAt ?? now;
    const ended = node.item.durationSeconds != null && node.item.startedAt != null ? node.item.startedAt + node.item.durationSeconds * 1000 : now;
    return {
      endAt: ended,
      idx,
      node,
      startAt: started
    };
  }).filter(s => s.endAt >= s.startAt);
  if (!spans.length) {
    return null;
  }
  const globalStart = Math.min(...spans.map(s => s.startAt));
  const globalEnd = Math.max(...spans.map(s => s.endAt));
  const totalSpan = Math.max(1, globalEnd - globalStart);
  const totalSeconds = (globalEnd - globalStart) / 1000;
  // 5-col id gutter ("  12  ") so the bar doesn't press against the id.
  // 10-col right reserve: pad + up to `12m 30s`-style label without
  // truncate-end against a full-width bar.
  const idGutter = 5;
  const labelReserve = 10;
  const barWidth = Math.max(10, cols - idGutter - labelReserve);
  const startIdx = Math.max(0, Math.min(Math.max(0, spans.length - maxRows), cursor - Math.floor(maxRows / 2)));
  const shown = spans.slice(startIdx, startIdx + maxRows);
  const bar = (startAt, endAt) => {
    const s = Math.floor((startAt - globalStart) / totalSpan * barWidth);
    const e = Math.min(barWidth, Math.ceil((endAt - globalStart) / totalSpan * barWidth));
    const fill = Math.max(1, e - s);
    return ' '.repeat(s) + '█'.repeat(fill) + ' '.repeat(Math.max(0, barWidth - s - fill));
  };
  const charStep = totalSeconds < 20 && barWidth > 20 ? 5 : 10;
  const ruler = Array.from({
    length: barWidth
  }, (_, i) => {
    if (i > 0 && i % 10 === 0) {
      return '┼';
    }
    if (i > 0 && i % 5 === 0) {
      return '·';
    }
    return '─';
  }).join('');
  const rulerLabels = (() => {
    const chars = new Array(barWidth).fill(' ');
    for (let pos = 0; pos < barWidth; pos += charStep) {
      const secs = pos / barWidth * totalSeconds;
      const label = pos === 0 ? '0' : secs >= 1 ? `${Math.round(secs)}s` : `${secs.toFixed(1)}s`;
      for (let j = 0; j < label.length && pos + j < barWidth; j++) {
        chars[pos + j] = label[j];
      }
    }
    return chars.join('');
  })();
  const windowLabel = spans.length > maxRows ? `  (${startIdx + 1}-${Math.min(spans.length, startIdx + maxRows)}/${spans.length})` : '';
  return _jsxs(Box, {
    flexDirection: "column",
    marginBottom: 1,
    children: [_jsxs(Text, {
      color: t.color.dim,
      children: ["Linha do tempo \u00B7 ", fmtElapsedLabel(Math.max(0, totalSeconds)), windowLabel]
    }), shown.map(({
      endAt,
      idx,
      node,
      startAt
    }) => {
      const active = idx === cursor;
      const {
        color
      } = statusGlyph(node.item, t);
      const accent = active ? t.color.cyan : t.color.dim;
      const elSec = displayElapsedSeconds(node.item, now);
      const elLabel = elSec != null ? fmtElapsedLabel(elSec) : '';
      return _jsxs(Text, {
        wrap: "truncate-end",
        children: [_jsxs(Text, {
          bold: active,
          color: accent,
          children: [formatRowId(idx), '  ']
        }), _jsx(Text, {
          color: active ? t.color.cyan : color,
          children: bar(startAt, endAt)
        }), elLabel ? _jsxs(Text, {
          color: accent,
          children: ['   ', elLabel]
        }) : null]
      }, node.item.id);
    }), _jsxs(Text, {
      color: t.color.dim,
      dim: true,
      children: ['    ', ruler]
    }), totalSeconds > 0 ? _jsxs(Text, {
      color: t.color.dim,
      dim: true,
      children: ['    ', rulerLabels]
    }) : null]
  });
}