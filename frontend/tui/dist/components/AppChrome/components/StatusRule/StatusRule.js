import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Box, Text } from '@ector/ink';
import { strings } from '../../../../content/strings.js';
import { isLoadingStatus, STATUS, STATUS_ERROR_DOT } from '../../../../content/uiStatus.js';
import { usageCostLabel, usageTokenLabel } from '../../../../domain/usage.js';
import { ctxBarColor, CtxBusyMeter, CtxUsageBar } from '../../../../lib/contextMeter.js';
import { Spinner } from '../../../Thinking/index.js';
import { modelLabel } from '../../lib/statusBarHelpers.js';
import { BusyTicker } from '../BusyTicker/index.js';
import { SessionDuration } from '../SessionDuration/index.js';
import { SpawnHud } from '../SpawnHud/index.js';
export function StatusRule({
  kind = 'primary',
  cwdLabel,
  cols,
  busy,
  status,
  statusColor,
  model,
  modelFast,
  modelReasoningEffort,
  usage,
  bgCount,
  sessionStartedAt,
  showCost,
  turnStartedAt,
  voiceLabel,
  t
}) {
  const pct = usage.context_percent;
  const barColor = ctxBarColor(pct, t);
  const ctxLabel = usageTokenLabel(usage);
  const costLabel = showCost ? usageCostLabel(usage) : '';
  const showCtxBar = Boolean(usage.context_max);
  const showCtxMeter = showCtxBar && pct != null && pct > 0;
  const sep = ' · ';
  if (kind === 'secondary') {
    const subtle = t.color.statusBarSubtle;
    const vl = voiceLabel ?? '';
    const voiceTone = vl.startsWith('●') ? t.color.error : vl.startsWith('◉') ? t.color.warn : subtle;
    return _jsxs(Box, {
      alignItems: "center",
      flexDirection: "row",
      height: 1,
      width: cols,
      children: [_jsx(Box, {
        flexGrow: 1,
        flexShrink: 1,
        minWidth: 0,
        children: _jsx(Text, {
          color: subtle,
          dim: true,
          wrap: "truncate-end",
          children: cwdLabel
        })
      }), vl ? _jsxs(Box, {
        flexDirection: "row",
        flexShrink: 0,
        children: [_jsx(Text, {
          color: subtle,
          dim: true,
          children: sep
        }), _jsx(Text, {
          color: voiceTone,
          dim: true,
          children: vl
        })]
      }) : null, sessionStartedAt ? _jsxs(Box, {
        flexDirection: "row",
        flexShrink: 0,
        children: [_jsx(Text, {
          color: subtle,
          dim: true,
          children: sep
        }), _jsx(Text, {
          color: subtle,
          dim: true,
          children: _jsx(SessionDuration, {
            startedAt: sessionStartedAt
          })
        })]
      }) : null]
    });
  }
  return _jsx(Box, {
    alignItems: "center",
    flexDirection: "row",
    height: 1,
    width: cols,
    children: _jsx(Box, {
      flexGrow: 1,
      flexShrink: 1,
      minWidth: 0,
      children: _jsxs(Text, {
        wrap: "truncate-end",
        children: [busy ? _jsx(BusyTicker, {
          color: statusColor,
          startedAt: turnStartedAt
        }) : bgCount > 0 ? _jsxs(Text, {
          color: t.color.cyan,
          children: [_jsx(Spinner, {
            color: t.color.cyan,
            variant: "think"
          }), ' ', bgCount === 1 ? strings.slash.backgroundRunning : strings.slash.backgroundRunningMany(bgCount)]
        }) : isLoadingStatus(status) ? _jsxs(Text, {
          color: statusColor,
          children: [_jsx(Spinner, {
            color: statusColor,
            variant: "think"
          }), " ", status]
        }) : status === STATUS.ready ? _jsx(Text, {
          color: t.color.ok,
          children: "\u25CF"
        }) : STATUS_ERROR_DOT.has(status) ? _jsx(Text, {
          color: t.color.error,
          children: "\u25CF"
        }) : _jsx(Text, {
          color: statusColor,
          children: status
        }), _jsxs(Text, {
          color: t.color.statusBarMeta,
          dim: true,
          children: [sep, modelLabel(model, modelReasoningEffort, modelFast)]
        }), ctxLabel ? _jsxs(Box, {
          alignItems: "center",
          flexDirection: "row",
          flexShrink: 0,
          children: [_jsxs(Text, {
            color: t.color.statusBarMeta,
            dim: true,
            children: [sep, ctxLabel]
          }), busy ? _jsx(CtxBusyMeter, {
            t: t
          }) : null]
        }) : null, showCtxMeter ? _jsxs(Text, {
          color: t.color.statusBarMeta,
          dim: true,
          children: [sep, _jsx(CtxUsageBar, {
            pct: pct,
            t: t,
            w: 6
          }), " ", _jsx(Text, {
            color: barColor,
            children: pct != null ? `${pct}%` : ''
          })]
        }) : null, _jsx(SpawnHud, {
          t: t
        }), costLabel ? _jsxs(Text, {
          color: t.color.statusBarMeta,
          dim: true,
          children: [sep, costLabel]
        }) : null]
      })
    })
  });
}