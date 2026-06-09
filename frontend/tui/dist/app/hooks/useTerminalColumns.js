import { c as _c } from "react/compiler-runtime";
import { useStdout } from '@ector/ink';
import { useEffect, useState } from 'react';
const BRACKET_PASTE_ON = '\x1b[?2004h';
const BRACKET_PASTE_OFF = '\x1b[?2004l';
/** Track stdout width and enable bracketed-paste on TTY. */
export function useTerminalColumns(t0) {
  const $ = _c(7);
  const defaultCols = t0 === undefined ? 80 : t0;
  const {
    stdout
  } = useStdout();
  const [cols, setCols] = useState(stdout?.columns ?? defaultCols);
  let t1;
  let t2;
  if ($[0] !== defaultCols || $[1] !== stdout) {
    t1 = () => {
      if (!stdout) {
        return;
      }
      const sync = () => setCols(stdout.columns ?? defaultCols);
      stdout.on("resize", sync);
      if (stdout.isTTY) {
        stdout.write(BRACKET_PASTE_ON);
      }
      return () => {
        stdout.off("resize", sync);
        if (stdout.isTTY) {
          stdout.write(BRACKET_PASTE_OFF);
        }
      };
    };
    t2 = [defaultCols, stdout];
    $[0] = defaultCols;
    $[1] = stdout;
    $[2] = t1;
    $[3] = t2;
  } else {
    t1 = $[2];
    t2 = $[3];
  }
  useEffect(t1, t2);
  let t3;
  if ($[4] !== cols || $[5] !== stdout) {
    t3 = {
      cols,
      stdout
    };
    $[4] = cols;
    $[5] = stdout;
    $[6] = t3;
  } else {
    t3 = $[6];
  }
  return t3;
}