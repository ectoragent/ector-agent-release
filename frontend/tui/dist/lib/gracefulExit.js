const SIGNAL_EXIT_CODE = {
  SIGHUP: 129,
  SIGINT: 130,
  SIGTERM: 143
};
let wired = false;
let registeredCleanups = [];
const runCleanupsSync = cleanups => {
  for (const fn of cleanups) {
    try {
      fn();
    } catch {
      // best-effort
    }
  }
};
/** Run all registered cleanups then exit — used by stdin force-quit and signal handlers. */
export function forceProcessExit(code) {
  runCleanupsSync(registeredCleanups);
  process.exit(code);
}
export function setupGracefulExit({
  cleanups = [],
  deferSigint,
  failsafeMs = 4000,
  onError,
  onSignal
} = {}) {
  if (wired) {
    return;
  }
  wired = true;
  registeredCleanups = cleanups;
  let shuttingDown = false;
  let sigintStreak = 0;
  const exit = (code, signal) => {
    if (shuttingDown) {
      process.exit(code);
      return;
    }
    shuttingDown = true;
    if (signal) {
      onSignal?.(signal);
    }
    runCleanupsSync(cleanups);
    process.exit(code);
  };
  for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
    process.on(sig, () => {
      if (sig === 'SIGINT') {
        sigintStreak++;
        if (deferSigint?.() && sigintStreak === 1) {
          return;
        }
        if (sigintStreak >= 2) {
          forceProcessExit(SIGNAL_EXIT_CODE[sig]);
          return;
        }
      }
      exit(SIGNAL_EXIT_CODE[sig], sig);
    });
  }
  process.on('uncaughtException', err => {
    onError?.('uncaughtException', err);
    forceProcessExit(1);
  });
  process.on('unhandledRejection', reason => {
    onError?.('unhandledRejection', reason);
    forceProcessExit(1);
  });
  if (failsafeMs > 0) {
    const watchdog = setInterval(() => {
      if (shuttingDown) {
        process.exit(1);
      }
    }, failsafeMs);
    watchdog.unref?.();
  }
}