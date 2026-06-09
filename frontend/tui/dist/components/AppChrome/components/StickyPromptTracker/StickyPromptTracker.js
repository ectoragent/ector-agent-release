import { c as _c } from "react/compiler-runtime";
import { useEffect } from 'react';
import { stickyPromptFromViewport } from '../../../../domain/viewport.js';
import { useViewportSnapshot } from '../../../../lib/viewportStore.js';
export function StickyPromptTracker(t0) {
  const $ = _c(10);
  const {
    messages,
    offsets,
    scrollRef,
    onChange
  } = t0;
  const {
    atBottom,
    bottom,
    top
  } = useViewportSnapshot(scrollRef);
  let t1;
  if ($[0] !== atBottom || $[1] !== bottom || $[2] !== messages || $[3] !== offsets || $[4] !== top) {
    t1 = stickyPromptFromViewport(messages, offsets, top, bottom, atBottom);
    $[0] = atBottom;
    $[1] = bottom;
    $[2] = messages;
    $[3] = offsets;
    $[4] = top;
    $[5] = t1;
  } else {
    t1 = $[5];
  }
  const text = t1;
  let t2;
  let t3;
  if ($[6] !== onChange || $[7] !== text) {
    t2 = () => onChange(text);
    t3 = [onChange, text];
    $[6] = onChange;
    $[7] = text;
    $[8] = t2;
    $[9] = t3;
  } else {
    t2 = $[8];
    t3 = $[9];
  }
  useEffect(t2, t3);
  return null;
}