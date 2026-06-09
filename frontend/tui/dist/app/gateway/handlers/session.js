import { STATUS } from '../../../content/uiStatus.js';
import { patchUiState } from '../../uiStore.js';
export function handleSessionInfo(ev, api) {
  const info = ev.payload;
  patchUiState(state => ({
    ...state,
    info,
    status: state.status === STATUS.startingAgent ? STATUS.ready : state.status,
    usage: info.usage ? {
      ...state.usage,
      ...info.usage
    } : state.usage
  }));
  api.setHistoryItems(prev => prev.map(m => m.kind === 'intro' ? {
    ...m,
    info
  } : m));
}
export function handleSessionTitle(ev) {
  const p = ev.payload;
  patchUiState({
    sessionTitle: String(p.title ?? '').trim() || null
  });
}