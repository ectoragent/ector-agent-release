import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Box, Text } from '@ector/ink';
import { memo, useEffect, useMemo, useState } from 'react';
import { THINKING_COT_MAX } from '../../../../config/limits.js';
import { sectionMode } from '../../../../domain/details.js';
import { buildSubagentTree, formatSummary as formatSpawnSummary, peakHotness, sparkline, treeTotals, widthByDepth } from '../../../../lib/subagentTree.js';
import { estimateTokensRough, fmtK, formatToolCallParts, inferToolNameFromTechnical, isAnalyzingToolOutputLine, parseToolTrailResultLine, splitToolDuration, thinkingPreview, toolKindLabel, toolStepDisplay } from '../../../../lib/text.js';
import { fmtElapsed, nextTreeRails } from '../../lib/treeLayout.js';
import { Chevron } from '../Chevron/index.js';
import { Spinner } from '../Spinner/index.js';
import { SubagentAccordion } from '../SubagentAccordion/index.js';
import { Thinking } from '../ThinkingPanel/index.js';
import { TreeNode } from '../TreeNode/index.js';
import { TreeTextRow } from '../TreeTextRow/index.js';
import { WorkStepRow } from '../WorkStepRow/index.js';
import { WorkStepsPanel } from '../WorkStepsPanel/index.js';
export const ToolTrail = memo(function ToolTrail(t0) {
  const $ = _c(42);
  const {
    busy: t1,
    commandOverride: t2,
    detailsMode: t3,
    outcome: t4,
    reasoningActive: t5,
    reasoning: t6,
    reasoningTokens,
    reasoningStreaming: t7,
    sections,
    subagents: t8,
    t,
    tools: t9,
    toolTokens,
    trail: t10,
    activity: t11
  } = t0;
  const busy = t1 === undefined ? false : t1;
  const commandOverride = t2 === undefined ? false : t2;
  const detailsMode = t3 === undefined ? "collapsed" : t3;
  const outcome = t4 === undefined ? "" : t4;
  const reasoningActive = t5 === undefined ? false : t5;
  const reasoning = t6 === undefined ? "" : t6;
  const reasoningStreaming = t7 === undefined ? false : t7;
  let t12;
  if ($[0] !== t8) {
    t12 = t8 === undefined ? [] : t8;
    $[0] = t8;
    $[1] = t12;
  } else {
    t12 = $[1];
  }
  const subagents = t12;
  const tools = t9 === undefined ? [] : t9;
  const trail = t10 === undefined ? [] : t10;
  const activity = t11 === undefined ? [] : t11;
  let t13;
  if ($[2] !== commandOverride || $[3] !== detailsMode || $[4] !== sections) {
    t13 = sectionMode("thinking", detailsMode, sections, commandOverride);
    $[2] = commandOverride;
    $[3] = detailsMode;
    $[4] = sections;
    $[5] = t13;
  } else {
    t13 = $[5];
  }
  let t14;
  if ($[6] !== commandOverride || $[7] !== detailsMode || $[8] !== sections) {
    t14 = sectionMode("tools", detailsMode, sections, commandOverride);
    $[6] = commandOverride;
    $[7] = detailsMode;
    $[8] = sections;
    $[9] = t14;
  } else {
    t14 = $[9];
  }
  let t15;
  if ($[10] !== commandOverride || $[11] !== detailsMode || $[12] !== sections) {
    t15 = sectionMode("subagents", detailsMode, sections, commandOverride);
    $[10] = commandOverride;
    $[11] = detailsMode;
    $[12] = sections;
    $[13] = t15;
  } else {
    t15 = $[13];
  }
  let t16;
  if ($[14] !== commandOverride || $[15] !== detailsMode || $[16] !== sections) {
    t16 = sectionMode("activity", detailsMode, sections, commandOverride);
    $[14] = commandOverride;
    $[15] = detailsMode;
    $[16] = sections;
    $[17] = t16;
  } else {
    t16 = $[17];
  }
  let t17;
  if ($[18] !== t13 || $[19] !== t14 || $[20] !== t15 || $[21] !== t16) {
    t17 = {
      thinking: t13,
      tools: t14,
      subagents: t15,
      activity: t16
    };
    $[18] = t13;
    $[19] = t14;
    $[20] = t15;
    $[21] = t16;
    $[22] = t17;
  } else {
    t17 = $[22];
  }
  const visible = t17;
  const [now, setNow] = useState(_temp);
  const [openThinking, setOpenThinking] = useState(visible.thinking === "expanded");
  const [openTools, setOpenTools] = useState(visible.tools === "expanded");
  const [openSubagents, setOpenSubagents] = useState(visible.subagents === "expanded");
  const [deepSubagents, setDeepSubagents] = useState(visible.subagents === "expanded");
  const [openMeta, setOpenMeta] = useState(visible.activity === "expanded");
  let t18;
  if ($[23] === Symbol.for("react.memo_cache_sentinel")) {
    t18 = {};
    $[23] = t18;
  } else {
    t18 = $[23];
  }
  const [expandedRows, setExpandedRows] = useState(t18);
  useEffect(() => {
    if (!tools.length || visible.tools !== "expanded" && !openTools) {
      return;
    }
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, [openTools, tools.length, visible.tools]);
  let t19;
  if ($[24] !== visible.activity || $[25] !== visible.subagents || $[26] !== visible.thinking || $[27] !== visible.tools) {
    t19 = () => {
      setOpenThinking(visible.thinking === "expanded");
      setOpenTools(visible.tools === "expanded");
      setOpenSubagents(visible.subagents === "expanded");
      setOpenMeta(visible.activity === "expanded");
    };
    $[24] = visible.activity;
    $[25] = visible.subagents;
    $[26] = visible.thinking;
    $[27] = visible.tools;
    $[28] = t19;
  } else {
    t19 = $[28];
  }
  let t20;
  if ($[29] !== visible) {
    t20 = [visible];
    $[29] = visible;
    $[30] = t20;
  } else {
    t20 = $[30];
  }
  useEffect(t19, t20);
  const cot = thinkingPreview(reasoning, "full", THINKING_COT_MAX);
  let t21;
  if ($[31] !== subagents) {
    t21 = buildSubagentTree(subagents);
    $[31] = subagents;
    $[32] = t21;
  } else {
    t21 = $[32];
  }
  const spawnTree = t21;
  let t22;
  if ($[33] !== spawnTree) {
    t22 = peakHotness(spawnTree);
    $[33] = spawnTree;
    $[34] = t22;
  } else {
    t22 = $[34];
  }
  const spawnPeak = t22;
  const spawnTotals = treeTotals(spawnTree);
  const spawnWidths = widthByDepth(spawnTree);
  const spawnSpark = sparkline(spawnWidths);
  const spawnSummaryLabel = formatSpawnSummary(spawnTotals);
  if (!busy && !trail.length && !tools.length && !subagents.length && !activity.length && !cot && !reasoningActive && !outcome) {
    return null;
  }
  const groups = [];
  const meta = [];
  const pushDetail = row => (groups.at(-1)?.details ?? meta).push(row);
  for (const [i, line] of trail.entries()) {
    const parsed = parseToolTrailResultLine(line);
    if (parsed) {
      const {
        duration,
        label: callLabel
      } = splitToolDuration(parsed.call);
      const tech = parsed.detail.trim();
      const toolName = parsed.toolName ?? inferToolNameFromTechnical(tech) ?? inferToolNameFromTechnical(callLabel);
      const {
        headline: title,
        subline: technical
      } = toolStepDisplay(toolName, callLabel, tech, parsed.detail, parsed.mark === "\u2717");
      groups.push({
        color: parsed.mark === "\u2717" ? t.color.error : t.color.text,
        content: parsed.call,
        details: [],
        duration,
        key: `tr-${i}`,
        label: parsed.call,
        status: parsed.mark === "\u2717" ? "error" : "ok",
        technical,
        title,
        toolName
      });
      continue;
    }
    if (line.startsWith("drafting ") || line.startsWith("Rascunhando ")) {
      const rest = line.startsWith("Rascunhando ") ? line.slice(12) : line.slice(9);
      const toolName_0 = rest.replace(/…$/, "").trim();
      const {
        kind
      } = formatToolCallParts(toolName_0, "");
      groups.push({
        color: t.color.text,
        content: kind,
        details: [],
        key: `tr-${i}`,
        label: kind,
        status: "active",
        technical: "",
        title: "rascunhando...",
        toolName: toolName_0
      });
      continue;
    }
    if (isAnalyzingToolOutputLine(line)) {
      pushDetail({
        color: t.color.dim,
        dimColor: true,
        key: `tr-${i}`,
        content: _jsxs(Text, {
          color: t.color.dim,
          dim: true,
          wrap: "wrap-trim",
          children: [_jsx(Spinner, {
            color: t.color.cyan,
            variant: "think"
          }), " analisando sa\xEDda da ferramenta\u2026"]
        })
      });
      continue;
    }
    meta.push({
      color: t.color.dim,
      content: line,
      dimColor: true,
      key: `tr-${i}`
    });
  }
  for (const tool of tools) {
    const ctx = tool.context || "";
    const tech_0 = tool.technical || "";
    const {
      headline: title_0,
      subline: technical_0
    } = toolStepDisplay(tool.name, ctx, tech_0);
    groups.push({
      color: t.color.text,
      content: ctx || title_0,
      details: [],
      duration: tool.startedAt ? ` (${fmtElapsed(now - tool.startedAt)})` : "",
      key: tool.id,
      label: ctx || title_0,
      status: "active",
      technical: technical_0,
      title: title_0,
      toolName: tool.name
    });
  }
  for (const item of activity.slice(-4)) {
    const glyph = item.tone === "error" ? "\u2717" : item.tone === "warn" ? "!" : "\xB7";
    const color = item.tone === "error" ? t.color.error : item.tone === "warn" ? t.color.warn : t.color.dim;
    meta.push({
      color,
      content: `${glyph} ${item.text}`,
      dimColor: item.tone === "info",
      key: `a-${item.id}`
    });
  }
  const analyzingOutput = trail.some(isAnalyzingToolOutputLine);
  const hasTools = groups.length > 0 || tools.length > 0;
  const showToolsShelf = hasTools || busy && analyzingOutput;
  const hasSubagents = subagents.length > 0;
  const hasMeta = meta.length > 0;
  const hasThinking = !!cot || reasoningActive || reasoningStreaming;
  const thinkingLive = reasoningActive || reasoningStreaming;
  const tokenCount = reasoningTokens && reasoningTokens > 0 ? reasoningTokens : reasoning ? estimateTokensRough(reasoning) : 0;
  const toolTokenCount = toolTokens ?? 0;
  const totalTokenCount = tokenCount + toolTokenCount;
  const thinkingTokensLabel = tokenCount > 0 ? `~${fmtK(tokenCount)} tokens` : null;
  const toolTokensLabel = toolTokens !== undefined && toolTokens > 0 ? `~${fmtK(toolTokens)} tokens` : undefined;
  const totalTokensLabel = tokenCount > 0 && toolTokenCount > 0 ? `~${fmtK(totalTokenCount)} no total` : null;
  const delegateTitle = toolKindLabel("delegate_task");
  const toolsAllDone = tools.length === 0 && groups.length > 0 && groups.every(_temp2);
  const stepCountLabel = groups.length === 1 ? "1 passo" : `${groups.length} passos`;
  const toolsPanelSuffix = [groups.length > 0 ? stepCountLabel : undefined, tools.length > 0 ? "em andamento" : analyzingOutput ? "processando" : busy && groups.length > 0 ? "aguardando" : undefined, toolsAllDone ? "conclu\xEDdo" : undefined, toolTokensLabel].filter(Boolean).join(" \xB7 ");
  const delegateGroups = groups.filter(g_0 => g_0.toolName === "delegate_task" || splitToolDuration(g_0.label).label.startsWith(`${delegateTitle}(`) || splitToolDuration(g_0.label).label.startsWith(delegateTitle));
  const inlineDelegateKey = hasSubagents && delegateGroups.length === 1 ? delegateGroups[0].key : null;
  let t23;
  if ($[35] === Symbol.for("react.memo_cache_sentinel")) {
    t23 = key => setExpandedRows(prev => ({
      ...prev,
      [key]: !prev[key]
    }));
    $[35] = t23;
  } else {
    t23 = $[35];
  }
  const toggleToolRow = t23;
  const allHidden = visible.thinking === "hidden" && visible.tools === "hidden" && visible.subagents === "hidden" && visible.activity === "hidden";
  if (allHidden) {
    const alerts = activity.filter(_temp3).slice(-2);
    return alerts.length ? _jsx(Box, {
      flexDirection: "column",
      children: alerts.map(i_1 => _jsxs(Text, {
        color: i_1.tone === "error" ? t.color.error : t.color.warn,
        children: [i_1.tone === "error" ? "\u2717" : "!", " ", i_1.text]
      }, `ha-${i_1.id}`))
    }) : null;
  }
  const expandAll = () => {
    if (visible.thinking !== "hidden") {
      setOpenThinking(true);
    }
    if (visible.tools !== "hidden") {
      setOpenTools(true);
    }
    if (visible.subagents !== "hidden") {
      setOpenSubagents(true);
      setDeepSubagents(true);
    }
    if (visible.activity !== "hidden") {
      setOpenMeta(true);
    }
  };
  const metaTone = activity.some(_temp4) ? "error" : activity.some(_temp5) ? "warn" : "dim";
  let t24;
  if ($[36] !== deepSubagents || $[37] !== spawnPeak || $[38] !== spawnTree || $[39] !== t || $[40] !== visible.subagents) {
    t24 = rails => _jsx(Box, {
      flexDirection: "column",
      children: spawnTree.map((node, index) => _jsx(SubagentAccordion, {
        branch: index === spawnTree.length - 1 ? "last" : "mid",
        expanded: visible.subagents === "expanded" || deepSubagents,
        node,
        peak: spawnPeak,
        rails,
        t
      }, node.item.id))
    });
    $[36] = deepSubagents;
    $[37] = spawnPeak;
    $[38] = spawnTree;
    $[39] = t;
    $[40] = visible.subagents;
    $[41] = t24;
  } else {
    t24 = $[41];
  }
  const renderSubagentList = t24;
  const panels = [];
  if (hasThinking && visible.thinking !== "hidden") {
    panels.push({
      header: _jsx(Chevron, {
        boldHeading: thinkingLive,
        onClick: shift => {
          if (shift) {
            expandAll();
          } else {
            setOpenThinking(_temp6);
          }
        },
        open: openThinking,
        suffix: thinkingTokensLabel ?? undefined,
        t,
        title: "Pensando"
      }),
      key: "thinking",
      open: openThinking,
      render: rails_0 => _jsx(Thinking, {
        active: reasoningActive,
        branch: "last",
        mode: "full",
        rails: rails_0,
        reasoning: busy ? reasoning : cot,
        streaming: busy && reasoningStreaming,
        t
      })
    });
  }
  if (showToolsShelf && visible.tools !== "hidden") {
    panels.push({
      header: _jsx(Chevron, {
        boldHeading: tools.length > 0,
        onClick: shift_0 => {
          if (shift_0) {
            expandAll();
          } else {
            setOpenTools(_temp7);
          }
        },
        open: openTools,
        suffix: toolsPanelSuffix || undefined,
        t,
        title: "Ferramentas"
      }),
      key: "tools",
      open: openTools,
      render: rails_1 => _jsxs(Box, {
        flexDirection: "column",
        children: [busy && tools.length === 0 && groups.length === 0 && analyzingOutput ? _jsx(Box, {
          marginBottom: 1,
          children: _jsxs(Text, {
            color: t.color.dim,
            dim: true,
            wrap: "wrap-trim",
            children: [_jsx(Spinner, {
              color: t.color.cyan,
              variant: "think"
            }), " analisando sa\xEDda da ferramenta\u2026"]
          })
        }) : null, groups.map((group, index_0) => {
          const childRails = nextTreeRails(rails_1, index_0 === groups.length - 1 ? "last" : "mid");
          const hasInlineSubagents = inlineDelegateKey === group.key;
          const mb = index_0 < groups.length - 1 ? 1 : 0;
          const status = group.status ?? (group.color === t.color.error ? "error" : tools.some(tool_0 => tool_0.id === group.key) ? "active" : "ok");
          return _jsxs(Box, {
            flexDirection: "column",
            children: [_jsx(WorkStepRow, {
              details: group.details,
              duration: group.duration ?? "",
              expanded: !!expandedRows[group.key],
              marginBottom: hasInlineSubagents ? 0 : mb,
              onToggle: () => toggleToolRow(group.key),
              status,
              t,
              technical: group.technical,
              title: group.title
            }), hasInlineSubagents ? _jsx(Box, {
              marginBottom: mb,
              marginTop: 1,
              children: renderSubagentList(childRails)
            }, `${group.key}-sub`) : null]
          }, group.key);
        })]
      })
    });
  }
  if (hasSubagents && !inlineDelegateKey && visible.subagents !== "hidden") {
    const suffix = spawnSpark ? `${spawnSummaryLabel}  ${spawnSpark}  (/agents)` : `${spawnSummaryLabel}  (/agents)`;
    panels.push({
      header: _jsx(Chevron, {
        count: spawnTotals.descendantCount,
        onClick: shift_1 => {
          if (shift_1) {
            expandAll();
            setDeepSubagents(true);
          } else {
            setOpenSubagents(_temp8);
            setDeepSubagents(false);
          }
        },
        open: openSubagents,
        suffix,
        t,
        title: "\xC1rvore de subagentes"
      }),
      key: "subagents",
      open: openSubagents,
      render: renderSubagentList
    });
  }
  if (hasMeta && visible.activity !== "hidden") {
    panels.push({
      header: _jsx(Chevron, {
        count: meta.length,
        onClick: shift_2 => {
          if (shift_2) {
            expandAll();
          } else {
            setOpenMeta(_temp9);
          }
        },
        open: openMeta,
        t,
        title: "Atividade",
        tone: metaTone
      }),
      key: "meta",
      open: openMeta,
      render: rails_2 => _jsx(Box, {
        flexDirection: "column",
        children: meta.map((row_0, index_1) => _jsx(TreeTextRow, {
          branch: index_1 === meta.length - 1 ? "last" : "mid",
          color: row_0.color,
          content: row_0.content,
          dimColor: row_0.dimColor,
          rails: rails_2,
          t
        }, row_0.key))
      })
    });
  }
  if (!panels.length && !totalTokensLabel && !outcome) {
    return null;
  }
  const topCount = panels.length + (totalTokensLabel ? 1 : 0);
  return _jsx(Box, {
    flexDirection: "column",
    children: [...panels.map((panel, index_2) => panel.key === "tools" ? _jsx(WorkStepsPanel, {
      header: panel.header,
      open: panel.open,
      t,
      children: panel.open ? panel.render([]) : null
    }, panel.key) : _jsx(TreeNode, {
      branch: index_2 === topCount - 1 ? "last" : "mid",
      children: panel.render,
      header: panel.header,
      open: panel.open,
      t
    }, panel.key)), totalTokensLabel ? _jsx(TreeTextRow, {
      branch: "last",
      color: t.color.statusBarMeta,
      content: _jsx(Text, {
        color: t.color.statusBarMeta,
        dim: true,
        wrap: "wrap-trim",
        children: totalTokensLabel
      }),
      dimColor: true,
      t
    }, "trail-tokens") : null, outcome ? _jsx(Box, {
      marginTop: 1,
      children: _jsxs(Text, {
        color: t.color.dim,
        dim: true,
        children: ["\xB7 ", outcome]
      })
    }, "trail-out") : null].filter(Boolean)
  });
});
function _temp() {
  return Date.now();
}
function _temp2(g) {
  return g.status === "ok" || g.status === "error";
}
function _temp3(i_0) {
  return i_0.tone !== "info";
}
function _temp4(i_3) {
  return i_3.tone === "error";
}
function _temp5(i_2) {
  return i_2.tone === "warn";
}
function _temp6(v) {
  return !v;
}
function _temp7(v_0) {
  return !v_0;
}
function _temp8(v_1) {
  return !v_1;
}
function _temp9(v_2) {
  return !v_2;
}