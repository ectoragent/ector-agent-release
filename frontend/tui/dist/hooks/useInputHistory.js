import { c as _c } from "react/compiler-runtime";
import { useRef, useState } from 'react';
import * as inputHistory from '../lib/history.js';
export function useInputHistory() {
  const $ = _c(3);
  let t0;
  if ($[0] === Symbol.for("react.memo_cache_sentinel")) {
    t0 = inputHistory.load();
    $[0] = t0;
  } else {
    t0 = $[0];
  }
  const historyRef = useRef(t0);
  const [historyIdx, setHistoryIdx] = useState(null);
  const historyDraftRef = useRef("");
  let t1;
  if ($[1] !== historyIdx) {
    t1 = {
      historyRef,
      historyIdx,
      setHistoryIdx,
      historyDraftRef,
      pushHistory: inputHistory.append
    };
    $[1] = historyIdx;
    $[2] = t1;
  } else {
    t1 = $[2];
  }
  return t1;
}