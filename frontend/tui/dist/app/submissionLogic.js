import { DOUBLE_ENTER_MS } from '../config/input.js';
import { PASTE_SNIPPET_RE } from '../protocol/paste.js';
export { DOUBLE_ENTER_MS };
export const SESSION_BUSY_RE = /session busy|waiting for model response/i;
export const isSessionBusyError = e => e instanceof Error && SESSION_BUSY_RE.test(e.message);
export const expandSnippets = snips => {
  const byLabel = new Map();
  for (const {
    label,
    text
  } of snips) {
    const hit = byLabel.get(label);
    hit ? hit.push(text) : byLabel.set(label, [text]);
  }
  return value => value.replace(PASTE_SNIPPET_RE, tok => byLabel.get(tok)?.shift() ?? tok);
};
export const resolveDoubleEnter = ctx => {
  if (!ctx.doubleTap) {
    return 'noop';
  }
  if (ctx.busy && ctx.hasSid) {
    return 'interrupt';
  }
  if (ctx.hasSid && ctx.hasQueue) {
    return 'dequeue';
  }
  return 'noop';
};
export const isDoubleEnterTap = (now, lastEmptyAt) => now - lastEmptyAt < DOUBLE_ENTER_MS;
export const shouldQueueSubmission = (busy, hasSid) => Boolean(hasSid && busy);