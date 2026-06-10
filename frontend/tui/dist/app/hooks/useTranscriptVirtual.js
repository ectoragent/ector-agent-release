import { MANUAL_SCROLL_GRACE_MS, maxScrollTop } from '@ector/ink';
import { useStore } from '@nanostores/react';
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import { FULL_RENDER_TAIL_ITEMS } from '../../config/limits.js';
import { TYPING_IDLE_MS } from '../../config/timing.js';
import { sectionMode } from '../../domain/details.js';
import { useVirtualHistory } from '../../hooks/useVirtualHistory.js';
import { getViewportSnapshot } from '../../lib/viewportStore.js';
import { estimatedMsgHeight, isHeavyTranscriptMessage, messageHeightKey } from '../../lib/virtualHeights.js';
import { shouldClearHeightCacheOnBusyEnd, shouldFollowNewHistoryAtBottom } from '../transcriptVirtualLogic.js';
import { turnController } from '../turnController.js';
import { $uiState } from '../uiStore.js';
const MAX_HEIGHT_CACHE_BUCKETS = 12;
const CHASE_BOTTOM_MAX_FRAMES = 8;
const CHASE_BOTTOM_LARGE_HISTORY = 40;
const CHASE_BOTTOM_LARGE_FRAMES = 2;
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
  const lastManualScrollAtRef = useRef(0);
  const scrollBoostTimerRef = useRef(null);
  useEffect(() => {
    const s = scrollRef.current;
    if (!s) {
      return;
    }
    const unsub = s.subscribe(() => {
      const manualAt = s.getLastManualScrollAt();
      if (!manualAt || manualAt === lastManualScrollAtRef.current || !busy) {
        return;
      }
      lastManualScrollAtRef.current = manualAt;
      turnController.boostStreamingForScroll();
      clearTimeout(scrollBoostTimerRef.current ?? undefined);
      scrollBoostTimerRef.current = setTimeout(() => {
        scrollBoostTimerRef.current = null;
        turnController.relaxStreaming();
      }, TYPING_IDLE_MS);
    });
    return () => {
      clearTimeout(scrollBoostTimerRef.current ?? undefined);
      scrollBoostTimerRef.current = null;
      unsub();
    };
  }, [busy, scrollRef]);
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
    const s_0 = scrollRef.current;
    if (!s_0) {
      return;
    }
    s_0.setClampBounds(undefined, undefined);
    const vp = Math.max(0, s_0.getViewportHeight());
    if (contentHeight != null && contentHeight > 0 && vp > 0) {
      s_0.scrollTo(Math.max(0, contentHeight - vp));
      return;
    }
    s_0.scrollToBottom();
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
      const s_1 = scrollRef.current;
      const snap = getViewportSnapshot(s_1);
      transcriptLenRef.current = len;
      if (s_1 && shouldFollowNewHistoryAtBottom({
        atBottom: snap.atBottom,
        isSticky: s_1.isSticky(),
        lastManualScrollAt: s_1.getLastManualScrollAt() || 0,
        manualGraceMs: MANUAL_SCROLL_GRACE_MS,
        now: Date.now(),
        viewportHeight: snap.viewportHeight
      })) {
        scrollTranscriptToBottom(virtualHistory.offsets[len] ?? 0);
      }
    } else {
      transcriptLenRef.current = len;
    }
  }, [historyItems.length, scrollRef, scrollTranscriptToBottom, sid]);
  useEffect(() => {
    if (!chaseBottomRef.current) {
      return;
    }
    let cancelled = false;
    let frames = 0;
    const maxFrames = historyItems.length >= CHASE_BOTTOM_LARGE_HISTORY ? CHASE_BOTTOM_LARGE_FRAMES : CHASE_BOTTOM_MAX_FRAMES;
    const chase = () => {
      if (cancelled || frames++ > maxFrames) {
        chaseBottomRef.current = false;
        return;
      }
      const s_2 = scrollRef.current;
      if (s_2 && Date.now() - s_2.getLastManualScrollAt() < 2500) {
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
  }, [historyItems.length, scrollRef, scrollTranscriptToBottom, sid]);
  useLayoutEffect(() => {
    if (!liveTailActive) {
      return;
    }
    const s_3 = scrollRef.current;
    if (!s_3) {
      return;
    }
    // scrollBy clears stickyScroll; do not snap back while the user reads
    // history (each stream paint used to call scrollToBottom and felt stuck).
    if (!s_3.isSticky() || Date.now() - s_3.getLastManualScrollAt() < MANUAL_SCROLL_GRACE_MS) {
      return;
    }
    const scrollH = Math.max(s_3.getScrollHeight(), s_3.getFreshScrollHeight?.() ?? 0);
    const vp_0 = Math.max(0, s_3.getViewportHeight());
    const maxTop = maxScrollTop(scrollH, vp_0);
    const cur = s_3.getScrollTop() + s_3.getPendingDelta();
    // Already docked — skip redundant scrollTo (was causing micro-jitter at bottom).
    if (cur >= maxTop - 1) {
      return;
    }
    s_3.setClampBounds(undefined, undefined);
    s_3.scrollTo(maxTop);
  }, [liveTailActive, scrollRef, virtualHistory.bottomSpacer, virtualHistory.end, virtualHistory.offsets, virtualHistory.topSpacer, virtualRows.length]);
  return {
    virtualHistory,
    virtualRows
  };
}