import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { Box, Text } from '@ector/ink';
import { useState } from 'react';
import { useViewportSnapshot } from '../../../../lib/viewportStore.js';
export function TranscriptScrollbar({
  scrollRef,
  t
}) {
  const [hover, setHover] = useState(false);
  const [grab, setGrab] = useState(null);
  const {
    scrollHeight: total,
    top: pos,
    viewportHeight: vp
  } = useViewportSnapshot(scrollRef);
  if (!vp) {
    return _jsx(Box, {
      width: 1
    });
  }
  const s = scrollRef.current;
  const scrollable = total > vp;
  const thumb = scrollable ? Math.max(1, Math.round(vp * vp / total)) : vp;
  const travel = Math.max(1, vp - thumb);
  const thumbTop = scrollable ? Math.round(pos / Math.max(1, total - vp) * travel) : 0;
  const thumbColor = grab !== null ? t.color.title : hover ? t.color.cyan : t.color.border;
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
    children: !scrollable ? _jsxs(Text, {
      color: trackColor,
      dim: true,
      children: [' \n'.repeat(Math.max(0, vp - 1)), ' ']
    }) : _jsxs(_Fragment, {
      children: [thumbTop > 0 ? _jsx(Text, {
        color: trackColor,
        dim: !hover,
        children: `${'│\n'.repeat(Math.max(0, thumbTop - 1))}${thumbTop > 0 ? '│' : ''}`
      }) : null, thumb > 0 ? _jsx(Text, {
        color: thumbColor,
        children: `${'┃\n'.repeat(Math.max(0, thumb - 1))}${thumb > 0 ? '┃' : ''}`
      }) : null, vp - thumbTop - thumb > 0 ? _jsx(Text, {
        color: trackColor,
        dim: !hover,
        children: `${'│\n'.repeat(Math.max(0, vp - thumbTop - thumb - 1))}${vp - thumbTop - thumb > 0 ? '│' : ''}`
      }) : null]
    })
  });
}