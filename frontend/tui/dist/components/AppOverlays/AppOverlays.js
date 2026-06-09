import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Box, Text } from '@ector/ink';
import { useStore } from '@nanostores/react';
import { useGateway } from '../../app/gatewayContext.js';
import { $overlayState, patchOverlayState } from '../../app/overlayStore.js';
import { $uiState } from '../../app/uiStore.js';
import { WISER_USER_CANCELLED } from '../../content/wiserMessages.js';
import { FloatBox } from '../AppChrome/index.js';
import { MaskedPrompt } from '../MaskedPrompt/index.js';
import { ModelPicker } from '../ModelPicker/index.js';
import { OverlayHint } from '../OverlayControls/index.js';
import { ApprovalPrompt, ConfirmPrompt, WiserPrompt } from '../Prompts/index.js';
import { SessionPicker } from '../SessionPicker/index.js';
import { SkillsHub } from '../SkillsHub/index.js';
const COMPLETION_WINDOW = 16;
function completionViewport(completions, compIdx) {
  const viewportSize = Math.min(COMPLETION_WINDOW, completions.length);
  const start = Math.max(0, Math.min(compIdx - Math.floor(COMPLETION_WINDOW / 2), completions.length - viewportSize));
  return {
    start,
    viewportSize
  };
}
export function CompletionMenu(t0) {
  const $ = _c(15);
  const {
    cols,
    completionMarginLeft: t1,
    compIdx,
    completions
  } = t0;
  const completionMarginLeft = t1 === undefined ? 0 : t1;
  const ui = useStore($uiState);
  if (!completions.length) {
    return null;
  }
  let t2;
  if ($[0] !== compIdx || $[1] !== completions) {
    t2 = completionViewport(completions, compIdx);
    $[0] = compIdx;
    $[1] = completions;
    $[2] = t2;
  } else {
    t2 = $[2];
  }
  const {
    start,
    viewportSize
  } = t2;
  const t3 = Math.max(28, cols - 6 - completionMarginLeft);
  let t4;
  if ($[3] !== compIdx || $[4] !== completionMarginLeft || $[5] !== completions || $[6] !== start || $[7] !== t3 || $[8] !== ui || $[9] !== viewportSize) {
    let t5;
    if ($[11] !== compIdx || $[12] !== start || $[13] !== ui) {
      t5 = (item, i) => {
        const active = start + i === compIdx;
        return _jsxs(Box, {
          alignSelf: "stretch",
          backgroundColor: active ? ui.theme.color.completionCurrentBg : ui.theme.color.completionBg,
          flexDirection: "row",
          children: [_jsx(Text, {
            bold: active,
            color: ui.theme.color.text,
            dim: !active,
            children: item.display
          }), item.meta ? _jsxs(Text, {
            color: active ? ui.theme.color.cyan : ui.theme.color.label,
            wrap: "truncate",
            children: [" ", item.meta]
          }) : null]
        }, `${start + i}:${item.text}:${item.display}:${item.meta ?? ""}`);
      };
      $[11] = compIdx;
      $[12] = start;
      $[13] = ui;
      $[14] = t5;
    } else {
      t5 = $[14];
    }
    t4 = _jsx(Box, {
      alignSelf: "flex-start",
      flexDirection: "column",
      flexShrink: 0,
      marginBottom: 1,
      marginLeft: completionMarginLeft,
      overflow: "hidden",
      width: t3,
      children: completions.slice(start, start + viewportSize).map(t5)
    });
    $[3] = compIdx;
    $[4] = completionMarginLeft;
    $[5] = completions;
    $[6] = start;
    $[7] = t3;
    $[8] = ui;
    $[9] = viewportSize;
    $[10] = t4;
  } else {
    t4 = $[10];
  }
  return t4;
}
export function PromptZone(t0) {
  const $ = _c(27);
  const {
    cols,
    onApprovalChoice,
    onWiserAnswer,
    onSecretSubmit,
    onSudoSubmit
  } = t0;
  const overlay = useStore($overlayState);
  const ui = useStore($uiState);
  if (overlay.approval) {
    let t1;
    if ($[0] !== onApprovalChoice || $[1] !== overlay.approval || $[2] !== ui.theme) {
      t1 = _jsx(Box, {
        flexDirection: "column",
        flexShrink: 0,
        paddingX: 1,
        paddingY: 1,
        children: _jsx(ApprovalPrompt, {
          onChoice: onApprovalChoice,
          req: overlay.approval,
          t: ui.theme
        })
      });
      $[0] = onApprovalChoice;
      $[1] = overlay.approval;
      $[2] = ui.theme;
      $[3] = t1;
    } else {
      t1 = $[3];
    }
    return t1;
  }
  if (overlay.confirm) {
    const req = overlay.confirm;
    let t1;
    if ($[4] !== req) {
      t1 = () => {
        patchOverlayState({
          confirm: null
        });
        req.onConfirm();
      };
      $[4] = req;
      $[5] = t1;
    } else {
      t1 = $[5];
    }
    const onConfirm = t1;
    const onCancel = _temp;
    let t2;
    if ($[6] !== onConfirm || $[7] !== req || $[8] !== ui.theme) {
      t2 = _jsx(Box, {
        flexDirection: "column",
        flexShrink: 0,
        paddingX: 1,
        paddingY: 1,
        children: _jsx(ConfirmPrompt, {
          onCancel,
          onConfirm,
          req,
          t: ui.theme
        })
      });
      $[6] = onConfirm;
      $[7] = req;
      $[8] = ui.theme;
      $[9] = t2;
    } else {
      t2 = $[9];
    }
    return t2;
  }
  if (overlay.wiser) {
    let t1;
    if ($[10] !== cols || $[11] !== onWiserAnswer || $[12] !== overlay.wiser || $[13] !== ui.theme) {
      let t2;
      if ($[15] !== onWiserAnswer) {
        t2 = () => onWiserAnswer(WISER_USER_CANCELLED);
        $[15] = onWiserAnswer;
        $[16] = t2;
      } else {
        t2 = $[16];
      }
      t1 = _jsx(Box, {
        flexDirection: "column",
        flexShrink: 0,
        paddingX: 1,
        paddingY: 1,
        children: _jsx(WiserPrompt, {
          cols,
          onAnswer: onWiserAnswer,
          onCancel: t2,
          req: overlay.wiser,
          t: ui.theme
        })
      });
      $[10] = cols;
      $[11] = onWiserAnswer;
      $[12] = overlay.wiser;
      $[13] = ui.theme;
      $[14] = t1;
    } else {
      t1 = $[14];
    }
    return t1;
  }
  if (overlay.sudo) {
    let t1;
    if ($[17] !== cols || $[18] !== onSudoSubmit || $[19] !== ui.theme) {
      t1 = _jsx(Box, {
        flexDirection: "column",
        flexShrink: 0,
        paddingX: 1,
        paddingY: 1,
        children: _jsx(MaskedPrompt, {
          cols,
          icon: "\uD83D\uDD10",
          label: "senha sudo necess\xE1ria",
          onSubmit: onSudoSubmit,
          t: ui.theme
        })
      });
      $[17] = cols;
      $[18] = onSudoSubmit;
      $[19] = ui.theme;
      $[20] = t1;
    } else {
      t1 = $[20];
    }
    return t1;
  }
  if (overlay.secret) {
    let t1;
    if ($[21] !== cols || $[22] !== onSecretSubmit || $[23] !== overlay.secret.envVar || $[24] !== overlay.secret.prompt || $[25] !== ui.theme) {
      t1 = _jsx(Box, {
        flexDirection: "column",
        flexShrink: 0,
        paddingX: 1,
        paddingY: 1,
        children: _jsx(MaskedPrompt, {
          cols,
          icon: "\uD83D\uDD11",
          label: overlay.secret.prompt,
          onSubmit: onSecretSubmit,
          sub: `para ${overlay.secret.envVar}`,
          t: ui.theme
        })
      });
      $[21] = cols;
      $[22] = onSecretSubmit;
      $[23] = overlay.secret.envVar;
      $[24] = overlay.secret.prompt;
      $[25] = ui.theme;
      $[26] = t1;
    } else {
      t1 = $[26];
    }
    return t1;
  }
  return null;
}
function _temp() {
  return patchOverlayState({
    confirm: null
  });
}
export function FloatingOverlays(t0) {
  const $ = _c(12);
  const {
    onModelSelect,
    onPickerSelect,
    pagerPageSize
  } = t0;
  const {
    gw
  } = useGateway();
  const overlay = useStore($overlayState);
  const ui = useStore($uiState);
  const hasAny = overlay.modelPicker || overlay.pager || overlay.picker || overlay.skillsHub;
  if (!hasAny) {
    return null;
  }
  const overlayBg = ui.theme.color.composerSurface;
  let t1;
  if ($[0] !== gw || $[1] !== onModelSelect || $[2] !== onPickerSelect || $[3] !== overlay.modelPicker || $[4] !== overlay.pager || $[5] !== overlay.picker || $[6] !== overlay.skillsHub || $[7] !== overlayBg || $[8] !== pagerPageSize || $[9] !== ui.sid || $[10] !== ui.theme) {
    t1 = _jsxs(Box, {
      alignItems: "flex-start",
      backgroundColor: overlayBg,
      bottom: "100%",
      flexDirection: "column",
      left: 0,
      opaque: true,
      position: "absolute",
      right: 0,
      children: [overlay.picker && _jsx(Box, {
        backgroundColor: overlayBg,
        flexDirection: "column",
        paddingX: 1,
        paddingY: 1,
        width: "100%",
        children: _jsx(SessionPicker, {
          gw,
          onCancel: _temp2,
          onSelect: onPickerSelect,
          t: ui.theme
        })
      }), overlay.modelPicker && _jsx(FloatBox, {
        backgroundColor: overlayBg,
        color: ui.theme.color.composerBorder,
        children: _jsx(ModelPicker, {
          gw,
          onCancel: _temp3,
          onSelect: onModelSelect,
          sessionId: ui.sid,
          t: ui.theme
        })
      }), overlay.skillsHub && _jsx(FloatBox, {
        backgroundColor: overlayBg,
        color: ui.theme.color.composerBorder,
        children: _jsx(SkillsHub, {
          gw,
          onClose: _temp4,
          t: ui.theme
        })
      }), overlay.pager && _jsx(FloatBox, {
        backgroundColor: overlayBg,
        color: ui.theme.color.composerBorder,
        children: _jsxs(Box, {
          flexDirection: "column",
          paddingX: 1,
          paddingY: 1,
          children: [overlay.pager.title && _jsx(Box, {
            justifyContent: "center",
            marginBottom: 1,
            children: _jsx(Text, {
              bold: true,
              color: ui.theme.color.title,
              children: overlay.pager.title
            })
          }), overlay.pager.lines.slice(overlay.pager.offset, overlay.pager.offset + pagerPageSize).map(_temp5), _jsx(Box, {
            marginTop: 1,
            children: _jsx(OverlayHint, {
              t: ui.theme,
              children: overlay.pager.offset + pagerPageSize < overlay.pager.lines.length ? `↑↓/jk linha · Enter/Espaço/PgDn página · b/PgUp voltar · g/G topo/fim · Esc/q fechar (${Math.min(overlay.pager.offset + pagerPageSize, overlay.pager.lines.length)}/${overlay.pager.lines.length})` : `fim · ↑↓/jk · b/PgUp voltar · g topo · Esc/q fechar (${overlay.pager.lines.length} linhas)`
            })
          })]
        })
      })]
    });
    $[0] = gw;
    $[1] = onModelSelect;
    $[2] = onPickerSelect;
    $[3] = overlay.modelPicker;
    $[4] = overlay.pager;
    $[5] = overlay.picker;
    $[6] = overlay.skillsHub;
    $[7] = overlayBg;
    $[8] = pagerPageSize;
    $[9] = ui.sid;
    $[10] = ui.theme;
    $[11] = t1;
  } else {
    t1 = $[11];
  }
  return t1;
}
function _temp5(line, i) {
  return _jsx(Text, {
    children: line
  }, i);
}
function _temp4() {
  return patchOverlayState({
    skillsHub: false
  });
}
function _temp3() {
  return patchOverlayState({
    modelPicker: false
  });
}
function _temp2() {
  return patchOverlayState({
    picker: false
  });
}