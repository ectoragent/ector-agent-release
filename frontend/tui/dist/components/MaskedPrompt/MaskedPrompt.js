import { c as _c } from "react/compiler-runtime";
import { jsxs as _jsxs, jsx as _jsx } from "react/jsx-runtime";
import { Box, Text } from '@ector/ink';
import { useState } from 'react';
import { TextInput } from '../TextInput/index.js';
export function MaskedPrompt(t0) {
  const $ = _c(10);
  const {
    cols: t1,
    icon,
    label,
    onSubmit,
    sub,
    t
  } = t0;
  const cols = t1 === undefined ? 80 : t1;
  const [value, setValue] = useState("");
  let t2;
  if ($[0] !== cols || $[1] !== icon || $[2] !== label || $[3] !== onSubmit || $[4] !== sub || $[5] !== t.color.dim || $[6] !== t.color.label || $[7] !== t.color.warn || $[8] !== value) {
    t2 = _jsxs(Box, {
      flexDirection: "column",
      children: [_jsxs(Text, {
        bold: true,
        color: t.color.warn,
        children: [icon, " ", label]
      }), sub && _jsxs(Text, {
        color: t.color.dim,
        children: [" ", sub]
      }), _jsxs(Box, {
        children: [_jsx(Text, {
          color: t.color.label,
          children: "> "
        }), _jsx(TextInput, {
          columns: Math.max(20, cols - 6),
          mask: "*",
          onChange: setValue,
          onSubmit,
          value
        })]
      })]
    });
    $[0] = cols;
    $[1] = icon;
    $[2] = label;
    $[3] = onSubmit;
    $[4] = sub;
    $[5] = t.color.dim;
    $[6] = t.color.label;
    $[7] = t.color.warn;
    $[8] = value;
    $[9] = t2;
  } else {
    t2 = $[9];
  }
  return t2;
}