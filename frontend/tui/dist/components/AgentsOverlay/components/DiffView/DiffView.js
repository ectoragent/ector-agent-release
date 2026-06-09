import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Box, Text, useInput } from '@ector/ink';
import { useMemo } from 'react';
import { buildSubagentTree, fmtCost, fmtTokens, formatSummary, topLevelSubagents, treeTotals } from '../../../../lib/subagentTree.js';
import { diffMetricLine, statusGlyph } from '../../lib/overlayRows.js';
function DiffPane({
  label,
  snapshot,
  t,
  totals,
  width
}) {
  return _jsxs(Box, {
    flexDirection: "column",
    width: width,
    children: [_jsx(Text, {
      bold: true,
      color: t.color.text,
      children: label
    }), _jsx(Text, {
      color: t.color.dim,
      wrap: "truncate-end",
      children: snapshot.label
    }), _jsx(Box, {
      marginTop: 1,
      children: _jsx(Text, {
        color: t.color.dim,
        wrap: "truncate-end",
        children: formatSummary(totals)
      })
    }), _jsx(Box, {
      flexDirection: "column",
      marginTop: 1,
      children: topLevelSubagents(snapshot.subagents).slice(0, 8).map(s => {
        const {
          color,
          glyph
        } = statusGlyph(s, t);
        return _jsxs(Text, {
          color: t.color.dim,
          wrap: "truncate-end",
          children: [_jsx(Text, {
            color: color,
            children: glyph
          }), " ", s.goal || 'subagente']
        }, s.id);
      })
    })]
  });
}
export function DiffView(t0) {
  const $ = _c(13);
  const {
    cols,
    onClose,
    pair,
    t
  } = t0;
  let t1;
  if ($[0] !== pair.baseline.subagents) {
    t1 = treeTotals(buildSubagentTree(pair.baseline.subagents));
    $[0] = pair.baseline.subagents;
    $[1] = t1;
  } else {
    t1 = $[1];
  }
  const aTotals = t1;
  let t2;
  if ($[2] !== pair.candidate.subagents) {
    t2 = treeTotals(buildSubagentTree(pair.candidate.subagents));
    $[2] = pair.candidate.subagents;
    $[3] = t2;
  } else {
    t2 = $[3];
  }
  const bTotals = t2;
  const paneWidth = Math.floor((cols - 4) / 2);
  let t3;
  if ($[4] !== onClose) {
    t3 = (ch, key) => {
      if (key.escape || ch === "q") {
        onClose();
      }
    };
    $[4] = onClose;
    $[5] = t3;
  } else {
    t3 = $[5];
  }
  useInput(t3);
  const round = _temp;
  const sumTokens = _temp2;
  const dollars = _temp3;
  let t4;
  if ($[6] !== aTotals || $[7] !== bTotals || $[8] !== pair.baseline || $[9] !== pair.candidate || $[10] !== paneWidth || $[11] !== t) {
    t4 = _jsxs(Box, {
      flexDirection: "column",
      flexGrow: 1,
      paddingX: 1,
      paddingY: 1,
      children: [_jsxs(Box, {
        flexDirection: "column",
        marginBottom: 1,
        children: [_jsx(Text, {
          bold: true,
          color: t.color.border,
          children: "Diff do replay"
        }), _jsx(Text, {
          color: t.color.dim,
          children: "linha de base vs candidato \xB7 esc/q fechar"
        })]
      }), _jsxs(Box, {
        flexDirection: "row",
        marginBottom: 1,
        children: [_jsx(DiffPane, {
          label: "A \xB7 linha de base",
          snapshot: pair.baseline,
          t,
          totals: aTotals,
          width: paneWidth
        }), _jsx(Box, {
          width: 2
        }), _jsx(DiffPane, {
          label: "B \xB7 candidato",
          snapshot: pair.candidate,
          t,
          totals: bTotals,
          width: paneWidth
        })]
      }), _jsxs(Box, {
        flexDirection: "column",
        marginTop: 1,
        children: [_jsx(Text, {
          bold: true,
          color: t.color.cyan,
          children: "\u0394"
        }), _jsx(Text, {
          color: t.color.text,
          children: diffMetricLine("agentes", aTotals.descendantCount, bTotals.descendantCount, round)
        }), _jsx(Text, {
          color: t.color.text,
          children: diffMetricLine("ferramentas", aTotals.totalTools, bTotals.totalTools, round)
        }), _jsx(Text, {
          color: t.color.text,
          children: diffMetricLine("profundidade", aTotals.maxDepthFromHere, bTotals.maxDepthFromHere, round)
        }), _jsx(Text, {
          color: t.color.text,
          children: diffMetricLine("dura\xE7\xE3o", aTotals.totalDuration, bTotals.totalDuration, _temp4)
        }), _jsx(Text, {
          color: t.color.text,
          children: diffMetricLine("tokens", sumTokens(aTotals), sumTokens(bTotals), fmtTokens)
        }), _jsx(Text, {
          color: t.color.text,
          children: diffMetricLine("custo", aTotals.costUsd, bTotals.costUsd, dollars)
        })]
      })]
    });
    $[6] = aTotals;
    $[7] = bTotals;
    $[8] = pair.baseline;
    $[9] = pair.candidate;
    $[10] = paneWidth;
    $[11] = t;
    $[12] = t4;
  } else {
    t4 = $[12];
  }
  return t4;
}
function _temp4(n_1) {
  return `${n_1.toFixed(1)}s`;
}
function _temp3(n_0) {
  return fmtCost(n_0) || "$0.00";
}
function _temp2(x) {
  return x.inputTokens + x.outputTokens;
}
function _temp(n) {
  return String(Math.round(n));
}