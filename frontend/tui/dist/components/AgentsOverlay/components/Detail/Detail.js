import { jsxs as _jsxs, jsx as _jsx, Fragment as _Fragment } from "react/jsx-runtime";
import { Box, Text } from '@ector/ink';
import { fmtCost, fmtTokens } from '../../../../lib/subagentTree.js';
import { STATUS_PT } from '../../lib/overlayConstants.js';
import { fmtDur, statusGlyph } from '../../lib/overlayRows.js';
import { OverlaySection } from '../OverlaySection/index.js';
function Field({
  name,
  t,
  value
}) {
  return _jsxs(Text, {
    wrap: "truncate-end",
    children: [_jsxs(Text, {
      color: t.color.label,
      children: [name, " \u00B7 "]
    }), _jsx(Text, {
      color: t.color.text,
      children: value
    })]
  });
}
export function Detail({
  id,
  node,
  t
}) {
  const {
    aggregate: agg,
    item
  } = node;
  const {
    color,
    glyph
  } = statusGlyph(item, t);
  const inputTokens = item.inputTokens ?? 0;
  const outputTokens = item.outputTokens ?? 0;
  const localTokens = inputTokens + outputTokens;
  const subtreeTokens = agg.inputTokens + agg.outputTokens - localTokens;
  const localCost = item.costUsd ?? 0;
  const subtreeCost = agg.costUsd - localCost;
  const filesRead = item.filesRead ?? [];
  const filesWritten = item.filesWritten ?? [];
  const outputTail = item.outputTail ?? [];
  // Tool calls: prefer the live stream; for archived / post-turn views
  // that stream is often empty even when tool_count > 0, so fall back to
  // the tool names captured in outputTail at subagent.complete time.
  const toolLines = item.tools.length > 0 ? item.tools : outputTail.map(e => e.tool).filter(Boolean);
  const filesOverflow = Math.max(0, filesRead.length - 8) + Math.max(0, filesWritten.length - 8);
  return _jsxs(Box, {
    flexDirection: "column",
    children: [_jsxs(Text, {
      bold: true,
      color: t.color.text,
      wrap: "wrap",
      children: [id ? _jsxs(Text, {
        color: t.color.cyan,
        children: ["#", id, " "]
      }) : null, _jsx(Text, {
        color: color,
        children: glyph
      }), " ", item.goal]
    }), _jsxs(Box, {
      flexDirection: "column",
      marginTop: 1,
      children: [_jsx(Field, {
        name: "profundidade",
        t: t,
        value: `${item.depth} · ${STATUS_PT[item.status] ?? item.status}`
      }), item.model ? _jsx(Field, {
        name: "modelo",
        t: t,
        value: item.model
      }) : null, item.toolsets?.length ? _jsx(Field, {
        name: "conjuntos de ferramentas",
        t: t,
        value: item.toolsets.join(', ')
      }) : null, _jsx(Field, {
        name: "ferramentas",
        t: t,
        value: `${item.toolCount ?? 0} (subárvore ${agg.totalTools})`
      }), _jsx(Field, {
        name: "sub\u00E1rvore",
        t: t,
        value: `${agg.descendantCount} agente${agg.descendantCount === 1 ? '' : 's'} · d${agg.maxDepthFromHere} · ⚡${agg.activeCount}`
      }), item.durationSeconds ? _jsx(Field, {
        name: "decorrido",
        t: t,
        value: fmtDur(item.durationSeconds)
      }) : null, item.iteration != null ? _jsx(Field, {
        name: "itera\u00E7\u00E3o",
        t: t,
        value: String(item.iteration)
      }) : null, item.apiCalls ? _jsx(Field, {
        name: "chamadas API",
        t: t,
        value: String(item.apiCalls)
      }) : null]
    }), localTokens > 0 || localCost > 0 ? _jsxs(OverlaySection, {
      defaultOpen: true,
      t: t,
      title: "Consumo",
      children: [localTokens > 0 ? _jsx(Field, {
        name: "tokens",
        t: t,
        value: _jsxs(_Fragment, {
          children: [fmtTokens(inputTokens), " entrada \u00B7 ", fmtTokens(outputTokens), " sa\u00EDda", item.reasoningTokens ? ` · ${fmtTokens(item.reasoningTokens)} raciocínio` : '']
        })
      }) : null, localCost > 0 ? _jsx(Field, {
        name: "custo",
        t: t,
        value: _jsxs(_Fragment, {
          children: [fmtCost(localCost), subtreeCost >= 0.01 ? ` · subárvore +${fmtCost(subtreeCost)}` : '']
        })
      }) : null, subtreeTokens > 0 ? _jsx(Field, {
        name: "tokens da sub\u00E1rvore",
        t: t,
        value: `+${fmtTokens(subtreeTokens)}`
      }) : null]
    }) : null, filesRead.length > 0 || filesWritten.length > 0 ? _jsxs(OverlaySection, {
      count: filesRead.length + filesWritten.length,
      t: t,
      title: "Arquivos",
      children: [filesWritten.slice(0, 8).map((p, i) => _jsxs(Text, {
        color: t.color.statusGood,
        wrap: "truncate-end",
        children: ["+", p]
      }, `w-${i}`)), filesRead.slice(0, 8).map((p, i) => _jsxs(Text, {
        color: t.color.text,
        wrap: "truncate-end",
        children: [_jsx(Text, {
          color: t.color.dim,
          children: "\u00B7"
        }), " ", p]
      }, `r-${i}`)), filesOverflow > 0 ? _jsxs(Text, {
        color: t.color.dim,
        children: ["\u2026+", filesOverflow, " a mais"]
      }) : null]
    }) : null, toolLines.length > 0 ? _jsx(OverlaySection, {
      count: toolLines.length,
      defaultOpen: true,
      t: t,
      title: "Chamadas de ferramenta",
      children: toolLines.map((line, i) => _jsxs(Text, {
        color: t.color.text,
        wrap: "wrap",
        children: [_jsx(Text, {
          color: t.color.dim,
          children: "\u00B7"
        }), " ", line]
      }, i))
    }) : null, outputTail.length > 0 ? _jsx(OverlaySection, {
      count: outputTail.length,
      defaultOpen: true,
      t: t,
      title: "Sa\u00EDda",
      children: outputTail.map((entry, i) => _jsxs(Text, {
        color: entry.isError ? t.color.error : t.color.text,
        wrap: "wrap",
        children: [_jsx(Text, {
          bold: true,
          color: entry.isError ? t.color.error : t.color.cyan,
          children: entry.tool
        }), ' ', entry.preview]
      }, i))
    }) : null, item.notes.length ? _jsx(OverlaySection, {
      count: item.notes.length,
      t: t,
      title: "Andamento",
      children: item.notes.slice(-6).map((line, i) => _jsxs(Text, {
        color: t.color.text,
        wrap: "wrap",
        children: [_jsx(Text, {
          color: t.color.label,
          children: "\u00B7"
        }), " ", line]
      }, i))
    }) : null, item.summary ? _jsx(OverlaySection, {
      defaultOpen: true,
      t: t,
      title: "Resumo",
      children: _jsx(Text, {
        color: t.color.text,
        wrap: "wrap",
        children: item.summary
      })
    }) : null]
  });
}