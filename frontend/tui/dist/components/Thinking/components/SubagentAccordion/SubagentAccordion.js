import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx } from "react/jsx-runtime";
import { Box } from '@ector/ink';
import { useEffect, useState } from 'react';
import { fmtCost, fmtTokens } from '../../../../lib/subagentTree.js';
import { compactPreview, isToolTrailResultLine, parseToolTrailResultLine, splitToolDuration, toolStepDisplay } from '../../../../lib/text.js';
import { heatColor } from '../../lib/heatColor.js';
import { fmtElapsed } from '../../lib/treeLayout.js';
import { Chevron } from '../Chevron/index.js';
import { Thinking } from '../ThinkingPanel/index.js';
import { TreeNode } from '../TreeNode/index.js';
import { TreeTextRow } from '../TreeTextRow/index.js';
import { WorkStepRow } from '../WorkStepRow/index.js';
import { WorkStepsPanel } from '../WorkStepsPanel/index.js';
export function SubagentAccordion(t0) {
  const $ = _c(47);
  const {
    branch,
    expanded,
    node,
    peak,
    rails: t1,
    t
  } = t0;
  const rails = t1 === undefined ? [] : t1;
  const [open, setOpen] = useState(expanded);
  const [deep, setDeep] = useState(expanded);
  const [openThinking, setOpenThinking] = useState(expanded);
  const [openTools, setOpenTools] = useState(expanded);
  const [openNotes, setOpenNotes] = useState(expanded);
  const [openKids, setOpenKids] = useState(expanded);
  let t2;
  if ($[0] === Symbol.for("react.memo_cache_sentinel")) {
    t2 = {};
    $[0] = t2;
  } else {
    t2 = $[0];
  }
  const [expandedToolRows, setExpandedToolRows] = useState(t2);
  let t3;
  let t4;
  if ($[1] !== expanded) {
    t3 = () => {
      if (!expanded) {
        return;
      }
      setOpen(true);
      setDeep(true);
      setOpenThinking(true);
      setOpenTools(true);
      setOpenNotes(true);
      setOpenKids(true);
    };
    t4 = [expanded];
    $[1] = expanded;
    $[2] = t3;
    $[3] = t4;
  } else {
    t3 = $[2];
    t4 = $[3];
  }
  useEffect(t3, t4);
  let t5;
  if ($[4] === Symbol.for("react.memo_cache_sentinel")) {
    t5 = () => {
      setOpen(true);
      setDeep(true);
      setOpenThinking(true);
      setOpenTools(true);
      setOpenNotes(true);
      setOpenKids(true);
    };
    $[4] = t5;
  } else {
    t5 = $[4];
  }
  const expandAll = t5;
  const item = node.item;
  const children = node.children;
  const aggregate = node.aggregate;
  const statusTone = item.status === "failed" ? "error" : item.status === "interrupted" ? "warn" : "dim";
  const prefix = item.taskCount > 1 ? `[${item.index + 1}/${item.taskCount}] ` : "";
  const goalLabel = item.goal || `Subagente ${item.index + 1}`;
  let t6;
  if ($[5] !== goalLabel || $[6] !== open) {
    t6 = open ? goalLabel : compactPreview(goalLabel, 60);
    $[5] = goalLabel;
    $[6] = open;
    $[7] = t6;
  } else {
    t6 = $[7];
  }
  const title = `${prefix}${t6}`;
  const summary = compactPreview((item.summary || "").replace(/\s+/g, " ").trim(), 72);
  const statusLabel = item.status === "queued" ? "na fila" : item.status === "running" ? "executando" : item.status === "completed" ? "conclu\xEDdo" : item.status === "failed" ? "falhou" : item.status === "interrupted" ? "Interrompido por voc\xEA" : String(item.status);
  let rollupBits;
  if ($[8] !== aggregate.activeCount || $[9] !== aggregate.costUsd || $[10] !== aggregate.descendantCount || $[11] !== aggregate.totalTools || $[12] !== children.length || $[13] !== item.costUsd || $[14] !== item.durationSeconds || $[15] !== item.filesRead?.length || $[16] !== item.filesWritten?.length || $[17] !== item.inputTokens || $[18] !== item.outputTokens || $[19] !== item.status || $[20] !== item.toolCount || $[21] !== statusLabel) {
    rollupBits = [statusLabel];
    if (item.durationSeconds) {
      const t7 = item.durationSeconds * 1000;
      let t8;
      if ($[23] !== t7) {
        t8 = fmtElapsed(t7);
        $[23] = t7;
        $[24] = t8;
      } else {
        t8 = $[24];
      }
      rollupBits.push(t8);
    }
    const localTools = item.toolCount ?? 0;
    const subtreeTools = aggregate.totalTools - localTools;
    if (localTools > 0) {
      rollupBits.push(`${localTools} ferramenta${localTools === 1 ? "" : "s"}`);
    }
    const localTokens = (item.inputTokens ?? 0) + (item.outputTokens ?? 0);
    if (localTokens > 0) {
      let t7;
      if ($[25] !== localTokens) {
        t7 = fmtTokens(localTokens);
        $[25] = localTokens;
        $[26] = t7;
      } else {
        t7 = $[26];
      }
      rollupBits.push(`${t7} tok`);
    }
    const localCost = item.costUsd ?? 0;
    if (localCost > 0) {
      let t7;
      if ($[27] !== localCost) {
        t7 = fmtCost(localCost);
        $[27] = localCost;
        $[28] = t7;
      } else {
        t7 = $[28];
      }
      rollupBits.push(t7);
    }
    const filesLocal = (item.filesWritten?.length ?? 0) + (item.filesRead?.length ?? 0);
    if (filesLocal > 0) {
      rollupBits.push(`⎘${filesLocal}`);
    }
    if (children.length > 0) {
      rollupBits.push(`${aggregate.descendantCount}↓`);
      if (subtreeTools > 0) {
        rollupBits.push(`+${subtreeTools}t subár`);
      }
      const subCost = aggregate.costUsd - localCost;
      if (subCost >= 0.01) {
        let t7;
        if ($[29] !== subCost) {
          t7 = fmtCost(subCost);
          $[29] = subCost;
          $[30] = t7;
        } else {
          t7 = $[30];
        }
        rollupBits.push(`+${t7} subár`);
      }
      if (aggregate.activeCount > 0 && item.status !== "running") {
        rollupBits.push(`⚡${aggregate.activeCount}`);
      }
    }
    $[8] = aggregate.activeCount;
    $[9] = aggregate.costUsd;
    $[10] = aggregate.descendantCount;
    $[11] = aggregate.totalTools;
    $[12] = children.length;
    $[13] = item.costUsd;
    $[14] = item.durationSeconds;
    $[15] = item.filesRead?.length;
    $[16] = item.filesWritten?.length;
    $[17] = item.inputTokens;
    $[18] = item.outputTokens;
    $[19] = item.status;
    $[20] = item.toolCount;
    $[21] = statusLabel;
    $[22] = rollupBits;
  } else {
    rollupBits = $[22];
  }
  const suffix = rollupBits.join(" \xB7 ");
  const thinkingText = item.thinking.join("\n");
  const hasThinking = Boolean(thinkingText);
  const hasTools = item.tools.length > 0;
  const noteRows = [...(summary ? [summary] : []), ...item.notes];
  const hasNotes = noteRows.length > 0;
  const noteColor = statusTone === "error" ? t.color.error : statusTone === "warn" ? t.color.warn : t.color.dim;
  const sections = [];
  if (hasThinking) {
    let t7;
    if ($[31] === Symbol.for("react.memo_cache_sentinel")) {
      t7 = shift => {
        if (shift) {
          expandAll();
        } else {
          setOpenThinking(_temp);
        }
      };
      $[31] = t7;
    } else {
      t7 = $[31];
    }
    sections.push({
      header: _jsx(Chevron, {
        count: item.thinking.length,
        onClick: t7,
        open: openThinking,
        t,
        title: "Pensando"
      }),
      key: "thinking",
      open: openThinking,
      render: childRails => _jsx(Thinking, {
        active: item.status === "running",
        branch: "last",
        mode: "full",
        rails: childRails,
        reasoning: thinkingText,
        streaming: item.status === "running",
        t
      })
    });
  }
  if (hasTools) {
    let t7;
    if ($[32] === Symbol.for("react.memo_cache_sentinel")) {
      t7 = shift_0 => {
        if (shift_0) {
          expandAll();
        } else {
          setOpenTools(_temp2);
        }
      };
      $[32] = t7;
    } else {
      t7 = $[32];
    }
    let t8;
    if ($[33] !== expandedToolRows || $[34] !== item.id || $[35] !== item.tools || $[36] !== t) {
      t8 = () => _jsx(Box, {
        flexDirection: "column",
        children: item.tools.map((line, index) => {
          const rowKey = `${item.id}-tool-${index}`;
          const mb = index < item.tools.length - 1 ? 1 : 0;
          const parsed = isToolTrailResultLine(line) ? parseToolTrailResultLine(line) : null;
          const {
            duration,
            label: callLabel
          } = parsed ? splitToolDuration(parsed.call) : {
            duration: "",
            label: line
          };
          const tech = parsed?.detail.trim() ?? "";
          const toolName = parsed?.toolName;
          const {
            headline: title_0,
            subline: technical
          } = parsed ? toolStepDisplay(toolName, callLabel, tech, parsed.detail) : {
            headline: line,
            subline: ""
          };
          const status = parsed ? parsed.mark === "\u2717" ? "error" : "ok" : "ok";
          return _jsx(WorkStepRow, {
            duration,
            expanded: !!expandedToolRows[rowKey],
            marginBottom: mb,
            onToggle: () => setExpandedToolRows(prev => ({
              ...prev,
              [rowKey]: !prev[rowKey]
            })),
            status,
            t,
            technical,
            title: title_0
          }, rowKey);
        })
      });
      $[33] = expandedToolRows;
      $[34] = item.id;
      $[35] = item.tools;
      $[36] = t;
      $[37] = t8;
    } else {
      t8 = $[37];
    }
    sections.push({
      header: _jsx(Chevron, {
        count: item.tools.length,
        onClick: t7,
        open: openTools,
        t,
        title: "Ferramentas"
      }),
      key: "tools",
      open: openTools,
      render: t8
    });
  }
  if (hasNotes) {
    let t7;
    if ($[38] === Symbol.for("react.memo_cache_sentinel")) {
      t7 = shift_1 => {
        if (shift_1) {
          expandAll();
        } else {
          setOpenNotes(_temp3);
        }
      };
      $[38] = t7;
    } else {
      t7 = $[38];
    }
    sections.push({
      header: _jsx(Chevron, {
        count: noteRows.length,
        onClick: t7,
        open: openNotes,
        t,
        title: "Progresso",
        tone: statusTone
      }),
      key: "notes",
      open: openNotes,
      render: childRails_0 => _jsx(Box, {
        flexDirection: "column",
        children: noteRows.map((line_0, index_0) => _jsx(TreeTextRow, {
          branch: index_0 === noteRows.length - 1 ? "last" : "mid",
          color: noteColor,
          content: line_0,
          dimColor: statusTone === "dim",
          rails: childRails_0,
          t
        }, `${item.id}-note-${index_0}`))
      })
    });
  }
  if (children.length > 0) {
    let t7;
    if ($[39] === Symbol.for("react.memo_cache_sentinel")) {
      t7 = shift_2 => {
        if (shift_2) {
          expandAll();
        } else {
          setOpenKids(_temp4);
        }
      };
      $[39] = t7;
    } else {
      t7 = $[39];
    }
    let t8;
    if ($[40] !== children || $[41] !== deep || $[42] !== expanded || $[43] !== peak || $[44] !== t) {
      t8 = childRails_1 => _jsx(Box, {
        flexDirection: "column",
        children: children.map((child, i) => _jsx(SubagentAccordion, {
          branch: i === children.length - 1 ? "last" : "mid",
          expanded: expanded || deep,
          node: child,
          peak,
          rails: childRails_1,
          t
        }, child.item.id))
      });
      $[40] = children;
      $[41] = deep;
      $[42] = expanded;
      $[43] = peak;
      $[44] = t;
      $[45] = t8;
    } else {
      t8 = $[45];
    }
    sections.push({
      header: _jsx(Chevron, {
        count: children.length,
        onClick: t7,
        open: openKids,
        suffix: `d${item.depth + 1} · ${aggregate.descendantCount} no total`,
        t,
        title: "Subagentes"
      }),
      key: "subagents",
      open: openKids,
      render: t8
    });
  }
  const stem = heatColor(node, peak, t);
  let t7;
  if ($[46] === Symbol.for("react.memo_cache_sentinel")) {
    t7 = shift_3 => {
      if (shift_3) {
        expandAll();
        return;
      }
      setOpen(v_3 => {
        if (!v_3) {
          setDeep(false);
        }
        return !v_3;
      });
    };
    $[46] = t7;
  } else {
    t7 = $[46];
  }
  return _jsx(TreeNode, {
    branch,
    children: childRails_2 => _jsx(Box, {
      flexDirection: "column",
      children: sections.map((section, index_1) => section.key === "tools" ? _jsx(WorkStepsPanel, {
        header: section.header,
        open: section.open,
        t,
        children: section.open ? section.render(childRails_2) : null
      }, `${item.id}-${section.key}`) : _jsx(TreeNode, {
        branch: index_1 === sections.length - 1 ? "last" : "mid",
        children: section.render,
        header: section.header,
        open: section.open,
        rails: childRails_2,
        t
      }, `${item.id}-${section.key}`))
    }),
    header: _jsx(Chevron, {
      onClick: t7,
      open,
      suffix,
      t,
      title,
      tone: statusTone
    }),
    open,
    rails,
    stemColor: stem,
    stemDim: stem == null,
    t
  });
}
function _temp4(v_2) {
  return !v_2;
}
function _temp3(v_1) {
  return !v_1;
}
function _temp2(v_0) {
  return !v_0;
}
function _temp(v) {
  return !v;
}