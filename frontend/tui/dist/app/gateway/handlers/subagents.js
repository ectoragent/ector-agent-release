import { formatToolCall } from '../../../lib/text.js';
import { getDelegationState } from '../../delegationStore.js';
import { pushNote, pushThinking, pushTool } from '../shared.js';
export function handleSubagentSpawnRequested(ev, api) {
  const p = ev.payload;
  api.turnController.upsertSubagent(p, c => api.isTerminalStatus(c.status) ? {} : {
    status: 'queued'
  });
  if (getDelegationState().maxSpawnDepth === null) {
    api.refreshDelegationStatus(true);
  } else {
    api.refreshDelegationStatus();
  }
}
export function handleSubagentStart(ev, api) {
  const p = ev.payload;
  api.turnController.upsertSubagent(p, c => api.isTerminalStatus(c.status) ? {} : {
    status: 'running'
  });
}
export function handleSubagentThinking(ev, api) {
  const p = ev.payload;
  const text = String(p.text ?? '').trim();
  if (!text) {
    return;
  }
  api.turnController.upsertSubagent(p, c => ({
    status: api.keepTerminalElseRunning(c.status),
    thinking: pushThinking(c.thinking, text)
  }), {
    createIfMissing: false
  });
}
export function handleSubagentTool(ev, api) {
  const p = ev.payload;
  const line = formatToolCall(p.tool_name ?? 'delegate_task', p.tool_preview ?? p.text ?? '');
  api.turnController.upsertSubagent(p, c => ({
    status: api.keepTerminalElseRunning(c.status),
    tools: pushTool(c.tools, line)
  }), {
    createIfMissing: false
  });
}
export function handleSubagentProgress(ev, api) {
  const p = ev.payload;
  const text = String(p.text ?? '').trim();
  if (!text) {
    return;
  }
  api.turnController.upsertSubagent(p, c => ({
    notes: pushNote(c.notes, text),
    status: api.keepTerminalElseRunning(c.status)
  }), {
    createIfMissing: false
  });
}
export function handleSubagentComplete(ev, api) {
  const p = ev.payload;
  api.turnController.upsertSubagent(p, c => ({
    durationSeconds: p.duration_seconds ?? c.durationSeconds,
    status: p.status ?? 'completed',
    summary: p.summary || p.text || c.summary
  }), {
    createIfMissing: false
  });
}