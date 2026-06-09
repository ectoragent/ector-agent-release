import { fmtDuration } from '../../../lib/subagentTree.js';
import { flattenTree } from '../../../lib/subagentTree.js';
import { FILTER_PREDICATES, SORT_COMPARATORS, STATUS_GLYPH } from './overlayConstants.js';
// ── Pure helpers ─────────────────────────────────────────────────────
export const fmtDur = seconds => seconds == null || seconds <= 0 ? '' : fmtDuration(seconds);
export const fmtElapsedLabel = seconds => seconds < 0 ? '' : fmtDuration(seconds);
export const displayElapsedSeconds = (item, nowMs) => {
  if (item.durationSeconds != null) {
    return item.durationSeconds;
  }
  if (item.startedAt != null && (item.status === 'running' || item.status === 'queued')) {
    return Math.max(0, (nowMs - item.startedAt) / 1000);
  }
  return null;
};
export const indentFor = depth => '  '.repeat(Math.max(0, depth));
export const formatRowId = n => String(n + 1).padStart(2, ' ');
export const cycle = (order, current) => order[(order.indexOf(current) + 1) % order.length];
export const statusGlyph = (item, t) => {
  const g = STATUS_GLYPH[item.status];
  return {
    color: g.color(t),
    glyph: g.glyph
  };
};
export const prepareRows = (tree, sort, filter) => tree.length === 0 ? [] : flattenTree([...tree].sort(SORT_COMPARATORS[sort])).filter(FILTER_PREDICATES[filter]);
export const diffMetricLine = (name, a, b, fmt) => {
  const d = b - a;
  const sign = d === 0 ? '' : d > 0 ? '+' : '-';
  return `${name}: ${fmt(a)} → ${fmt(b)}  (${sign}${fmt(Math.abs(d)) || '0'})`;
};