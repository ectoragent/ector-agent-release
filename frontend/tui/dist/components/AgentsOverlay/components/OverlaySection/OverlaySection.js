import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Box, Text } from '@ector/ink';
import { useStore } from '@nanostores/react';
import { $overlaySectionsOpen, toggleOverlaySection } from '../../../../app/delegationStore.js';
export function OverlaySection(t0) {
  const $ = _c(11);
  const {
    children,
    count,
    defaultOpen: t1,
    title,
    t
  } = t0;
  const defaultOpen = t1 === undefined ? false : t1;
  const openMap = useStore($overlaySectionsOpen);
  const open = title in openMap ? openMap[title] : defaultOpen;
  let t2;
  if ($[0] !== children || $[1] !== count || $[2] !== defaultOpen || $[3] !== open || $[4] !== t.color.cyan || $[5] !== t.color.label || $[6] !== title) {
    let t3;
    if ($[8] !== defaultOpen || $[9] !== title) {
      t3 = () => toggleOverlaySection(title, defaultOpen);
      $[8] = defaultOpen;
      $[9] = title;
      $[10] = t3;
    } else {
      t3 = $[10];
    }
    t2 = _jsxs(Box, {
      flexDirection: "column",
      marginTop: 1,
      children: [_jsx(Box, {
        onClick: t3,
        children: _jsxs(Text, {
          color: t.color.label,
          children: [_jsx(Text, {
            color: t.color.cyan,
            children: open ? "\u25BE " : "\u25B8 "
          }), title, typeof count === "number" ? ` (${count})` : ""]
        })
      }), open ? _jsx(Box, {
        flexDirection: "column",
        children
      }) : null]
    });
    $[0] = children;
    $[1] = count;
    $[2] = defaultOpen;
    $[3] = open;
    $[4] = t.color.cyan;
    $[5] = t.color.label;
    $[6] = title;
    $[7] = t2;
  } else {
    t2 = $[7];
  }
  return t2;
}