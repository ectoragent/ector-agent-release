import { buildLoginRequiredSections, LOGIN_REQUIRED_TITLE } from '../../../content/auth.js';
import { STATUS } from '../../../content/uiStatus.js';
import { getUiState, patchUiState } from '../../uiStore.js';
import { turnController } from '../../turnController.js';
export function handleIdentityRevoked(_ev, api) {
  api.panel(LOGIN_REQUIRED_TITLE, buildLoginRequiredSections());
  patchUiState({
    status: STATUS.loginRequired
  });
  turnController.idle();
  api.turnController.pushActivity('Sessão encerrada noutro terminal. Execute `ector login` para continuar.', 'warn');
}
export function handleIdentityRestored(ev, api) {
  const user = ev.payload?.user;
  const email = user?.email?.trim();
  const id = user?.id?.trim();
  const hasSid = Boolean(getUiState().sid);
  patchUiState({
    bootUserEmail: email || null,
    bootUserId: id || null,
    status: hasSid ? STATUS.ready : STATUS.forgingSession
  });
  api.turnController.pushActivity(email ? `Sessão restaurada (${email}).` : 'Sessão restaurada.', 'info');
  if (!hasSid) {
    void api.newSession();
  }
}
export async function handleIdentityUserChanged(ev, api, ctx) {
  const payload = ev.payload;
  const user = payload?.user;
  const email = user?.email?.trim() || '';
  const id = user?.id?.trim() || '';
  patchUiState({
    bootUserEmail: email || null,
    bootUserId: id || null
  });
  const sid = getUiState().sid;
  if (sid) {
    await ctx.session.closeSession(sid);
  }
  ctx.session.resetSession();
  turnController.idle();
  api.turnController.pushActivity(email ? `Conta alterada para ${email}. A iniciar sessão nova…` : 'Conta alterada. A iniciar sessão nova…', 'warn');
  await ctx.session.newSession();
}