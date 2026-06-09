import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx } from "react/jsx-runtime";
import { Box, NoSelect, ScrollBox } from '@ector/ink';
import { useStore } from '@nanostores/react';
import { Fragment, memo, useMemo } from 'react';
import { $uiState } from '../../../../app/uiStore.js';
import { FULL_RENDER_TAIL_ITEMS } from '../../../../config/limits.js';
import { TRANSCRIPT_INNER_PAD_LEFT, TRANSCRIPT_INNER_PAD_RIGHT, TRANSCRIPT_INNER_PAD_TOP } from '../../../../domain/transcriptLayout.js';
import { StickyPromptTracker, TranscriptScrollbar } from '../../../AppChrome/index.js';
import { BackgroundTasksRow } from '../../../BackgroundTasks/index.js';
import { Banner, Panel } from '../../../Branding/index.js';
import { MessageLine } from '../../../MessageLine/index.js';
import { LiveTodoPanel, StreamingAssistant } from '../../../StreamingAssistant/index.js';
export const TranscriptPane = memo(function TranscriptPane(t0) {
  const $ = _c(14);
  const {
    actions,
    composer,
    progress,
    transcript
  } = t0;
  const ui = useStore($uiState);
  let t1;
  bb0: {
    const items = transcript.historyItems;
    for (let i = items.length - 1; i >= 0; i--) {
      if (items[i].role === "user") {
        t1 = i;
        break bb0;
      }
    }
    t1 = -1;
  }
  const lastUserIdx = t1;
  let t2;
  if ($[0] !== actions.setStickyPrompt || $[1] !== composer.cols || $[2] !== lastUserIdx || $[3] !== progress || $[4] !== transcript.historyItems || $[5] !== transcript.scrollRef || $[6] !== transcript.virtualHistory || $[7] !== transcript.virtualRows || $[8] !== ui.compact || $[9] !== ui.detailsMode || $[10] !== ui.detailsModeCommandOverride || $[11] !== ui.sections || $[12] !== ui.theme) {
    t2 = _jsx(Fragment, {
      children: [_jsx(ScrollBox, {
        flexDirection: "column",
        flexGrow: 1,
        flexShrink: 1,
        ref: transcript.scrollRef,
        stickyScroll: true,
        children: [_jsx(Box, {
          flexDirection: "column",
          paddingLeft: TRANSCRIPT_INNER_PAD_LEFT,
          paddingRight: TRANSCRIPT_INNER_PAD_RIGHT,
          paddingTop: TRANSCRIPT_INNER_PAD_TOP,
          children: [transcript.virtualHistory.topSpacer > 0 ? _jsx(Box, {
            height: transcript.virtualHistory.topSpacer
          }, "vtop") : null, ...transcript.virtualRows.slice(transcript.virtualHistory.start, transcript.virtualHistory.end).map(row => _jsx(Box, {
            flexDirection: "column",
            ref: transcript.virtualHistory.measureRef(row.key),
            children: [row.msg.kind === "intro" ? _jsx(Box, {
              flexDirection: "column",
              children: _jsx(Banner, {
                cols: composer.cols,
                t: ui.theme,
                version: row.msg.info?.version_name ?? row.msg.info?.version,
                versionCode: row.msg.info?.version_code
              })
            }, `${row.key}-body`) : row.msg.kind === "panel" && row.msg.panelData ? _jsx(Panel, {
              sections: row.msg.panelData.sections,
              t: ui.theme,
              title: row.msg.panelData.title
            }, `${row.key}-body`) : _jsx(MessageLine, {
              cols: composer.cols,
              compact: ui.compact,
              detailsMode: ui.detailsMode,
              detailsModeCommandOverride: ui.detailsModeCommandOverride,
              limitHistoryRender: row.index < transcript.historyItems.length - FULL_RENDER_TAIL_ITEMS,
              msg: row.msg,
              sections: ui.sections,
              t: ui.theme
            }, `${row.key}-body`), row.index === lastUserIdx ? _jsx(LiveTodoPanel, {}, `${row.key}-todo`) : null].filter(Boolean)
          }, row.key)), transcript.virtualHistory.bottomSpacer > 0 ? _jsx(Box, {
            height: transcript.virtualHistory.bottomSpacer
          }, "vbot") : null, _jsx(StreamingAssistant, {
            cols: composer.cols,
            compact: ui.compact,
            detailsMode: ui.detailsMode,
            detailsModeCommandOverride: ui.detailsModeCommandOverride,
            progress,
            sections: ui.sections
          }, "vstream"), _jsx(BackgroundTasksRow, {}, "bg-load")].filter(Boolean)
        }, "transcript-inner")]
      }, "transcript-scroll"), _jsx(NoSelect, {
        flexShrink: 0,
        marginLeft: 1,
        children: _jsx(TranscriptScrollbar, {
          scrollRef: transcript.scrollRef,
          t: ui.theme
        })
      }, "transcript-scrollbar-col"), _jsx(StickyPromptTracker, {
        messages: transcript.historyItems,
        offsets: transcript.virtualHistory.offsets,
        onChange: actions.setStickyPrompt,
        scrollRef: transcript.scrollRef
      }, "sticky-tracker")]
    });
    $[0] = actions.setStickyPrompt;
    $[1] = composer.cols;
    $[2] = lastUserIdx;
    $[3] = progress;
    $[4] = transcript.historyItems;
    $[5] = transcript.scrollRef;
    $[6] = transcript.virtualHistory;
    $[7] = transcript.virtualRows;
    $[8] = ui.compact;
    $[9] = ui.detailsMode;
    $[10] = ui.detailsModeCommandOverride;
    $[11] = ui.sections;
    $[12] = ui.theme;
    $[13] = t2;
  } else {
    t2 = $[13];
  }
  return t2;
});