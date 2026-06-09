import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Box, Text, useInput } from '@ector/ink';
import { useEffect, useMemo, useState } from 'react';
import { CMD_PREVIEW_LINES, LABELS, OPT_HINTS, OPTS } from '../../lib/promptConstants.js';
import { severityColor } from '../../lib/severityColor.js';
import { severityDisplayLabel } from '../../lib/severityLabel.js';
import { parseApprovalFindings } from '../../parseApprovalFindings.js';
export function ApprovalPrompt(t0) {
  const $ = _c(19);
  const {
    onChoice,
    req,
    t
  } = t0;
  const [sel, setSel] = useState(0);
  const [armed, setArmed] = useState(false);
  let t1;
  let t2;
  if ($[0] === Symbol.for("react.memo_cache_sentinel")) {
    t1 = () => {
      const timer = setTimeout(() => setArmed(true), 75);
      return () => clearTimeout(timer);
    };
    t2 = [];
    $[0] = t1;
    $[1] = t2;
  } else {
    t1 = $[0];
    t2 = $[1];
  }
  useEffect(t1, t2);
  let t3;
  if ($[2] !== armed || $[3] !== onChoice || $[4] !== sel) {
    t3 = (ch, key) => {
      if (key.upArrow && sel > 0) {
        setSel(_temp);
      }
      if (key.downArrow && sel < OPTS.length - 1) {
        setSel(_temp2);
      }
      const n = parseInt(ch, 10);
      if (n >= 1 && n <= OPTS.length) {
        onChoice(OPTS[n - 1]);
        return;
      }
      if (key.return) {
        if (!armed) {
          return;
        }
        onChoice(OPTS[sel]);
      }
    };
    $[2] = armed;
    $[3] = onChoice;
    $[4] = sel;
    $[5] = t3;
  } else {
    t3 = $[5];
  }
  useInput(t3);
  let t4;
  if ($[6] !== req.description) {
    t4 = parseApprovalFindings(req.description);
    $[6] = req.description;
    $[7] = t4;
  } else {
    t4 = $[7];
  }
  const findings = t4;
  let t5;
  if ($[8] !== findings || $[9] !== req.command || $[10] !== sel || $[11] !== t) {
    const topSeverity = findings.find(_temp3)?.severity ?? "";
    const accent = topSeverity ? severityColor(topSeverity, t) : t.color.warn;
    const rawLines = req.command.split("\n");
    const shown = rawLines.slice(0, CMD_PREVIEW_LINES);
    const overflow = rawLines.length - shown.length;
    let t6;
    if ($[13] !== findings.length || $[14] !== t) {
      t6 = (f_0, i) => _jsxs(Box, {
        flexDirection: "column",
        marginBottom: i === findings.length - 1 ? 0 : 1,
        children: [_jsxs(Box, {
          flexDirection: "row",
          flexWrap: "wrap",
          children: [f_0.severity ? _jsx(Text, {
            bold: true,
            color: severityColor(f_0.severity, t),
            children: severityDisplayLabel(f_0.severity)
          }) : _jsx(Text, {
            color: t.color.dim,
            children: "\u2022"
          }), _jsx(Text, {
            color: t.color.dim,
            children: "  "
          }), _jsx(Text, {
            bold: true,
            color: t.color.text,
            children: f_0.title || "Risco detectado"
          })]
        }), f_0.detail ? _jsx(Box, {
          paddingLeft: f_0.severity ? severityDisplayLabel(f_0.severity).length + 2 : 2,
          children: _jsx(Text, {
            color: t.color.label,
            wrap: "wrap",
            children: f_0.detail
          })
        }) : null]
      }, i);
      $[13] = findings.length;
      $[14] = t;
      $[15] = t6;
    } else {
      t6 = $[15];
    }
    let t7;
    if ($[16] !== t.color.shellDollar || $[17] !== t.color.text) {
      t7 = (line, i_0) => _jsxs(Box, {
        flexDirection: "row",
        children: [_jsx(Text, {
          color: t.color.shellDollar,
          children: i_0 === 0 ? "$ " : "  "
        }), _jsx(Text, {
          color: t.color.text,
          wrap: "wrap",
          children: line || " "
        })]
      }, i_0);
      $[16] = t.color.shellDollar;
      $[17] = t.color.text;
      $[18] = t7;
    } else {
      t7 = $[18];
    }
    t5 = _jsxs(Box, {
      borderColor: t.color.border,
      borderStyle: "round",
      flexDirection: "column",
      paddingX: 1,
      paddingY: 0,
      children: [_jsxs(Box, {
        flexDirection: "row",
        flexWrap: "wrap",
        children: [_jsx(Text, {
          bold: true,
          color: accent,
          children: "\u25B2 "
        }), _jsx(Text, {
          bold: true,
          color: t.color.text,
          children: "Aprova\xE7\xE3o necess\xE1ria"
        }), _jsx(Text, {
          color: t.color.dim,
          children: "  \xB7  o agente quer executar um comando sens\xEDvel"
        })]
      }), _jsx(Text, {}), _jsx(Box, {
        flexDirection: "column",
        children: findings.map(t6)
      }), _jsx(Text, {}), _jsx(Box, {
        children: _jsx(Text, {
          color: t.color.dim,
          children: "comando"
        })
      }), _jsxs(Box, {
        borderColor: t.color.composerBorder,
        borderStyle: "single",
        flexDirection: "column",
        paddingX: 1,
        children: [shown.map(t7), overflow > 0 ? _jsxs(Text, {
          color: t.color.dim,
          children: ["\u2026 +", overflow, " linha", overflow === 1 ? "" : "s", " ocultada", overflow === 1 ? "" : "s"]
        }) : null]
      }), _jsx(Text, {}), OPTS.map((o, i_1) => {
        const selected = sel === i_1;
        const isDeny = o === "deny";
        const lineColor = selected ? isDeny ? t.color.error : accent : t.color.label;
        const line_0 = `${selected ? "\u25B8" : " "} ${i_1 + 1}. ${LABELS[o]}${selected ? ` — ${OPT_HINTS[o]}` : ""}`;
        return _jsx(Box, {
          flexDirection: "row",
          children: _jsx(Text, {
            bold: selected,
            color: lineColor,
            wrap: "wrap",
            children: line_0
          })
        }, o);
      }), _jsx(Text, {}), _jsx(Text, {
        color: t.color.dim,
        children: "\u2191/\u2193 navegar \xB7 Enter confirmar \xB7 1-4 atalho \xB7 Ctrl+C negar"
      })]
    });
    $[8] = findings;
    $[9] = req.command;
    $[10] = sel;
    $[11] = t;
    $[12] = t5;
  } else {
    t5 = $[12];
  }
  return t5;
}
function _temp3(f) {
  return f.severity;
}
function _temp2(s_0) {
  return s_0 + 1;
}
function _temp(s) {
  return s - 1;
}