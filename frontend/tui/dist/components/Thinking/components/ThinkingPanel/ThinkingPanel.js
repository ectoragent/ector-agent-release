import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Box, Text } from '@ector/ink';
import { memo, useMemo } from 'react';
import { THINKING_COT_MAX } from '../../../../config/limits.js';
import { boundedLiveRenderText, thinkingPreview } from '../../../../lib/text.js';
import { StreamCursor } from '../StreamCursor/index.js';
import { TreeRow } from '../TreeRow/index.js';
export const Thinking = memo(function Thinking(t0) {
  const $ = _c(14);
  const {
    active: t1,
    branch: t2,
    mode: t3,
    rails: t4,
    reasoning,
    streaming: t5,
    t
  } = t0;
  const active = t1 === undefined ? false : t1;
  const branch = t2 === undefined ? "last" : t2;
  const mode = t3 === undefined ? "truncated" : t3;
  let t6;
  let t7;
  if ($[0] !== active || $[1] !== branch || $[2] !== mode || $[3] !== reasoning || $[4] !== t || $[5] !== t4 || $[6] !== t5) {
    t7 = Symbol.for("react.early_return_sentinel");
    bb0: {
      const rails = t4 === undefined ? [] : t4;
      const streaming = t5 === undefined ? false : t5;
      let t8;
      if ($[9] !== mode || $[10] !== reasoning) {
        const raw = thinkingPreview(reasoning, mode, THINKING_COT_MAX);
        t8 = mode === "full" ? boundedLiveRenderText(raw) : raw;
        $[9] = mode;
        $[10] = reasoning;
        $[11] = t8;
      } else {
        t8 = $[11];
      }
      const preview = t8;
      let t9;
      if ($[12] !== preview) {
        t9 = preview.split("\n").map(_temp);
        $[12] = preview;
        $[13] = t9;
      } else {
        t9 = $[13];
      }
      const lines = t9;
      if (!preview && !active) {
        t7 = null;
        break bb0;
      }
      t6 = _jsx(TreeRow, {
        branch,
        rails,
        t,
        children: [_jsx(Box, {
          flexDirection: "column",
          flexGrow: 1,
          children: preview ? mode === "full" ? lines.map((line_0, index) => _jsxs(Text, {
            color: t.color.dim,
            wrap: "wrap-trim",
            children: [line_0 || " ", index === lines.length - 1 ? _jsx(StreamCursor, {
              color: t.color.dim,
              streaming,
              visible: active
            }) : null]
          }, index)) : _jsxs(Text, {
            color: t.color.dim,
            wrap: "truncate-end",
            children: [preview, _jsx(StreamCursor, {
              color: t.color.dim,
              streaming,
              visible: active
            })]
          }) : _jsx(Text, {
            color: t.color.dim,
            children: _jsx(StreamCursor, {
              color: t.color.dim,
              streaming,
              visible: active
            })
          })
        }, "think-inner")]
      });
    }
    $[0] = active;
    $[1] = branch;
    $[2] = mode;
    $[3] = reasoning;
    $[4] = t;
    $[5] = t4;
    $[6] = t5;
    $[7] = t6;
    $[8] = t7;
  } else {
    t6 = $[7];
    t7 = $[8];
  }
  if (t7 !== Symbol.for("react.early_return_sentinel")) {
    return t7;
  }
  return t6;
});
function _temp(line) {
  return line.replace(/\t/g, "  ");
}