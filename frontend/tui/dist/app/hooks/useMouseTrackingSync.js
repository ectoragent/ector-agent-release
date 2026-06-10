import { c as _c } from "react/compiler-runtime";
import { getRenderer } from '@ector/ink';
import { useStore } from '@nanostores/react';
import { useEffect } from 'react';
import { $overlayState } from '../overlayStore.js';
/** Keep OpenTUI `useMouse` in sync with `/mouse` and config (renderer is created once). */
export function useMouseTrackingSync(enabled) {
  const $ = _c(3);
  const overlay = useStore($overlayState);
  const suspendForPrompt = Boolean(overlay.sudo || overlay.secret);
  const effective = enabled && !suspendForPrompt;
  let t0;
  let t1;
  if ($[0] !== effective) {
    t0 = () => {
      const renderer = getRenderer();
      if (!renderer || renderer.isDestroyed) {
        return;
      }
      if (renderer.useMouse !== effective) {
        renderer.useMouse = effective;
      }
    };
    t1 = [effective];
    $[0] = effective;
    $[1] = t0;
    $[2] = t1;
  } else {
    t0 = $[1];
    t1 = $[2];
  }
  useEffect(t0, t1);
}