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
  let sigintStreak = 0;
  const exit = (code, signal) => {
    if (shuttingDown) {
      // Shutdown already started but the process is stuck — force exit.
      process.exit(code);
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
    process.on(sig, () => {
      if (sig === 'SIGINT') {
        sigintStreak++;
        if (sigintStreak >= 2) {
          runCleanupsSync(cleanups);
          process.exit(SIGNAL_EXIT_CODE[sig]);
          return;
        }
      }
      exit(SIGNAL_EXIT_CODE[sig], sig);
    });
  }
  process.on('uncaughtException', err => {
    onError?.('uncaughtException', err);
    if (!shuttingDown) {
      shuttingDown = true;
      runCleanupsSync(cleanups);
      process.exit(1);
    } else {
      process.exit(1);
    }
  });
  process.on('unhandledRejection', reason => {
    onError?.('unhandledRejection', reason);
    runCleanupsSync(cleanups);
    process.exit(1);
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