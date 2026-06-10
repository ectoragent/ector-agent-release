import { useInput } from '@ector/ink';
import { useStore } from '@nanostores/react';
import { useEffect, useRef } from 'react';
import { CTRL_C_DOUBLE_TAP_MS } from '../config/input.js';
import { TYPING_IDLE_MS } from '../config/timing.js';
import { strings } from '../content/strings.js';
import { STATUS } from '../content/uiStatus.js';
import { isAction, isCopyShortcut, isMac, isVoiceToggleKey } from '../lib/platform.js';
import { computeWheelStep, initWheelAccelForHost } from '../lib/wheelAccel.js';
import { resolveCtrlCAction } from './inputHandlersLogic.js';
import { getInputSelection } from './inputSelectionStore.js';
import { $isBlocked, $overlayState, patchOverlayState } from './overlayStore.js';
import { turnController } from './turnController.js';
import { patchTurnState } from './turnStore.js';
import { getUiState, patchUiState } from './uiStore.js';
const isCtrl = (key, ch, target) => key.ctrl && ch.toLowerCase() === target;
export function useInputHandlers(ctx) {
  const {
    actions,
    composer,
    gateway,
    terminal,
    voice,
    wheelStep
  } = ctx;
  const {
    actions: cActions,
    refs: cRefs,
    state: cState
  } = composer;
  const overlay = useStore($overlayState);
  const isBlocked = useStore($isBlocked);
  const pagerPageSize = Math.max(5, (terminal.stdout?.rows ?? 24) - 6);
  const scrollIdleTimer = useRef(null);
  const pendingScrollRef = useRef(0);
  const scrollRafRef = useRef(null);
  const lastCtrlCRef = useRef(0);
  // Wheel accel ported from claude-code: inter-event timing drives step size,
  // direction flips reset. wheelStep (WHEEL_SCROLL_STEP) is the base; final
  // rows = wheelStep × accelMult. State mutates in place across renders.
  const wheelAccelRef = useRef(initWheelAccelForHost());
  useEffect(() => () => {
    clearTimeout(scrollIdleTimer.current ?? undefined);
    if (scrollRafRef.current !== null) {
      cancelAnimationFrame(scrollRafRef.current);
    }
  }, []);
  const relaxScrollBoost = () => {
    clearTimeout(scrollIdleTimer.current ?? undefined);
    scrollIdleTimer.current = setTimeout(() => {
      scrollIdleTimer.current = null;
      turnController.relaxStreaming();
    }, TYPING_IDLE_MS);
  };
  const boostScrollWhileBusy = () => {
    if (!getUiState().busy) {
      return;
    }
    turnController.boostStreamingForScroll();
    relaxScrollBoost();
  };
  const flushPendingScroll = () => {
    scrollRafRef.current = null;
    const delta = pendingScrollRef.current;
    pendingScrollRef.current = 0;
    if (!delta) {
      return;
    }
    boostScrollWhileBusy();
    terminal.scrollWithSelection(delta);
  };
  const scrollTranscript = delta_0 => {
    if (!delta_0) {
      return;
    }
    pendingScrollRef.current += delta_0;
    if (scrollRafRef.current !== null) {
      return;
    }
    scrollRafRef.current = requestAnimationFrame(flushPendingScroll);
  };
  const copySelection = () => {
    void terminal.selection.copySelection();
  };
  const clearSelection = () => {
    terminal.selection.clearSelection();
  };
  const cancelOverlayFromCtrlC = () => {
    if (overlay.wiser) {
      return actions.answerWiser('');
    }
    if (overlay.approval) {
      return gateway.rpc('approval.respond', {
        choice: 'deny',
        session_id: getUiState().sid
      }).then(r => r && (patchOverlayState({
        approval: null
      }), patchTurnState({
        outcome: 'denied'
      })));
    }
    if (overlay.sudo) {
      return gateway.rpc('sudo.respond', {
        password: '',
        request_id: overlay.sudo.requestId
      }).then(r_0 => r_0 && (patchOverlayState({
        sudo: null
      }), actions.sys('sudo cancelled')));
    }
    if (overlay.secret) {
      return gateway.rpc('secret.respond', {
        request_id: overlay.secret.requestId,
        value: ''
      }).then(r_1 => r_1 && (patchOverlayState({
        secret: null
      }), actions.sys('secret entry cancelled')));
    }
    if (overlay.modelPicker) {
      return patchOverlayState({
        modelPicker: false
      });
    }
    if (overlay.skillsHub) {
      return patchOverlayState({
        skillsHub: false
      });
    }
    if (overlay.picker) {
      return patchOverlayState({
        picker: false
      });
    }
    if (overlay.agents) {
      return patchOverlayState({
        agents: false
      });
    }
  };
  const overlayCtrlCOrQuit = () => {
    const now = Date.now();
    if (now - lastCtrlCRef.current < CTRL_C_DOUBLE_TAP_MS) {
      actions.die();
      return;
    }
    lastCtrlCRef.current = now;
    cancelOverlayFromCtrlC();
  };
  const cycleQueue = dir => {
    const len = cRefs.queueRef.current.length;
    if (!len) {
      return false;
    }
    const index = cState.queueEditIdx === null ? dir > 0 ? 0 : len - 1 : (cState.queueEditIdx + dir + len) % len;
    cActions.setQueueEdit(index);
    cActions.setHistoryIdx(null);
    cActions.setInput(cRefs.queueRef.current[index] ?? '');
    return true;
  };
  const cycleHistory = dir_0 => {
    const h = cRefs.historyRef.current;
    const cur = cState.historyIdx;
    if (dir_0 < 0) {
      if (!h.length) {
        return;
      }
      if (cur === null) {
        cRefs.historyDraftRef.current = cState.input;
      }
      const index_0 = cur === null ? h.length - 1 : Math.max(0, cur - 1);
      cActions.setHistoryIdx(index_0);
      cActions.setQueueEdit(null);
      cActions.setInput(h[index_0] ?? '');
      return;
    }
    if (cur === null) {
      return;
    }
    const next = cur + 1;
    if (next >= h.length) {
      cActions.setHistoryIdx(null);
      cActions.setInput(cRefs.historyDraftRef.current);
    } else {
      cActions.setHistoryIdx(next);
      cActions.setInput(h[next] ?? '');
    }
  };
  // CLI parity: Ctrl+B toggles the VAD-driven continuous recording loop
  // (NOT the voice-mode umbrella bit). The mode is enabled via /voice on;
  // Ctrl+B while the mode is off sys-nudges the user. While the mode is
  // on, the first press starts a continuous loop (gateway → start_continuous,
  // VAD auto-stop → transcribe → auto-restart), a subsequent press stops it.
  // The gateway publishes voice.status + voice.transcript events that
  // createGatewayEventHandler turns into UI badges and composer injection.
  const voiceRecordToggle = () => {
    if (!voice.enabled) {
      return actions.sys('voice: mode is off — enable with /voice on');
    }
    const starting = !voice.recording;
    const action = starting ? 'start' : 'stop';
    // Optimistic UI — flip the REC badge immediately so the user gets
    // feedback while the RPC round-trips; the voice.status event is the
    // authoritative source and may correct us.
    if (starting) {
      voice.setRecording(true);
    } else {
      voice.setRecording(false);
      voice.setProcessing(false);
    }
    gateway.rpc('voice.record', {
      action
    }).catch(e => {
      // Revert optimistic UI on failure.
      if (starting) {
        voice.setRecording(false);
      }
      actions.sys(`voice error: ${e.message}`);
    });
  };
  useInput((ch, key) => {
    const live = getUiState();
    if (key.wheelUp || key.wheelDown) {
      const dir_1 = key.wheelUp ? -1 : 1;
      const rows = computeWheelStep(wheelAccelRef.current, dir_1, Date.now());
      if (rows) {
        return scrollTranscript(dir_1 * rows * wheelStep);
      }
    }
    if (isBlocked) {
      // When approval/wiser/confirm/sudo/secret overlays are active, their own
      // useInput handlers must receive keystrokes (arrow keys, numbers, Enter).
      // Only intercept Ctrl+C here so the user can deny/dismiss — all other
      // keys fall through to the component-level handlers.
      if (overlay.approval || overlay.wiser || overlay.confirm || overlay.sudo || overlay.secret) {
        if (isCtrl(key, ch, 'c')) {
          overlayCtrlCOrQuit();
        }
        return;
      }
      if (overlay.pager) {
        if (key.escape || isCtrl(key, ch, 'c') || ch === 'q') {
          return patchOverlayState({
            pager: null
          });
        }
        const move = delta_1 => patchOverlayState(prev => {
          if (!prev.pager) {
            return prev;
          }
          const {
            lines,
            offset
          } = prev.pager;
          const max = Math.max(0, lines.length - pagerPageSize);
          const step = delta_1 === 'top' ? -lines.length : delta_1 === 'bottom' ? lines.length : delta_1;
          const next_0 = Math.max(0, Math.min(offset + step, max));
          return next_0 === offset ? prev : {
            ...prev,
            pager: {
              ...prev.pager,
              offset: next_0
            }
          };
        });
        if (key.upArrow || ch === 'k') {
          return move(-1);
        }
        if (key.downArrow || ch === 'j') {
          return move(1);
        }
        if (key.pageUp || ch === 'b') {
          return move(-pagerPageSize);
        }
        if (ch === 'g') {
          return move('top');
        }
        if (ch === 'G') {
          return move('bottom');
        }
        if (key.return || ch === ' ' || key.pageDown) {
          patchOverlayState(prev_0 => {
            if (!prev_0.pager) {
              return prev_0;
            }
            const {
              lines: lines_0,
              offset: offset_0
            } = prev_0.pager;
            const max_0 = Math.max(0, lines_0.length - pagerPageSize);
            // Auto-close only when already at the last page — otherwise clamp
            // to `max` so the offset matches what the line/page-back handlers
            // can reach (prevents a snap-back jump on the next ↑/↓/PgUp).
            return offset_0 >= max_0 ? {
              ...prev_0,
              pager: null
            } : {
              ...prev_0,
              pager: {
                ...prev_0.pager,
                offset: Math.min(offset_0 + pagerPageSize, max_0)
              }
            };
          });
        }
        return;
      }
      if (overlay.picker || overlay.modelPicker || overlay.skillsHub) {
        if (key.escape || ch === 'q') {
          patchOverlayState({
            ...(overlay.picker ? {
              picker: false
            } : {}),
            ...(overlay.modelPicker ? {
              modelPicker: false
            } : {}),
            ...(overlay.skillsHub ? {
              skillsHub: false
            } : {})
          });
          return;
        }
        if (isCtrl(key, ch, 'c')) {
          overlayCtrlCOrQuit();
          return;
        }
        // Setas/Enter/dígitos ficam com SessionPicker, ModelPicker e SkillsHub.
      } else if (overlay.agents) {
        if (key.escape || ch === 'q') {
          patchOverlayState({
            agents: false
          });
          return;
        }
        if (isCtrl(key, ch, 'c')) {
          overlayCtrlCOrQuit();
          return;
        }
      }
    }
    if (cState.completions.length && cState.input && cState.historyIdx === null && (key.upArrow || key.downArrow)) {
      const len_0 = cState.completions.length;
      cActions.setCompIdx(i => key.upArrow ? (i - 1 + len_0) % len_0 : (i + 1) % len_0);
      return;
    }
    if (key.shift && key.upArrow) {
      return scrollTranscript(-wheelStep * 3);
    }
    if (key.shift && key.downArrow) {
      return scrollTranscript(wheelStep * 3);
    }
    if (key.pageUp || key.pageDown) {
      // Half-viewport keeps 50% continuity and stays under Ink's
      // `delta < innerHeight` DECSTBM fast-path threshold.
      const viewport = terminal.scrollRef.current?.getViewportHeight() ?? Math.max(6, (terminal.stdout?.rows ?? 24) - 8);
      const step_0 = Math.max(4, Math.floor(viewport / 2));
      return scrollTranscript(key.pageUp ? -step_0 : step_0);
    }
    if (key.escape && terminal.hasSelection) {
      return clearSelection();
    }
    if (key.escape && live.returnSessionKey && live.sessionKey?.startsWith('bg_')) {
      actions.resumeById(live.returnSessionKey);
      return;
    }
    if (key.escape && live.bgTasks.size > 0 && !live.busy) {
      patchUiState({
        bgTasks: new Set()
      });
      actions.sys(strings.slash.backgroundDismissed);
      return;
    }
    if (key.escape && live.busy && live.sid) {
      return turnController.interruptTurn({
        appendMessage: actions.appendMessage,
        appendMessages: actions.appendMessages,
        gw: gateway.gw,
        sid: live.sid,
        sys: actions.sys
      });
    }
    if (key.upArrow && !cState.inputBuf.length) {
      const inputSel = getInputSelection();
      const cursor = inputSel && inputSel.start === inputSel.end ? inputSel.start : null;
      const noLineAbove = !cState.input || cursor !== null && cState.input.lastIndexOf('\n', Math.max(0, cursor - 1)) < 0;
      if (noLineAbove) {
        cycleQueue(1) || cycleHistory(-1);
        return;
      }
    }
    if (key.downArrow && !cState.inputBuf.length) {
      const inputSel_0 = getInputSelection();
      const cursor_0 = inputSel_0 && inputSel_0.start === inputSel_0.end ? inputSel_0.start : null;
      const noLineBelow = !cState.input || cursor_0 !== null && cState.input.indexOf('\n', cursor_0) < 0;
      if (noLineBelow || cState.historyIdx !== null) {
        cycleQueue(-1) || cycleHistory(1);
        return;
      }
    }
    if (isCopyShortcut(key, ch)) {
      if (terminal.hasSelection) {
        return copySelection();
      }
      const inputSel_1 = getInputSelection();
      if (inputSel_1 && inputSel_1.end > inputSel_1.start) {
        inputSel_1.clear();
        return;
      }
      // On macOS, Cmd+C with no selection is a no-op. On non-macOS, isAction uses Ctrl,
      // so fall through to clear-draft / exit only when the agent is idle.
      if (isMac) {
        return;
      }
    }
    if (key.ctrl && ch.toLowerCase() === 'c') {
      const now_0 = Date.now();
      const action_0 = resolveCtrlCAction({
        busy: live.busy,
        hasDraft: Boolean(cState.input || cState.inputBuf.length),
        hasSid: Boolean(live.sid),
        lastCtrlCAt: lastCtrlCRef.current,
        now: now_0,
        windowMs: CTRL_C_DOUBLE_TAP_MS
      });
      if (action_0 === 'clear_draft') {
        return cActions.clearIn();
      }
      if (action_0 === 'die') {
        return actions.die();
      }
      if (action_0 === 'interrupt' && live.sid) {
        lastCtrlCRef.current = now_0;
        return turnController.interruptTurn({
          appendMessage: actions.appendMessage,
          appendMessages: actions.appendMessages,
          gw: gateway.gw,
          sid: live.sid,
          sys: actions.sys
        });
      }
      return;
    }
    if (isAction(key, ch, 'd')) {
      return actions.die();
    }
    if (isAction(key, ch, 'l')) {
      if (actions.guardBusySessionSwitch()) {
        return;
      }
      patchUiState({
        status: STATUS.forgingSession
      });
      return actions.newSession();
    }
    if (isVoiceToggleKey(key, ch)) {
      return voiceRecordToggle();
    }
    // Cmd/Ctrl+G, plus Alt+G fallback for VSCode/Cursor (they bind the
    // primary keystroke to "Find Next" before the TUI sees it; Alt+G
    // arrives as meta+g across platforms).
    if (ch.toLowerCase() === 'g' && (isAction(key, ch, 'g') || key.meta)) {
      return void cActions.openEditor().catch(err => {
        actions.sys(err instanceof Error ? `failed to open editor: ${err.message}` : 'failed to open editor');
      });
    }
    // shift-tab flips yolo without spending a turn (claude-code parity)
    if (key.shift && key.tab && !cState.completions.length) {
      if (!live.sid) {
        return void actions.sys('yolo needs an active session');
      }
      // gateway.rpc swallows errors with its own sys() message and resolves to null,
      // so we only speak when it came back with a real shape. null = rpc already spoke.
      return void gateway.rpc('config.set', {
        key: 'yolo',
        session_id: live.sid
      }).then(r_2 => {
        if (r_2?.value === '1') {
          return actions.sys('yolo on');
        }
        if (r_2?.value === '0') {
          return actions.sys('yolo off');
        }
        if (r_2) {
          actions.sys('failed to toggle yolo');
        }
      });
    }
    if (key.tab && cState.completions.length) {
      const row = cState.completions[cState.compIdx];
      if (row?.text) {
        const text = cState.input.startsWith('/') && row.text.startsWith('/') && cState.compReplace > 0 ? row.text.slice(1) : row.text;
        cActions.setInput(cState.input.slice(0, cState.compReplace) + text);
      }
      return;
    }
    if (isAction(key, ch, 'k') && cRefs.queueRef.current.length && live.sid) {
      const next_1 = cActions.dequeue();
      if (next_1) {
        cActions.setQueueEdit(null);
        actions.dispatchSubmission(next_1);
      }
    }
  });
  return {
    pagerPageSize
  };
}