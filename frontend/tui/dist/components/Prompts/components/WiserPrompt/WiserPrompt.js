import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/**
 * Ector CLI - Wiser Prompt
 * WiserPrompt is a component that displays a wiser prompt.
 * It is used to ask the user a question and get a response.
 * It is used in the Wiser tool.
 */
import { Box, Text, useInput } from '@ector/ink';
import { useEffect, useState } from 'react';
import { isMac } from '../../../../lib/platform.js';
import { TextInput } from '../../../TextInput/index.js';
export function WiserPrompt(t0) {
  const $ = _c(11);
  const {
    cols: t1,
    onAnswer,
    onCancel,
    req,
    t
  } = t0;
  const cols = t1 === undefined ? 80 : t1;
  const [sel, setSel] = useState(0);
  const [custom, setCustom] = useState("");
  const [typing, setTyping] = useState(false);
  const [armed, setArmed] = useState(false);
  let t2;
  if ($[0] !== req.choices) {
    t2 = req.choices ?? [];
    $[0] = req.choices;
    $[1] = t2;
  } else {
    t2 = $[1];
  }
  const choices = t2;
  const accent = t.color.cyan;
  let t3;
  let t4;
  if ($[2] === Symbol.for("react.memo_cache_sentinel")) {
    t3 = () => {
      const timer = setTimeout(() => setArmed(true), 75);
      return () => clearTimeout(timer);
    };
    t4 = [];
    $[2] = t3;
    $[3] = t4;
  } else {
    t3 = $[2];
    t4 = $[3];
  }
  useEffect(t3, t4);
  const header = _jsx(Box, {
    marginBottom: 1,
    children: _jsx(Text, {
      color: t.color.text,
      children: req.question
    })
  });
  const hints = _jsx(Text, {
    color: t.color.dim,
    children: typing || !choices.length ? `Enter enviar · Esc ${choices.length ? "voltar" : "cancelar"} · ${isMac ? "Cmd+C copiar \xB7 Cmd+V colar \xB7 Ctrl+C cancelar" : "Ctrl+C cancelar"}` : `↑/↓ escolher · Enter confirmar · 1-${choices.length} rápido · Esc/Ctrl+C cancelar`
  });
  let t5;
  if ($[4] !== armed || $[5] !== choices || $[6] !== onAnswer || $[7] !== onCancel || $[8] !== sel || $[9] !== typing) {
    t5 = (ch, key) => {
      if (key.escape) {
        typing && choices.length ? setTyping(false) : onCancel();
        return;
      }
      if (typing || !choices.length) {
        return;
      }
      if (key.upArrow && sel > 0) {
        setSel(_temp);
      }
      if (key.downArrow && sel < choices.length) {
        setSel(_temp2);
      }
      if (key.return) {
        if (!armed) {
          return;
        }
        sel === choices.length ? setTyping(true) : choices[sel] && onAnswer(choices[sel]);
      }
      const n = parseInt(ch);
      if (n >= 1 && n <= choices.length) {
        onAnswer(choices[n - 1]);
      }
    };
    $[4] = armed;
    $[5] = choices;
    $[6] = onAnswer;
    $[7] = onCancel;
    $[8] = sel;
    $[9] = typing;
    $[10] = t5;
  } else {
    t5 = $[10];
  }
  useInput(t5);
  if (typing || !choices.length) {
    return _jsxs(Box, {
      flexDirection: "column",
      children: [header, _jsxs(Box, {
        flexDirection: "row",
        marginBottom: 1,
        children: [_jsx(Text, {
          color: accent,
          children: "\u203A "
        }), _jsx(TextInput, {
          columns: Math.max(20, cols - 4),
          onChange: setCustom,
          onSubmit: onAnswer,
          value: custom
        })]
      }), hints]
    });
  }
  const items = [...choices, "Outro (digite sua resposta)"];
  return _jsxs(Box, {
    flexDirection: "column",
    children: [header, _jsx(Box, {
      flexDirection: "column",
      marginBottom: 1,
      children: items.map((c, i) => {
        const selected = sel === i;
        const isCustom = i === items.length - 1;
        const line = `${selected ? "\u25B8" : " "} ${i + 1}. ${c}`;
        return _jsx(Box, {
          flexDirection: "row",
          children: _jsx(Text, {
            bold: selected,
            color: selected ? t.color.cyan : isCustom ? t.color.dim : t.color.label,
            wrap: "truncate-end",
            children: line
          })
        }, i);
      })
    }), hints]
  });
}
function _temp2(s_0) {
  return s_0 + 1;
}
function _temp(s) {
  return s - 1;
}