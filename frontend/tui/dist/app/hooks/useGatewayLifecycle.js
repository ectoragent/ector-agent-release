import { useEffect, useRef } from 'react';
import { STATUS } from '../../content/uiStatus.js';
import { turnController } from '../turnController.js';
import { patchUiState } from '../uiStore.js';
/** Attach gateway JSON-RPC events; drain buffered events; kill on unmount. */
export function useGatewayLifecycle(gw, onEvent, sys) {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  useEffect(() => {
    const handler = ev => onEventRef.current(ev);
    const exitHandler = () => {
      turnController.reset();
      patchUiState({
        busy: false,
        sid: null,
        status: STATUS.gatewayExited
      });
      turnController.pushActivity('gateway encerrou · /logs para inspecionar', 'error');
      sys('erro: gateway encerrou');
    };
    gw.on('event', handler);
    gw.on('exit', exitHandler);
    gw.drain();
    return () => {
      gw.off('event', handler);
      gw.off('exit', exitHandler);
      gw.kill();
    };
  }, [gw, sys]);
}