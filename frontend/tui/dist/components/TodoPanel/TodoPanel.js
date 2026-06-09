import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Box, Text } from '@ector/ink';
import { memo, useState } from 'react';
import { countPendingTodos } from '../../lib/liveProgress.js';
import { todoGlyph, todoTone } from '../../lib/todo.js';
const rowColor = (t, status) => {
  const tone = todoTone(status);
  return tone === 'active' ? t.color.text : tone === 'body' ? t.color.statusFg : t.color.dim;
};
export const TodoPanel = memo(function TodoPanel(t0) {
  const $ = _c(9);
  const {
    collapsed,
    defaultCollapsed: t1,
    incomplete: t2,
    onToggle,
    t,
    todos
  } = t0;
  const defaultCollapsed = t1 === undefined ? false : t1;
  const incomplete = t2 === undefined ? false : t2;
  const [localCollapsed, setLocalCollapsed] = useState(defaultCollapsed);
  const isControlled = typeof collapsed === "boolean";
  const effectiveCollapsed = isControlled ? collapsed : localCollapsed;
  let t3;
  if ($[0] !== isControlled || $[1] !== onToggle) {
    t3 = () => {
      if (onToggle) {
        onToggle();
        return;
      }
      if (!isControlled) {
        setLocalCollapsed(_temp);
      }
    };
    $[0] = isControlled;
    $[1] = onToggle;
    $[2] = t3;
  } else {
    t3 = $[2];
  }
  const handleToggle = t3;
  if (!todos.length) {
    return null;
  }
  let t4;
  if ($[3] !== effectiveCollapsed || $[4] !== handleToggle || $[5] !== incomplete || $[6] !== t || $[7] !== todos) {
    const done = todos.filter(_temp2).length;
    const pending = countPendingTodos(todos);
    t4 = _jsxs(Box, {
      flexDirection: "column",
      children: [_jsx(Box, {
        onClick: handleToggle,
        children: _jsxs(Text, {
          color: t.color.dim,
          children: [_jsx(Text, {
            color: t.color.cyan,
            children: effectiveCollapsed ? "\u25B8 " : "\u25BE "
          }), _jsx(Text, {
            bold: true,
            color: t.color.text,
            children: "Tarefas"
          }), " ", _jsxs(Text, {
            color: t.color.statusFg,
            dim: true,
            children: ["(", done, "/", todos.length, ")"]
          }), incomplete && pending > 0 && _jsxs(Text, {
            color: t.color.dim,
            dim: true,
            children: [" ", "\xB7 pendentes \xB7 ", pending, " ", pending === 1 ? "em aberto" : "em aberto/em progresso"]
          })]
        })
      }), !effectiveCollapsed && _jsx(Box, {
        flexDirection: "column",
        marginLeft: 2,
        children: todos.map(todo_0 => {
          const tone = todoTone(todo_0.status);
          const color = rowColor(t, todo_0.status);
          return _jsxs(Text, {
            color,
            dim: tone === "dim",
            children: [_jsxs(Text, {
              color,
              children: [todoGlyph(todo_0.status), " "]
            }), todo_0.content]
          }, todo_0.id);
        })
      })]
    });
    $[3] = effectiveCollapsed;
    $[4] = handleToggle;
    $[5] = incomplete;
    $[6] = t;
    $[7] = todos;
    $[8] = t4;
  } else {
    t4 = $[8];
  }
  return t4;
});
function _temp(v) {
  return !v;
}
function _temp2(todo) {
  return todo.status === "completed";
}