const ROOT_KEY = '__root__';
/**
 * Reconstruct the subagent spawn tree from a flat event-ordered list.
 *
 * Grouping is by `parentId`; a missing `parentId` (or one pointing at an
 * unknown subagent) is treated as a top-level spawn of the current turn.
 * Children within a parent are sorted by `depth` then `index` — same key
 * used in `turnController.upsertSubagent`, so render order matches spawn
 * order regardless of network reordering of gateway events.
 *
 * Older gateways omit `parentId`; every subagent is then a top-level node
 * and the tree renders flat — matching pre-observability behaviour.
 */
export function buildSubagentTree(items) {
  if (!items.length) {
    return [];
  }
  const byParent = new Map();
  const known = new Set();
  for (const item of items) {
    known.add(item.id);
  }
  for (const item of items) {
    const parentKey = item.parentId && known.has(item.parentId) ? item.parentId : ROOT_KEY;
    const bucket = byParent.get(parentKey) ?? [];
    bucket.push(item);
    byParent.set(parentKey, bucket);
  }
  for (const bucket of byParent.values()) {
    bucket.sort((a, b) => a.depth - b.depth || a.index - b.index);
  }
  const build = item => {
    const kids = byParent.get(item.id) ?? [];
    const children = kids.map(build);
    return {
      aggregate: aggregate(item, children),
      children,
      item
    };
  };
  return (byParent.get(ROOT_KEY) ?? []).map(build);
}
/**
 * Roll up counts for a node's whole subtree.  Kept pure so the live view
 * and the post-hoc replay can share the same renderer unchanged.
 *
 * `hotness` = tools per second across the subtree — a crude proxy for
 * "how much work is happening in this branch".  Used to colour tree rails
 * in the overlay / inline view so the eye spots the expensive branch.
 */
export function aggregate(item, children) {
  let totalTools = item.toolCount ?? 0;
  let totalDuration = item.durationSeconds ?? 0;
  let descendantCount = 0;
  let activeCount = isRunning(item) ? 1 : 0;
  let maxDepthFromHere = 0;
  let inputTokens = item.inputTokens ?? 0;
  let outputTokens = item.outputTokens ?? 0;
  let costUsd = item.costUsd ?? 0;
  let filesTouched = (item.filesRead?.length ?? 0) + (item.filesWritten?.length ?? 0);
  for (const child of children) {
    totalTools += child.aggregate.totalTools;
    totalDuration += child.aggregate.totalDuration;
    descendantCount += child.aggregate.descendantCount + 1;
    activeCount += child.aggregate.activeCount;
    maxDepthFromHere = Math.max(maxDepthFromHere, child.aggregate.maxDepthFromHere + 1);
    inputTokens += child.aggregate.inputTokens;
    outputTokens += child.aggregate.outputTokens;
    costUsd += child.aggregate.costUsd;
    filesTouched += child.aggregate.filesTouched;
  }
  const hotness = totalDuration > 0 ? totalTools / totalDuration : 0;
  return {
    activeCount,
    costUsd,
    descendantCount,
    filesTouched,
    hotness,
    inputTokens,
    maxDepthFromHere,
    outputTokens,
    totalDuration,
    totalTools
  };
}
/**
 * Count of subagents at each depth level, indexed by depth (0 = top level).
 * Drives the inline sparkline (`▁▃▇▅`) and the status-bar HUD.
 */
export function widthByDepth(tree) {
  const widths = [];
  const walk = (nodes, depth) => {
    if (!nodes.length) {
      return;
    }
    widths[depth] = (widths[depth] ?? 0) + nodes.length;
    for (const node of nodes) {
      walk(node.children, depth + 1);
    }
  };
  walk(tree, 0);
  return widths;
}
/**
 * Flat totals across the full tree — feeds the summary chip header.
 */
export function treeTotals(tree) {
  let totalTools = 0;
  let totalDuration = 0;
  let descendantCount = 0;
  let activeCount = 0;
  let maxDepthFromHere = 0;
  let inputTokens = 0;
  let outputTokens = 0;
  let costUsd = 0;
  let filesTouched = 0;
  for (const node of tree) {
    totalTools += node.aggregate.totalTools;
    totalDuration += node.aggregate.totalDuration;
    descendantCount += node.aggregate.descendantCount + 1;
    activeCount += node.aggregate.activeCount;
    maxDepthFromHere = Math.max(maxDepthFromHere, node.aggregate.maxDepthFromHere + 1);
    inputTokens += node.aggregate.inputTokens;
    outputTokens += node.aggregate.outputTokens;
    costUsd += node.aggregate.costUsd;
    filesTouched += node.aggregate.filesTouched;
  }
  const hotness = totalDuration > 0 ? totalTools / totalDuration : 0;
  return {
    activeCount,
    costUsd,
    descendantCount,
    filesTouched,
    hotness,
    inputTokens,
    maxDepthFromHere,
    outputTokens,
    totalDuration,
    totalTools
  };
}
/**
 * Flatten the tree into visit order — useful for keyboard navigation and
 * for "kill subtree" walks that fire one RPC per descendant.
 */
export function flattenTree(tree) {
  const out = [];
  const walk = nodes => {
    for (const node of nodes) {
      out.push(node);
      walk(node.children);
    }
  };
  walk(tree);
  return out;
}
/**
 * Collect every descendant's id for a given node (excluding the node itself).
 */
export function descendantIds(node) {
  const ids = [];
  const walk = children => {
    for (const child of children) {
      ids.push(child.item.id);
      walk(child.children);
    }
  };
  walk(node.children);
  return ids;
}
export function isRunning(item) {
  return item.status === 'running' || item.status === 'queued';
}
const SPARK_RAMP = ['▁', '▂', '▃', '▄', '▅', '▆', '▇', '█'];
/**
 * 8-step unicode bar sparkline from a positive-integer array.  Zeroes render
 * as spaces so a sparse tree doesn't read as equal activity at every depth.
 */
export function sparkline(values) {
  if (!values.length) {
    return '';
  }
  const max = Math.max(...values);
  if (max <= 0) {
    return ' '.repeat(values.length);
  }
  return values.map(v => {
    if (v <= 0) {
      return ' ';
    }
    const idx = Math.min(SPARK_RAMP.length - 1, Math.max(0, Math.ceil(v / max * (SPARK_RAMP.length - 1))));
    return SPARK_RAMP[idx];
  }).join('');
}
/**
 * Format totals into a compact one-line summary: `d2 · 7 agentes · 124 ferramentas · 2m 14s`
 */
export function formatSummary(totals) {
  const pieces = [`d${Math.max(0, totals.maxDepthFromHere)}`];
  pieces.push(`${totals.descendantCount} agente${totals.descendantCount === 1 ? '' : 's'}`);
  if (totals.totalTools > 0) {
    pieces.push(`${totals.totalTools} ferramenta${totals.totalTools === 1 ? '' : 's'}`);
  }
  if (totals.totalDuration > 0) {
    pieces.push(fmtDuration(totals.totalDuration));
  }
  const tokens = totals.inputTokens + totals.outputTokens;
  if (tokens > 0) {
    pieces.push(`${fmtTokens(tokens)} tok`);
  }
  if (totals.costUsd > 0) {
    pieces.push(fmtCost(totals.costUsd));
  }
  if (totals.activeCount > 0) {
    pieces.push(`⚡${totals.activeCount}`);
  }
  return pieces.join(' · ');
}
/** Compact dollar amount: `$0.02`, `$1.34`, `$12.4` — never > 5 chars beyond the `$`. */
export function fmtCost(usd) {
  if (!Number.isFinite(usd) || usd <= 0) {
    return '';
  }
  if (usd < 0.01) {
    return '<$0.01';
  }
  if (usd < 10) {
    return `$${usd.toFixed(2)}`;
  }
  return `$${usd.toFixed(1)}`;
}
/** Compact token count: `12k`, `1.2k`, `542`. */
export function fmtTokens(n) {
  if (!Number.isFinite(n) || n <= 0) {
    return '0';
  }
  if (n < 1000) {
    return String(Math.round(n));
  }
  if (n < 10_000) {
    return `${(n / 1000).toFixed(1)}k`;
  }
  return `${Math.round(n / 1000)}k`;
}
/**
 * `Ns` / `Nm` / `Nm Ss` formatter for seconds.  Shared with the agents
 * overlay so the timeline + list + summary all speak the same dialect.
 */
export function fmtDuration(seconds) {
  if (seconds < 60) {
    return `${Math.max(0, Math.round(seconds))}s`;
  }
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds - m * 60);
  return s === 0 ? `${m}m` : `${m}m ${s}s`;
}
/**
 * A subagent is top-level if it has no `parentId`, or its parent isn't in
 * the same snapshot (orphaned by a pruned mid-flight root).  Same rule
 * `buildSubagentTree` uses — keep call sites consistent across the live
 * view, disk label, and diff pane.
 */
export function topLevelSubagents(items) {
  const ids = new Set(items.map(s => s.id));
  return items.filter(s => !s.parentId || !ids.has(s.parentId));
}
/**
 * Normalize a node's hotness into a palette index 0..N-1 where N = buckets.
 * Higher hotness = "hotter" colour. Normalized against the tree's peak hotness
 * so a uniformly slow tree still shows gradient across its busiest branches.
 */
export function hotnessBucket(hotness, peakHotness, buckets) {
  if (!Number.isFinite(hotness) || hotness <= 0 || peakHotness <= 0 || buckets <= 1) {
    return 0;
  }
  const ratio = Math.min(1, hotness / peakHotness);
  return Math.min(buckets - 1, Math.max(0, Math.round(ratio * (buckets - 1))));
}
export function peakHotness(tree) {
  let peak = 0;
  const walk = nodes => {
    for (const node of nodes) {
      peak = Math.max(peak, node.aggregate.hotness);
      walk(node.children);
    }
  };
  walk(tree);
  return peak;
}