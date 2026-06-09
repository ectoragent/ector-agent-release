import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx } from "react/jsx-runtime";
import { Text } from '@ector/ink';
import { useEffect, useState } from 'react';
import { HEART_COLORS } from '../../lib/statusBarHelpers.js';
export function GoodVibesHeart(t0) {
  const $ = _c(6);
  const {
    tick,
    t
  } = t0;
  const [active, setActive] = useState(false);
  const [color, setColor] = useState(t.color.cyan);
  let t1;
  let t2;
  if ($[0] !== t.color.cyan || $[1] !== tick) {
    t1 = () => {
      if (tick <= 0) {
        return;
      }
      const palette = [...HEART_COLORS, t.color.cyan];
      setColor(palette[Math.floor(Math.random() * palette.length)]);
      setActive(true);
      const id = setTimeout(() => setActive(false), 650);
      return () => clearTimeout(id);
    };
    t2 = [t.color.cyan, tick];
    $[0] = t.color.cyan;
    $[1] = tick;
    $[2] = t1;
    $[3] = t2;
  } else {
    t1 = $[2];
    t2 = $[3];
  }
  useEffect(t1, t2);
  if (!active) {
    return null;
  }
  let t3;
  if ($[4] !== color) {
    t3 = _jsx(Text, {
      color,
      children: "\u2665"
    });
    $[4] = color;
    $[5] = t3;
  } else {
    t3 = $[5];
  }
  return t3;
}