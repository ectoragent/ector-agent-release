// Extracts the raw patch from a diff-only segment produced by
// pushInlineDiffSegment. Used at message.complete to dedupe against final
// assistant text that narrates the same patch. Returns null for anything
// else so real assistant narration never gets touched.
export const diffSegmentBody = msg => {
  if (msg.kind !== 'diff') {
    return null;
  }
  const m = msg.text.match(/^```diff\n([\s\S]*?)\n```$/);
  return m ? m[1] : null;
};
export const hasDetails = msg => Boolean(msg.thinking || msg.tools?.length || msg.toolTokens);
const isTodoStatus = status => status === 'pending' || status === 'in_progress' || status === 'completed' || status === 'cancelled';
export const parseTodos = value => {
  if (!Array.isArray(value)) {
    return null;
  }
  return value.map(item => {
    if (!item || typeof item !== 'object') {
      return null;
    }
    const row = item;
    const status = row.status;
    if (!isTodoStatus(status)) {
      return null;
    }
    return {
      content: String(row.content ?? '').trim(),
      id: String(row.id ?? '').trim(),
      status
    };
  }).filter(item => Boolean(item?.id && item.content));
};
export const textSegments = segments => segments.filter(msg => msg.role === 'assistant' && msg.kind !== 'diff').map(msg => msg.text);
export const finalTail = (finalText, segments) => {
  let tail = finalText;
  for (const text of textSegments(segments)) {
    const trimmed = text.trim();
    if (trimmed && tail.startsWith(trimmed)) {
      tail = tail.slice(trimmed.length).trimStart();
    }
  }
  return tail;
};
const clear = t => {
  if (t) {
    clearTimeout(t);
  }
  return null;
};