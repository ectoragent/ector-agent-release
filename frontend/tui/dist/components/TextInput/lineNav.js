import { stringWidth } from '@ector/ink';
let _seg = null;
const seg = () => _seg ??= new Intl.Segmenter(undefined, {
  granularity: 'grapheme'
});
const STOP_CACHE_MAX = 32;
const stopCache = new Map();
function graphemeStops(s) {
  const hit = stopCache.get(s);
  if (hit) {
    return hit;
  }
  const stops = [0];
  for (const {
    index
  } of seg().segment(s)) {
    if (index > 0) {
      stops.push(index);
    }
  }
  if (stops.at(-1) !== s.length) {
    stops.push(s.length);
  }
  stopCache.set(s, stops);
  if (stopCache.size > STOP_CACHE_MAX) {
    const oldest = stopCache.keys().next().value;
    if (oldest !== undefined) {
      stopCache.delete(oldest);
    }
  }
  return stops;
}
function snapPos(s, p) {
  const pos = Math.max(0, Math.min(p, s.length));
  let last = 0;
  for (const stop of graphemeStops(s)) {
    if (stop > pos) {
      break;
    }
    last = stop;
  }
  return last;
}
/**
 * Move cursor one logical line up or down inside `s` while preserving the
 * column offset from the current line's start. Returns `null` when the cursor
 * is already on the first line (up) or last line (down).
 */
export function lineNav(s, p, dir) {
  const pos = snapPos(s, p);
  const curStart = s.lastIndexOf('\n', pos - 1) + 1;
  const col = pos - curStart;
  if (dir < 0) {
    if (curStart === 0) {
      return null;
    }
    const prevStart = s.lastIndexOf('\n', curStart - 2) + 1;
    return snapPos(s, Math.min(prevStart + col, curStart - 1));
  }
  const nextBreak = s.indexOf('\n', pos);
  if (nextBreak < 0) {
    return null;
  }
  const nextEnd = s.indexOf('\n', nextBreak + 1);
  const lineEnd = nextEnd < 0 ? s.length : nextEnd;
  return snapPos(s, Math.min(nextBreak + 1 + col, lineEnd));
}
export function offsetFromPosition(value, row, col, cols) {
  if (!value.length) {
    return 0;
  }
  const targetRow = Math.max(0, Math.floor(row));
  const targetCol = Math.max(0, Math.floor(col));
  const w = Math.max(1, cols);
  let line = 0;
  let column = 0;
  let lastOffset = 0;
  for (const {
    segment,
    index
  } of seg().segment(value)) {
    lastOffset = index;
    if (segment === '\n') {
      if (line === targetRow) {
        return index;
      }
      line++;
      column = 0;
      continue;
    }
    const sw = Math.max(1, stringWidth(segment));
    if (column + sw > w) {
      if (line === targetRow) {
        return index;
      }
      line++;
      column = 0;
    }
    if (line === targetRow && targetCol <= column + Math.max(0, sw - 1)) {
      return index;
    }
    column += sw;
  }
  if (targetRow >= line) {
    return value.length;
  }
  return lastOffset;
}
/** Grapheme-aware navigation helpers used by TextInput. */
export function prevGraphemePos(s, p) {
  const pos = snapPos(s, p);
  let prev = 0;
  for (const stop of graphemeStops(s)) {
    if (stop >= pos) {
      return prev;
    }
    prev = stop;
  }
  return prev;
}
export function nextGraphemePos(s, p) {
  const pos = snapPos(s, p);
  for (const stop of graphemeStops(s)) {
    if (stop > pos) {
      return stop;
    }
  }
  return s.length;
}
export function wordLeft(s, p) {
  let i = snapPos(s, p) - 1;
  while (i > 0 && /\s/.test(s[i])) {
    i--;
  }
  while (i > 0 && !/\s/.test(s[i - 1])) {
    i--;
  }
  return Math.max(0, i);
}
export function wordRight(s, p) {
  let i = snapPos(s, p);
  while (i < s.length && !/\s/.test(s[i])) {
    i++;
  }
  while (i < s.length && /\s/.test(s[i])) {
    i++;
  }
  return i;
}
export function snapGraphemePos(s, p) {
  return snapPos(s, p);
}