#!/usr/bin/env bun
import { jsx as _jsx } from "react/jsx-runtime";
import { shutdownTui } from '@ector/ink';
import { MOUSE_MOVEMENT_TRACKING, MOUSE_TRACKING } from './config/env.js';
import { getUiState } from './app/uiStore.js';
import { GatewayClient } from './gatewayClient.js';
import { withBootSpinner } from './lib/bootSpinner.js';
import { debugSessionLog } from './lib/debugSessionLog.js';
import { forceProcessExit, setupGracefulExit } from './lib/gracefulExit.js';
import { formatBytes, performHeapDump } from './lib/memory.js';
import { startMemoryMonitor } from './lib/memoryMonitor.js';
if (!process.stdin.isTTY) {
  console.log('ector-tui: no TTY');
  process.exit(0);
}
const gw = new GatewayClient();
const {
  registerForceProcessExit
} = await import('@ector/ink');
registerForceProcessExit(forceProcessExit);
gw.start();
const dumpNotice = (snap, dump) => `ector-tui: ${snap.level} memory (${formatBytes(snap.heapUsed)}) — auto heap dump → ${dump?.heapPath ?? '(failed)'}\n`;
setupGracefulExit({
  cleanups: [() => gw.kill(), () => shutdownTui()],
  deferSigint: () => getUiState().busy,
  onError: (scope, err) => {
    const message = err instanceof Error ? `${err.name}: ${err.message}` : String(err);
    // #region agent log
    debugSessionLog('entry.tsx:onError', 'tui fatal error', {
      message: message.slice(0, 500),
      scope,
      stack: err instanceof Error ? err.stack?.slice(0, 800) : undefined
    }, 'C');
    // #endregion
    process.stderr.write(`ector-tui ${scope}: ${message.slice(0, 2000)}\n`);
  },
  onSignal: signal => {
    // #region agent log
    debugSessionLog('entry.tsx:onSignal', 'tui signal exit', {
      signal
    }, 'E');
    // #endregion
    process.stderr.write(`ector-tui: received ${signal}\n`);
  }
});
const stopMemoryMonitor = startMemoryMonitor({
  onCritical: (snap, dump) => {
    process.stderr.write(dumpNotice(snap, dump));
    process.stderr.write('ector-tui: exiting to avoid OOM; restart to recover\n');
    forceProcessExit(137);
  },
  onHigh: (snap, dump) => process.stderr.write(dumpNotice(snap, dump))
});
if (process.env.ECTOR_HEAPDUMP_ON_START === '1') {
  void performHeapDump('manual');
}
// Do not call shutdownTui() here — a momentarily idle loop must not tear down
// the renderer while the gateway child is still running (leaves alt-screen and
// scrolls the host terminal scrollback).
process.on('beforeExit', () => {
  stopMemoryMonitor();
});
const [ink, {
  App
}, {
  logFrameEvent
}, {
  trackFrame
}] = await withBootSpinner('a carregar interface…', () => Promise.all([import('@ector/ink'), import('./app.js'), import('./lib/perfPane.js'), import('./lib/fpsStore.js')]));
// Both consumers are undefined when their env flags are off; only attach
// onFrame when at least one is on so ink skips timing in the default case.
const onFrame = logFrameEvent || trackFrame ? event => {
  logFrameEvent?.(event);
  trackFrame?.(event.durationMs);
} : undefined;
await ink.render(_jsx(App, {
  gw: gw
}), {
  enableMouseMovement: MOUSE_MOVEMENT_TRACKING,
  exitOnCtrlC: false,
  mouseTracking: MOUSE_TRACKING,
  onFrame
});