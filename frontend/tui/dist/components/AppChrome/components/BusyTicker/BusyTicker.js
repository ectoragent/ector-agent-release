import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Text } from '@ector/ink';
import { useEffect, useState } from 'react';
import { fmtDuration } from '../../../../domain/messages.js';
import { Spinner } from '../../../Thinking/index.js';
export function BusyTicker(t0) {
  const $ = _c(9);
  const {
    color,
    startedAt
  } = t0;
  const [now, setNow] = useState(_temp);
  let t1;
  let t2;
  if ($[0] === Symbol.for("react.memo_cache_sentinel")) {
    t1 = () => {
      const id = setInterval(() => setNow(Date.now()), 1000);
      return () => clearInterval(id);
    };
    t2 = [];
    $[0] = t1;
    $[1] = t2;
  } else {
    t1 = $[0];
    t2 = $[1];
  }
  useEffect(t1, t2);
  let t3;
  if ($[2] !== color || $[3] !== now || $[4] !== startedAt) {
    let t4;
    if ($[6] !== now || $[7] !== startedAt) {
      t4 = startedAt ? ` · ${fmtDuration(now - startedAt)}` : "";
      $[6] = now;
      $[7] = startedAt;
      $[8] = t4;
    } else {
      t4 = $[8];
    }
    t3 = _jsxs(Text, {
      color,
      children: [_jsx(Spinner, {
        color,
        variant: "think"
      }), t4]
    });
    $[2] = color;
    $[3] = now;
    $[4] = startedAt;
    $[5] = t3;
  } else {
    t3 = $[5];
  }
  return t3;
}
function _temp() {
  return Date.now();
}