import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx } from "react/jsx-runtime";
import { Text, useInput } from '@ector/ink';
export function useOverlayKeys(t0) {
  const $ = _c(4);
  const {
    disabled: t1,
    onBack,
    onClose
  } = t0;
  const disabled = t1 === undefined ? false : t1;
  let t2;
  if ($[0] !== disabled || $[1] !== onBack || $[2] !== onClose) {
    t2 = (ch, key) => {
      if (disabled) {
        return;
      }
      if (ch === "q") {
        return onClose();
      }
      if (key.escape) {
        return onBack ? onBack() : onClose();
      }
    };
    $[0] = disabled;
    $[1] = onBack;
    $[2] = onClose;
    $[3] = t2;
  } else {
    t2 = $[3];
  }
  useInput(t2);
}
export function OverlayHint({
  children,
  t
}) {
  return _jsx(Text, {
    color: t.color.dim,
    wrap: "truncate-end",
    children: children
  });
}
export const windowOffset = (count, selected, visible) => Math.max(0, Math.min(selected - Math.floor(visible / 2), count - visible));
export function windowItems(items, selected, visible) {
  const offset = windowOffset(items.length, selected, visible);
  return {
    items: items.slice(offset, offset + visible),
    offset
  };
}