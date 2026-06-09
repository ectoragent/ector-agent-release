import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx } from "react/jsx-runtime";
import { useStore } from '@nanostores/react';
import { GatewayProvider } from './app/gatewayContext.js';
import { $uiState } from './app/uiStore.js';
import { useMainApp } from './app/useMainApp.js';
import { AppLayout } from './components/AppLayout/index.js';
export function App(t0) {
  const $ = _c(8);
  const {
    gw
  } = t0;
  const {
    appActions,
    appComposer,
    appProgress,
    appStatus,
    appTranscript,
    gateway
  } = useMainApp(gw);
  const {
    mouseTracking
  } = useStore($uiState);
  let t1;
  if ($[0] !== appActions || $[1] !== appComposer || $[2] !== appProgress || $[3] !== appStatus || $[4] !== appTranscript || $[5] !== gateway || $[6] !== mouseTracking) {
    t1 = _jsx(GatewayProvider, {
      value: gateway,
      children: _jsx(AppLayout, {
        actions: appActions,
        composer: appComposer,
        mouseTracking,
        progress: appProgress,
        status: appStatus,
        transcript: appTranscript
      })
    });
    $[0] = appActions;
    $[1] = appComposer;
    $[2] = appProgress;
    $[3] = appStatus;
    $[4] = appTranscript;
    $[5] = gateway;
    $[6] = mouseTracking;
    $[7] = t1;
  } else {
    t1 = $[7];
  }
  return t1;
}