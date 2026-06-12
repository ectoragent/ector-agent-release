import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Ansi, Box, NoSelect, Text } from '@ector/ink';
import { memo } from 'react';
import { LONG_MSG } from '../../config/limits.js';
import { sectionMode } from '../../domain/details.js';
import { backgroundMessageParts, userDisplay } from '../../domain/messages.js';
import { ROLE } from '../../domain/roles.js';
import { TOOL_BLOCK_MARGIN_LEFT, TRANSCRIPT_BUBBLE_PAD_X, TRANSCRIPT_BUBBLE_PAD_Y, transcriptContentCols } from '../../domain/transcriptLayout.js';
import { formatInteractionFooter } from '../../domain/turnTiming.js';
import { boundedHistoryRenderText, boundedLiveRenderText, compactPreview, hasAnsi, isPasteBackedText, stripAnsi } from '../../lib/text.js';
import { isHeavyTranscriptMessage } from '../../lib/virtualHeights.js';
import { Md } from '../Markdown/index.js';
import { StreamingMd } from '../StreamingMarkdown/index.js';
import { ToolTrail } from '../Thinking/index.js';
import { TodoPanel } from '../TodoPanel/index.js';
import { TranscriptCard } from '../TranscriptCard/index.js';
export const MessageLine = memo(function MessageLine({
  cols,
  compact,
  detailsMode = 'collapsed',
  detailsModeCommandOverride = false,
  inlineDetails = true,
  isStreaming = false,
  limitHistoryRender = false,
  msg,
  sections,
  t,
  toolTrailLive,
  tools = []
}) {
  if (msg.kind === 'turnTiming') {
    const label = msg.turnTiming != null ? formatInteractionFooter(msg.turnTiming) : msg.text.trim();
    if (!label) {
      return null;
    }
    return _jsx(Box, {
      flexDirection: "row",
      justifyContent: "flex-start",
      width: transcriptContentCols(cols),
      children: _jsx(Text, {
        color: t.color.dim,
        dimColor: true,
        children: label
      })
    });
  }
  const boundedRender = limitHistoryRender || isHeavyTranscriptMessage(msg.text, cols);
  const trailExtras = toolTrailLive ?? {};
  const liveTools = trailExtras.tools ?? tools;
  const liveTrail = trailExtras.trail ?? msg.tools ?? [];
  // Per-section overrides win over the global mode, so resolve each section
  // we might consume here once and gate visibility on the *content-bearing*
  // sections only — never on the global mode.  A `trail` message feeds Tool
  // calls + Activity; an assistant message with thinking/tools metadata
  // feeds Thinking + Tool calls.  Gating on every section would let a
  // default-expanded section keep an empty wrapper alive when only another
  // section is hidden — exactly the empty-Box bug Copilot caught.
  const thinkingMode = sectionMode('thinking', detailsMode, sections, detailsModeCommandOverride);
  const toolsMode = sectionMode('tools', detailsMode, sections, detailsModeCommandOverride);
  const activityMode = sectionMode('activity', detailsMode, sections, detailsModeCommandOverride);
  const thinking = msg.thinking?.trim() ?? '';
  const trailPayload = Boolean((msg.tools?.length ?? 0) || liveTools.length || liveTrail.length || thinking || trailExtras.reasoningActive || trailExtras.reasoningStreaming);
  if (msg.kind === 'trail' && !msg.todos?.length && !trailPayload && !msg.text?.trim()) {
    return null;
  }
  if (msg.kind === 'trail' && msg.todos?.length) {
    return _jsx(TranscriptCard, {
      t: t,
      tone: "userPlain",
      children: _jsx(TodoPanel, {
        defaultCollapsed: msg.todoCollapsedByDefault,
        incomplete: msg.todoIncomplete,
        t: t,
        todos: msg.todos
      })
    });
  }
  if (msg.kind === 'trail' && (msg.tools?.length || liveTools.length || liveTrail.length || thinking || trailExtras.reasoningActive || trailExtras.reasoningStreaming)) {
    const trailPanelsOpen = thinkingMode !== 'hidden' || toolsMode !== 'hidden' || activityMode !== 'hidden';
    if (!trailPanelsOpen) {
      return null;
    }
    const shelfForTools = Boolean((msg.tools?.length ?? 0) || liveTools.length || liveTrail.length);
    const shelfForThinking = (Boolean(thinking) || Boolean(trailExtras.reasoningActive) || Boolean(trailExtras.reasoningStreaming)) && thinkingMode !== 'hidden';
    if (!shelfForTools && !shelfForThinking) {
      return null;
    }
    return _jsx(TranscriptCard, {
      t: t,
      tone: "userPlain",
      children: _jsx(Box, {
        flexDirection: "column",
        paddingLeft: TOOL_BLOCK_MARGIN_LEFT,
        children: _jsx(ToolTrail, {
          activity: trailExtras.activity,
          busy: trailExtras.busy,
          commandOverride: detailsModeCommandOverride,
          detailsMode: detailsMode,
          outcome: trailExtras.outcome,
          reasoning: trailExtras.reasoning ?? thinking,
          reasoningActive: trailExtras.reasoningActive,
          reasoningStreaming: trailExtras.reasoningStreaming,
          reasoningTokens: msg.thinkingTokens,
          sections: sections,
          subagents: trailExtras.subagents,
          t: t,
          tools: liveTools,
          toolTokens: trailExtras.toolTokens ?? msg.toolTokens,
          trail: liveTrail
        })
      })
    });
  }
  if (msg.role === 'tool') {
    const maxChars = Math.max(24, transcriptContentCols(cols) - 14);
    const stripped = hasAnsi(msg.text) ? stripAnsi(msg.text) : msg.text;
    const preview = compactPreview(stripped, maxChars) || '(resultado vazio)';
    return _jsx(TranscriptCard, {
      t: t,
      tone: "userPlain",
      children: hasAnsi(msg.text) ? _jsx(Text, {
        wrap: "truncate-end",
        children: _jsx(Ansi, {
          children: msg.text
        })
      }) : _jsx(Text, {
        color: t.color.dim,
        wrap: "truncate-end",
        children: preview
      })
    });
  }
  if (msg.role === 'system' && msg.kind !== 'slash' && msg.kind !== 'trail' && !msg.text?.trim()) {
    return null;
  }
  const roleStyle = ROLE[msg.role](t);
  const {
    anchor,
    body,
    boldBody,
    prefix
  } = roleStyle;
  const speakerChrome = msg.role === 'user' || msg.role === 'assistant';
  // UX: layout simples, tudo à esquerda e com largura cheia.
  // Diferencia user/assistant via borda + header no topo do balão.
  const contentCols = transcriptContentCols(cols);
  const bubbleTone = msg.role === 'user' || msg.role === 'assistant' ? 'full' : 'userPlain';
  const hasLiveThinking = Boolean(thinking) || Boolean(trailExtras.reasoningActive) || Boolean(trailExtras.reasoningStreaming);
  const hasLiveTools = Boolean(msg.tools?.length || liveTools.length || liveTrail.length);
  const inlineDetailVisible = inlineDetails ? hasLiveTools && toolsMode !== 'hidden' || hasLiveThinking && thinkingMode !== 'hidden' : false;
  const content = (() => {
    if (msg.kind === 'slash') {
      // Saídas do slash runner (Rich) trazem ANSI — sem <Ansi> o layout/bg fica errado no Ink.
      if (hasAnsi(msg.text)) {
        return _jsx(Ansi, {
          children: msg.text
        });
      }
      return _jsx(Text, {
        color: t.color.dim,
        children: msg.text
      });
    }
    if (msg.role !== 'user' && hasAnsi(msg.text)) {
      return _jsx(Ansi, {
        children: msg.text
      });
    }
    if (msg.kind === 'background') {
      const mdWidth = Math.max(24, contentCols - 4);
      const mdText = boundedRender ? boundedHistoryRenderText(msg.text) : msg.text;
      return _jsx(Md, {
        compact: compact,
        t: t,
        text: mdText,
        width: mdWidth
      });
    }
    const legacyBg = msg.role === 'system' ? backgroundMessageParts(msg.text) : null;
    if (legacyBg) {
      const mdWidth = Math.max(24, contentCols - 4);
      const mdText = boundedRender ? boundedHistoryRenderText(legacyBg.body) : legacyBg.body;
      return _jsx(Md, {
        compact: compact,
        t: t,
        text: mdText,
        width: mdWidth
      });
    }
    if (msg.role === 'assistant') {
      return isStreaming ?
      // Incremental markdown: split at the last stable block boundary so
      // only the in-flight tail re-tokenizes per delta. See
      // streamingMarkdown.tsx for the cost model.
      _jsx(StreamingMd, {
        compact: compact,
        t: t,
        text: boundedLiveRenderText(msg.text),
        width: Math.max(24, contentCols - 4)
      }) : _jsx(Md, {
        compact: compact,
        t: t,
        text: boundedRender ? boundedHistoryRenderText(msg.text) : msg.text,
        width: Math.max(24, contentCols - 4)
      });
    }
    const sysColor = msg.role === 'system' && !body ? t.color.dim : body;
    const bodyProps = sysColor ? {
      bold: boldBody,
      color: sysColor
    } : {
      bold: boldBody
    };
    if (msg.role === 'user' && msg.text.length > LONG_MSG && isPasteBackedText(msg.text)) {
      const [head, ...rest] = userDisplay(msg.text).split('[long message]');
      return _jsxs(Text, {
        bold: boldBody,
        color: body,
        children: [head, _jsx(Text, {
          color: t.color.dim,
          dimColor: true,
          children: "[long message]"
        }), rest.join('')]
      });
    }
    return _jsx(Text, {
      ...bodyProps,
      children: msg.text
    });
  })();
  return _jsx(Box, {
    flexDirection: "row",
    justifyContent: "flex-start",
    width: contentCols,
    children: _jsx(Box, {
      flexGrow: 1,
      width: contentCols,
      children: _jsx(TranscriptCard, {
        paddingX: speakerChrome ? TRANSCRIPT_BUBBLE_PAD_X : 2,
        paddingY: speakerChrome ? TRANSCRIPT_BUBBLE_PAD_Y : 0,
        rounded: speakerChrome,
        t: t,
        tone: bubbleTone,
        variant: msg.role === 'assistant' ? 'assistant' : msg.role === 'user' ? 'user' : 'neutral',
        children: _jsx(Box, {
          flexDirection: "column",
          children: [inlineDetailVisible ? _jsx(Box, {
            flexDirection: "column",
            marginBottom: speakerChrome ? 1 : 0,
            paddingLeft: TOOL_BLOCK_MARGIN_LEFT,
            children: _jsx(ToolTrail, {
              activity: trailExtras.activity,
              busy: trailExtras.busy,
              commandOverride: detailsModeCommandOverride,
              detailsMode: detailsMode,
              outcome: trailExtras.outcome,
              reasoning: trailExtras.reasoning ?? thinking,
              reasoningActive: trailExtras.reasoningActive,
              reasoningStreaming: trailExtras.reasoningStreaming,
              reasoningTokens: msg.thinkingTokens,
              sections: sections,
              subagents: trailExtras.subagents,
              t: t,
              tools: liveTools,
              toolTokens: trailExtras.toolTokens ?? msg.toolTokens,
              trail: liveTrail.length ? liveTrail : msg.tools
            })
          }, "msg-shelf") : null, speakerChrome ? _jsx(Box, {
            flexDirection: "column",
            flexShrink: 0,
            minWidth: 0,
            children: content
          }, "msg-sp") : _jsx(Box, {
            flexDirection: "row",
            flexShrink: 0,
            children: [_jsx(NoSelect, {
              flexShrink: 0,
              fromLeftEdge: true,
              width: 3,
              children: _jsxs(Text, {
                bold: msg.role === 'user',
                color: prefix,
                children: [anchor, ' ']
              })
            }, "nsp-pre"), _jsx(Box, {
              flexGrow: 1,
              minWidth: 12,
              width: Math.max(20, contentCols - 5),
              children: content
            }, "nsp-body")]
          }, "msg-nsp")].filter(Boolean)
        })
      })
    })
  });
});