import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx } from "react/jsx-runtime";
import { Text } from '@ector/ink';
import { useStore } from '@nanostores/react';
import { $uiState } from '../../app/uiStore.js';
export function Fg(t0) {
  const $ = _c(9);
  const {
    bold,
    c,
    children,
    dim,
    italic,
    literal,
    strikethrough,
    underline,
    wrap
  } = t0;
  const {
    theme
  } = useStore($uiState);
  const t1 = literal ?? (c && theme.color[c]);
  let t2;
  if ($[0] !== bold || $[1] !== children || $[2] !== dim || $[3] !== italic || $[4] !== strikethrough || $[5] !== t1 || $[6] !== underline || $[7] !== wrap) {
    t2 = _jsx(Text, {
      color: t1,
      dimColor: dim,
      bold,
      italic,
      strikethrough,
      underline,
      wrap,
      children
    });
    $[0] = bold;
    $[1] = children;
    $[2] = dim;
    $[3] = italic;
    $[4] = strikethrough;
    $[5] = t1;
    $[6] = underline;
    $[7] = wrap;
    $[8] = t2;
  } else {
    t2 = $[8];
  }
  return t2;
}