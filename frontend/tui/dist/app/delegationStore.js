import { atom } from 'nanostores';
const buildState = () => ({
  maxConcurrentChildren: null,
  maxSpawnDepth: null,
  paused: false,
  updatedAt: null
});
export const $delegationState = atom(buildState());
export const getDelegationState = () => $delegationState.get();
export const patchDelegationState = next => $delegationState.set({
  ...$delegationState.get(),
  ...next
});
export const resetDelegationState = () => $delegationState.set(buildState());
// ── Overlay accordion open-state ──────────────────────────────────────
//
// Lifted out of OverlaySection's local useState so collapse choices
// survive:
//   - navigating to a different subagent (Detail remounts)
//   - switching list ↔ detail mode (Detail unmounts in list mode)
//   - walking history (←/→)
// Keyed by section title; missing entries fall back to the section's
// `defaultOpen` prop.
export const $overlaySectionsOpen = atom({});
export const toggleOverlaySection = (title, defaultOpen) => {
  const state = $overlaySectionsOpen.get();
  const current = title in state ? state[title] : defaultOpen;
  $overlaySectionsOpen.set({
    ...state,
    [title]: !current
  });
};
export const getOverlaySectionOpen = (title, defaultOpen) => {
  const state = $overlaySectionsOpen.get();
  return title in state ? state[title] : defaultOpen;
};
/** Merge a raw RPC response into the store.  Tolerant of partial/omitted fields. */
export const applyDelegationStatus = r => {
  if (!r) {
    return;
  }
  const patch = {
    updatedAt: Date.now()
  };
  if (typeof r.max_spawn_depth === 'number') {
    patch.maxSpawnDepth = r.max_spawn_depth;
  }
  if (typeof r.max_concurrent_children === 'number') {
    patch.maxConcurrentChildren = r.max_concurrent_children;
  }
  if (typeof r.paused === 'boolean') {
    patch.paused = r.paused;
  }
  patchDelegationState(patch);
};