import { stripAnsi } from '../../../lib/text.js';
import { patchOverlayState } from '../../overlayStore.js';
import { getUiState } from '../../uiStore.js';
const WISER_TOOL_NAMES = new Set(['wiser', 'ask_user', 'clarify']);
export function handleToolProgress(ev, api) {
  const p = ev.payload;
  if (p?.preview && p.name) {
    api.turnController.recordToolProgress(p.name, p.preview);
  }
}
export function handleToolGenerating(ev, api) {
  const p = ev.payload;
  if (p?.name) {
    api.turnController.pushTrail(`Rascunhando ${p.name}…`);
  }
}
export function handleToolStart(ev, api) {
  const p = ev.payload;
  api.turnController.recordTodos(p.todos);
  api.turnController.recordToolStart(p.tool_id ?? '', p.name ?? 'tool', p.context ?? '', p.technical ?? '');
}
export function handleToolComplete(ev, api) {
  const p = ev.payload;
  if (p.name && WISER_TOOL_NAMES.has(p.name)) {
    patchOverlayState({
      wiser: null
    });
  }
  const inlineDiffText = p.inline_diff && getUiState().inlineDiffs ? stripAnsi(String(p.inline_diff)).trim() : '';
  const toolId = p.tool_id ?? '';
  if (inlineDiffText) {
    api.turnController.recordInlineDiffToolComplete(inlineDiffText, toolId, p.name, p.error, p.duration_s);
  } else {
    api.turnController.recordToolComplete(toolId, p.name, p.error, p.summary, p.duration_s, p.todos);
  }
}