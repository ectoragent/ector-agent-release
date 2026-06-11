export const countPendingTodos = todos => todos.filter(todo => todo.status === 'in_progress' || todo.status === 'pending').length;
export const isTodoDone = todos => todos.length > 0 && todos.every(todo => todo.status === 'completed' || todo.status === 'cancelled');
export const isToolShelfMessage = msg => Boolean(msg?.kind === 'trail' && !msg.text && !msg.thinking?.trim() && msg.tools?.length);
export const canHoldToolShelf = msg => Boolean(msg?.kind === 'trail' && !msg.text && (msg.thinking?.trim() || msg.tools?.length));
export const mergeToolShelfInto = (target, source) => ({
  ...target,
  tools: [...(target.tools ?? []), ...(source.tools ?? [])]
});
const isBarrierMessage = msg => {
  if (!msg) {
    return true;
  }
  // Assistant text, user input, intro/panel rows all terminate the shelf.
  if (msg.kind === 'intro' || msg.kind === 'panel' || msg.kind === 'diff') {
    return true;
  }
  if (msg.role && msg.role !== 'system') {
    return true;
  }
  if (msg.text) {
    return true;
  }
  return false;
};
const isToolCarryingTrail = msg => Boolean(msg?.kind === 'trail' && !msg.text && msg.tools?.length);
export const appendToolShelfMessage = (prev, msg) => {
  if (!isToolShelfMessage(msg)) {
    return [...prev, msg];
  }
  let fallbackHolder = null;
  for (let index = prev.length - 1; index >= 0; index--) {
    const candidate = prev[index];
    if (isToolCarryingTrail(candidate)) {
      // Merge tools into a thinking shelf only — keep tool-only trails separate
      // so assistant narration can sit between consecutive tool cards.
      if (candidate.thinking?.trim()) {
        const next = [...prev];
        next[index] = mergeToolShelfInto(candidate, msg);
        return next;
      }
      break;
    }
    if (fallbackHolder === null && canHoldToolShelf(candidate)) {
      fallbackHolder = index;
    }
    if (isBarrierMessage(candidate)) {
      break;
    }
  }
  if (fallbackHolder !== null) {
    const next = [...prev];
    next[fallbackHolder] = mergeToolShelfInto(prev[fallbackHolder], msg);
    return next;
  }
  return [...prev, msg];
};