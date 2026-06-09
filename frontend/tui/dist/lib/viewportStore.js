import { useCallback, useMemo, useSyncExternalStore } from 'react';
const EMPTY = {
  atBottom: true,
  bottom: 0,
  pending: 0,
  scrollHeight: 0,
  top: 0,
  viewportHeight: 0
};
export function getViewportSnapshot(s) {
  if (!s) {
    return EMPTY;
  }
  const pending = s.getPendingDelta();
  const top = Math.max(0, s.getScrollTop() + pending);
  const viewportHeight = Math.max(0, s.getViewportHeight());
  const scrollHeight = Math.max(viewportHeight, s.getScrollHeight());
  const bottom = top + viewportHeight;
  return {
    atBottom: s.isSticky() || bottom >= scrollHeight - 2,
    bottom,
    pending,
    scrollHeight,
    top,
    viewportHeight
  };
}
export function viewportSnapshotKey(v) {
  return `${v.atBottom ? 1 : 0}:${Math.ceil(v.top / 8) * 8}:${v.viewportHeight}:${Math.ceil(v.scrollHeight / 8) * 8}:${v.pending}`;
}
export function useViewportSnapshot(scrollRef) {
  const key = useSyncExternalStore(useCallback(cb => scrollRef.current?.subscribe(cb) ?? (() => {}), [scrollRef]), () => viewportSnapshotKey(getViewportSnapshot(scrollRef.current)), () => viewportSnapshotKey(EMPTY));
  // Key is quantized for fewer invalidations; geometry passed to
  // stickyPromptFromViewport / scrollbar must match real scrollTop + offsets
  // (Float64Array), not the rounded values embedded in the key string.
  // `key` invalidates when useSyncExternalStore reports a quantized viewport change.
  // eslint-disable-next-line react-hooks/exhaustive-deps -- key is the external-store tick, not redundant
  return useMemo(() => getViewportSnapshot(scrollRef.current), [key, scrollRef]);
}