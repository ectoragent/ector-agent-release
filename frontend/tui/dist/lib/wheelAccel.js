// Wheel-scroll acceleration state machine.
//
// One event = 1 row feels sluggish on trackpads (200+ ev/s) and sustained
// mouse-wheel; one event = 6 rows teleports and ruins precision.
// Heuristic on inter-event gap + direction flips:
//
//   gap < 5ms                 → same-batch burst → 1 row/event
//   gap < 40ms (native)       → ramp +0.3, cap 6
//   gap 80-500ms (xterm.js)   → mult = 1 + (mult-1)·0.5^(gap/150) + 5·decay
//                               cap 3 slow / 6 fast
//   gap > 500ms               → reset (deliberate click stays responsive)
//   flip + flip-back ≤200ms   → encoder bounce → engage wheel-mode (sticky cap)
//   5 consecutive <5ms events → trackpad flick → disengage wheel-mode
//
// Native terminals (Ghostty, iTerm2) and xterm.js embedders (VS Code,
// Cursor) emit wheel events with different cadences, hence two paths.
import { isXtermJs } from '@ector/ink';
// ── Native (ghostty, iTerm2, WezTerm, …) ───────────────────────────────
const WHEEL_ACCEL_WINDOW_MS = 90;
const WHEEL_ACCEL_STEP = 1.25;
const WHEEL_ACCEL_MAX = 22;
// ── Encoder bounce / wheel-mode (mechanical wheels) ────────────────────
const WHEEL_BOUNCE_GAP_MAX_MS = 200;
const WHEEL_MODE_STEP = 15;
const WHEEL_MODE_CAP = 15;
const WHEEL_MODE_RAMP = 3;
const WHEEL_MODE_IDLE_DISENGAGE_MS = 1500;
// ── xterm.js (VS Code / Cursor / browser terminals) ────────────────────
const WHEEL_DECAY_HALFLIFE_MS = 120;
const WHEEL_DECAY_STEP = 16;
const WHEEL_BURST_MS = 5;
const WHEEL_DECAY_GAP_MS = 70;
const WHEEL_DECAY_CAP_SLOW = 10;
const WHEEL_DECAY_CAP_FAST = 26;
const WHEEL_DECAY_IDLE_MS = 450;
export function initWheelAccel(xtermJs = false, base = 1) {
  return {
    burstCount: 0,
    base,
    dir: 0,
    frac: 0,
    mult: base,
    pendingFlip: false,
    time: 0,
    wheelMode: false,
    xtermJs
  };
}
/** ECTOR_TUI_SCROLL_SPEED (or CLAUDE_CODE_SCROLL_SPEED for portability).
 *  Default 1.5, clamped (0, 20]. */
export function readScrollSpeedBase() {
  const n = parseFloat(process.env.ECTOR_TUI_SCROLL_SPEED ?? process.env.CLAUDE_CODE_SCROLL_SPEED ?? '');
  return Number.isFinite(n) && n > 0 ? Math.min(n, 20) : 2.5;
}
export function initWheelAccelForHost() {
  return initWheelAccel(isXtermJs(), readScrollSpeedBase());
}
/** Compute rows for one wheel event, mutating `state`. Returns 0 when a
 *  direction flip is deferred for bounce detection — call sites should
 *  no-op on 0. */
export function computeWheelStep(state, dir, now) {
  return state.xtermJs ? xtermJsStep(state, dir, now) : nativeStep(state, dir, now);
}
/** Spread fractional rows across high-frequency wheel events (smoother trackpad). */
const applyWheelRows = (state, mult) => {
  const total = mult + state.frac;
  const rows = Math.floor(total);
  state.frac = total - rows;
  return rows;
};
function nativeStep(state, dir, now) {
  // Idle disengage runs first so a pending bounce can't mask "user paused
  // 1.5s then mouse-clicked" as a real reversal.
  if (state.wheelMode && now - state.time > WHEEL_MODE_IDLE_DISENGAGE_MS) {
    state.wheelMode = false;
    state.burstCount = 0;
    state.mult = state.base;
  }
  if (state.pendingFlip) {
    state.pendingFlip = false;
    if (dir !== state.dir || now - state.time > WHEEL_BOUNCE_GAP_MAX_MS) {
      // Real reversal (flip persisted OR flip-back too late). Commit.
      state.dir = dir;
      state.time = now;
      state.mult = state.base;
      return applyWheelRows(state, state.mult);
    }
    state.wheelMode = true;
    state.dir = dir;
    state.time = now;
    return applyWheelRows(state, Math.max(1, state.base));
  }
  const gap = now - state.time;
  if (dir !== state.dir && state.dir !== 0) {
    state.pendingFlip = true;
    state.time = now;
    return 0;
  }
  state.dir = dir;
  state.time = now;
  if (state.wheelMode) {
    if (gap < WHEEL_BURST_MS) {
      // Same-batch burst (SGR proportional) OR trackpad flick.
      if (++state.burstCount >= 5) {
        state.wheelMode = false;
        state.burstCount = 0;
        state.mult = state.base;
      } else {
        return applyWheelRows(state, state.base * 0.65);
      }
    } else {
      state.burstCount = 0;
    }
  }
  if (state.wheelMode) {
    const m = Math.pow(0.5, gap / WHEEL_DECAY_HALFLIFE_MS);
    const cap = Math.max(WHEEL_MODE_CAP, state.base * 2);
    const next = 1 + (state.mult - 1) * m + WHEEL_MODE_STEP * m;
    state.mult = Math.min(cap, next, state.mult + WHEEL_MODE_RAMP);
    return applyWheelRows(state, state.mult);
  }
  // Trackpad / hi-res native: wider window keeps ramp smooth between ticks.
  if (gap > WHEEL_ACCEL_WINDOW_MS) {
    state.mult = state.base;
  } else {
    const cap = Math.max(WHEEL_ACCEL_MAX, state.base * 2.5);
    state.mult = Math.min(cap, state.mult + WHEEL_ACCEL_STEP);
  }
  return applyWheelRows(state, state.mult);
}
function xtermJsStep(state, dir, now) {
  const gap = now - state.time;
  const sameDir = dir === state.dir;
  state.time = now;
  state.dir = dir;
  if (sameDir && gap < WHEEL_BURST_MS) {
    return applyWheelRows(state, state.base || 1.5);
  }
  if (!sameDir || gap > WHEEL_DECAY_IDLE_MS) {
    state.mult = 7;
    state.frac = 0;
  } else {
    const m = Math.pow(0.5, gap / WHEEL_DECAY_HALFLIFE_MS);
    const cap = gap >= WHEEL_DECAY_GAP_MS ? WHEEL_DECAY_CAP_SLOW : WHEEL_DECAY_CAP_FAST;
    state.mult = Math.min(cap, 1 + (state.mult - 1) * m + WHEEL_DECAY_STEP * m);
  }
  return applyWheelRows(state, state.mult);
}