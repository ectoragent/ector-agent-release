import { STATUS } from '../../../content/uiStatus.js';
import { turnTimingMsg } from '../../../domain/turnTiming.js';
import { getUiState } from '../../uiStore.js';
import { patchUiState } from '../../uiStore.js';
export function handleThinkingDelta(ev, api) {
  const p = ev.payload;
  const text = p?.text;
  if (text !== undefined) {
    const value = String(text);
    if (value) {
      api.turnController.recordReasoningDelta(value);
    }
  }
}
export function handleMessageStart(_ev, api) {
  api.turnController.startMessage();
}
/** Map legacy agent status lines to current user-facing labels (pt-BR). */
function normalizeLegacyStatusText(text) {
  const trimmed = text.trim();
  if (!/^Aguardando resposta do provedor/i.test(trimmed)) {
    return text;
  }
  const secs = /\((\d+)s\)/.exec(trimmed)?.[1];
  return secs ? `Raciocinando… (${secs}s)` : 'Raciocinando…';
}
export function handleStatusUpdate(ev, api) {
  const p = ev.payload;
  if (!p?.text) {
    return;
  }
  const status = getUiState().status;
  if (status === STATUS.resuming || status === STATUS.forgingSession) {
    return;
  }
  const text = normalizeLegacyStatusText(p.text);
  api.setStatus(text);
  if (!p.kind || p.kind === 'status') {
    return;
  }
  if (api.turnController.lastStatusNote !== text) {
    api.turnController.lastStatusNote = text;
    api.turnController.pushActivity(text, p.kind === 'error' ? 'error' : p.kind === 'warn' || p.kind === 'approval' ? 'warn' : 'info');
  }
  api.restoreStatusAfter(4000);
}
export function handleReasoningDelta(ev, api) {
  const p = ev.payload;
  if (p?.text) {
    api.turnController.recordReasoningDelta(p.text);
  }
}
export function handleReasoningAvailable(ev, api) {
  const p = ev.payload;
  api.turnController.recordReasoningAvailable(String(p?.text ?? ''));
}
export function handleMessageDelta(ev, api) {
  api.turnController.recordMessageDelta(ev.payload ?? {});
}
export function handleMessageComplete(ev, api) {
  const p = ev.payload;
  const {
    finalMessages,
    finalText,
    wasInterrupted
  } = api.turnController.recordMessageComplete(ev.payload ?? {});
  if (!wasInterrupted) {
    const msgs = finalMessages.length ? finalMessages : [{
      role: 'assistant',
      text: finalText
    }];
    const startedAt = api.turnStartedAtRef.current;
    if (startedAt != null) {
      msgs.push(turnTimingMsg(startedAt, Date.now()));
    }
    api.appendMessages(msgs);
    if (api.bellOnComplete && process.stderr.isTTY) {
      process.stderr.write('\x07');
    }
  }
  api.setStatus(STATUS.ready);
  if (p?.usage) {
    patchUiState(state => ({
      ...state,
      usage: {
        ...state.usage,
        ...p.usage
      }
    }));
  }
}
export function handleGatewayStderr(ev, api) {
  const p = ev.payload;
  const line = String(p.line).slice(0, 120);
  api.turnController.pushActivity(line, 'info');
}
export function handleGatewayStartTimeout(ev, api) {
  const p = ev.payload ?? {};
  const trace = p.python || p.cwd ? ` · ${String(p.python || '')} ${String(p.cwd || '')}`.trim() : '';
  api.setStatus(STATUS.gatewayStartupTimeout);
  api.turnController.pushActivity(`gateway startup timed out${trace} · /logs to inspect`, 'error');
}
export function handleGatewayProtocolError(ev, api) {
  const p = ev.payload;
  api.setStatus(STATUS.protocolWarning);
  api.restoreStatusAfter(4000);
  if (!api.turnController.protocolWarned) {
    api.turnController.protocolWarned = true;
    api.turnController.pushActivity('protocol noise detected · /logs to inspect', 'info');
  }
  if (p?.preview) {
    api.turnController.pushActivity(`protocol noise: ${String(p.preview).slice(0, 120)}`, 'info');
  }
}