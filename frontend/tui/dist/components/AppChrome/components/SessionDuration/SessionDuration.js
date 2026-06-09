import { c as _c } from "react/compiler-runtime";
import { useEffect, useState } from 'react';
import { fmtDuration } from '../../../../domain/messages.js';
export function SessionDuration(t0) {
  const $ = _c(5);
  const {
    startedAt
  } = t0;
  const [now, setNow] = useState(_temp);
  let t1;
  if ($[0] === Symbol.for("react.memo_cache_sentinel")) {
    t1 = () => {
      setNow(Date.now());
      const id = setInterval(() => setNow(Date.now()), 1000);
      return () => clearInterval(id);
    };
    $[0] = t1;
  } else {
    t1 = $[0];
  }
  let t2;
  if ($[1] !== startedAt) {
    t2 = [startedAt];
    $[1] = startedAt;
    $[2] = t2;
  } else {
    t2 = $[2];
  }
  useEffect(t1, t2);
  const t3 = now - startedAt;
  let t4;
  if ($[3] !== t3) {
    t4 = fmtDuration(t3);
    $[3] = t3;
    $[4] = t4;
  } else {
    t4 = $[4];
  }
  return t4;
}
function _temp() {
  return Date.now();
}