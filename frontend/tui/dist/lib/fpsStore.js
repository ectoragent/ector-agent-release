// Tiny FPS tracker fed by ink's onFrame callback. Each entry is an Ink
// frame (React commit + drain-only frames) — the right notion for
// user-perceived motion.
//
// Zero-cost when ECTOR_TUI_FPS is unset: trackFrame is undefined so the
// onFrame callback short-circuits at the optional chain.
import { atom } from 'nanostores';
import { SHOW_FPS } from '../config/env.js';
const WINDOW_SIZE = 30;
export const $fpsState = atom({
  fps: 0,
  lastDurationMs: 0,
  totalFrames: 0
});
const timestamps = [];
let totalFrames = 0;
export const trackFrame = SHOW_FPS ? durationMs => {
  timestamps.push(performance.now());
  if (timestamps.length > WINDOW_SIZE) {
    timestamps.shift();
  }
  totalFrames++;
  if (timestamps.length < 2) {
    return;
  }
  const elapsed = (timestamps[timestamps.length - 1] - timestamps[0]) / 1000;
  if (elapsed > 0) {
    $fpsState.set({
      fps: Math.round((timestamps.length - 1) / elapsed * 10) / 10,
      lastDurationMs: Math.round(durationMs * 100) / 100,
      totalFrames
    });
  }
} : undefined;