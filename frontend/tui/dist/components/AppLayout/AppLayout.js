import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx } from "react/jsx-runtime";
import { AlternateScreen, Box } from '@ector/ink';
import { useStore } from '@nanostores/react';
import { Fragment, memo } from 'react';
import { $overlayState } from '../../app/overlayStore.js';
import { $uiState } from '../../app/uiStore.js';
import { INLINE_MODE, SHOW_FPS } from '../../config/env.js';
import { PerfPane } from '../../lib/perfPane.js';
import { PromptZone } from '../AppOverlays/index.js';
import { FpsOverlay } from '../FpsOverlay/index.js';
import { AgentsOverlayPane } from './components/AgentsOverlayPane/index.js';
import { ComposerPane } from './components/ComposerPane/index.js';
import { TranscriptPane } from './components/TranscriptPane/index.js';
export const AppLayout = memo(function AppLayout(t0) {
  const $ = _c(9);
  const {
    actions,
    composer,
    mouseTracking,
    progress,
    status,
    transcript
  } = t0;
  const ui = useStore($uiState);
  const overlay = useStore($overlayState);
  const Shell = INLINE_MODE ? Fragment : AlternateScreen;
  let t1;
  if ($[0] !== actions || $[1] !== composer || $[2] !== mouseTracking || $[3] !== overlay.agents || $[4] !== progress || $[5] !== status || $[6] !== transcript || $[7] !== ui.theme.color.statusBg) {
    const shellProps = INLINE_MODE ? {} : {
      mouseTracking
    };
    t1 = _jsx(Shell, {
      ...shellProps,
      children: _jsx(Box, {
        backgroundColor: ui.theme.color.statusBg,
        flexDirection: "column",
        flexGrow: 1,
        children: [_jsx(Box, {
          flexDirection: "row",
          flexGrow: 1,
          children: overlay.agents ? _jsx(PerfPane, {
            id: "agents",
            children: _jsx(AgentsOverlayPane, {})
          }) : _jsx(PerfPane, {
            id: "transcript",
            children: _jsx(TranscriptPane, {
              actions,
              composer,
              progress,
              transcript
            })
          })
        }, "main-row"), !overlay.agents ? _jsx(Fragment, {
          children: [_jsx(PerfPane, {
            id: "prompt",
            children: _jsx(PromptZone, {
              cols: composer.cols,
              onApprovalChoice: actions.answerApproval,
              onSecretSubmit: actions.answerSecret,
              onSudoSubmit: actions.answerSudo,
              onWiserAnswer: actions.answerWiser
            })
          }, "prompt"), _jsx(PerfPane, {
            id: "composer",
            children: _jsx(ComposerPane, {
              actions,
              composer,
              status
            })
          }, "composer"), SHOW_FPS ? _jsx(Box, {
            flexShrink: 0,
            justifyContent: "flex-end",
            paddingRight: 1,
            children: _jsx(FpsOverlay, {})
          }, "fps") : null].filter(Boolean)
        }, "below-transcript") : null].filter(Boolean)
      })
    });
    $[0] = actions;
    $[1] = composer;
    $[2] = mouseTracking;
    $[3] = overlay.agents;
    $[4] = progress;
    $[5] = status;
    $[6] = transcript;
    $[7] = ui.theme.color.statusBg;
    $[8] = t1;
  } else {
    t1 = $[8];
  }
  return t1;
});