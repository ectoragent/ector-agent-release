import { c as _c } from "react/compiler-runtime";
import { jsxs as _jsxs } from "react/jsx-runtime";
import { Text } from '@ector/ink';
import { useStore } from '@nanostores/react';
import { useMemo } from 'react';
import { $delegationState } from '../../../../app/delegationStore.js';
import { useTurnSelector } from '../../../../app/turnStore.js';
import { buildSubagentTree, treeTotals, widthByDepth } from '../../../../lib/subagentTree.js';
export function SpawnHud(t0) {
  const $ = _c(18);
  const {
    t
  } = t0;
  const delegation = useStore($delegationState);
  const subagents = useTurnSelector(_temp);
  let t1;
  if ($[0] !== subagents) {
    t1 = buildSubagentTree(subagents);
    $[0] = subagents;
    $[1] = t1;
  } else {
    t1 = $[1];
  }
  const tree = t1;
  let t2;
  if ($[2] !== tree) {
    t2 = treeTotals(tree);
    $[2] = tree;
    $[3] = t2;
  } else {
    t2 = $[3];
  }
  const totals = t2;
  if (!totals.descendantCount && !delegation.paused) {
    return null;
  }
  const maxDepth = delegation.maxSpawnDepth;
  const maxConc = delegation.maxConcurrentChildren;
  const depth = Math.max(0, totals.maxDepthFromHere);
  const active = totals.activeCount;
  let t3;
  if ($[4] !== tree) {
    t3 = widthByDepth(tree).reduce(_temp2, 0);
    $[4] = tree;
    $[5] = t3;
  } else {
    t3 = $[5];
  }
  const widestLevel = t3;
  const depthRatio = maxDepth ? depth / maxDepth : 0;
  const concRatio = maxConc ? widestLevel / maxConc : 0;
  const ratio = Math.max(depthRatio, concRatio);
  const color = delegation.paused || ratio >= 1 ? t.color.error : ratio >= 0.66 ? t.color.warn : t.color.dim;
  let pieces;
  if ($[6] !== active || $[7] !== delegation.paused || $[8] !== depth || $[9] !== maxConc || $[10] !== maxDepth || $[11] !== totals.descendantCount || $[12] !== widestLevel) {
    pieces = [];
    if (delegation.paused) {
      pieces.push("\u23F8 pausado");
    }
    if (totals.descendantCount > 0) {
      const depthLabel = maxDepth ? `${depth}/${maxDepth}` : `${depth}`;
      pieces.push(`d${depthLabel}`);
      if (active > 0) {
        const extra = Math.max(0, active - widestLevel);
        const widthLabel = maxConc ? `${widestLevel}/${maxConc}` : `${widestLevel}`;
        const suffix = extra > 0 ? `+${extra}` : "";
        pieces.push(`⚡${widthLabel}${suffix}`);
      }
    }
    $[6] = active;
    $[7] = delegation.paused;
    $[8] = depth;
    $[9] = maxConc;
    $[10] = maxDepth;
    $[11] = totals.descendantCount;
    $[12] = widestLevel;
    $[13] = pieces;
  } else {
    pieces = $[13];
  }
  const atCap = depthRatio >= 1 || concRatio >= 1;
  const t4 = atCap ? " \xB7 \u25B2 " : " \xB7 ";
  const t5 = pieces.join(" ");
  let t6;
  if ($[14] !== color || $[15] !== t4 || $[16] !== t5) {
    t6 = _jsxs(Text, {
      color,
      children: [t4, t5]
    });
    $[14] = color;
    $[15] = t4;
    $[16] = t5;
    $[17] = t6;
  } else {
    t6 = $[17];
  }
  return t6;
}
function _temp2(a, b) {
  return Math.max(a, b);
}
function _temp(state) {
  return state.subagents;
}