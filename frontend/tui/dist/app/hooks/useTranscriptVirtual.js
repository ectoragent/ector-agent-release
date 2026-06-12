import { MANUAL_SCROLL_GRACE_MS } from '@ector/ink';
import { useStore } from '@nanostores/react';
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import { TYPING_IDLE_MS } from '../../config/timing.js';
import { sectionMode } from '../../domain/details.js';
import { useVirtualHistory } from '../../hooks/useVirtualHistory.js';
import { getViewportSnapshot } from '../../lib/viewportStore.js';
import { messageHeightKey } from '../../lib/virtualHeights.js';
import { $isBlocked } from '../overlayStore.js';
import { buildInitialHeightEstimates, isAtVirtualBottom, shouldAutoScrollTail, shouldClearHeightCacheOnBusyEnd } from '../transcriptVirtualLogic.js';
import { turnController } from '../turnController.js';
import { useTurnSelector } from '../turnStore.js';
import { $uiState } from '../uiStore.js';
const MAX_HEIGHT_CACHE_BUCKETS = 12;
const CHASE_BOTTOM_MAX_FRAMES = 12;
const CHASE_BOTTOM_LARGE_HISTORY = 40;
const CHASE_BOTTOM_LARGE_FRAMES = 8;
const CHASE_BOTTOM_RESUME_FRAMES = 32;
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
  const isBlocked = useStore($isBlocked);
  const streamingLiveTail = useTurnSelector(state => Boolean(state.streaming.trim()));
  const liveScrollFingerprint = useTurnSelector(state_0 => `${state_0.streaming.length}:${state_0.reasoning.length}:${state_0.streamSegments.length}`);
  const prevBusyRef = useRef(busy);
  const prevLiveTailRef = useRef(liveTailActive);
  const prevFlowBlockRef = useRef(isBlocked);
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
  const layoutEstKey = `${cols}:${compact ? '1' : '0'}:${detailsLayoutKey}`;
  const prevLayoutEstKeyRef = useRef('');
  const prevTotalRowsRef = useRef(0);
  const estimateCacheRef = useRef(new Map());
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
    const layoutChanged = prevLayoutEstKeyRef.current !== layoutEstKey;
    if (layoutChanged) {
      estimateCacheRef.current.clear();
      prevLayoutEstKeyRef.current = layoutEstKey;
    }
    const out = buildInitialHeightEstimates(virtualRows, {
      cols,
      compact,
      detailsVisible,
      heightCache,
      layoutChanged,
      prevEstimates: estimateCacheRef.current,
      prevTotalRows: prevTotalRowsRef.current
    });
    estimateCacheRef.current = out;
    prevTotalRowsRef.current = virtualRows.length;
    return out;
  }, [cols, compact, detailsVisible, heightCache, layoutEstKey, virtualRows]);
  const syncHeightCache = useCallback(heights => {
    for (const [key, h] of heights) {
      if (h) {
        heightCache.set(key, h);
      }
    }
  }, [heightCache]);
  const virtualHistory = useVirtualHistory(scrollRef, virtualRows, cols, {
    initialHeights,
    // Only growing stream text disables the bottomSpacer yoga cap — tools-only
    // live UI must keep the cap or virtual spacers balloon and corrupt the frame.
    liveTailActive: streamingLiveTail,
    onHeightsChange: syncHeightCache
  });
  const virtualTotal = virtualRows.length > 0 ? virtualHistory.offsets[virtualRows.length] ?? 0 : 0;
  const transcriptLenRef = useRef(0);
  const prevSidRef = useRef(undefined);
  const chaseBottomRef = useRef(false);
  const resumeScrollPendingRef = useRef(false);
  const tailFollowRef = useRef(true);
  const turnEndFollowLatchRef = useRef(false);
  const lastManualScrollAtRef = useRef(0);
  const scrollBoostTimerRef = useRef(null);
  const refreshTailFollow = useCallback(s => {
    const manualAt = s.getLastManualScrollAt() || 0;
    const now = Date.now();
    if (manualAt > 0 && now - manualAt < MANUAL_SCROLL_GRACE_MS) {
      tailFollowRef.current = false;
      turnEndFollowLatchRef.current = false;
      return;
    }
    const snap = getViewportSnapshot(s);
    const follow = shouldAutoScrollTail({
      atBottom: snap.atBottom,
      lastManualScrollAt: manualAt,
      manualGraceMs: MANUAL_SCROLL_GRACE_MS,
      now,
      viewportHeight: snap.viewportHeight
    });
    if (follow) {
      tailFollowRef.current = true;
      turnEndFollowLatchRef.current = false;
      return;
    }
    if (turnEndFollowLatchRef.current) {
      return;
    }
    tailFollowRef.current = false;
  }, []);
  useEffect(() => {
    const s_0 = scrollRef.current;
    if (!s_0) {
      return;
    }
    refreshTailFollow(s_0);
    const unsub = s_0.subscribe(() => {
      refreshTailFollow(s_0);
      const manualAt_0 = s_0.getLastManualScrollAt();
      if (!manualAt_0 || manualAt_0 === lastManualScrollAtRef.current || !busy) {
        return;
      }
      lastManualScrollAtRef.current = manualAt_0;
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
  }, [busy, refreshTailFollow, scrollRef]);
  useEffect(() => {
    const wasBusy = prevBusyRef.current;
    prevBusyRef.current = busy;
    if (wasBusy && !busy && tailFollowRef.current) {
      turnEndFollowLatchRef.current = true;
    }
    if (busy) {
      turnEndFollowLatchRef.current = false;
    }
    if (shouldClearHeightCacheOnBusyEnd(wasBusy, busy, sid)) {
      const prefix = `${sid}:`;
      for (const key_0 of heightCachesRef.current.keys()) {
        if (key_0.startsWith(prefix)) {
          heightCachesRef.current.delete(key_0);
        }
      }
      scrollRef.current?.setClampBounds(undefined, undefined);
    }
  }, [busy, scrollRef, sid]);
  const scrollTranscriptToBottom = useCallback(contentHeight => {
    const s_1 = scrollRef.current;
    if (!s_1) {
      return;
    }
    s_1.setClampBounds(undefined, undefined);
    const vp = Math.max(0, s_1.getViewportHeight());
    if (contentHeight != null && contentHeight > 0 && vp > 0) {
      s_1.scrollTo(Math.max(0, contentHeight - vp));
    } else {
      s_1.scrollToBottom();
    }
    refreshTailFollow(s_1);
  }, [refreshTailFollow, scrollRef]);
  useLayoutEffect(() => {
    const len = historyItems.length;
    const sidChanged = sid !== prevSidRef.current;
    if (sidChanged) {
      prevSidRef.current = sid;
      transcriptLenRef.current = len;
      if (sid && len > 0) {
        tailFollowRef.current = true;
        turnEndFollowLatchRef.current = false;
        chaseBottomRef.current = true;
        resumeScrollPendingRef.current = true;
        lastManualScrollAtRef.current = 0;
        scrollTranscriptToBottom(virtualTotal > 0 ? virtualTotal : undefined);
      }
      return;
    }
    if (len > transcriptLenRef.current) {
      const s_2 = scrollRef.current;
      transcriptLenRef.current = len;
      const follow_0 = tailFollowRef.current || turnEndFollowLatchRef.current;
      if (s_2 && follow_0) {
        scrollTranscriptToBottom();
        if (getViewportSnapshot(s_2).atBottom) {
          turnEndFollowLatchRef.current = false;
        }
      }
    } else {
      transcriptLenRef.current = len;
    }
  }, [historyItems.length, scrollRef, scrollTranscriptToBottom, sid, virtualTotal, virtualRows.length]);
  useLayoutEffect(() => {
    if (prevLiveTailRef.current && !liveTailActive && tailFollowRef.current) {
      turnEndFollowLatchRef.current = true;
    }
    prevLiveTailRef.current = liveTailActive;
  }, [liveTailActive]);
  useLayoutEffect(() => {
    if (!resumeScrollPendingRef.current || !sid || historyItems.length === 0) {
      return;
    }
    const snap_0 = getViewportSnapshot(scrollRef.current);
    if (isAtVirtualBottom(snap_0, virtualTotal)) {
      resumeScrollPendingRef.current = false;
      chaseBottomRef.current = false;
      return;
    }
    chaseBottomRef.current = true;
    scrollTranscriptToBottom(virtualTotal > 0 ? virtualTotal : undefined);
  }, [historyItems.length, scrollRef, scrollTranscriptToBottom, sid, virtualTotal]);
  useEffect(() => {
    if (!chaseBottomRef.current) {
      return;
    }
    let cancelled = false;
    let frames = 0;
    const maxFrames = resumeScrollPendingRef.current ? CHASE_BOTTOM_RESUME_FRAMES : historyItems.length >= CHASE_BOTTOM_LARGE_HISTORY ? CHASE_BOTTOM_LARGE_FRAMES : CHASE_BOTTOM_MAX_FRAMES;
    const chase = () => {
      if (cancelled || frames++ > maxFrames) {
        chaseBottomRef.current = false;
        resumeScrollPendingRef.current = false;
        return;
      }
      const s_3 = scrollRef.current;
      if (s_3 && Date.now() - s_3.getLastManualScrollAt() < 2500) {
        chaseBottomRef.current = false;
        resumeScrollPendingRef.current = false;
        return;
      }
      const total = virtualRows.length > 0 ? virtualHistory.offsets[virtualRows.length] ?? 0 : 0;
      scrollTranscriptToBottom(total > 0 ? total : undefined);
      const snap_1 = getViewportSnapshot(scrollRef.current);
      if (isAtVirtualBottom(snap_1, total)) {
        chaseBottomRef.current = false;
        resumeScrollPendingRef.current = false;
        return;
      }
      requestAnimationFrame(chase);
    };
    requestAnimationFrame(chase);
    return () => {
      cancelled = true;
    };
  }, [historyItems.length, scrollRef, scrollTranscriptToBottom, sid, virtualHistory.offsets, virtualRows.length, virtualTotal]);
  useLayoutEffect(() => {
    if (!liveTailActive) {
      return;
    }
    const s_4 = scrollRef.current;
    if (!s_4) {
      return;
    }
    const snap_2 = getViewportSnapshot(s_4);
    const manualAt_1 = s_4.getLastManualScrollAt() || 0;
    if (!shouldAutoScrollTail({
      atBottom: snap_2.atBottom,
      lastManualScrollAt: manualAt_1,
      manualGraceMs: MANUAL_SCROLL_GRACE_MS,
      now: Date.now(),
      viewportHeight: snap_2.viewportHeight
    }) && !turnEndFollowLatchRef.current) {
      return;
    }
    scrollTranscriptToBottom();
    let frame = 0;
    let cancelled_0 = false;
    const settle = () => {
      if (cancelled_0 || frame++ > 3 || !tailFollowRef.current) {
        return;
      }
      scrollTranscriptToBottom();
      const snap_3 = getViewportSnapshot(scrollRef.current);
      if (!snap_3.atBottom) {
        requestAnimationFrame(settle);
      }
    };
    requestAnimationFrame(settle);
    return () => {
      cancelled_0 = true;
    };
  }, [liveTailActive, liveScrollFingerprint, scrollRef, scrollTranscriptToBottom]);
  useLayoutEffect(() => {
    const blockChanged = isBlocked !== prevFlowBlockRef.current;
    prevFlowBlockRef.current = isBlocked;
    if (!liveTailActive || !blockChanged) {
      return;
    }
    if (!tailFollowRef.current && !turnEndFollowLatchRef.current) {
      return;
    }
    scrollTranscriptToBottom();
    let frame_0 = 0;
    let cancelled_1 = false;
    const settle_0 = () => {
      if (cancelled_1 || frame_0++ > 3) {
        return;
      }
      scrollTranscriptToBottom();
      requestAnimationFrame(settle_0);
    };
    requestAnimationFrame(settle_0);
    return () => {
      cancelled_1 = true;
    };
  }, [isBlocked, liveTailActive, scrollRef, scrollTranscriptToBottom]);
  return {
    virtualHistory,
    virtualRows
  };
}