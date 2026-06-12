import { INTERRUPT_USER_LABEL, STATUS } from '../../content/uiStatus.js';
import { topLevelSubagents } from '../../lib/subagentTree.js';
import { applyDelegationStatus } from '../delegationStore.js';
import { turnController } from '../turn/index.js';
import { getUiState, patchUiState } from '../uiStore.js';
export const statusFromBusy = () => getUiState().busy ? STATUS.running : STATUS.ready;
export const dropBgTask = taskId => patchUiState(state => {
  const next = new Set(state.bgTasks);
  next.delete(taskId);
  return {
    ...state,
    bgTasks: next
  };
});
export const pushUnique = max => (xs, x) => xs.at(-1) === x ? xs : [...xs, x].slice(-max);
export const pushThinking = pushUnique(6);
export const pushNote = pushUnique(6);
export const pushTool = pushUnique(8);
export const isTerminalStatus = s => s === 'completed' || s === 'failed' || s === 'interrupted';
export const keepTerminalElseRunning = s => isTerminalStatus(s) ? s : 'running';
export function buildHandlerApi(ctx) {
  const {
    rpc
  } = ctx.gateway;
  const {
    STARTUP_RESUME_ID,
    newSession,
    resumeById,
    setCatalog
  } = ctx.session;
  const {
    bellOnComplete,
    stdout,
    sys,
    turnStartedAtRef
  } = ctx.system;
  const {
    appendMessage,
    appendMessages,
    panel,
    setHistoryItems
  } = ctx.transcript;
  const {
    setInput
  } = ctx.composer;
  const {
    submitRef
  } = ctx.submission;
  const {
    setProcessing: setVoiceProcessing,
    setRecording: setVoiceRecording,
    setVoiceEnabled
  } = ctx.voice;
  turnController.persistSpawnTree = async (subagents, sessionId) => {
    try {
      const startedAt = subagents.reduce((min, s) => {
        if (!s.startedAt) {
          return min;
        }
        return min === 0 ? s.startedAt : Math.min(min, s.startedAt);
      }, 0);
      const top = topLevelSubagents(subagents).map(s => s.goal).filter(Boolean).slice(0, 2);
      const label = top.length ? top.join(' · ') : `${subagents.length} subagents`;
      await rpc('spawn_tree.save', {
        finished_at: Date.now() / 1000,
        label: label.slice(0, 120),
        session_id: sessionId ?? 'default',
        started_at: startedAt ? startedAt / 1000 : null,
        subagents
      });
    } catch {
      // best-effort persistence
    }
  };
  let lastDelegationFetchAt = 0;
  const refreshDelegationStatus = (force = false) => {
    const now = Date.now();
    if (!force && now - lastDelegationFetchAt < 5000) {
      return;
    }
    lastDelegationFetchAt = now;
    rpc('delegation.status', {}).then(r => applyDelegationStatus(r)).catch(() => {});
  };
  const setStatus = status => {
    patchUiState({
      status: status === 'interrupted' || status === 'interrompido' ? INTERRUPT_USER_LABEL : status
    });
  };
  const restoreStatusAfter = ms => {
    turnController.clearStatusTimer();
    turnController.statusTimer = setTimeout(() => {
      turnController.statusTimer = null;
      patchUiState({
        status: statusFromBusy()
      });
    }, ms);
  };
  return {
    appendMessage,
    appendMessages,
    bellOnComplete,
    dropBgTask,
    isTerminalStatus,
    keepTerminalElseRunning,
    newSession,
    panel,
    refreshDelegationStatus,
    restoreStatusAfter,
    resumeById,
    rpc,
    setCatalog,
    setHistoryItems,
    setInput,
    setStatus,
    setVoiceEnabled,
    setVoiceProcessing,
    setVoiceRecording,
    STARTUP_RESUME_ID,
    stdout,
    submitRef,
    sys,
    turnController,
    turnStartedAtRef
  };
}