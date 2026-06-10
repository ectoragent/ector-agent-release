const SIGNAL_EXIT_CODE = {
  SIGHUP: 129,
  SIGINT: 130,
  SIGTERM: 143
};
let wired = false;
const runCleanupsSync = cleanups => {
  for (const fn of cleanups) {
    try {
      fn();
    } catch {
      // best-effort
    }
  }
};
export function setupGracefulExit({
  cleanups = [],
  failsafeMs = 4000,
  onError,
  onSignal
} = {}) {
  if (wired) {
    return;
  }
  wired = true;
  let shuttingDown = false;
  const exit = (code, signal) => {
    if (shuttingDown) {
      return;
    }
    shuttingDown = true;
    if (signal) {
      onSignal?.(signal);
    }
    // Restore TTY synchronously — async cleanups left the shell in mouse/raw mode.
    runCleanupsSync(cleanups);
    process.exit(code);
  };
  for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
    process.on(sig, () => exit(SIGNAL_EXIT_CODE[sig], sig));
  }
  process.on('uncaughtException', err => {
    onError?.('uncaughtException', err);
    if (!shuttingDown) {
      shuttingDown = true;
      runCleanupsSync(cleanups);
      process.exit(1);
    }
  });
  process.on('unhandledRejection', reason => onError?.('unhandledRejection', reason));
  void failsafeMs;
}