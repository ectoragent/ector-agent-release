import { autolinkUrl } from './blockRegex.js';
const UNSAFE_SCHEME_RE = /^(?:javascript|data|vbscript):/i;
/** Allow only safe schemes for terminal link handlers (http(s), mailto, file). */
export const safeLinkUrl = raw => {
  const u = raw.trim();
  if (!u || UNSAFE_SCHEME_RE.test(u)) {
    return null;
  }
  const lower = u.toLowerCase();
  if (lower.startsWith('file://')) {
    return /^file:\/\/(?:\/|[a-z]:)/i.test(u) ? u : null;
  }
  if ((/^\/(?!\/)/.test(u) || /^[a-z]:[\\/]/i.test(u)) && !/^\\\\/.test(u)) {
    return `file://${u}`;
  }
  if (/^https?:\/\//i.test(u)) {
    return u;
  }
  if (lower.startsWith('mailto:')) {
    return autolinkUrl(u);
  }
  if (/^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/.test(u)) {
    return autolinkUrl(u);
  }
  return null;
};