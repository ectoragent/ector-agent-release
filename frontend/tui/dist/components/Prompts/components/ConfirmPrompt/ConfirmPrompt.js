import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Box, Text, useInput } from '@ector/ink';
import { useState } from 'react';
export function ConfirmPrompt(t0) {
  const $ = _c(16);
  const {
    onCancel,
    onConfirm,
    req,
    t
  } = t0;
  const [sel, setSel] = useState(0);
  let t1;
  if ($[0] !== onCancel || $[1] !== onConfirm || $[2] !== sel) {
    t1 = (ch, key) => {
      const lower = ch.toLowerCase();
      if (key.escape || key.ctrl && lower === "c" || lower === "n") {
        return onCancel();
      }
      if (lower === "y") {
        return onConfirm();
      }
      if (key.upArrow) {
        setSel(0);
      }
      if (key.downArrow) {
        setSel(1);
      }
      if (key.return) {
        sel === 0 ? onCancel() : onConfirm();
      }
    };
    $[0] = onCancel;
    $[1] = onConfirm;
    $[2] = sel;
    $[3] = t1;
  } else {
    t1 = $[3];
  }
  useInput(t1);
  const accent = req.danger ? t.color.error : t.color.cyan;
  const t2 = req.cancelLabel ?? "N\xE3o";
  let t3;
  if ($[4] !== accent || $[5] !== req.confirmLabel || $[6] !== req.danger || $[7] !== req.detail || $[8] !== req.title || $[9] !== sel || $[10] !== t.color.dim || $[11] !== t.color.error || $[12] !== t.color.label || $[13] !== t.color.text || $[14] !== t2) {
    const rows = [{
      color: t.color.text,
      key: "N",
      label: t2
    }, {
      color: req.danger ? t.color.error : t.color.text,
      key: "Y",
      label: req.confirmLabel ?? "Sim"
    }];
    t3 = _jsxs(Box, {
      borderColor: accent,
      borderStyle: "round",
      flexDirection: "column",
      paddingX: 1,
      children: [_jsxs(Box, {
        flexDirection: "row",
        flexWrap: "wrap",
        children: [_jsx(Text, {
          bold: true,
          color: accent,
          children: req.danger ? "\u25B2 " : "\u2726 "
        }), _jsx(Text, {
          bold: true,
          color: t.color.text,
          children: req.title
        })]
      }), req.detail ? _jsx(Box, {
        paddingLeft: 2,
        paddingTop: 1,
        children: _jsx(Text, {
          color: t.color.label,
          wrap: "wrap",
          children: req.detail
        })
      }) : null, _jsx(Text, {}), rows.map((row, i) => {
        const selected = sel === i;
        const line = `${selected ? "\u25B8" : " "} ${row.key} ${row.label}`;
        return _jsx(Box, {
          flexDirection: "row",
          children: _jsx(Text, {
            bold: selected,
            color: selected ? row.color : t.color.label,
            wrap: "wrap",
            children: line
          })
        }, row.label);
      }), _jsx(Text, {}), _jsx(Text, {
        color: t.color.dim,
        children: "\u2191/\u2193 navegar \xB7 Enter confirmar \xB7 Y/N atalho \xB7 Esc cancelar"
      })]
    });
    $[4] = accent;
    $[5] = req.confirmLabel;
    $[6] = req.danger;
    $[7] = req.detail;
    $[8] = req.title;
    $[9] = sel;
    $[10] = t.color.dim;
    $[11] = t.color.error;
    $[12] = t.color.label;
    $[13] = t.color.text;
    $[14] = t2;
    $[15] = t3;
  } else {
    t3 = $[15];
  }
  return t3;
}