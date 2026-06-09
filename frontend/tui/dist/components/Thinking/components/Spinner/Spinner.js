import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx } from "react/jsx-runtime";
import { Text } from '@ector/ink';
import { useEffect, useMemo, useState } from 'react';
import { SPIN_INTERVAL_MS, THINK_SPIN_FRAMES, TOOL_SPIN_FRAMES } from '../../lib/treeLayout.js';
export function Spinner(t0) {
  const $ = _c(12);
  const {
    color,
    variant: t1
  } = t0;
  const variant = t1 === undefined ? "think" : t1;
  const t2 = variant === "tool" ? TOOL_SPIN_FRAMES : THINK_SPIN_FRAMES;
  let t3;
  if ($[0] !== t2) {
    t3 = [...t2];
    $[0] = t2;
    $[1] = t3;
  } else {
    t3 = $[1];
  }
  const frames = t3;
  const [frame, setFrame] = useState(0);
  let t4;
  if ($[2] === Symbol.for("react.memo_cache_sentinel")) {
    t4 = () => {
      setFrame(0);
    };
    $[2] = t4;
  } else {
    t4 = $[2];
  }
  let t5;
  if ($[3] !== frames) {
    t5 = [frames];
    $[3] = frames;
    $[4] = t5;
  } else {
    t5 = $[4];
  }
  useEffect(t4, t5);
  let t6;
  if ($[5] !== frames.length) {
    t6 = () => {
      const id = setInterval(() => setFrame(f => (f + 1) % frames.length), SPIN_INTERVAL_MS);
      return () => clearInterval(id);
    };
    $[5] = frames.length;
    $[6] = t6;
  } else {
    t6 = $[6];
  }
  let t7;
  if ($[7] !== frames) {
    t7 = [frames];
    $[7] = frames;
    $[8] = t7;
  } else {
    t7 = $[8];
  }
  useEffect(t6, t7);
  const t8 = frames[frame];
  let t9;
  if ($[9] !== color || $[10] !== t8) {
    t9 = _jsx(Text, {
      color,
      children: t8
    });
    $[9] = color;
    $[10] = t8;
    $[11] = t9;
  } else {
    t9 = $[11];
  }
  return t9;
}