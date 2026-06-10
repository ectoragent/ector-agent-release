/** Height cache for history rows is keyed per message — no session-wide flush on turn end. */
export const shouldClearHeightCacheOnBusyEnd = (_wasBusy, _busy, _sid) => false;
export const shouldFollowNewHistoryAtBottom = ctx => ctx.isSticky && ctx.now - ctx.lastManualScrollAt >= ctx.manualGraceMs && (ctx.atBottom || ctx.viewportHeight <= 0);