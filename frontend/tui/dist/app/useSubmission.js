import { useCallback, useEffect, useRef } from 'react';
import { TYPING_IDLE_MS } from '../config/timing.js';
import { isComposerReady, STATUS } from '../content/uiStatus.js';
import { attachedImageNotice } from '../domain/messages.js';
import { looksLikeSlashCommand } from '../domain/slash.js';
import { asRpcResult } from '../lib/rpc.js';
import { hasInterpolation, INTERPOLATION_RE } from '../protocol/interpolation.js';
import { expandSnippets, isDoubleEnterTap, isSessionBusyError, resolveDoubleEnter } from './submissionLogic.js';
import { turnController } from './turnController.js';
import { getUiState, patchUiState } from './uiStore.js';
const spliceMatches = (text, matches, results) => matches.reduceRight((acc, m, i) => acc.slice(0, m.index) + results[i] + acc.slice(m.index + m[0].length), text);
export function useSubmission(opts) {
  const {
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
  } = opts;
  const lastEmptyAt = useRef(0);
  const typingIdleTimer = useRef(null);
  useEffect(() => {
    if (typingIdleTimer.current) {
      clearTimeout(typingIdleTimer.current);
      typingIdleTimer.current = null;
    }
    if (!composerState.input && !composerState.inputBuf.length) {
      turnController.relaxStreaming();
      return;
    }
    if (getUiState().busy) {
      turnController.boostStreamingForTyping();
    }
    typingIdleTimer.current = setTimeout(() => {
      typingIdleTimer.current = null;
      turnController.relaxStreaming();
    }, TYPING_IDLE_MS);
    return () => {
      if (typingIdleTimer.current) {
        clearTimeout(typingIdleTimer.current);
        typingIdleTimer.current = null;
      }
    };
  }, [composerState.input, composerState.inputBuf]);
  const send = useCallback((text, showUserMessage = true) => {
    const expand = expandSnippets(composerState.pasteSnips);
    const startSubmit = (displayText, submitText, showUserMessage_0 = true) => {
      const live = getUiState();
      if (!isComposerReady(live)) {
        return sys('session not ready yet');
      }
      const sid = live.sid;
      turnController.clearStatusTimer();
      maybeGoodVibes(submitText);
      setLastUserMsg(text);
      if (showUserMessage_0) {
        appendMessage({
          role: 'user',
          text: displayText
        });
      }
      patchUiState({
        busy: true,
        status: STATUS.running
      });
      turnController.bufRef = '';
      turnController.interrupted = false;
      gw.request('prompt.submit', {
        session_id: sid,
        text: submitText
      }).catch(e => {
        if (isSessionBusyError(e)) {
          composerActions.enqueue(submitText);
          patchUiState({
            busy: true,
            status: STATUS.queuedNextTurn
          });
          return sys(`queued: "${submitText.slice(0, 50)}${submitText.length > 50 ? '…' : ''}"`);
        }
        sys(`error: ${e.message}`);
        patchUiState({
          busy: false,
          status: STATUS.ready
        });
      });
    };
    const live_0 = getUiState();
    if (!isComposerReady(live_0)) {
      return sys('session not ready yet');
    }
    const sid_0 = live_0.sid;
    gw.request('input.detect_drop', {
      session_id: sid_0,
      text
    }).then(r => {
      if (!r?.matched) {
        return startSubmit(text, expand(text), showUserMessage);
      }
      if (r.is_image) {
        turnController.pushActivity(attachedImageNotice(r));
      } else {
        turnController.pushActivity(`detected file: ${r.name}`);
      }
      startSubmit(r.text || text, expand(r.text || text), showUserMessage);
    }).catch(() => startSubmit(text, expand(text), showUserMessage));
  }, [appendMessage, composerActions, composerState.pasteSnips, gw, maybeGoodVibes, setLastUserMsg, sys]);
  const shellExec = useCallback(cmd => {
    appendMessage({
      role: 'user',
      text: `!${cmd}`
    });
    patchUiState({
      busy: true,
      status: STATUS.running
    });
    gw.request('shell.exec', {
      command: cmd
    }).then(raw => {
      const r_0 = asRpcResult(raw);
      if (!r_0) {
        return sys('error: invalid response: shell.exec');
      }
      const out = [r_0.stdout, r_0.stderr].filter(Boolean).join('\n').trim();
      if (out) {
        sys(out);
      }
      if (r_0.code !== 0 || !out) {
        sys(`exit ${r_0.code}`);
      }
    }).catch(e_0 => sys(`error: ${e_0.message}`)).finally(() => patchUiState({
      busy: false,
      status: STATUS.ready
    }));
  }, [appendMessage, gw, sys]);
  const interpolate = useCallback((text_0, then) => {
    patchUiState({
      status: STATUS.interpolating
    });
    const matches = [...text_0.matchAll(new RegExp(INTERPOLATION_RE.source, 'g'))];
    Promise.all(matches.map(m => gw.request('shell.exec', {
      command: m[1]
    }).then(raw_0 => {
      const r_1 = asRpcResult(raw_0);
      return [r_1?.stdout, r_1?.stderr].filter(Boolean).join('\n').trim();
    }).catch(() => '(error)'))).then(results => then(spliceMatches(text_0, matches, results)));
  }, [gw]);
  const sendQueued = useCallback(text_1 => {
    if (text_1.startsWith('!')) {
      return shellExec(text_1.slice(1).trim());
    }
    if (hasInterpolation(text_1)) {
      patchUiState({
        busy: true
      });
      return interpolate(text_1, send);
    }
    send(text_1);
  }, [interpolate, send, shellExec]);
  const dispatchSubmission = useCallback(full => {
    if (!full.trim()) {
      return;
    }
    if (looksLikeSlashCommand(full)) {
      appendMessage({
        kind: 'slash',
        role: 'system',
        text: full
      });
      composerActions.pushHistory(full);
      slashRef.current(full);
      composerActions.clearIn();
      return;
    }
    if (full.startsWith('!')) {
      composerActions.clearIn();
      return shellExec(full.slice(1).trim());
    }
    const live_1 = getUiState();
    if (!live_1.sid) {
      composerActions.pushHistory(full);
      composerActions.enqueue(full);
      composerActions.clearIn();
      return;
    }
    const editIdx = composerRefs.queueEditRef.current;
    composerActions.clearIn();
    if (editIdx !== null) {
      composerActions.replaceQueue(editIdx, full);
      const picked = composerRefs.queueRef.current.splice(editIdx, 1)[0];
      composerActions.syncQueue();
      composerActions.setQueueEdit(null);
      if (!picked || !live_1.sid) {
        return;
      }
      if (getUiState().busy) {
        composerRefs.queueRef.current.unshift(picked);
        return composerActions.syncQueue();
      }
      return sendQueued(picked);
    }
    composerActions.pushHistory(full);
    if (getUiState().busy) {
      return composerActions.enqueue(full);
    }
    if (hasInterpolation(full)) {
      patchUiState({
        busy: true
      });
      return interpolate(full, send);
    }
    send(full);
  }, [appendMessage, composerActions, composerRefs, interpolate, send, sendQueued, shellExec, slashRef]);
  const submit = useCallback(value => {
    if (composerState.completions.length) {
      const row = composerState.completions[composerState.compIdx];
      if (row?.text) {
        const text_2 = value.startsWith('/') && row.text.startsWith('/') ? row.text.slice(1) : row.text;
        const next = value.slice(0, composerState.compReplace) + text_2;
        if (next !== value) {
          return composerActions.setInput(next);
        }
      }
    }
    if (!value.trim() && !composerState.inputBuf.length) {
      const live_2 = getUiState();
      const now = Date.now();
      const doubleTap = isDoubleEnterTap(now, lastEmptyAt.current);
      lastEmptyAt.current = now;
      const action = resolveDoubleEnter({
        busy: live_2.busy,
        doubleTap,
        hasQueue: composerRefs.queueRef.current.length > 0,
        hasSid: Boolean(live_2.sid)
      });
      if (action === 'interrupt' && live_2.sid) {
        return turnController.interruptTurn({
          appendMessage,
          appendMessages,
          gw,
          sid: live_2.sid,
          sys
        });
      }
      if (action === 'dequeue') {
        const next_0 = composerActions.dequeue();
        composerActions.syncQueue();
        if (next_0) {
          composerActions.setQueueEdit(null);
          dispatchSubmission(next_0);
        }
      }
      return;
    }
    lastEmptyAt.current = 0;
    if (value.endsWith('\\')) {
      composerActions.setInputBuf(prev => [...prev, value.slice(0, -1)]);
      return composerActions.setInput('');
    }
    dispatchSubmission([...composerState.inputBuf, value].join('\n'));
  }, [appendMessage, composerActions, composerRefs, composerState, dispatchSubmission, gw, sys]);
  submitRef.current = submit;
  return {
    dispatchSubmission,
    send,
    sendQueued,
    submit
  };
}