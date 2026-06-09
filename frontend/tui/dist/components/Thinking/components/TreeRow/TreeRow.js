import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Box, Text } from '@ector/ink';
import { treeLead } from '../../lib/treeLayout.js';
export function TreeRow({
  branch,
  children,
  marginBottom = 0,
  rails = [],
  stemColor,
  stemDim = true,
  t
}) {
  const lead = treeLead(rails, branch);
  return _jsxs(Box, {
    alignItems: "flex-start",
    columnGap: 0,
    flexDirection: "row",
    marginBottom: marginBottom,
    children: [_jsx(Text, {
      color: stemColor ?? t.color.dim,
      dim: stemDim,
      flexShrink: 0,
      children: lead
    }), _jsx(Box, {
      flexDirection: "column",
      flexGrow: 1,
      minWidth: 0,
      children: children
    })]
  });
}