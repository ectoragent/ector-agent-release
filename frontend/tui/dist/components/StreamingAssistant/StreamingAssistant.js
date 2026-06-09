import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Box, NoSelect, Text } from '@ector/ink';
import { useStore } from '@nanostores/react';
import { Fragment, memo, useMemo } from 'react';
import { toggleTodoCollapsed, useTurnSelector } from '../../app/turnStore.js';
import { $uiState } from '../../app/uiStore.js';
import { STATUS } from '../../content/uiStatus.js';
import { sectionMode } from '../../domain/details.js';
import { appendToolShelfMessage } from '../../lib/liveProgress.js';
import { MessageLine } from '../MessageLine/index.js';
import { ChatLoadingRow } from '../Thinking/components/ChatLoadingRow/index.js';
import { Spinner } from '../Thinking/index.js';
import { liveToolTrailProps } from '../Thinking/lib/liveToolTrail.js';
import { TodoPanel } from '../TodoPanel/index.js';
import { TranscriptCard } from '../TranscriptCard/index.js';
const groupedSegments = segments => segments.reduce((acc, msg) => appendToolShelfMessage(acc, msg), []);
function useLiveToolTrailFeed() {
  const $ = _c(10);
  const activity = useTurnSelector(_temp);
  const outcome = useTurnSelector(_temp2);
  const reasoning = useTurnSelector(_temp3);
  const reasoningActive = useTurnSelector(_temp4);
  const reasoningStreaming = useTurnSelector(_temp5);
  const subagents = useTurnSelector(_temp6);
  const toolTokens = useTurnSelector(_temp7);
  const tools = useTurnSelector(_temp8);
  const turnTrail = useTurnSelector(_temp9);
  let t0;
  if ($[0] !== activity || $[1] !== outcome || $[2] !== reasoning || $[3] !== reasoningActive || $[4] !== reasoningStreaming || $[5] !== subagents || $[6] !== toolTokens || $[7] !== tools || $[8] !== turnTrail) {
    t0 = {
      activity,
      outcome,
      reasoning,
      reasoningActive,
      reasoningStreaming,
      subagents,
      toolTokens,
      tools,
      turnTrail
    };
    $[0] = activity;
    $[1] = outcome;
    $[2] = reasoning;
    $[3] = reasoningActive;
    $[4] = reasoningStreaming;
    $[5] = subagents;
    $[6] = toolTokens;
    $[7] = tools;
    $[8] = turnTrail;
    $[9] = t0;
  } else {
    t0 = $[9];
  }
  return t0;
}
function _temp9(state_7) {
  return state_7.turnTrail;
}
function _temp8(state_6) {
  return state_6.tools;
}
function _temp7(state_5) {
  return state_5.toolTokens;
}
function _temp6(state_4) {
  return state_4.subagents;
}
function _temp5(state_3) {
  return state_3.reasoningStreaming;
}
function _temp4(state_2) {
  return state_2.reasoningActive;
}
function _temp3(state_1) {
  return state_1.reasoning;
}
function _temp2(state_0) {
  return state_0.outcome;
}
function _temp(state) {
  return state.activity;
}
export const StreamingAssistant = memo(function StreamingAssistant(t0) {
  const $ = _c(30);
  const {
    cols,
    compact,
    detailsMode,
    detailsModeCommandOverride,
    inlineDetails: t1,
    progress,
    sections
  } = t0;
  const inlineDetails = t1 === undefined ? true : t1;
  const ui = useStore($uiState);
  const feed = useLiveToolTrailFeed();
  const streamSegments = useTurnSelector(_temp0);
  const streamPendingTools = useTurnSelector(_temp1);
  const streaming = useTurnSelector(_temp10);
  const activeTools = feed.tools;
  const reasoningActive = feed.reasoningActive;
  const reasoningStreaming = feed.reasoningStreaming;
  const showStreamingArea = Boolean(streaming);
  let t2;
  if ($[0] !== detailsMode || $[1] !== detailsModeCommandOverride || $[2] !== sections) {
    t2 = sectionMode("thinking", detailsMode, sections, detailsModeCommandOverride);
    $[0] = detailsMode;
    $[1] = detailsModeCommandOverride;
    $[2] = sections;
    $[3] = t2;
  } else {
    t2 = $[3];
  }
  const thinkingHidden = t2 === "hidden";
  let t3;
  if ($[4] !== reasoningActive || $[5] !== reasoningStreaming || $[6] !== streaming || $[7] !== thinkingHidden) {
    t3 = thinkingHidden && (reasoningActive || reasoningStreaming) && !String(streaming ?? "").trim();
    $[4] = reasoningActive;
    $[5] = reasoningStreaming;
    $[6] = streaming;
    $[7] = thinkingHidden;
    $[8] = t3;
  } else {
    t3 = $[8];
  }
  const showCompactThought = t3;
  const hasLiveTools = activeTools.length > 0 || streamPendingTools.length > 0 || feed.turnTrail.length > 0;
  const idle = !showStreamingArea && !streamSegments.length && !hasLiveTools && !reasoningActive && !reasoningStreaming;
  const showThinkingSpinner = showCompactThought;
  const showChatLoading = ui.busy && idle && !showThinkingSpinner;
  const loadingLabel = reasoningActive || reasoningStreaming ? "Pensando\u2026" : STATUS.interpolating;
  let t4;
  let t5;
  if ($[9] !== activeTools.length || $[10] !== cols || $[11] !== compact || $[12] !== detailsMode || $[13] !== detailsModeCommandOverride || $[14] !== feed || $[15] !== hasLiveTools || $[16] !== inlineDetails || $[17] !== loadingLabel || $[18] !== progress.showProgressArea || $[19] !== sections || $[20] !== showChatLoading || $[21] !== showStreamingArea || $[22] !== showThinkingSpinner || $[23] !== streamPendingTools || $[24] !== streamSegments || $[25] !== streaming || $[26] !== ui.busy || $[27] !== ui.theme) {
    t5 = Symbol.for("react.early_return_sentinel");
    bb0: {
      const toolTrail = liveToolTrailProps(feed, streamPendingTools, ui.busy);
      if (!progress.showProgressArea && !showStreamingArea && !activeTools.length && !showThinkingSpinner && !showChatLoading) {
        t5 = null;
        break bb0;
      }
      t4 = _jsx(Fragment, {
        children: [...groupedSegments(streamSegments).map((msg, i) => _jsx(MessageLine, {
          cols,
          compact,
          detailsMode,
          detailsModeCommandOverride,
          msg,
          sections,
          t: ui.theme
        }, `seg:${i}`)), !!activeTools.length && inlineDetails ? _jsx(MessageLine, {
          cols,
          compact,
          detailsMode,
          detailsModeCommandOverride,
          inlineDetails,
          msg: {
            kind: "trail",
            role: "system",
            text: ""
          },
          sections,
          t: ui.theme,
          toolTrailLive: toolTrail
        }, "sa-tools") : null, showStreamingArea ? _jsx(MessageLine, {
          cols,
          compact,
          detailsMode,
          detailsModeCommandOverride,
          inlineDetails,
          isStreaming: true,
          msg: {
            role: "assistant",
            text: streaming,
            ...(streamPendingTools.length && {
              tools: streamPendingTools
            })
          },
          sections,
          t: ui.theme,
          toolTrailLive: toolTrail
        }, "sa-stream") : null, !showStreamingArea && inlineDetails && hasLiveTools && !activeTools.length ? _jsx(MessageLine, {
          cols,
          compact,
          detailsMode,
          detailsModeCommandOverride,
          inlineDetails,
          msg: {
            kind: "trail",
            role: "system",
            text: "",
            tools: streamPendingTools
          },
          sections,
          t: ui.theme,
          toolTrailLive: toolTrail
        }, "sa-pend") : null, showChatLoading ? _jsx(ChatLoadingRow, {
          label: loadingLabel,
          t: ui.theme
        }, "sa-load") : null, showThinkingSpinner ? _jsx(TranscriptCard, {
          t: ui.theme,
          tone: "userPlain",
          children: _jsx(Box, {
            alignItems: "flex-start",
            columnGap: 1,
            flexDirection: "row",
            flexGrow: 1,
            children: [_jsx(NoSelect, {
              flexShrink: 0,
              fromLeftEdge: true,
              children: _jsx(Text, {
                color: ui.theme.color.border,
                dim: true,
                children: "\u258E"
              })
            }, "sa-rail"), _jsx(Box, {
              flexGrow: 1,
              children: _jsxs(Text, {
                color: ui.theme.color.dim,
                dim: true,
                wrap: "wrap-trim",
                children: [_jsx(Spinner, {
                  color: ui.theme.color.cyan,
                  variant: "think"
                }), " ", loadingLabel]
              })
            }, "sa-msg")]
          })
        }, "sa-compact") : null].filter(Boolean)
      });
    }
    $[9] = activeTools.length;
    $[10] = cols;
    $[11] = compact;
    $[12] = detailsMode;
    $[13] = detailsModeCommandOverride;
    $[14] = feed;
    $[15] = hasLiveTools;
    $[16] = inlineDetails;
    $[17] = loadingLabel;
    $[18] = progress.showProgressArea;
    $[19] = sections;
    $[20] = showChatLoading;
    $[21] = showStreamingArea;
    $[22] = showThinkingSpinner;
    $[23] = streamPendingTools;
    $[24] = streamSegments;
    $[25] = streaming;
    $[26] = ui.busy;
    $[27] = ui.theme;
    $[28] = t4;
    $[29] = t5;
  } else {
    t4 = $[28];
    t5 = $[29];
  }
  if (t5 !== Symbol.for("react.early_return_sentinel")) {
    return t5;
  }
  return t4;
});
export const LiveTodoPanel = memo(function LiveTodoPanel() {
  const $ = _c(4);
  const ui = useStore($uiState);
  const todos = useTurnSelector(_temp11);
  const collapsed = useTurnSelector(_temp12);
  let t0;
  if ($[0] !== collapsed || $[1] !== todos || $[2] !== ui.theme) {
    t0 = _jsx(TodoPanel, {
      collapsed,
      onToggle: toggleTodoCollapsed,
      t: ui.theme,
      todos
    });
    $[0] = collapsed;
    $[1] = todos;
    $[2] = ui.theme;
    $[3] = t0;
  } else {
    t0 = $[3];
  }
  return t0;
});
function _temp0(state) {
  return state.streamSegments;
}
function _temp1(state_0) {
  return state_0.streamPendingTools;
}
function _temp10(state_1) {
  return state_1.streaming;
}
function _temp11(state) {
  return state.todos;
}
function _temp12(state_0) {
  return state_0.todoCollapsed;
}