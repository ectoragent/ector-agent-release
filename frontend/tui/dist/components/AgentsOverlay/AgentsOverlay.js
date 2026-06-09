import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Box, NoSelect, ScrollBox, Text, useInput, useStdout } from '@ector/ink';
import { useStore } from '@nanostores/react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { $delegationState, applyDelegationStatus } from '../../app/delegationStore.js';
import { $spawnDiff, $spawnHistory, clearDiffPair } from '../../app/spawnHistoryStore.js';
import { useTurnSelector } from '../../app/turnStore.js';
import { asRpcResult } from '../../lib/rpc.js';
import { buildSubagentTree, descendantIds, formatSummary, peakHotness, sparkline, treeTotals, widthByDepth } from '../../lib/subagentTree.js';
import { Detail } from './components/Detail/index.js';
import { DiffView } from './components/DiffView/index.js';
import { GanttStrip } from './components/GanttStrip/index.js';
import { ListRow } from './components/ListRow/index.js';
import { OverlayScrollbar } from './components/OverlayScrollbar/index.js';
import { FILTER_LABEL, FILTER_ORDER, SORT_LABEL, SORT_ORDER } from './lib/overlayConstants.js';
import { cycle, formatRowId, prepareRows } from './lib/overlayRows.js';
export { closeAgentsOverlay, openAgentsOverlay } from './agentsOverlayActions.js';
export function AgentsOverlay({
  gw,
  initialHistoryIndex = 0,
  onClose,
  t
}) {
  const liveSubagents = useTurnSelector(state => state.subagents);
  const delegation = useStore($delegationState);
  const history = useStore($spawnHistory);
  const diffPair = useStore($spawnDiff);
  const {
    stdout
  } = useStdout();
  // historyIndex === 0: live turn.  1..N pulls the Nth-most-recent archived
  // snapshot.  /replay passes N on open.
  const [historyIndex, setHistoryIndex] = useState(() => Math.max(0, Math.min(history.length, Math.floor(initialHistoryIndex))));
  const [sort, setSort] = useState('depth-first');
  const [filter, setFilter] = useState('all');
  const [cursor, setCursor] = useState(0);
  const [flash, setFlash] = useState('');
  const [now, setNow] = useState(() => Date.now());
  // cc-style view switching: list = full-width row picker, detail = full-width
  // scrollable pane.  Two panes side-by-side in Ink fought Yoga flex.
  const [mode, setMode] = useState('list');
  const detailScrollRef = useRef(null);
  const prevLiveCountRef = useRef(liveSubagents.length);
  // ── Derived state ──────────────────────────────────────────────────
  const activeSnapshot = historyIndex > 0 ? history[historyIndex - 1] : null;
  // Instant fallback to history[0] the moment the live list clears — avoids
  // a one-frame "no subagents" flash while the auto-follow effect fires.
  const justFinishedSnapshot = historyIndex === 0 && liveSubagents.length === 0 ? history[0] ?? null : null;
  const effectiveSnapshot = activeSnapshot ?? justFinishedSnapshot;
  const replayMode = effectiveSnapshot != null;
  const subagents = replayMode ? effectiveSnapshot.subagents : liveSubagents;
  const tree = useMemo(() => buildSubagentTree(subagents), [subagents]);
  const totals = useMemo(() => treeTotals(tree), [tree]);
  const widths = useMemo(() => widthByDepth(tree), [tree]);
  const spark = useMemo(() => sparkline(widths), [widths]);
  const peak = useMemo(() => peakHotness(tree), [tree]);
  const rows = useMemo(() => prepareRows(tree, sort, filter), [tree, sort, filter]);
  const selected = rows[cursor] ?? null;
  const cols = stdout?.columns ?? 80;
  const rowsH = Math.max(8, (stdout?.rows ?? 24) - 10);
  const listWindowStart = Math.max(0, cursor - Math.floor(rowsH / 2));
  // ── Effects ────────────────────────────────────────────────────────
  useEffect(() => {
    // Ticker drives both the live gantt and OverlayScrollbar content-reflow
    // detection.  Slower in replay (nothing's growing) but not stopped
    // because accordions still expand.
    const id = setInterval(() => setNow(Date.now()), replayMode ? 300 : 500);
    return () => clearInterval(id);
  }, [replayMode]);
  useEffect(() => {
    // Clamp stale index when history grows/shrinks beneath us.
    if (historyIndex > history.length) {
      setHistoryIndex(history.length);
    }
  }, [history.length, historyIndex]);
  useEffect(() => {
    // Auto-follow the just-finished turn onto history[1] so the user isn't
    // dropped into an empty live view.  Fires only when transitioning from
    // "had live subagents" → "live empty" while in live mode.
    const prev = prevLiveCountRef.current;
    prevLiveCountRef.current = liveSubagents.length;
    if (historyIndex === 0 && prev > 0 && liveSubagents.length === 0 && history.length > 0) {
      setHistoryIndex(1);
      setCursor(0);
      setFlash('turno concluído · navegue à vontade · q para fechar');
    }
  }, [history.length, historyIndex, liveSubagents.length]);
  useEffect(() => {
    // Reset detail scroll on navigation so the top of the new node shows.
    detailScrollRef.current?.scrollTo(0);
  }, [cursor, historyIndex, mode]);
  useEffect(() => {
    // Warm caps + paused flag on open.
    gw.request('delegation.status', {}).then(r => applyDelegationStatus(asRpcResult(r))).catch(() => {});
  }, [gw]);
  useEffect(() => {
    if (cursor >= rows.length) {
      setCursor(Math.max(0, rows.length - 1));
    }
  }, [cursor, rows.length]);
  // ── Actions ────────────────────────────────────────────────────────
  const guardLive = action => {
    if (replayMode) {
      setFlash('modo replay — controles desativados');
    } else {
      action();
    }
  };
  const interrupt = id_0 => gw.request('subagent.interrupt', {
    subagent_id: id_0
  });
  const killOne = id_1 => guardLive(() => {
    interrupt(id_1).then(raw => {
      const r_0 = asRpcResult(raw);
      setFlash(r_0?.found ? `encerrando ${id_1}` : `não encontrado: ${id_1}`);
    }).catch(() => setFlash(`falha ao encerrar: ${id_1}`));
  });
  const killSubtree = node => guardLive(() => {
    const ids = [node.item.id, ...descendantIds(node)];
    ids.forEach(id_2 => interrupt(id_2).catch(() => {}));
    setFlash(`encerrando subárvore · ${ids.length} nó${ids.length === 1 ? '' : 's'}`);
  });
  const togglePause = () => guardLive(() => {
    gw.request('delegation.pause', {
      paused: !delegation.paused
    }).then(raw_0 => {
      const r_1 = asRpcResult(raw_0);
      applyDelegationStatus({
        paused: r_1?.paused
      });
      setFlash(r_1?.paused ? 'spawn pausado' : 'spawn retomado');
    }).catch(() => setFlash('falha ao pausar'));
  });
  const stepHistory = delta => setHistoryIndex(idx => {
    const next = Math.max(0, Math.min(history.length, idx + delta));
    if (next !== idx) {
      setCursor(0);
      setFlash(next === 0 ? 'turno ao vivo' : `reprodução · ${next}/${history.length}`);
    }
    return next;
  });
  const closeWithCleanup = () => {
    clearDiffPair();
    onClose();
  };
  // ── Input ──────────────────────────────────────────────────────────
  const detailPageSize = Math.max(4, rowsH - 2);
  const wheelDetailDy = 3;
  const scrollDetail = dy => detailScrollRef.current?.scrollBy(dy);
  useInput((ch, key) => {
    if (ch === 'q') {
      return closeWithCleanup();
    }
    if (key.escape) {
      return mode === 'detail' ? setMode('list') : closeWithCleanup();
    }
    // Shared actions (both modes).
    if (ch === '<' || ch === '[') {
      return stepHistory(1);
    }
    if (ch === '>' || ch === ']') {
      return stepHistory(-1);
    }
    if (ch === 'p') {
      return togglePause();
    }
    if (ch === 'x' && selected) {
      return killOne(selected.item.id);
    }
    if (ch === 'X' && selected) {
      return killSubtree(selected);
    }
    if (mode === 'detail') {
      if (key.leftArrow || ch === 'h') {
        return setMode('list');
      }
      if (key.pageUp || key.ctrl && ch === 'u') {
        return scrollDetail(-detailPageSize);
      }
      if (key.pageDown || key.ctrl && ch === 'd') {
        return scrollDetail(detailPageSize);
      }
      if (key.wheelUp) {
        return scrollDetail(-wheelDetailDy);
      }
      if (key.wheelDown) {
        return scrollDetail(wheelDetailDy);
      }
      if (key.upArrow || ch === 'k') {
        return scrollDetail(-2);
      }
      if (key.downArrow || ch === 'j') {
        return scrollDetail(2);
      }
      if (ch === 'g') {
        return detailScrollRef.current?.scrollTo(0);
      }
      if (ch === 'G') {
        return detailScrollRef.current?.scrollToBottom?.();
      }
      return;
    }
    // List mode.
    if ((key.return || key.rightArrow || ch === 'l') && selected) {
      return setMode('detail');
    }
    if (key.upArrow || ch === 'k' || key.wheelUp) {
      return setCursor(c => Math.max(0, c - 1));
    }
    if (key.downArrow || ch === 'j' || key.wheelDown) {
      return setCursor(c_0 => Math.min(Math.max(0, rows.length - 1), c_0 + 1));
    }
    if (ch === 'g') {
      return setCursor(0);
    }
    if (ch === 'G') {
      return setCursor(Math.max(0, rows.length - 1));
    }
    if (ch === 's') {
      return setSort(m => cycle(SORT_ORDER, m));
    }
    if (ch === 'f') {
      return setFilter(m_0 => cycle(FILTER_ORDER, m_0));
    }
  });
  // ── Header assembly ────────────────────────────────────────────────
  const mix = Object.entries(subagents.reduce((acc, it) => {
    const key_0 = it.model ? it.model.split('/').pop() : 'herança';
    acc[key_0] = (acc[key_0] ?? 0) + 1;
    return acc;
  }, {})).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([k, v]) => `${k}×${v}`).join(' · ');
  const capsLabel = delegation.maxSpawnDepth ? `caps d${delegation.maxSpawnDepth}/${delegation.maxConcurrentChildren ?? '?'}` : '';
  const title = replayMode && effectiveSnapshot ? `${historyIndex > 0 ? `Reprodução ${historyIndex}/${history.length}` : 'Último turno'} · concluído ${new Date(effectiveSnapshot.finishedAt).toLocaleTimeString()}` : `Árvore de spawn${delegation.paused ? ' · ⏸ pausado' : ''}`;
  const metaLine = [formatSummary(totals), spark, capsLabel, mix ? `· ${mix}` : ''].filter(Boolean).join('  ');
  const controlsHint = replayMode ? ' · controles bloqueados' : ` · x encerrar · X subárvore · p ${delegation.paused ? 'retomar' : 'pausar'}`;
  // ── Rendering ──────────────────────────────────────────────────────
  if (diffPair) {
    return _jsx(DiffView, {
      cols: cols,
      onClose: closeWithCleanup,
      pair: diffPair,
      t: t
    });
  }
  return _jsxs(Box, {
    alignItems: "stretch",
    flexDirection: "column",
    flexGrow: 1,
    paddingX: 1,
    paddingY: 1,
    children: [_jsx(Box, {
      flexDirection: "column",
      marginBottom: 1,
      children: _jsxs(Text, {
        wrap: "truncate-end",
        children: [_jsx(Text, {
          bold: true,
          color: replayMode ? t.color.border : t.color.title,
          children: title
        }), metaLine ? _jsxs(Text, {
          color: t.color.dim,
          children: ['   ', metaLine]
        }) : null]
      })
    }), rows.length === 0 ? _jsx(Box, {
      flexDirection: "column",
      flexGrow: 1,
      children: _jsx(Text, {
        color: t.color.dim,
        children: "Nenhum subagente neste turno. Use delegate_task para popular a \u00E1rvore."
      })
    }) : mode === 'list' ? _jsxs(Box, {
      flexDirection: "column",
      flexGrow: 1,
      flexShrink: 1,
      minHeight: 0,
      children: [_jsx(GanttStrip, {
        cols: cols,
        cursor: cursor,
        flatNodes: rows,
        maxRows: 6,
        now: now,
        t: t
      }), _jsx(Box, {
        flexDirection: "column",
        flexGrow: 0,
        flexShrink: 0,
        overflow: "hidden",
        children: rows.slice(listWindowStart, listWindowStart + rowsH).map((node_0, i) => _jsx(ListRow, {
          active: listWindowStart + i === cursor,
          index: listWindowStart + i,
          node: node_0,
          peak: peak,
          t: t,
          width: cols
        }, node_0.item.id))
      })]
    }) : _jsxs(Box, {
      flexDirection: "row",
      flexGrow: 1,
      flexShrink: 1,
      minHeight: 0,
      children: [_jsx(ScrollBox, {
        flexDirection: "column",
        flexGrow: 1,
        flexShrink: 1,
        ref: detailScrollRef,
        children: _jsx(Box, {
          flexDirection: "column",
          paddingBottom: 4,
          paddingRight: 1,
          children: selected ? _jsx(Detail, {
            id: formatRowId(cursor).trim(),
            node: selected,
            t: t
          }) : null
        })
      }), _jsx(NoSelect, {
        flexShrink: 0,
        marginLeft: 1,
        children: _jsx(OverlayScrollbar, {
          scrollRef: detailScrollRef,
          t: t,
          tick: now
        })
      })]
    }), _jsxs(Box, {
      flexDirection: "column",
      marginTop: 1,
      children: [flash ? _jsx(Text, {
        color: t.color.cyan,
        children: flash
      }) : null, mode === 'list' ? _jsxs(Text, {
        color: t.color.dim,
        children: ["\u2191\u2193/jk mover \u00B7 g/G topo/fim \u00B7 Enter/\u2192 abrir detalhe", controlsHint, " \u00B7 s ordenar:", SORT_LABEL[sort], " \u00B7 f filtro:", FILTER_LABEL[filter], history.length > 0 ? ` · [ / ] histórico ${historyIndex}/${history.length}` : '', ' · q fechar']
      }) : _jsxs(Text, {
        color: t.color.dim,
        children: ["\u2191\u2193/jk rolar \u00B7 PgUp/PgDn p\u00E1gina \u00B7 g/G topo/fim \u00B7 Esc/\u2190 voltar \u00E0 lista", controlsHint, " \u00B7 q fechar"]
      })]
    })]
  });
}