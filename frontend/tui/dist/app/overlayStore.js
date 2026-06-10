import { atom, computed } from 'nanostores';
const buildOverlayState = () => ({
  agents: false,
  agentsInitialHistoryIndex: 0,
  approval: null,
  wiser: null,
  confirm: null,
  modelPicker: false,
  pager: null,
  picker: false,
  secret: null,
  skillsHub: false,
  sudo: null
});
export const $overlayState = atom(buildOverlayState());
export const $isBlocked = computed($overlayState, ({
  agents,
  approval,
  wiser,
  confirm,
  modelPicker,
  pager,
  picker,
  secret,
  skillsHub,
  sudo
}) => Boolean(agents || approval || wiser || confirm || modelPicker || pager || picker || secret || skillsHub || sudo));
export const getOverlayState = () => $overlayState.get();
export const patchOverlayState = next => $overlayState.set(typeof next === 'function' ? next($overlayState.get()) : {
  ...$overlayState.get(),
  ...next
});
/** Full reset — used by session/turn teardown and tests. */
export const resetOverlayState = () => $overlayState.set(buildOverlayState());
/**
 * Soft reset: drop FLOW-scoped overlays (approval / wiser / confirm / sudo
 * / secret / pager) but PRESERVE user-toggled ones — agents dashboard, model
 * picker, skills hub, session picker.  Those are opened deliberately and
 * shouldn't vanish when a turn ends.  Called from turnController.idle() on
 * every turn completion / interrupt; the old "reset everything" behaviour
 * silently closed /agents the moment delegation finished.
 */
export const resetFlowOverlays = () => {
  const prev = $overlayState.get();
  $overlayState.set({
    ...buildOverlayState(),
    agents: prev.agents,
    agentsInitialHistoryIndex: prev.agentsInitialHistoryIndex,
    modelPicker: prev.modelPicker,
    picker: prev.picker,
    skillsHub: prev.skillsHub,
    // idle() runs on message.complete but the gateway thread may still be
    // blocked in sudo/secret/approval/wiser — never dismiss those prompts.
    ...(prev.sudo ? {
      sudo: prev.sudo
    } : {}),
    ...(prev.secret ? {
      secret: prev.secret
    } : {}),
    ...(prev.approval ? {
      approval: prev.approval
    } : {}),
    ...(prev.wiser ? {
      wiser: prev.wiser
    } : {}),
    ...(prev.confirm ? {
      confirm: prev.confirm
    } : {})
  });
};