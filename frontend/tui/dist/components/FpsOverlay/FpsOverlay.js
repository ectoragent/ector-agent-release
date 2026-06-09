import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
// FPS counter overlay (ECTOR_TUI_FPS=1). Zero-cost when disabled.
import { Text } from '@ector/ink';
import { useStore } from '@nanostores/react';
import { SHOW_FPS } from '../../config/env.js';
import { $fpsState } from '../../lib/fpsStore.js';
const fpsColor = fps => fps >= 50 ? 'green' : fps >= 30 ? 'yellow' : 'red';
export function FpsOverlay() {
  if (!SHOW_FPS) {
    return null;
  }
  return _jsx(FpsOverlayInner, {});
}
function FpsOverlayInner() {
  const $ = _c(4);
  const {
    fps,
    lastDurationMs,
    totalFrames
  } = useStore($fpsState);
  let t0;
  if ($[0] !== fps || $[1] !== lastDurationMs || $[2] !== totalFrames) {
    t0 = _jsxs(Text, {
      color: fpsColor(fps),
      children: [fps.toFixed(1).padStart(5), "fps \xB7 ", lastDurationMs.toFixed(1).padStart(5), "ms \xB7 #", totalFrames]
    });
    $[0] = fps;
    $[1] = lastDurationMs;
    $[2] = totalFrames;
    $[3] = t0;
  } else {
    t0 = $[3];
  }
  return t0;
}