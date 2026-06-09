import { jsx as _jsx, Fragment as _Fragment, jsxs as _jsxs } from "react/jsx-runtime";
import { Box, Text } from '@ector/ink';
import { useState } from 'react';
/** Polled on parent `tick` so accordions can resize the thumb without a scroll event. */
export function OverlayScrollbar({
  scrollRef,
  t,
  tick
}) {
  void tick; // ensures re-render when the parent clock advances
  const [hover, setHover] = useState(false);
  const [grab, setGrab] = useState(null);
  const s = scrollRef.current;
  const vp = Math.max(0, s?.getViewportHeight() ?? 0);
  if (!vp) {
    return _jsx(Box, {
      width: 1
    });
  }
  const total = Math.max(vp, s?.getScrollHeight() ?? vp);
  const scrollable = total > vp;
  const thumb = scrollable ? Math.max(1, Math.round(vp * vp / total)) : vp;
  const travel = Math.max(1, vp - thumb);
  const pos = Math.max(0, (s?.getScrollTop() ?? 0) + (s?.getPendingDelta() ?? 0));
  const thumbTop = scrollable ? Math.round(pos / Math.max(1, total - vp) * travel) : 0;
  const below = Math.max(0, vp - thumbTop - thumb);
  const vBar = n => n > 0 ? `${'│\n'.repeat(n - 1)}│` : '';
  const thumbBody = `${'┃\n'.repeat(Math.max(0, thumb - 1))}┃`;
  const thumbColor = grab !== null ? t.color.title : t.color.cyan;
  const trackColor = hover ? t.color.border : t.color.dim;
  const jump = (row, offset) => {
    if (!s || !scrollable) {
      return;
    }
    s.scrollTo(Math.round(Math.max(0, Math.min(travel, row - offset)) / travel * Math.max(0, total - vp)));
  };
  return _jsx(Box, {
    flexDirection: "column",
    onMouseDown: e => {
      const row_0 = Math.max(0, Math.min(vp - 1, e.localRow ?? 0));
      const off = row_0 >= thumbTop && row_0 < thumbTop + thumb ? row_0 - thumbTop : Math.floor(thumb / 2);
      setGrab(off);
      jump(row_0, off);
    },
    onMouseDrag: e_0 => jump(Math.max(0, Math.min(vp - 1, e_0.localRow ?? 0)), grab ?? Math.floor(thumb / 2)),
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => setHover(false),
    onMouseUp: () => setGrab(null),
    width: 1,
    children: !scrollable ? _jsx(Text, {
      color: trackColor,
      dim: true,
      children: vBar(vp)
    }) : _jsxs(_Fragment, {
      children: [thumbTop > 0 ? _jsx(Text, {
        color: trackColor,
        dim: !hover,
        children: vBar(thumbTop)
      }) : null, _jsx(Text, {
        color: thumbColor,
        children: thumbBody
      }), below > 0 ? _jsx(Text, {
        color: trackColor,
        dim: !hover,
        children: vBar(below)
      }) : null]
    })
  });
}