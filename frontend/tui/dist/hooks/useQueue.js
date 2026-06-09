import { c as _c } from "react/compiler-runtime";
import { useCallback, useRef, useState } from 'react';
export function useQueue() {
  const $ = _c(10);
  let t0;
  if ($[0] === Symbol.for("react.memo_cache_sentinel")) {
    t0 = [];
    $[0] = t0;
  } else {
    t0 = $[0];
  }
  const queueRef = useRef(t0);
  let t1;
  if ($[1] === Symbol.for("react.memo_cache_sentinel")) {
    t1 = [];
    $[1] = t1;
  } else {
    t1 = $[1];
  }
  const [queuedDisplay, setQueuedDisplay] = useState(t1);
  const queueEditRef = useRef(null);
  const [queueEditIdx, setQueueEditIdx] = useState(null);
  let t2;
  if ($[2] === Symbol.for("react.memo_cache_sentinel")) {
    t2 = () => setQueuedDisplay([...queueRef.current]);
    $[2] = t2;
  } else {
    t2 = $[2];
  }
  const syncQueue = t2;
  let t3;
  if ($[3] === Symbol.for("react.memo_cache_sentinel")) {
    t3 = idx => {
      queueEditRef.current = idx;
      setQueueEditIdx(idx);
    };
    $[3] = t3;
  } else {
    t3 = $[3];
  }
  const setQueueEdit = t3;
  let t4;
  if ($[4] === Symbol.for("react.memo_cache_sentinel")) {
    t4 = text => {
      queueRef.current.push(text);
      syncQueue();
    };
    $[4] = t4;
  } else {
    t4 = $[4];
  }
  const enqueue = t4;
  let t5;
  if ($[5] === Symbol.for("react.memo_cache_sentinel")) {
    t5 = () => {
      const head = queueRef.current.shift();
      syncQueue();
      return head;
    };
    $[5] = t5;
  } else {
    t5 = $[5];
  }
  const dequeue = t5;
  let t6;
  if ($[6] === Symbol.for("react.memo_cache_sentinel")) {
    t6 = (i, text_0) => {
      queueRef.current[i] = text_0;
      syncQueue();
    };
    $[6] = t6;
  } else {
    t6 = $[6];
  }
  const replaceQ = t6;
  let t7;
  if ($[7] !== queueEditIdx || $[8] !== queuedDisplay) {
    t7 = {
      dequeue,
      enqueue,
      queueEditIdx,
      queueEditRef,
      queueRef,
      queuedDisplay,
      replaceQ,
      setQueueEdit,
      syncQueue
    };
    $[7] = queueEditIdx;
    $[8] = queuedDisplay;
    $[9] = t7;
  } else {
    t7 = $[9];
  }
  return t7;
}