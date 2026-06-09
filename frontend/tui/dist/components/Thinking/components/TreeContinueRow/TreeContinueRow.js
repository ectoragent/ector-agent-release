import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Box, Text } from '@ector/ink';
import { treeSublineLead } from '../../lib/treeLayout.js';
export function TreeContinueRow({
  branch,
  children,
  marginBottom = 0,
  rails = [],
  stemColor,
  stemDim = true,
  t
}) {
  const lead = treeSublineLead(rails, branch);
  return _jsxs(Box, {
    alignItems: "flex-start",
    flexDirection: "row",
    marginBottom: marginBottom,
    children: [_jsx(Text, {
      color: stemColor ?? t.color.dim,
      dim: stemDim,
      children: lead
    }), _jsx(Box, {
      flexDirection: "column",
      flexGrow: 1,
      minWidth: 0,
      children: children
    })]
  });
}