import { c as _c } from "react/compiler-runtime";
import { atom } from 'nanostores';
import { useSyncExternalStore } from 'react';
import { isTodoDone } from '../lib/liveProgress.js';
const buildTurnState = () => ({
  activity: [],
  outcome: '',
  reasoning: '',
  reasoningActive: false,
  reasoningStreaming: false,
  reasoningTokens: 0,
  streamPendingTools: [],
  streamSegments: [],
  streaming: '',
  subagents: [],
  todoCollapsed: false,
  todos: [],
  toolTokens: 0,
  tools: [],
  turnTrail: []
});
export const $turnState = atom(buildTurnState());
export const getTurnState = () => $turnState.get();
const subscribeTurn = cb => $turnState.listen(() => cb());
export const useTurnSelector = selector => {
  const $ = _c(3);
  let t0;
  let t1;
  if ($[0] !== selector) {
    t0 = () => selector($turnState.get());
    t1 = () => selector($turnState.get());
    $[0] = selector;
    $[1] = t0;
    $[2] = t1;
  } else {
    t0 = $[1];
    t1 = $[2];
  }
  return useSyncExternalStore(subscribeTurn, t0, t1);
};
export const patchTurnState = next => $turnState.set(typeof next === 'function' ? next($turnState.get()) : {
  ...$turnState.get(),
  ...next
});
export const toggleTodoCollapsed = () => patchTurnState(state => ({
  ...state,
  todoCollapsed: !state.todoCollapsed
}));
export const archiveDoneTodos = () => archiveTodosAtTurnEnd();
export const archiveTodosAtTurnEnd = () => {
  const state = $turnState.get();
  if (!state.todos.length) {
    return [];
  }
  const done = isTodoDone(state.todos);
  const msg = {
    kind: 'trail',
    role: 'system',
    text: '',
    todos: state.todos,
    ...(done ? {
      todoCollapsedByDefault: true
    } : {
      todoIncomplete: true
    })
  };
  patchTurnState({
    todoCollapsed: false,
    todos: []
  });
  return [msg];
};
export const resetTurnState = () => $turnState.set(buildTurnState());