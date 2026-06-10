import { c as _c } from "react/compiler-runtime";
import { getRenderer } from '@ector/ink';
import { useEffect } from 'react';
/** Keep OpenTUI `useMouse` in sync with `/mouse` and config (renderer is created once). */
export function useMouseTrackingSync(enabled) {
  const $ = _c(3);
  let t0;
  let t1;
  if ($[0] !== enabled) {
    t0 = () => {
      const renderer = getRenderer();
      if (!renderer || renderer.isDestroyed) {
        return;
      }
      renderer.useMouse = enabled;
    };
    t1 = [enabled];
    $[0] = enabled;
    $[1] = t0;
    $[2] = t1;
  } else {
    t0 = $[1];
    t1 = $[2];
  }
  useEffect(t0, t1);
}