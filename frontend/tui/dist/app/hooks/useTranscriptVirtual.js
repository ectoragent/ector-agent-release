import { MANUAL_SCROLL_GRACE_MS, maxScrollTop } from '@ector/ink';
import { useStore } from '@nanostores/react';
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import { FULL_RENDER_TAIL_ITEMS } from '../../config/limits.js';
import { sectionMode } from '../../domain/details.js';
import { useVirtualHistory } from '../../hooks/useVirtualHistory.js';
import { getViewportSnapshot } from '../../lib/viewportStore.js';
import { estimatedMsgHeight, isHeavyTranscriptMessage, messageHeightKey } from '../../lib/virtualHeights.js';
import { shouldClearHeightCacheOnBusyEnd, shouldFollowNewHistoryAtBottom } from '../transcriptVirtualLogic.js';
import { $uiState } from '../uiStore.js';
const MAX_HEIGHT_CACHE_BUCKETS = 12;
export function useTranscriptVirtual(opts) {
  const {
    cols,
    compact,
    detailsMode,
    detailsModeCommandOverride,
    historyItems,
    liveTailActive,
    scrollRef,
    sections,
    sid
  } = opts;
  const {
    busy
  } = useStore($uiState);
  const prevBusyRef = useRef(busy);
  const msgIdsRef = useRef(new WeakMap());
  const msgIdSeqRef = useRef(0);
  const heightCachesRef = useRef(new Map());
  const messageId = useCallback(msg => {
    const hit = msgIdsRef.current.get(msg);
    if (hit) {
      return hit;
    }
    const next = `${messageHeightKey(msg)}:${++msgIdSeqRef.current}`;
    msgIdsRef.current.set(msg, next);
    return next;
  }, []);
  const virtualRows = useMemo(() => historyItems.map((msg_0, index) => ({
    index,
    key: messageId(msg_0),
    msg: msg_0
  })), [historyItems, messageId]);
  const detailsLayoutKey = useMemo(() => {
    const thinking = sectionMode('thinking', detailsMode, sections, detailsModeCommandOverride);
    const tools = sectionMode('tools', detailsMode, sections, detailsModeCommandOverride);
    return `${thinking}:${tools}`;
  }, [detailsMode, detailsModeCommandOverride, sections]);
  const detailsVisible = detailsLayoutKey !== 'hidden:hidden';
  const heightCacheKey = `${sid ?? 'draft'}:${cols}:${compact ? '1' : '0'}:${detailsLayoutKey}`;
  const heightCache = useMemo(() => {
    let cache = heightCachesRef.current.get(heightCacheKey);
    if (!cache) {
      cache = new Map();
      heightCachesRef.current.set(heightCacheKey, cache);
      if (heightCachesRef.current.size > MAX_HEIGHT_CACHE_BUCKETS) {
        heightCachesRef.current.delete(heightCachesRef.current.keys().next().value);
      }
    }
    return cache;
  }, [heightCacheKey]);
  const initialHeights = useMemo(() => {
    const out = new Map();
    for (const row of virtualRows) {
      const boundedRender = isHeavyTranscriptMessage(row.msg.text, cols);
      const limitHistory = row.index < virtualRows.length - FULL_RENDER_TAIL_ITEMS;
      const estimate = estimatedMsgHeight(row.msg, cols, {
        boundedRender,
        compact,
        details: detailsVisible,
        limitHistory
      });
      const cached = heightCache.get(row.key);
      const cachedOk = cached !== undefined && (!boundedRender || cached <= estimate * 2 + 8);
      out.set(row.key, cachedOk ? cached : estimate);
    }
    return out;
  }, [cols, compact, detailsVisible, heightCache, virtualRows]);
  const syncHeightCache = useCallback(heights => {
    for (const row_0 of virtualRows) {
      const h = heights.get(row_0.key);
      if (h) {
        heightCache.set(row_0.key, h);
      }
    }
  }, [heightCache, virtualRows]);
  const virtualHistory = useVirtualHistory(scrollRef, virtualRows, cols, {
    initialHeights,
    liveTailActive,
    onHeightsChange: syncHeightCache
  });
  const transcriptLenRef = useRef(0);
  const prevSidRef = useRef(undefined);
  const chaseBottomRef = useRef(false);
  useEffect(() => {
    const wasBusy = prevBusyRef.current;
    prevBusyRef.current = busy;
    if (shouldClearHeightCacheOnBusyEnd(wasBusy, busy, sid)) {
      const prefix = `${sid}:`;
      for (const key of heightCachesRef.current.keys()) {
        if (key.startsWith(prefix)) {
          heightCachesRef.current.delete(key);
        }
      }
      scrollRef.current?.setClampBounds(undefined, undefined);
    }
  }, [busy, scrollRef, sid]);
  const scrollTranscriptToBottom = useCallback(contentHeight => {
    const s = scrollRef.current;
    if (!s) {
      return;
    }
    s.setClampBounds(undefined, undefined);
    const vp = s.getViewportHeight();
    if (contentHeight != null && contentHeight > 0 && vp > 0) {
      s.scrollTo(Math.max(0, contentHeight - vp));
    }
    s.scrollToBottom();
    queueMicrotask(() => {
      const sb = scrollRef.current;
      if (!sb) {
        return;
      }
      sb.setClampBounds(undefined, undefined);
      if (contentHeight != null && contentHeight > 0 && sb.getViewportHeight() > 0) {
        sb.scrollTo(Math.max(0, contentHeight - sb.getViewportHeight()));
      }
      sb.scrollToBottom();
    });
    requestAnimationFrame(() => scrollRef.current?.scrollToBottom());
  }, [scrollRef]);
  useLayoutEffect(() => {
    const len = historyItems.length;
    const sidChanged = sid !== prevSidRef.current;
    const virtualTotal = virtualHistory.offsets[virtualRows.length] ?? 0;
    if (sidChanged) {
      prevSidRef.current = sid;
      transcriptLenRef.current = len;
      if (sid && len > 0) {
        chaseBottomRef.current = true;
        scrollTranscriptToBottom(virtualTotal);
      }
      return;
    }
    if (len > transcriptLenRef.current) {
      const s_0 = scrollRef.current;
      const snap = getViewportSnapshot(s_0);
      transcriptLenRef.current = len;
      if (s_0 && shouldFollowNewHistoryAtBottom({
        atBottom: snap.atBottom,
        isSticky: s_0.isSticky(),
        lastManualScrollAt: s_0.getLastManualScrollAt() || 0,
        manualGraceMs: MANUAL_SCROLL_GRACE_MS,
        now: Date.now(),
        viewportHeight: snap.viewportHeight
      })) {
        scrollTranscriptToBottom(virtualHistory.offsets[len] ?? 0);
      }
    } else {
      transcriptLenRef.current = len;
    }
  }, [historyItems.length, scrollRef, scrollTranscriptToBottom, sid, virtualHistory.offsets, virtualRows.length]);
  useEffect(() => {
    if (!chaseBottomRef.current) {
      return;
    }
    let cancelled = false;
    let frames = 0;
    const chase = () => {
      if (cancelled || frames++ > 20) {
        chaseBottomRef.current = false;
        return;
      }
      const s_1 = scrollRef.current;
      if (s_1 && Date.now() - s_1.getLastManualScrollAt() < 2500) {
        chaseBottomRef.current = false;
        return;
      }
      scrollTranscriptToBottom(virtualHistory.offsets[virtualRows.length] ?? 0);
      const snap_0 = getViewportSnapshot(scrollRef.current);
      if (snap_0.atBottom && snap_0.viewportHeight > 0) {
        chaseBottomRef.current = false;
        return;
      }
      requestAnimationFrame(chase);
    };
    requestAnimationFrame(chase);
    return () => {
      cancelled = true;
    };
  }, [historyItems.length, scrollRef, scrollTranscriptToBottom, sid, virtualRows.length]);
  useLayoutEffect(() => {
    if (!liveTailActive) {
      return;
    }
    const s_2 = scrollRef.current;
    if (!s_2) {
      return;
    }
    // scrollBy clears stickyScroll; do not snap back while the user reads
    // history (each stream paint used to call scrollToBottom and felt stuck).
    if (!s_2.isSticky() || Date.now() - s_2.getLastManualScrollAt() < MANUAL_SCROLL_GRACE_MS) {
      return;
    }
    const scrollH = Math.max(s_2.getScrollHeight(), s_2.getFreshScrollHeight?.() ?? 0);
    const vp_0 = Math.max(0, s_2.getViewportHeight());
    const maxTop = maxScrollTop(scrollH, vp_0);
    const cur = s_2.getScrollTop() + s_2.getPendingDelta();
    // Already docked — skip redundant scrollTo (was causing micro-jitter at bottom).
    if (cur >= maxTop - 1) {
      return;
    }
    s_2.setClampBounds(undefined, undefined);
    s_2.scrollTo(maxTop);
  }, [liveTailActive, scrollRef, virtualHistory.bottomSpacer, virtualHistory.end, virtualHistory.offsets, virtualHistory.topSpacer, virtualRows.length]);
  return {
    virtualHistory,
    virtualRows
  };
}