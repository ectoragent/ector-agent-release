import { patchOverlayState } from '../../app/overlayStore.js';
export const closeAgentsOverlay = () => patchOverlayState({
  agents: false
});
export const openAgentsOverlay = () => patchOverlayState({
  agents: true
});