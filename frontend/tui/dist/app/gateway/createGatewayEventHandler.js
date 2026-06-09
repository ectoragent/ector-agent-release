import { getUiState } from '../uiStore.js';
import { handleIdentityRestored, handleIdentityRevoked, handleIdentityUserChanged } from './handlers/identity.js';
import { handleError, handleGatewayReady } from './handlers/gatewayReady.js';
import { handleApprovalRequest, handleBackgroundComplete, handleSecretRequest, handleSudoRequest, handleWiserRequest } from './handlers/overlays.js';
import { handleSessionInfo, handleSessionTitle } from './handlers/session.js';
import { handleGatewayProtocolError, handleGatewayStartTimeout, handleGatewayStderr, handleMessageComplete, handleMessageDelta, handleMessageStart, handleReasoningAvailable, handleReasoningDelta, handleStatusUpdate, handleThinkingDelta } from './handlers/streaming.js';
import { handleSubagentComplete, handleSubagentProgress, handleSubagentSpawnRequested, handleSubagentStart, handleSubagentThinking, handleSubagentTool } from './handlers/subagents.js';
import { handleToolComplete, handleToolGenerating, handleToolProgress, handleToolStart } from './handlers/tools.js';
import { handleVoiceStatus, handleVoiceTranscript } from './handlers/voice.js';
import { buildHandlerApi } from './shared.js';
export function createGatewayEventHandler(ctx) {
  const api = buildHandlerApi(ctx);
  return ev => {
    const sid = getUiState().sid;
    if (ev.session_id && sid && ev.session_id !== sid && !ev.type.startsWith('gateway.') && !ev.type.startsWith('identity.') && ev.type !== 'background.complete') {
      return;
    }
    switch (ev.type) {
      case 'gateway.ready':
        handleGatewayReady(ev, api);
        break;
      case 'identity.revoked':
        handleIdentityRevoked(ev, api);
        break;
      case 'identity.restored':
        handleIdentityRestored(ev, api);
        break;
      case 'identity.user_changed':
        void handleIdentityUserChanged(ev, api, ctx);
        break;
      case 'session.info':
        handleSessionInfo(ev, api);
        break;
      case 'session.title':
        handleSessionTitle(ev);
        break;
      case 'thinking.delta':
        handleThinkingDelta(ev, api);
        break;
      case 'message.start':
        handleMessageStart(ev, api);
        break;
      case 'status.update':
        handleStatusUpdate(ev, api);
        break;
      case 'gateway.stderr':
        handleGatewayStderr(ev, api);
        break;
      case 'voice.status':
        handleVoiceStatus(ev, api);
        break;
      case 'voice.transcript':
        handleVoiceTranscript(ev, api);
        break;
      case 'gateway.start_timeout':
        handleGatewayStartTimeout(ev, api);
        break;
      case 'gateway.protocol_error':
        handleGatewayProtocolError(ev, api);
        break;
      case 'reasoning.delta':
        handleReasoningDelta(ev, api);
        break;
      case 'reasoning.available':
        handleReasoningAvailable(ev, api);
        break;
      case 'tool.progress':
        handleToolProgress(ev, api);
        break;
      case 'tool.generating':
        handleToolGenerating(ev, api);
        break;
      case 'tool.start':
        handleToolStart(ev, api);
        break;
      case 'tool.complete':
        handleToolComplete(ev, api);
        break;
      case 'wiser.request':
        handleWiserRequest(ev, api);
        break;
      case 'approval.request':
        handleApprovalRequest(ev, api);
        break;
      case 'sudo.request':
        handleSudoRequest(ev, api);
        break;
      case 'secret.request':
        handleSecretRequest(ev, api);
        break;
      case 'background.complete':
        handleBackgroundComplete(ev, api);
        break;
      case 'subagent.spawn_requested':
        handleSubagentSpawnRequested(ev, api);
        break;
      case 'subagent.start':
        handleSubagentStart(ev, api);
        break;
      case 'subagent.thinking':
        handleSubagentThinking(ev, api);
        break;
      case 'subagent.tool':
        handleSubagentTool(ev, api);
        break;
      case 'subagent.progress':
        handleSubagentProgress(ev, api);
        break;
      case 'subagent.complete':
        handleSubagentComplete(ev, api);
        break;
      case 'message.delta':
        handleMessageDelta(ev, api);
        break;
      case 'message.complete':
        handleMessageComplete(ev, api);
        break;
      case 'error':
        handleError(ev, api);
        break;
    }
  };
}