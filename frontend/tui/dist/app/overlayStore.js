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
export const resetFlowOverlays = () => $overlayState.set({
  ...buildOverlayState(),
  agents: $overlayState.get().agents,
  agentsInitialHistoryIndex: $overlayState.get().agentsInitialHistoryIndex,
  modelPicker: $overlayState.get().modelPicker,
  picker: $overlayState.get().picker,
  skillsHub: $overlayState.get().skillsHub
});