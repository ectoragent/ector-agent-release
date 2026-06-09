import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Text } from '@ector/ink';
import { useEffect, useState } from 'react';
/** spinner frames */
export const BUSY_METER_GLYPHS = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];
const BUSY_METER_TICK_MS = 120;
export function ctxBusyMeterGlyph(frame) {
  return BUSY_METER_GLYPHS[frame % BUSY_METER_GLYPHS.length];
}
export function ctxBarColor(pct, t) {
  if (pct == null) {
    return t.color.dim;
  }
  if (pct >= 95) {
    return t.color.statusCritical;
  }
  if (pct > 80) {
    return t.color.statusBad;
  }
  if (pct >= 50) {
    return t.color.statusWarn;
  }
  return t.color.cyan;
}
/** Context window usage: filled blocks + dim track, no ASCII brackets. */
export function CtxUsageBar({
  pct,
  w,
  t
}) {
  const p = Math.max(0, Math.min(100, pct ?? 0));
  const filled = Math.round(p / 100 * w);
  const empty = Math.max(0, w - filled);
  const fillColor = ctxBarColor(pct, t);
  const track = t.color.dim;
  return _jsxs(Text, {
    children: [_jsx(Text, {
      color: track,
      children: '\u258f'
    }), _jsx(Text, {
      color: fillColor,
      children: '\u2588'.repeat(filled)
    }), _jsx(Text, {
      color: track,
      children: '\u2592'.repeat(empty)
    }), _jsx(Text, {
      color: track,
      children: '\u2595'
    })]
  });
}
/** Hook for braille busy-meter animation (use in footer/status siblings, not inside `<Text dim>`). */
export function useCtxBusyMeterFrame(t0) {
  const $ = _c(3);
  const tickMs = t0 === undefined ? BUSY_METER_TICK_MS : t0;
  const [frame, setFrame] = useState(0);
  let t1;
  let t2;
  if ($[0] !== tickMs) {
    t1 = () => {
      const id = setInterval(() => setFrame(_temp), tickMs);
      return () => clearInterval(id);
    };
    t2 = [tickMs];
    $[0] = tickMs;
    $[1] = t1;
    $[2] = t2;
  } else {
    t1 = $[1];
    t2 = $[2];
  }
  useEffect(t1, t2);
  return frame;
}
/** Single braille spinner — sibling of footer `<Text>`, not nested inside `dim` parents. */
function _temp(f) {
  return f + 1;
}
export function CtxBusyMeter(t0) {
  const $ = _c(3);
  const {
    t
  } = t0;
  const frame = useCtxBusyMeterFrame();
  let t1;
  if ($[0] !== frame || $[1] !== t.color.statusBarMeta) {
    t1 = _jsxs(Text, {
      color: t.color.statusBarMeta,
      children: [" ", ctxBusyMeterGlyph(frame)]
    });
    $[0] = frame;
    $[1] = t.color.statusBarMeta;
    $[2] = t1;
  } else {
    t1 = $[2];
  }
  return t1;
}