const FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];
/** Stderr spinner while Ink/modules load (before the TUI can render). */
export async function withBootSpinner(label, run) {
  if (!process.stderr.isTTY) {
    process.stderr.write(`ector-tui: ${label}\n`);
    return run();
  }
  let frame = 0;
  const tick = () => {
    process.stderr.write(`\r\x1b[2Kector-tui: ${FRAMES[frame % FRAMES.length]} ${label}`);
    frame += 1;
  };
  tick();
  const timer = setInterval(tick, 80);
  try {
    return await run();
  } finally {
    clearInterval(timer);
    process.stderr.write('\r\x1b[2K');
  }
}