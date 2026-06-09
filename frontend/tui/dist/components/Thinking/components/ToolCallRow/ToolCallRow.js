import { jsx as _jsx } from "react/jsx-runtime";
import { Box } from '@ector/ink';
export function ToolCallRow({
  children,
  marginBottom,
  railColor
}) {
  return _jsx(Box, {
    borderLeft: true,
    borderLeftColor: railColor,
    flexDirection: "column",
    marginBottom: marginBottom,
    paddingLeft: 1,
    children: children
  });
}