import { atom } from 'nanostores';
import { MOUSE_TRACKING } from '../config/env.js';
import { STATUS } from '../content/uiStatus.js';
import { ZERO } from '../domain/usage.js';
import { DEFAULT_THEME } from '../theme.js';
const buildUiState = () => ({
  bgTasks: new Set(),
  sessionKey: null,
  returnSessionKey: null,
  pendingBackgroundReply: null,
  busy: false,
  compact: false,
  detailsMode: 'collapsed',
  detailsModeCommandOverride: false,
  info: null,
  inlineDiffs: true,
  mouseTracking: MOUSE_TRACKING,
  sections: {},
  showCost: false,
  showReasoning: false,
  sessionTitle: null,
  sid: null,
  bootUserId: null,
  bootUserEmail: null,
  status: STATUS.initializing,
  statusBar: 'top',
  streaming: true,
  theme: DEFAULT_THEME,
  usage: ZERO
});
export const $uiState = atom(buildUiState());
export const getUiState = () => $uiState.get();
export const patchUiState = next => $uiState.set(typeof next === 'function' ? next($uiState.get()) : {
  ...$uiState.get(),
  ...next
});
export const resetUiState = () => $uiState.set(buildUiState());