import { CTRL_C_DOUBLE_TAP_MS } from '../config/input.js';
export const resolveCtrlCAction = ctx => {
  const windowMs = ctx.windowMs ?? CTRL_C_DOUBLE_TAP_MS;
  if (ctx.busy) {
    if (ctx.hasDraft) {
      return 'clear_draft';
    }
    if (ctx.now - ctx.lastCtrlCAt < windowMs) {
      return 'die';
    }
    return ctx.hasSid ? 'interrupt' : 'noop';
  }
  if (ctx.hasDraft) {
    return 'clear_draft';
  }
  return 'die';
};
export const resolveOverlayCtrlCAction = overlay => {
  if (overlay.approval || overlay.wiser || overlay.confirm || overlay.sudo || overlay.secret || overlay.modelPicker || overlay.skillsHub || overlay.picker || overlay.agents) {
    return 'cancel';
  }
  return 'noop';
};