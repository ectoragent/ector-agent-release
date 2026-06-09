import { c as _c } from "react/compiler-runtime";
import { useEffect, useRef, useState } from 'react';
import { asRpcResult } from '../lib/rpc.js';
const TAB_PATH_RE = /((?:["']?(?:[A-Za-z]:[\\/]|\.{1,2}\/|~\/|\/|@|[^"'`\s]+\/))[^\s]*)$/;
export function useCompletion(input, blocked, gw) {
  const $ = _c(10);
  let t0;
  if ($[0] === Symbol.for("react.memo_cache_sentinel")) {
    t0 = [];
    $[0] = t0;
  } else {
    t0 = $[0];
  }
  const [completions, setCompletions] = useState(t0);
  const [compIdx, setCompIdx] = useState(0);
  const [compReplace, setCompReplace] = useState(0);
  const ref = useRef("");
  let t1;
  let t2;
  if ($[1] !== blocked || $[2] !== gw || $[3] !== input) {
    t1 = () => {
      const clear = () => {
        setCompletions(_temp);
        setCompIdx(_temp2);
        setCompReplace(_temp3);
      };
      if (blocked) {
        ref.current = "";
        clear();
        return;
      }
      if (input === ref.current) {
        return;
      }
      ref.current = input;
      const isSlash = input.startsWith("/");
      const pathWord = isSlash ? null : input.match(TAB_PATH_RE)?.[1] ?? null;
      if (!isSlash && !pathWord) {
        clear();
        return;
      }
      const pathReplace = input.length - (pathWord?.length ?? 0);
      const t = setTimeout(() => {
        if (ref.current !== input) {
          return;
        }
        const req = isSlash ? gw.request("complete.slash", {
          text: input
        }) : gw.request("complete.path", {
          word: pathWord
        });
        req.then(raw => {
          if (ref.current !== input) {
            return;
          }
          const r = asRpcResult(raw);
          setCompletions(r?.items ?? []);
          setCompIdx(0);
          setCompReplace(isSlash ? r?.replace_from ?? 1 : pathReplace);
        }).catch(e => {
          if (ref.current !== input) {
            return;
          }
          setCompletions([{
            text: "",
            display: "completion unavailable",
            meta: e instanceof Error && e.message ? e.message : "indispon\xEDvel"
          }]);
          setCompIdx(0);
          setCompReplace(isSlash ? 1 : pathReplace);
        });
      }, 60);
      return () => clearTimeout(t);
    };
    t2 = [blocked, gw, input];
    $[1] = blocked;
    $[2] = gw;
    $[3] = input;
    $[4] = t1;
    $[5] = t2;
  } else {
    t1 = $[4];
    t2 = $[5];
  }
  useEffect(t1, t2);
  let t3;
  if ($[6] !== compIdx || $[7] !== compReplace || $[8] !== completions) {
    t3 = {
      completions,
      compIdx,
      setCompIdx,
      compReplace
    };
    $[6] = compIdx;
    $[7] = compReplace;
    $[8] = completions;
    $[9] = t3;
  } else {
    t3 = $[9];
  }
  return t3;
}
function _temp3(prev_1) {
  return prev_1 ? 0 : prev_1;
}
function _temp2(prev_0) {
  return prev_0 ? 0 : prev_0;
}
function _temp(prev) {
  return prev.length ? [] : prev;
}