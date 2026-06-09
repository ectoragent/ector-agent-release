import { buildSetupRequiredSections, SETUP_REQUIRED_TITLE } from '../../../content/setup.js';
import { STATUS } from '../../../content/uiStatus.js';
import { rpcErrorMessage } from '../../../lib/rpc.js';
import { patchUiState } from '../../uiStore.js';
import { NO_PROVIDER_RE } from '../handlerApi.js';
export function handleGatewayReady(ev, api) {
  const user = ev.payload?.user;
  if (user?.id || user?.email) {
    patchUiState({
      bootUserEmail: user.email?.trim() || null,
      bootUserId: user.id?.trim() || null
    });
  }
  api.rpc('commands.catalog', {}).then(r => {
    if (!r?.pairs) {
      return;
    }
    api.setCatalog({
      canon: r.canon ?? {},
      categories: r.categories ?? [],
      pairs: r.pairs,
      skillCount: r.skill_count ?? 0,
      sub: r.sub ?? {}
    });
    if (r.warning) {
      api.turnController.pushActivity(String(r.warning), 'warn');
    }
  }).catch(e => api.turnController.pushActivity(`command catalog unavailable: ${rpcErrorMessage(e)}`, 'info'));
  if (!api.STARTUP_RESUME_ID) {
    patchUiState({
      status: STATUS.forgingSession
    });
    api.newSession();
    return;
  }
  patchUiState({
    status: STATUS.resuming
  });
  api.resumeById(api.STARTUP_RESUME_ID);
}
export function handleError(ev, api) {
  api.turnController.recordError();
  const message = String(ev.payload?.message || 'unknown error');
  api.turnController.pushActivity(message, 'error');
  if (NO_PROVIDER_RE.test(message)) {
    api.panel(SETUP_REQUIRED_TITLE, buildSetupRequiredSections());
    api.setStatus(STATUS.setupRequired);
    return;
  }
  api.sys(`error: ${message}`);
  api.setStatus(STATUS.ready);
}