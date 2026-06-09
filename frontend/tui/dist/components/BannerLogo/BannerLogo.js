import { jsx as _jsx, Fragment as _Fragment } from "react/jsx-runtime";
import { Ansi, Box } from '@ector/ink';
import { useEffect, useMemo, useState } from 'react';
import { ECTOR_ASCII_LINES, logoClickCol, paintBannerGradient, rippleActive } from '../../content/pixelLogo.js';
export function BannerLogo({
  contentCols,
  edge,
  peak,
  rippleBlue
}) {
  const [ripple, setRipple] = useState(null);
  const [frame, setFrame] = useState(0);
  useEffect(() => {
    if (!ripple || !rippleActive(ripple)) {
      return;
    }
    const id = setInterval(() => {
      if (!rippleActive(ripple)) {
        setRipple(null);
        return;
      }
      setFrame(n => n + 1);
    }, 40);
    return () => clearInterval(id);
  }, [ripple]);
  const logoLines = useMemo(() => paintBannerGradient(ECTOR_ASCII_LINES, edge, peak, ripple, performance.now(), rippleBlue),
  // frame força repaint durante a onda
  // eslint-disable-next-line react-hooks/exhaustive-deps -- frame tick drives ripple animation
  [edge, peak, ripple, rippleBlue, frame]);
  return _jsx(_Fragment, {
    children: logoLines.map((line, row) => _jsx(Box, {
      justifyContent: "center",
      onClick: event => {
        if (event.cellIsBlank) {
          return;
        }
        setRipple({
          at: performance.now(),
          col: logoClickCol(ECTOR_ASCII_LINES[row] ?? '', event.localCol, contentCols),
          row
        });
        setFrame(n => n + 1);
      },
      width: contentCols,
      children: _jsx(Ansi, {
        children: line
      })
    }, row))
  });
}