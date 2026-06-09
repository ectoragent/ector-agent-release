import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx } from "react/jsx-runtime";
import { useStore } from '@nanostores/react';
import { memo } from 'react';
import { useGateway } from '../../../../app/gatewayContext.js';
import { $overlayState, patchOverlayState } from '../../../../app/overlayStore.js';
import { $uiState } from '../../../../app/uiStore.js';
import { AgentsOverlay } from '../../../AgentsOverlay/index.js';
export const AgentsOverlayPane = memo(function AgentsOverlayPane() {
  const $ = _c(4);
  const {
    gw
  } = useGateway();
  const ui = useStore($uiState);
  const overlay = useStore($overlayState);
  let t0;
  if ($[0] !== gw || $[1] !== overlay.agentsInitialHistoryIndex || $[2] !== ui.theme) {
    t0 = _jsx(AgentsOverlay, {
      gw,
      initialHistoryIndex: overlay.agentsInitialHistoryIndex,
      onClose: _temp,
      t: ui.theme
    });
    $[0] = gw;
    $[1] = overlay.agentsInitialHistoryIndex;
    $[2] = ui.theme;
    $[3] = t0;
  } else {
    t0 = $[3];
  }
  return t0;
});
function _temp() {
  return patchOverlayState({
    agents: false,
    agentsInitialHistoryIndex: 0
  });
}