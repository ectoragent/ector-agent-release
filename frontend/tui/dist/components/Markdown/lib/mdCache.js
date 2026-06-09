// Cross-instance parsed-children cache: useMemo's per-instance cache dies
// on remount, so virtualization re-parses every row that scrolls back into
// view. Theme-keyed WeakMap drops stale palettes; inner Map is LRU-bounded.
const MD_CACHE_LIMIT = 512;
const mdCache = new WeakMap();
export const cacheBucket = t => {
  const b = mdCache.get(t);
  if (b) {
    return b;
  }
  const fresh = new Map();
  mdCache.set(t, fresh);
  return fresh;
};
export const cacheGet = (b, key) => {
  const v = b.get(key);
  if (v) {
    b.delete(key);
    b.set(key, v);
  }
  return v;
};
export const cacheSet = (b, key, v) => {
  b.set(key, v);
  if (b.size > MD_CACHE_LIMIT) {
    b.delete(b.keys().next().value);
  }
};