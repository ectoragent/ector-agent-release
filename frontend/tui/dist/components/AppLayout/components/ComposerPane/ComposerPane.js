import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { Box, NoSelect, Text } from '@ector/ink';
import { useStore } from '@nanostores/react';
import { memo, useMemo } from 'react';
import { $isBlocked, $overlayState } from '../../../../app/overlayStore.js';
import { $uiState } from '../../../../app/uiStore.js';
import { BUSY_INTERRUPT_PLACEHOLDER, PLACEHOLDER } from '../../../../content/placeholders.js';
import { isComposerReady, isLoadingStatus, STATUS, STATUS_ERROR_DOT } from '../../../../content/uiStatus.js';
import { COMPOSER_PROMPT_GAP, composerCardWidth, stableComposerColumns } from '../../../../lib/inputMetrics.js';
import { CompletionMenu, FloatingOverlays } from '../../../AppOverlays/index.js';
import { ComposerFooter } from '../../../ComposerFooter/index.js';
import { MaskedPrompt } from '../../../MaskedPrompt/index.js';
import { QueuedMessages } from '../../../QueuedMessages/index.js';
import { TextInput } from '../../../TextInput/index.js';
import { Spinner } from '../../../Thinking/index.js';
export const ComposerPane = memo(function ComposerPane(t0) {
  const $ = _c(16);
  const {
    actions,
    composer,
    status
  } = t0;
  const ui = useStore($uiState);
  const overlay = useStore($overlayState);
  const isBlocked = useStore($isBlocked);
  const menuOverlay = overlay.picker || overlay.modelPicker || overlay.skillsHub;
  let t1;
  if ($[0] !== ui) {
    t1 = isComposerReady(ui);
    $[0] = ui;
    $[1] = t1;
  } else {
    t1 = $[1];
  }
  const composerReady = t1;
  const t2 = composer.inputBuf[0] ?? composer.input;
  let t3;
  if ($[2] !== t2) {
    t3 = t2.startsWith("!");
    $[2] = t2;
    $[3] = t3;
  } else {
    t3 = $[3];
  }
  const sh = t3;
  const promptColW = sh ? 2 : composer.inputBuf.length > 0 ? 2 : 0;
  let t4;
  if ($[4] !== actions || $[5] !== composer || $[6] !== composerReady || $[7] !== isBlocked || $[8] !== menuOverlay || $[9] !== overlay.secret || $[10] !== overlay.sudo || $[11] !== promptColW || $[12] !== sh || $[13] !== status || $[14] !== ui) {
    const inputColumns = stableComposerColumns(composer.cols, promptColW);
    const statusHud = {
      bgCount: ui.bgTasks.size,
      busy: ui.busy,
      cols: composer.cols,
      cwdLabel: status.cwdLabel,
      model: ui.info?.model ?? "",
      modelFast: ui.info?.fast || ui.info?.service_tier === "priority",
      modelReasoningEffort: ui.info?.reasoning_effort,
      sessionStartedAt: status.sessionStartedAt,
      showCost: ui.showCost,
      status: ui.status,
      statusColor: status.statusColor,
      t: ui.theme,
      turnStartedAt: status.turnStartedAt,
      usage: ui.usage,
      voiceLabel: status.voiceLabel
    };
    const shortModel = _temp;
    const effort = String(statusHud.modelReasoningEffort ?? "").trim().toLowerCase();
    const effortLabel = effort && effort !== "medium" && effort !== "normal" && effort !== "default" ? effort : "";
    const fastLabel = statusHud.modelFast ? "r\xE1pido" : "";
    const modelLabel = [shortModel(statusHud.model), effortLabel, fastLabel].filter(Boolean).join(" ");
    const pctRaw = typeof statusHud.usage.context_percent === "number" ? statusHud.usage.context_percent : statusHud.usage.context_max ? Math.round((statusHud.usage.context_used ?? 0) / statusHud.usage.context_max * 100) : null;
    const pct = pctRaw == null || Number.isNaN(pctRaw) ? null : Math.max(0, Math.min(100, Math.round(pctRaw)));
    const dotColor = statusHud.busy || isLoadingStatus(statusHud.status) ? statusHud.t.color.cyan : statusHud.status === STATUS.ready ? statusHud.t.color.ok : STATUS_ERROR_DOT.has(statusHud.status) ? statusHud.t.color.error : statusHud.t.color.ok;
    const modelFooter = {
      pct,
      dotColor,
      modelLabel: modelLabel || "(modelo)"
    };
    t4 = _jsx(NoSelect, {
      flexDirection: "column",
      flexShrink: 0,
      fromLeftEdge: true,
      padding: 1,
      rowGap: 1,
      children: [composerReady ? _jsx(QueuedMessages, {
        cols: composer.cols,
        queued: composer.queuedDisplay,
        queueEditIdx: composer.queueEditIdx,
        t: ui.theme
      }, "qmsg") : null, status.showStickyPrompt ? _jsxs(Text, {
        color: ui.theme.color.dim,
        wrap: "truncate-end",
        children: [_jsx(Text, {
          color: ui.theme.color.label,
          children: "\u21B3 "
        }), status.stickyPrompt]
      }, "sticky") : null, _jsx(Box, {
        backgroundColor: ui.theme.color.composerSurface,
        flexDirection: "column",
        flexShrink: 1,
        minWidth: 0,
        paddingX: 1,
        paddingY: 1,
        rowGap: 1,
        width: composerCardWidth(composer.cols),
        children: [composerReady ? _jsx(Box, {
          flexDirection: "column",
          minHeight: 2,
          position: "relative",
          rowGap: 0,
          children: [_jsx(FloatingOverlays, {
            onModelSelect: actions.onModelSelect,
            onPickerSelect: actions.resumeById,
            pagerPageSize: composer.pagerPageSize
          }, "fov"), !isBlocked ? [...composer.inputBuf.map((line, i) => {
            const rowGutter = sh ? 2 : i > 0 ? 2 : 0;
            return _jsx(Box, {
              columnGap: rowGutter > 0 ? COMPOSER_PROMPT_GAP : 0,
              flexDirection: "row",
              children: [rowGutter > 0 ? _jsx(Box, {
                width: rowGutter,
                children: _jsx(Text, {
                  color: ui.theme.color.dim,
                  children: sh ? i === 0 ? "$ " : "  " : "  "
                })
              }, `${i}-pw`) : null, _jsx(Text, {
                color: ui.theme.color.text,
                children: line || " "
              }, `${i}-ln`)].filter(Boolean)
            }, `buf-${i}`);
          }), _jsx(CompletionMenu, {
            cols: composer.cols,
            compIdx: composer.compIdx,
            completionMarginLeft: promptColW > 0 ? promptColW + COMPOSER_PROMPT_GAP : 0,
            completions: composer.completions
          }, "completion-menu"), _jsx(Box, {
            columnGap: promptColW > 0 ? COMPOSER_PROMPT_GAP : 0,
            flexDirection: "row",
            position: "relative",
            children: [promptColW > 0 ? _jsx(Box, {
              width: promptColW,
              children: sh ? _jsx(Text, {
                color: ui.theme.color.shellDollar,
                children: "$ "
              }) : _jsx(Text, {
                color: ui.theme.color.dim,
                children: "  "
              })
            }, "pw2") : null, _jsx(Box, {
              flexGrow: 1,
              flexShrink: 1,
              minWidth: 0,
              position: "relative",
              width: "100%",
              children: _jsx(TextInput, {
                columns: inputColumns,
                onChange: composer.updateInput,
                onPaste: composer.handleTextPaste,
                onSubmit: composer.submit,
                placeholder: composer.empty ? PLACEHOLDER : ui.busy ? BUSY_INTERRUPT_PLACEHOLDER : "",
                placeholderColor: composer.empty ? ui.theme.color.inputPlaceholder : undefined,
                textColor: ui.theme.color.text,
                value: composer.input
              }, "ti")
            }, "ti-wrap")].filter(Boolean)
          }, "comp-active")].flat() : null, !isBlocked || menuOverlay || overlay.sudo || overlay.secret ? null : _jsx(Text, {
            color: ui.theme.color.dim,
            children: ui.status
          }, "comp-blocked"), overlay.sudo ? _jsx(MaskedPrompt, {
            cols: composer.cols,
            icon: "\uD83D\uDD10",
            label: "senha sudo necess\xE1ria",
            onSubmit: actions.answerSudo,
            t: ui.theme
          }, "comp-sudo") : null, overlay.secret ? _jsx(MaskedPrompt, {
            cols: composer.cols,
            icon: "\uD83D\uDD11",
            label: overlay.secret.prompt,
            onSubmit: actions.answerSecret,
            sub: `para ${overlay.secret.envVar}`,
            t: ui.theme
          }, "comp-secret") : null].filter(Boolean)
        }, "composer-body") : !isBlocked ? _jsx(Text, {
          color: ui.theme.color.dim,
          children: isLoadingStatus(ui.status) ? _jsxs(_Fragment, {
            children: [_jsx(Spinner, {
              color: ui.theme.color.dim,
              variant: "think"
            }), " ", ui.status]
          }) : ui.status
        }, "comp-boot") : null].filter(Boolean)
      }, "composer-card"), !isBlocked ? _jsx(Box, {
        flexDirection: "row",
        flexShrink: 0,
        height: 1,
        width: "100%",
        children: _jsx(ComposerFooter, {
          busy: statusHud.busy || isLoadingStatus(statusHud.status),
          cols: composerCardWidth(composer.cols),
          cwdShort: status.cwdShort,
          dotColor: modelFooter.dotColor,
          modelLabel: modelFooter.modelLabel,
          pct: modelFooter.pct,
          showCost: statusHud.showCost,
          t: ui.theme,
          usage: statusHud.usage
        })
      }, "composer-status") : null].filter(Boolean)
    });
    $[4] = actions;
    $[5] = composer;
    $[6] = composerReady;
    $[7] = isBlocked;
    $[8] = menuOverlay;
    $[9] = overlay.secret;
    $[10] = overlay.sudo;
    $[11] = promptColW;
    $[12] = sh;
    $[13] = status;
    $[14] = ui;
    $[15] = t4;
  } else {
    t4 = $[15];
  }
  return t4;
});
function _temp(model) {
  return model.split("/").pop().replace(/^claude[-_]/, "").replace(/^anthropic[-_]/, "").replace(/[-_]/g, " ").replace(/\b(\d+)\s+(\d+)\b/g, "$1.$2").trim();
}