import { FULL_RENDER_TAIL_ITEMS } from '../config/limits.js';
import { estimatedMsgHeight, isHeavyTranscriptMessage } from '../lib/virtualHeights.js';
/** Height cache for history rows is keyed per message — no session-wide flush on turn end. */
export const shouldClearHeightCacheOnBusyEnd = (_wasBusy, _busy, _sid) => false;
/** Rows outside the live tail render with bounded history text (no full table layout). */
export const isHistoryRenderLimited = (index, totalRows, tailItems = FULL_RENDER_TAIL_ITEMS) => index < totalRows - tailItems;
/** Skip expensive height re-estimation when only new tail rows were appended. */
export const shouldReuseHeightEstimate = (rowIndex, prevTotalRows, newTotalRows, layoutChanged, tailItems = FULL_RENDER_TAIL_ITEMS) => {
  if (layoutChanged || prevTotalRows <= 0) {
    return false;
  }
  if (newTotalRows > prevTotalRows) {
    if (rowIndex >= prevTotalRows) {
      return false;
    }
    const wasLimited = rowIndex < prevTotalRows - tailItems;
    const isLimited = rowIndex < newTotalRows - tailItems;
    if (wasLimited !== isLimited) {
      return false;
    }
  }
  return true;
};
export const rowBoundedRender = (text, cols, limitHistory) => limitHistory || isHeavyTranscriptMessage(text, cols);
export function buildInitialHeightEstimates(rows, ctx) {
  const out = new Map();
  const total = rows.length;
  for (const row of rows) {
    const limitHistory = isHistoryRenderLimited(row.index, total);
    const boundedRender = rowBoundedRender(row.msg.text, ctx.cols, limitHistory);
    const cached = ctx.heightCache.get(row.key);
    const reuse = shouldReuseHeightEstimate(row.index, ctx.prevTotalRows, total, ctx.layoutChanged);
    const prevEst = reuse ? ctx.prevEstimates.get(row.key) : undefined;
    const estimate = prevEst ?? estimatedMsgHeight(row.msg, ctx.cols, {
      boundedRender,
      compact: ctx.compact,
      details: ctx.detailsVisible,
      limitHistory
    });
    const cachedOk = cached !== undefined && (!boundedRender || cached <= estimate * 2 + 8);
    out.set(row.key, cachedOk ? cached : estimate);
  }
  return out;
}
export const shouldFollowNewHistoryAtBottom = ctx => shouldAutoScrollTail(ctx);
/** User scrolled up to read history — do not pull them back to the live tail. */
export const isReadingHistory = ctx => {
  if (ctx.lastManualScrollAt <= 0) {
    return false;
  }
  if (ctx.now - ctx.lastManualScrollAt < ctx.manualGraceMs) {
    return true;
  }
  return !ctx.atBottom;
};
/** Auto-scroll when docked at bottom, or until the user manually scrolls away. */
export const shouldAutoScrollTail = ctx => !isReadingHistory(ctx);