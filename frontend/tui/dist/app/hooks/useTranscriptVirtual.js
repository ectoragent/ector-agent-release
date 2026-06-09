import { useCallback, useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import { FULL_RENDER_TAIL_ITEMS } from '../../config/limits.js';
import { sectionMode } from '../../domain/details.js';
import { useVirtualHistory } from '../../hooks/useVirtualHistory.js';
import { getViewportSnapshot } from '../../lib/viewportStore.js';
import { estimatedMsgHeight, messageHeightKey } from '../../lib/virtualHeights.js';
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
      out.set(row.key, heightCache.get(row.key) ?? estimatedMsgHeight(row.msg, cols, {
        compact,
        details: detailsVisible,
        limitHistory: row.index < virtualRows.length - FULL_RENDER_TAIL_ITEMS
      }));
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
      transcriptLenRef.current = len;
      scrollTranscriptToBottom(virtualHistory.offsets[len] ?? 0);
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
      const total = virtualHistory.offsets[virtualRows.length] ?? 0;
      scrollTranscriptToBottom(total);
      const snap = getViewportSnapshot(scrollRef.current);
      if (snap.atBottom && snap.viewportHeight > 0) {
        chaseBottomRef.current = false;
        return;
      }
      requestAnimationFrame(chase);
    };
    requestAnimationFrame(chase);
    return () => {
      cancelled = true;
    };
  }, [historyItems.length, scrollRef, scrollTranscriptToBottom, sid, virtualHistory.offsets, virtualRows.length]);
  useLayoutEffect(() => {
    if (!liveTailActive) {
      return;
    }
    const s_0 = scrollRef.current;
    if (!s_0?.isSticky()) {
      return;
    }
    s_0.setClampBounds(undefined, undefined);
    s_0.scrollToBottom();
  }, [liveTailActive, scrollRef, virtualHistory.bottomSpacer, virtualHistory.end, virtualHistory.offsets, virtualHistory.topSpacer, virtualRows.length]);
  return {
    virtualHistory,
    virtualRows
  };
}