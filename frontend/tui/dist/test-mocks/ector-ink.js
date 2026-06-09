import { createElement, Fragment } from 'react';
export const Box = ({
  children
}) => createElement('motion.div', null, children);
export const Text = ({
  children
}) => createElement('motion.span', null, children);
export const ScrollBox = ({
  children
}) => createElement(Fragment, null, children);
export const Ansi = ({
  children
}) => createElement(Fragment, null, children);
export const AlternateScreen = ({
  children
}) => createElement(Fragment, null, children);
export const NoSelect = ({
  children
}) => createElement(Fragment, null, children);
export const Link = ({
  children
}) => createElement('a', null, children);
export const Newline = () => '\n';
export const Spacer = () => null;
export const RawAnsi = ({
  children
}) => children;
export const TextInput = () => null;
export const stringWidth = s => [...s].length;
export const isXtermJs = () => false;
export const scrollFastPathStats = {
  captured: 0,
  declined: {
    heightDeltaMismatch: 0,
    noPrevScreen: 0,
    other: 0
  },
  taken: 0
};
export const evictInkCaches = () => ({
  lineWidth: 0,
  slice: 0,
  width: 0,
  wrap: 0
});
export const measureElement = () => ({
  height: 1,
  width: 80
});
export const supportsTerminalFastEcho = () => false;
export function render() {
  return Promise.resolve({
    cleanup: () => {},
    rerender: () => {},
    unmount: () => {},
    waitUntilExit: async () => {}
  });
}
export const renderSync = render;
export function useInput() {}
export function useStdin() {
  return {
    exitOnCtrlC: false,
    inputEmitter: {
      on: () => {},
      off: () => {}
    },
    isRawModeSupported: true,
    querier: null,
    setRawMode: () => {},
    stdin: process.stdin
  };
}
export function useStdout() {
  return {
    stdout: process.stdout
  };
}
export function useStderr() {
  return {
    stderr: process.stderr
  };
}
export function useApp() {
  return {
    exit: () => process.exit(0)
  };
}
export function useSelection() {
  return {
    captureScrolledRows: () => {},
    clearSelection: () => {},
    copySelection: async () => '',
    copySelectionNoClear: async () => '',
    getState: () => null,
    hasSelection: () => false,
    moveFocus: () => {},
    setSelectionBgColor: () => {},
    shiftAnchor: () => {},
    shiftSelection: () => {},
    subscribe: () => () => {}
  };
}
export function useHasSelection() {
  return false;
}
export function writeClipboardTextSync(text) {
  return Boolean(text?.trim());
}
export function copyTextToSystemClipboard() {}
export function writeOsc52Clipboard() {}
export function useTerminalTitle() {}
export function useTerminalFocus() {
  return true;
}
export function useDeclaredCursor() {
  return () => {};
}
export function useTerminalViewport() {
  return [() => {}, {
    isVisible: true
  }];
}
export function useTabStatus() {
  return true;
}
export async function withInkSuspended(run) {
  await run();
}
export function useExternalProcess() {
  return withInkSuspended;
}