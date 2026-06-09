import { STATUS } from '../../../content/uiStatus.js';
import { patchOverlayState } from '../../overlayStore.js';
import { getUiState, patchUiState } from '../../uiStore.js';
export function handleWiserRequest(ev, api) {
  const p = ev.payload;
  patchOverlayState({
    wiser: {
      choices: p.choices ?? null,
      question: p.question,
      requestId: p.request_id
    }
  });
  api.setStatus(STATUS.waitingInput);
}
export function handleApprovalRequest(ev, api) {
  const p = ev.payload;
  const description = String(p.description ?? 'dangerous command');
  patchOverlayState({
    approval: {
      command: String(p.command ?? ''),
      description
    }
  });
  api.setStatus(STATUS.approvalNeeded);
}
export function handleSudoRequest(ev, api) {
  const p = ev.payload;
  patchOverlayState({
    sudo: {
      requestId: p.request_id
    }
  });
  api.setStatus(STATUS.sudoNeeded);
}
export function handleSecretRequest(ev, api) {
  const p = ev.payload;
  patchOverlayState({
    secret: {
      envVar: p.env_var ?? '',
      prompt: p.prompt ?? '',
      requestId: p.request_id
    }
  });
  api.setStatus(STATUS.secretNeeded);
}
export function handleBackgroundComplete(ev, api) {
  const p = ev.payload;
  api.dropBgTask(p.task_id);
  const live = getUiState();
  // Utilizador abriu a sessão bg_* manualmente — Esc volta ao principal; resposta no principal.
  if (live.sessionKey?.startsWith('bg_') && live.returnSessionKey) {
    patchUiState({
      pendingBackgroundReply: p.text
    });
    return api.resumeById(live.returnSessionKey);
  }
  api.appendMessage({
    kind: 'background',
    role: 'system',
    text: p.text
  });
}