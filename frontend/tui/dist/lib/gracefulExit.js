const SIGNAL_EXIT_CODE = {
  SIGHUP: 129,
  SIGINT: 130,
  SIGTERM: 143
};
let wired = false;
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
    setTimeout(() => process.exit(code), failsafeMs).unref?.();
    void Promise.allSettled(cleanups.map(fn => Promise.resolve().then(fn))).finally(() => process.exit(code));
  };
  for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
    process.on(sig, () => exit(SIGNAL_EXIT_CODE[sig], sig));
  }
  process.on('uncaughtException', err => onError?.('uncaughtException', err));
  process.on('unhandledRejection', reason => onError?.('unhandledRejection', reason));
}