import { jsxs as _jsxs, jsx as _jsx } from "react/jsx-runtime";
import { Box, Text } from '@ector/ink';
import { compactPreview } from '../../lib/text.js';
export const QUEUE_WINDOW = 3;
export function getQueueWindow(queueLen, queueEditIdx) {
  const start = queueEditIdx === null ? 0 : Math.max(0, Math.min(queueEditIdx - 1, Math.max(0, queueLen - QUEUE_WINDOW)));
  const end = Math.min(queueLen, start + QUEUE_WINDOW);
  return {
    end,
    showLead: start > 0,
    showTail: end < queueLen,
    start
  };
}
export function QueuedMessages({
  cols,
  queueEditIdx,
  queued,
  t
}) {
  if (!queued.length) {
    return null;
  }
  const q = getQueueWindow(queued.length, queueEditIdx);
  return _jsx(Box, {
    flexDirection: "column",
    marginTop: 1,
    children: [_jsxs(Text, {
      color: t.color.dim,
      dimColor: true,
      children: ["na fila (", queued.length, ")", queueEditIdx !== null ? ` · editando ${queueEditIdx + 1}` : '']
    }, "qhead"), q.showLead ? _jsxs(Text, {
      color: t.color.dim,
      dimColor: true,
      children: [' ', "\u2026"]
    }, "qlead") : null, ...queued.slice(q.start, q.end).map((item, i) => {
      const idx = q.start + i;
      const active = queueEditIdx === idx;
      return _jsxs(Text, {
        color: active ? t.color.cyan : t.color.dim,
        dimColor: true,
        children: [active ? '▸' : ' ', " ", idx + 1, ". ", compactPreview(item, Math.max(16, cols - 10))]
      }, `${idx}-${item.slice(0, 16)}`);
    }), q.showTail ? _jsxs(Text, {
      color: t.color.dim,
      dimColor: true,
      children: ['  ', "\u2026e mais ", queued.length - q.end]
    }, "qtail") : null].filter(Boolean)
  });
}