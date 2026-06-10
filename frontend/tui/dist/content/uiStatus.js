/** Label when the user cancels the turn (Esc / interrupt). */
export const INTERRUPT_USER_LABEL = 'Interrompido por você';
/**
 * User-visible status strings for the status bar and composer (pt-BR).
 * Gateway `status.update` payloads are shown as received unless normalized.
 */
export const STATUS = {
  approvalNeeded: 'preciso da sua aprovação',
  forgingSession: 'preparando sessão…',
  gatewayExited: 'gateway encerrado',
  gatewayStartupTimeout: 'demorou para iniciar o gateway',
  initializing: 'inicializando ECTOR…',
  interpolating: 'Raciocinando…',
  interrupted: INTERRUPT_USER_LABEL,
  protocolWarning: 'algo inesperado no protocolo',
  queuedNextTurn: 'na fila — próximo turno',
  ready: 'pronto',
  resuming: 'carregando sessão…',
  running: 'trabalhando…',
  secretNeeded: 'preciso de um dado sensível',
  loginRequired: 'login necessário',
  setupRequired: 'configuração necessária',
  setupRunning: 'configuração em andamento…',
  startingAgent: 'iniciando assistente…',
  sudoNeeded: 'senha sudo — ou corra sudo -v noutro terminal',
  waitingInput: 'sua vez de responder…'
};
/** Startup / session prep statuses that show a spinner in the bar. */
export const LOADING_STATUSES = new Set([STATUS.initializing, STATUS.forgingSession, STATUS.resuming, STATUS.startingAgent, STATUS.setupRunning]);
export function isLoadingStatus(status) {
  return LOADING_STATUSES.has(status);
}
/** Composer accepts input once a session is bound; queue handles busy turns. */
export function isComposerReady(state) {
  if (state.status === STATUS.loginRequired || isLoadingStatus(state.status)) {
    return false;
  }
  return Boolean(state.sid);
}
/** Statuses that render as a red dot only (no long label). */
export const STATUS_ERROR_DOT = new Set([STATUS.interrupted, STATUS.gatewayExited, STATUS.gatewayStartupTimeout, STATUS.protocolWarning]);