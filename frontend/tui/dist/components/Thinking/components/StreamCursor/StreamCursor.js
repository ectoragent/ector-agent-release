import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx } from "react/jsx-runtime";
import { Text } from '@ector/ink';
import { useEffect, useState } from 'react';
export function StreamCursor(t0) {
  const $ = _c(9);
  const {
    color,
    dimColor,
    streaming: t1,
    visible: t2
  } = t0;
  const streaming = t1 === undefined ? false : t1;
  const visible = t2 === undefined ? false : t2;
  const [on, setOn] = useState(true);
  let t3;
  let t4;
  if ($[0] !== streaming || $[1] !== visible) {
    t3 = () => {
      if (!visible || !streaming) {
        setOn(true);
        return;
      }
      const id = setInterval(() => setOn(_temp), 420);
      return () => clearInterval(id);
    };
    t4 = [streaming, visible];
    $[0] = streaming;
    $[1] = visible;
    $[2] = t3;
    $[3] = t4;
  } else {
    t3 = $[2];
    t4 = $[3];
  }
  useEffect(t3, t4);
  if (!visible) {
    return null;
  }
  let t5;
  if ($[4] !== color || $[5] !== dimColor || $[6] !== on || $[7] !== streaming) {
    t5 = dimColor ? _jsx(Text, {
      color,
      dim: true,
      children: streaming && on ? ">" : " "
    }) : _jsx(Text, {
      color,
      children: streaming && on ? ">" : " "
    });
    $[4] = color;
    $[5] = dimColor;
    $[6] = on;
    $[7] = streaming;
    $[8] = t5;
  } else {
    t5 = $[8];
  }
  return t5;
}
function _temp(v) {
  return !v;
}