import { useApp, useHasSelection, useSelection, useTerminalTitle } from '@ector/ink';
import { useStore } from '@nanostores/react';
import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { STARTUP_RESUME_ID } from '../config/env.js';
import { WHEEL_SCROLL_STEP } from '../config/limits.js';
import { INTERRUPT_USER_LABEL, isComposerReady, STATUS } from '../content/uiStatus.js';
import { SECTION_NAMES, sectionMode } from '../domain/details.js';
import { attachedImageNotice, imageTokenMeta } from '../domain/messages.js';
import { capTranscriptHistory, isIntroDismissInteraction, withoutIntro } from '../domain/messages.js';
import { compactCwd, statusBarCwd } from '../domain/paths.js';
import { useGitBranch } from '../hooks/useGitBranch.js';
import { appendTranscriptMessage } from '../lib/messages.js';
import { asRpcResult, rpcErrorMessage } from '../lib/rpc.js';
import { forceProcessExit } from '../lib/gracefulExit.js';
import { terminalParityHints } from '../lib/terminalParity.js';
import { createGatewayEventHandler } from './createGatewayEventHandler.js';
import { createSlashHandler } from './createSlashHandler.js';
import { useGatewayLifecycle } from './hooks/useGatewayLifecycle.js';
import { useOverlayResponders } from './hooks/useOverlayResponders.js';
import { useStartupPrompt } from './hooks/useStartupPrompt.js';
import { useTerminalColumns } from './hooks/useTerminalColumns.js';
import { useTranscriptVirtual } from './hooks/useTranscriptVirtual.js';
import { $overlayState, patchOverlayState } from './overlayStore.js';
import { scrollWithSelectionBy } from './scroll.js';
import { turnController } from './turnController.js';
import { useTurnSelector } from './turnStore.js';
import { $uiState, getUiState, patchUiState } from './uiStore.js';
import { useComposerState } from './useComposerState.js';
import { useConfigSync } from './useConfigSync.js';
import { useInputHandlers } from './useInputHandlers.js';
import { useLongRunToolCharms } from './useLongRunToolCharms.js';
import { useSessionLifecycle } from './useSessionLifecycle.js';
import { useSubmission } from './useSubmission.js';
const GOOD_VIBES_RE = /\b(good bot|thanks|thank you|thx|ty|ily|love you)\b/i;
const statusColorOf = (status, t) => {
  if (status === STATUS.ready) {
    return t.statusReady;
  }
  if (status.toLowerCase().startsWith('error') || /^erro\s*:/i.test(status) || status.toLowerCase().startsWith('erro:')) {
    return t.error;
  }
  if (status === STATUS.interrupted || status === 'interrupted' || status === INTERRUPT_USER_LABEL) {
    return t.warn;
  }
  return t.dim;
};
export function useMainApp(gw) {
  useApp();
  const {
    cols,
    stdout
  } = useTerminalColumns(80);
  const [historyItems, setHistoryItems] = useState(() => [{
    kind: 'intro',
    role: 'system',
    text: ''
  }]);
  const [lastUserMsg, setLastUserMsg] = useState('');
  const [stickyPrompt, setStickyPrompt] = useState('');
  const [catalog, setCatalog] = useState(null);
  const [voiceEnabled, setVoiceEnabled] = useState(false);
  const [voiceRecording, setVoiceRecording] = useState(false);
  const [voiceProcessing, setVoiceProcessing] = useState(false);
  const [sessionStartedAt, setSessionStartedAt] = useState(() => Date.now());
  const [turnStartedAt, setTurnStartedAt] = useState(null);
  const [goodVibesTick, setGoodVibesTick] = useState(0);
  const [bellOnComplete, setBellOnComplete] = useState(false);
  const ui = useStore($uiState);
  const overlay = useStore($overlayState);
  const turnLiveTailActive = useTurnSelector(state => Boolean(state.streaming || state.streamPendingTools.length || state.streamSegments.length || state.reasoning.trim() || state.reasoningActive || state.tools.length || state.subagents.length || state.todos.length));
  const slashFlightRef = useRef(0);
  const slashRef = useRef(() => false);
  const colsRef = useRef(cols);
  const scrollRef = useRef(null);
  const clipboardPasteRef = useRef(() => {});
  const submitRef = useRef(() => {});
  const terminalHintsShownRef = useRef(new Set());
  const historyItemsRef = useRef(historyItems);
  const lastUserMsgRef = useRef(lastUserMsg);
  colsRef.current = cols;
  historyItemsRef.current = historyItems;
  lastUserMsgRef.current = lastUserMsg;
  const hasSelection = useHasSelection();
  const selection = useSelection();
  useEffect(() => {
    selection.setSelectionBgColor(ui.theme.color.selectionBg);
  }, [selection, ui.theme.color.selectionBg]);
  const composer = useComposerState({
    gw,
    onClipboardPaste: quiet => clipboardPasteRef.current(quiet),
    onImageAttached: info => {
      sys(attachedImageNotice(info));
    },
    submitRef
  });
  const {
    actions: composerActions,
    refs: composerRefs,
    state: composerState
  } = composer;
  const empty = !historyItems.some(msg => msg.kind !== 'intro');
  useEffect(() => {
    void terminalParityHints().then(hints => {
      for (const hint of hints) {
        if (terminalHintsShownRef.current.has(hint.key)) {
          continue;
        }
        terminalHintsShownRef.current.add(hint.key);
        turnController.pushActivity(hint.message, hint.tone);
      }
    }).catch(() => {});
  }, []);
  const {
    virtualHistory,
    virtualRows
  } = useTranscriptVirtual({
    cols,
    compact: ui.compact,
    detailsMode: ui.detailsMode,
    detailsModeCommandOverride: ui.detailsModeCommandOverride,
    historyItems,
    liveTailActive: turnLiveTailActive,
    scrollRef,
    sections: ui.sections,
    sid: ui.sid
  });
  const scrollWithSelection = useCallback(delta => scrollWithSelectionBy(delta, {
    scrollRef,
    selection
  }), [selection]);
  const foldTranscriptMessages = useCallback((prev, msgs) => {
    let next = prev;
    for (const msg_0 of msgs) {
      next = appendTranscriptMessage(next, msg_0);
      if (isIntroDismissInteraction(msg_0)) {
        next = withoutIntro(next);
      }
    }
    return capTranscriptHistory(next);
  }, []);
  const appendMessage = useCallback(msg_1 => setHistoryItems(prev_0 => foldTranscriptMessages(prev_0, [msg_1])), [foldTranscriptMessages]);
  const appendMessages = useCallback(msgs_0 => {
    if (!msgs_0.length) {
      return;
    }
    // Turn-end batches can be large (trail + assistant table) — defer so
    // streaming teardown (busy→false) paints before heavy history mount.
    startTransition(() => {
      setHistoryItems(prev_1 => foldTranscriptMessages(prev_1, msgs_0));
    });
  }, [foldTranscriptMessages]);
  const sys = useCallback(text => appendMessage({
    role: 'system',
    text
  }), [appendMessage]);
  const page = useCallback((text_0, title) => patchOverlayState({
    pager: {
      lines: text_0.split('\n'),
      offset: 0,
      title
    }
  }), []);
  const panel = useCallback((title_0, sections) => appendMessage({
    kind: 'panel',
    panelData: {
      sections,
      title: title_0
    },
    role: 'system',
    text: ''
  }), [appendMessage]);
  const maybeWarn = useCallback(value => {
    const warning = value?.warning;
    if (typeof warning === 'string' && warning) {
      sys(`warning: ${warning}`);
    }
  }, [sys]);
  const maybeGoodVibes = useCallback(text_1 => {
    if (GOOD_VIBES_RE.test(text_1)) {
      setGoodVibesTick(v => v + 1);
    }
  }, []);
  const rpc = useCallback(async (method, params = {}) => {
    try {
      const result = asRpcResult(await gw.request(method, params));
      if (result) {
        return result;
      }
      sys(`error: invalid response: ${method}`);
    } catch (e) {
      sys(`error: ${rpcErrorMessage(e)}`);
    }
    return null;
  }, [gw, sys]);
  const gateway = useMemo(() => ({
    gw,
    rpc
  }), [gw, rpc]);
  const die = useCallback(() => {
    forceProcessExit(130);
  }, []);
  const session = useSessionLifecycle({
    colsRef,
    composerActions,
    gw,
    panel,
    rpc,
    setHistoryItems,
    setLastUserMsg,
    setSessionStartedAt,
    setStickyPrompt,
    setVoiceProcessing,
    setVoiceRecording,
    sys
  });
  useEffect(() => {
    if (ui.busy) {
      setTurnStartedAt(prev_2 => prev_2 ?? Date.now());
    } else {
      setTurnStartedAt(null);
    }
  }, [ui.busy]);
  useConfigSync({
    gw,
    setBellOnComplete,
    setVoiceEnabled,
    sid: ui.sid
  });
  const terminalTitle = ui.sessionTitle ? `Ector | ${ui.sessionTitle}` : 'Ector';
  useTerminalTitle(terminalTitle);
  useEffect(() => {
    if (!ui.sid || !stdout) {
      return;
    }
    let timer;
    const onResize = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        timer = undefined;
        void rpc('terminal.resize', {
          cols: stdout.columns ?? 80,
          session_id: ui.sid
        });
      }, 100);
    };
    stdout.on('resize', onResize);
    return () => {
      clearTimeout(timer);
      stdout.off('resize', onResize);
    };
  }, [rpc, stdout, ui.sid]);
  const {
    answerApproval,
    answerSecret,
    answerSudo,
    answerWiser,
    onModelSelect
  } = useOverlayResponders({
    appendMessage,
    overlaySecret: overlay.secret,
    overlaySudo: overlay.sudo,
    overlayWiser: overlay.wiser,
    rpc,
    sessionId: ui.sid,
    slashRef,
    sys
  });
  const paste = useCallback((quiet_0 = false) => rpc('clipboard.paste', {
    session_id: getUiState().sid
  }).then(r => {
    if (!r) {
      return;
    }
    if (r.attached) {
      const meta = imageTokenMeta(r);
      return sys(`📎 Image #${r.count} attached from clipboard${meta ? ` · ${meta}` : ''}`);
    }
    if (!quiet_0) {
      sys(r.message || 'No image found in clipboard');
    }
  }), [rpc, sys]);
  clipboardPasteRef.current = paste;
  const {
    dispatchSubmission,
    send,
    sendQueued,
    submit
  } = useSubmission({
    appendMessage,
    appendMessages,
    composerActions,
    composerRefs,
    composerState,
    gw,
    maybeGoodVibes,
    setLastUserMsg,
    slashRef,
    submitRef,
    sys
  });
  useStartupPrompt(gw, submitRef, sys);
  // Drain one queued message whenever the session settles (busy → false):
  // agent turn ends, interrupt, shell.exec finishes, error recovered, or the
  // session first comes up with pre-queued messages. Without this, shell.exec
  // and error paths never emit message.complete, so anything enqueued while
  // `!sleep` / a failed turn was running would stay stuck forever.
  useEffect(() => {
    if (!isComposerReady(ui) || ui.busy || composerRefs.queueEditRef.current !== null || composerRefs.queueRef.current.length === 0) {
      return;
    }
    // Defer one tick so turn-end history paint (startTransition) can commit
    // before the next prompt re-claims busy.
    queueMicrotask(() => {
      if (!isComposerReady(getUiState()) || getUiState().busy || composerRefs.queueEditRef.current !== null || composerRefs.queueRef.current.length === 0) {
        return;
      }
      const next_0 = composerActions.dequeue();
      if (next_0) {
        patchUiState({
          busy: true,
          status: STATUS.running
        });
        sendQueued(next_0);
      }
    });
  }, [ui.sid, ui.busy, composerActions, composerRefs, sendQueued]);
  const {
    pagerPageSize
  } = useInputHandlers({
    actions: {
      answerWiser,
      appendMessage,
      appendMessages,
      die,
      dispatchSubmission,
      guardBusySessionSwitch: session.guardBusySessionSwitch,
      newSession: session.newSession,
      resumeById: session.resumeById,
      sys
    },
    composer: {
      actions: composerActions,
      refs: composerRefs,
      state: composerState
    },
    gateway,
    terminal: {
      hasSelection,
      scrollRef,
      scrollWithSelection,
      selection,
      stdout
    },
    voice: {
      enabled: voiceEnabled,
      recording: voiceRecording,
      setProcessing: setVoiceProcessing,
      setRecording: setVoiceRecording,
      setVoiceEnabled
    },
    wheelStep: WHEEL_SCROLL_STEP
  });
  const onEvent = useMemo(() => createGatewayEventHandler({
    composer: {
      setInput: composerActions.setInput
    },
    gateway,
    session: {
      STARTUP_RESUME_ID,
      closeSession: session.closeSession,
      colsRef,
      newSession: session.newSession,
      resetSession: session.resetSession,
      resumeById: session.resumeById,
      setCatalog
    },
    submission: {
      submitRef
    },
    system: {
      bellOnComplete,
      stdout,
      sys
    },
    transcript: {
      appendMessage,
      appendMessages,
      panel,
      setHistoryItems
    },
    voice: {
      setProcessing: setVoiceProcessing,
      setRecording: setVoiceRecording,
      setVoiceEnabled
    }
  }), [appendMessage, appendMessages, bellOnComplete, composerActions.setInput, gateway, panel, session.closeSession, session.newSession, session.resetSession, session.resumeById, setVoiceEnabled, setVoiceProcessing, setVoiceRecording, stdout, submitRef, sys]);
  useGatewayLifecycle(gw, onEvent, sys);
  useLongRunToolCharms();
  const slash = useMemo(() => createSlashHandler({
    composer: {
      enqueue: composerActions.enqueue,
      hasSelection,
      paste,
      queueRef: composerRefs.queueRef,
      selection,
      setInput: composerActions.setInput
    },
    gateway,
    local: {
      catalog,
      getHistoryItems: () => historyItemsRef.current,
      getLastUserMsg: () => lastUserMsgRef.current,
      maybeWarn
    },
    session: {
      closeSession: session.closeSession,
      die,
      guardBusySessionSwitch: session.guardBusySessionSwitch,
      newSession: session.newSession,
      resetVisibleHistory: session.resetVisibleHistory,
      resumeById: session.resumeById,
      setSessionStartedAt
    },
    slashFlightRef,
    transcript: {
      page,
      panel,
      send,
      setHistoryItems,
      sys,
      trimLastExchange: session.trimLastExchange
    },
    voice: {
      setVoiceEnabled
    }
  }), [catalog, composerActions, composerRefs, die, gateway, hasSelection, maybeWarn, page, panel, paste, selection, send, session, sys]);
  slashRef.current = slash;
  const hasReasoning = useTurnSelector(state_0 => Boolean(state_0.reasoning.trim()));
  // Per-section overrides win over the global mode — when every section is
  // resolved to hidden, the only thing ToolTrail will surface is the
  // floating-alert backstop (errors/warnings).  Mirror that so we don't
  // render an empty wrapper Box above the streaming area in quiet mode.
  const anyPanelVisible = SECTION_NAMES.some(s => sectionMode(s, ui.detailsMode, ui.sections, ui.detailsModeCommandOverride) !== 'hidden');
  const showProgressArea = useTurnSelector(state_1 => anyPanelVisible ? Boolean(ui.busy || state_1.outcome || state_1.streamPendingTools.length || state_1.streamSegments.length || state_1.subagents.length || state_1.tools.length || state_1.todos.length || state_1.turnTrail.length || hasReasoning || state_1.activity.length) : state_1.activity.some(item => item.tone !== 'info'));
  const appActions = useMemo(() => ({
    answerApproval,
    answerWiser,
    answerSecret,
    answerSudo,
    onModelSelect,
    resumeById: session.resumeById,
    setStickyPrompt
  }), [answerApproval, answerWiser, answerSecret, answerSudo, onModelSelect, session.resumeById]);
  const appComposer = useMemo(() => ({
    cols,
    compIdx: composerState.compIdx,
    completions: composerState.completions,
    empty,
    handleTextPaste: composerActions.handleTextPaste,
    input: composerState.input,
    inputBuf: composerState.inputBuf,
    pagerPageSize,
    queueEditIdx: composerState.queueEditIdx,
    queuedDisplay: composerState.queuedDisplay,
    submit,
    updateInput: composerActions.setInput
  }), [cols, composerActions, composerState, empty, pagerPageSize, submit]);
  // Pass current progress through unfrozen — streaming update throttling
  // handles interaction load; progress must stay truthful so panels don't
  // randomly disappear when the live tail scrolls offscreen.
  const appProgress = useMemo(() => ({
    showProgressArea
  }), [showProgressArea]);
  const cwd = ui.info?.cwd || process.env.ECTOR_CWD || process.cwd();
  const gitBranch = useGitBranch(cwd);
  const appStatus = useMemo(() => ({
    cwdLabel: statusBarCwd(cwd, gitBranch),
    cwdShort: compactCwd(cwd, gitBranch),
    goodVibesTick,
    sessionStartedAt: ui.sid ? sessionStartedAt : null,
    showStickyPrompt: !!stickyPrompt,
    statusColor: statusColorOf(ui.status, ui.theme.color),
    stickyPrompt,
    turnStartedAt: ui.sid ? turnStartedAt : null,
    // CLI parity: the classic prompt_toolkit status bar shows a red dot
    // on REC (cli.py:_get_voice_status_fragments line 2344).
    voiceLabel: voiceRecording ? '● rec' : voiceProcessing ? '◉ voz' : voiceEnabled ? 'voz on' : 'voz off'
  }), [cwd, gitBranch, goodVibesTick, sessionStartedAt, stickyPrompt, turnStartedAt, ui, voiceEnabled, voiceProcessing, voiceRecording]);
  const appTranscript = useMemo(() => ({
    historyItems,
    scrollRef,
    virtualHistory,
    virtualRows
  }), [historyItems, virtualHistory, virtualRows]);
  return {
    appActions,
    appComposer,
    appProgress,
    appStatus,
    appTranscript,
    gateway
  };
}