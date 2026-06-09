import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { Box, Text } from '@ector/ink';
import { memo } from 'react';
import { usageCostLabel, usageTokenLabel } from '../../domain/usage.js';
import { ctxBarColor, CtxBusyMeter } from '../../lib/contextMeter.js';
/** Custo no rodapé só quando `display.show_cost` está ativo. */
export function composerCostLabel(showCost, usage) {
  return showCost ? usageCostLabel(usage) : '';
}
/** Context % in the status line only when usage is strictly above zero. */
export function showComposerContextPct(pct) {
  return pct != null && pct > 0;
}
export const ComposerFooter = memo(function ComposerFooter({
  busy = false,
  cols,
  cwdShort,
  dotColor,
  modelLabel,
  pct,
  showCost,
  t,
  usage
}) {
  const showPct = showComposerContextPct(pct);
  const costLabel = composerCostLabel(showCost, usage);
  const tokenLabel = usageTokenLabel(usage);
  const sep = ' · ';
  return _jsxs(Box, {
    flexDirection: "row",
    flexShrink: 0,
    height: 1,
    width: cols,
    children: [_jsxs(Box, {
      flexDirection: "row",
      flexShrink: 0,
      children: [_jsx(Text, {
        color: dotColor,
        children: "\u25CF "
      }), _jsx(Text, {
        color: t.color.statusBarMeta,
        dim: true,
        children: modelLabel
      }), costLabel ? _jsxs(Text, {
        color: t.color.statusBarMeta,
        dim: true,
        children: [sep, costLabel]
      }) : null, tokenLabel ? _jsxs(Box, {
        alignItems: "center",
        flexDirection: "row",
        flexShrink: 0,
        height: 1,
        children: [_jsxs(Text, {
          color: t.color.statusBarMeta,
          dim: true,
          children: [sep, tokenLabel]
        }), busy ? _jsx(CtxBusyMeter, {
          t: t
        }) : null]
      }) : null, showPct ? _jsxs(Text, {
        color: t.color.statusBarMeta,
        dim: true,
        children: [sep, _jsxs(Text, {
          color: ctxBarColor(pct, t),
          children: [pct, "%"]
        })]
      }) : null]
    }), cwdShort ? _jsxs(_Fragment, {
      children: [_jsx(Box, {
        flexGrow: 1
      }), _jsx(Box, {
        flexShrink: 0,
        minWidth: 0,
        children: _jsx(Text, {
          color: t.color.statusBarMeta,
          dim: true,
          wrap: "truncate-start",
          children: cwdShort
        })
      })]
    }) : null]
  });
});