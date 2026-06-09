import { c as _c } from "react/compiler-runtime";
import { useStdin } from '@ector/ink';
import { useEffect, useRef } from 'react';
import { FWD_DEL_RE } from '../lib/keyPatterns.js';
export function useFwdDelete(active) {
  const $ = _c(4);
  const ref = useRef(false);
  const {
    inputEmitter: ee
  } = useStdin();
  let t0;
  let t1;
  if ($[0] !== active || $[1] !== ee) {
    t0 = () => {
      if (!active) {
        return;
      }
      const h = d => {
        ref.current = FWD_DEL_RE.test(d);
      };
      ee.prependListener("input", h);
      return () => {
        ee.removeListener("input", h);
      };
    };
    t1 = [active, ee];
    $[0] = active;
    $[1] = ee;
    $[2] = t0;
    $[3] = t1;
  } else {
    t0 = $[2];
    t1 = $[3];
  }
  useEffect(t0, t1);
  return ref;
}