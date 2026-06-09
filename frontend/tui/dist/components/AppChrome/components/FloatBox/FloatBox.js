import { jsx as _jsx } from "react/jsx-runtime";
import { Box } from '@ector/ink';
export function FloatBox({
  backgroundColor,
  children,
  color
}) {
  return _jsx(Box, {
    alignSelf: "flex-start",
    backgroundColor: backgroundColor,
    borderColor: color,
    borderStyle: "round",
    flexDirection: "column",
    marginTop: 1,
    opaque: true,
    paddingX: 1,
    paddingY: 1,
    children: children
  });
}