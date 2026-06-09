const truthy = v => /^(?:1|true|yes|on)$/i.test((v ?? '').trim());
export const STARTUP_RESUME_ID = (process.env.ECTOR_TUI_RESUME ?? '').trim();
/** First user turn after session.create (from `ector chat -q` / `--query` on a TTY). */
export const STARTUP_INITIAL_PROMPT = (process.env.ECTOR_TUI_INITIAL_PROMPT ?? '').trim();
/** Local image path to attach before the startup prompt (from `ector chat --image`). */
export const STARTUP_INITIAL_IMAGE = (process.env.ECTOR_TUI_INITIAL_IMAGE ?? '').trim();
/** Create session in an isolated git worktree (`ector chat -w`). */
export const STARTUP_WORKTREE = truthy(process.env.ECTOR_TUI_WORKTREE);
export const MOUSE_TRACKING = !truthy(process.env.ECTOR_TUI_DISABLE_MOUSE);
export const NO_CONFIRM_DESTRUCTIVE = truthy(process.env.ECTOR_TUI_NO_CONFIRM);
// Skip AlternateScreen — TUI renders into the primary buffer so the host
// terminal's native scrollback captures whatever scrolls off the top.
// Experiment gate: lets us measure native scroll vs our virtualization on
// the same pipeline.
export const INLINE_MODE = truthy(process.env.ECTOR_TUI_INLINE);
// Live FPS counter overlay, fed by ink's onFrame (real render rate, not a
// synthetic timer).
export const SHOW_FPS = truthy(process.env.ECTOR_TUI_FPS);