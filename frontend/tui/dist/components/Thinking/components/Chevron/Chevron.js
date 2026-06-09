import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Box, Text } from '@ector/ink';
export function Chevron({
  boldHeading = false,
  count,
  onClick,
  open,
  suffix,
  t,
  title,
  tone = 'dim'
}) {
  const headingColor = tone === 'error' ? t.color.error : tone === 'warn' ? t.color.warn : boldHeading ? t.color.text : t.color.label;
  const secondary = t.color.statusBarMeta;
  return _jsx(Box, {
    alignItems: "flex-start",
    columnGap: 1,
    flexDirection: "row",
    flexWrap: "wrap",
    onClick: e => onClick(!!e?.shiftKey || !!e?.ctrlKey),
    children: [_jsx(Text, {
      color: t.color.cyan,
      children: open ? '▾' : '▸'
    }, "chev-mark"), _jsx(Text, {
      bold: boldHeading,
      color: headingColor,
      children: title
    }, "chev-title"), typeof count === 'number' ? _jsxs(Text, {
      color: secondary,
      dim: true,
      children: ["(", count, ")"]
    }, "chev-count") : null, suffix ? _jsx(Text, {
      color: secondary,
      dim: true,
      children: suffix
    }, "chev-suffix") : null].filter(Boolean)
  });
}