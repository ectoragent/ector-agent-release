import { c as _c } from "react/compiler-runtime";
import { evictInkCaches } from '@ector/ink';
import { useCallback, useRef } from 'react';
import { STARTUP_WORKTREE } from '../config/env.js';
import { buildSetupRequiredSections, SETUP_REQUIRED_TITLE } from '../content/setup.js';
import { STATUS } from '../content/uiStatus.js';
import { capTranscriptHistory, introMsg, sessionHistoryItems, toTranscriptMessages } from '../domain/messages.js';
import { ZERO } from '../domain/usage.js';
import { asRpcResult } from '../lib/rpc.js';
import { patchOverlayState } from './overlayStore.js';
import { turnController } from './turnController.js';
import { patchTurnState } from './turnStore.js';
import { getUiState, patchUiState } from './uiStore.js';
const usageFrom = info => info?.usage ? {
  ...ZERO,
  ...info.usage
} : ZERO;
const trimTail = items => {
  const q = [...items];
  while (q.at(-1)?.role === 'assistant' || q.at(-1)?.role === 'tool') {
    q.pop();
  }
  if (q.at(-1)?.role === 'user') {
    q.pop();
  }
  return q;
};
export function useSessionLifecycle(opts) {
  const $ = _c(47);
  const {
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
  } = opts;
  const resumeGenerationRef = useRef(0);
  let t0;
  if ($[0] !== rpc) {
    t0 = targetSid => targetSid ? rpc("session.close", {
      session_id: targetSid
    }) : Promise.resolve(null);
    $[0] = rpc;
    $[1] = t0;
  } else {
    t0 = $[1];
  }
  const closeSession = t0;
  let t1;
  if ($[2] !== composerActions || $[3] !== setHistoryItems || $[4] !== setLastUserMsg || $[5] !== setStickyPrompt || $[6] !== setVoiceProcessing || $[7] !== setVoiceRecording) {
    t1 = () => {
      turnController.fullReset();
      setVoiceRecording(false);
      setVoiceProcessing(false);
      patchUiState({
        bgTasks: new Set(),
        info: null,
        returnSessionKey: null,
        pendingBackgroundReply: null,
        sessionKey: null,
        sessionTitle: null,
        sid: null,
        usage: ZERO
      });
      setHistoryItems([]);
      setLastUserMsg("");
      setStickyPrompt("");
      composerActions.setPasteSnips([]);
      evictInkCaches("half");
    };
    $[2] = composerActions;
    $[3] = setHistoryItems;
    $[4] = setLastUserMsg;
    $[5] = setStickyPrompt;
    $[6] = setVoiceProcessing;
    $[7] = setVoiceRecording;
    $[8] = t1;
  } else {
    t1 = $[8];
  }
  const resetSession = t1;
  let t2;
  if ($[9] !== composerActions || $[10] !== setHistoryItems || $[11] !== setLastUserMsg || $[12] !== setStickyPrompt) {
    t2 = t3 => {
      const info = t3 === undefined ? null : t3;
      turnController.idle();
      turnController.clearReasoning();
      turnController.turnTools = [];
      turnController.persistedToolLabels.clear();
      setHistoryItems(info ? [introMsg(info)] : []);
      setStickyPrompt("");
      setLastUserMsg("");
      composerActions.setPasteSnips([]);
      patchTurnState({
        activity: []
      });
      patchUiState({
        info,
        sessionTitle: null,
        usage: usageFrom(info)
      });
    };
    $[9] = composerActions;
    $[10] = setHistoryItems;
    $[11] = setLastUserMsg;
    $[12] = setStickyPrompt;
    $[13] = t2;
  } else {
    t2 = $[13];
  }
  const resetVisibleHistory = t2;
  let t3;
  if ($[14] !== closeSession || $[15] !== colsRef || $[16] !== panel || $[17] !== resetSession || $[18] !== rpc || $[19] !== setHistoryItems || $[20] !== setSessionStartedAt || $[21] !== sys) {
    t3 = async msg => {
      const setup = await rpc("setup.status", {});
      if (setup?.provider_configured === false) {
        panel(SETUP_REQUIRED_TITLE, buildSetupRequiredSections());
        patchUiState({
          status: STATUS.setupRequired
        });
        return;
      }
      await closeSession(getUiState().sid);
      const r = await rpc("session.create", {
        cols: colsRef.current,
        worktree: STARTUP_WORKTREE
      });
      if (!r) {
        return patchUiState({
          status: STATUS.ready
        });
      }
      const info_0 = r.info ?? null;
      resetSession();
      setSessionStartedAt(Date.now());
      patchUiState({
        info: info_0,
        sid: r.session_id,
        status: info_0?.version ? STATUS.ready : STATUS.startingAgent,
        usage: usageFrom(info_0)
      });
      if (info_0) {
        setHistoryItems([introMsg(info_0)]);
      }
      if (info_0?.credential_warning) {
        sys(`warning: ${info_0.credential_warning}`);
      }
      if (info_0?.config_warning) {
        sys(`warning: ${info_0.config_warning}`);
      }
      if (msg) {
        sys(msg);
      }
    };
    $[14] = closeSession;
    $[15] = colsRef;
    $[16] = panel;
    $[17] = resetSession;
    $[18] = rpc;
    $[19] = setHistoryItems;
    $[20] = setSessionStartedAt;
    $[21] = sys;
    $[22] = t3;
  } else {
    t3 = $[22];
  }
  const newSession = t3;
  let t4;
  if ($[23] !== closeSession || $[24] !== colsRef || $[25] !== composerActions || $[26] !== gw || $[27] !== newSession || $[28] !== panel || $[29] !== rpc || $[30] !== setHistoryItems || $[31] !== setLastUserMsg || $[32] !== setSessionStartedAt || $[33] !== setStickyPrompt || $[34] !== setVoiceProcessing || $[35] !== setVoiceRecording || $[36] !== sys) {
    t4 = id => {
      const generation = resumeGenerationRef.current = resumeGenerationRef.current + 1;
      const prior = getUiState();
      const returnSessionKey = id.startsWith("bg_") ? prior.sessionKey && !prior.sessionKey.startsWith("bg_") ? prior.sessionKey : prior.returnSessionKey : null;
      turnController.fullReset();
      patchOverlayState({
        picker: false
      });
      setHistoryItems([]);
      patchUiState(state => ({
        ...state,
        busy: false,
        sid: null,
        status: STATUS.resuming,
        ...(id.startsWith("bg_") ? {
          returnSessionKey: returnSessionKey ?? state.returnSessionKey
        } : {
          returnSessionKey: null,
          pendingBackgroundReply: null
        })
      }));
      rpc("setup.status", {}).then(setup_0 => {
        if (generation !== resumeGenerationRef.current) {
          return;
        }
        if (setup_0?.provider_configured === false) {
          panel(SETUP_REQUIRED_TITLE, buildSetupRequiredSections());
          patchUiState({
            status: STATUS.setupRequired
          });
          return;
        }
        closeSession(prior.sid).then(() => gw.request("session.resume", {
          cols: colsRef.current,
          session_id: id
        }).then(raw => {
          if (generation !== resumeGenerationRef.current) {
            return;
          }
          const r_0 = asRpcResult(raw);
          if (!r_0) {
            sys("error: invalid response: session.resume");
            newSession();
            return;
          }
          turnController.fullReset();
          setVoiceRecording(false);
          setVoiceProcessing(false);
          setLastUserMsg("");
          setStickyPrompt("");
          composerActions.setPasteSnips([]);
          evictInkCaches("half");
          setSessionStartedAt(Date.now());
          const resumed = toTranscriptMessages(r_0.messages);
          const pending = getUiState().pendingBackgroundReply;
          let items = sessionHistoryItems(r_0.info, resumed);
          if (pending) {
            items = [...items, {
              kind: "background",
              role: "system",
              text: pending
            }];
          }
          const capped = capTranscriptHistory(items);
          setHistoryItems(capped);
          patchUiState({
            info: r_0.info ?? null,
            pendingBackgroundReply: null,
            sessionKey: r_0.resumed ?? id,
            sessionTitle: r_0.title?.trim() || null,
            status: STATUS.ready,
            usage: usageFrom(r_0.info ?? null)
          });
          requestAnimationFrame(() => {
            if (generation !== resumeGenerationRef.current) {
              return;
            }
            patchUiState({
              sid: r_0.session_id
            });
          });
        }).catch(e => {
          if (generation !== resumeGenerationRef.current) {
            return;
          }
          sys(`error: ${e.message}`);
          newSession();
        }));
      });
    };
    $[23] = closeSession;
    $[24] = colsRef;
    $[25] = composerActions;
    $[26] = gw;
    $[27] = newSession;
    $[28] = panel;
    $[29] = rpc;
    $[30] = setHistoryItems;
    $[31] = setLastUserMsg;
    $[32] = setSessionStartedAt;
    $[33] = setStickyPrompt;
    $[34] = setVoiceProcessing;
    $[35] = setVoiceRecording;
    $[36] = sys;
    $[37] = t4;
  } else {
    t4 = $[37];
  }
  const resumeById = t4;
  let t5;
  if ($[38] !== sys) {
    t5 = t6 => {
      const what = t6 === undefined ? "switch sessions" : t6;
      if (!getUiState().busy) {
        return false;
      }
      sys(`interrupt the current turn before trying to ${what}`);
      return true;
    };
    $[38] = sys;
    $[39] = t5;
  } else {
    t5 = $[39];
  }
  const guardBusySessionSwitch = t5;
  let t6;
  if ($[40] !== closeSession || $[41] !== guardBusySessionSwitch || $[42] !== newSession || $[43] !== resetSession || $[44] !== resetVisibleHistory || $[45] !== resumeById) {
    t6 = {
      closeSession,
      guardBusySessionSwitch,
      newSession,
      resetSession,
      resetVisibleHistory,
      resumeById,
      trimLastExchange: trimTail
    };
    $[40] = closeSession;
    $[41] = guardBusySessionSwitch;
    $[42] = newSession;
    $[43] = resetSession;
    $[44] = resetVisibleHistory;
    $[45] = resumeById;
    $[46] = t6;
  } else {
    t6 = $[46];
  }
  return t6;
}