import { c as _c } from "react/compiler-runtime";
import { useEffect, useRef } from 'react';
import { LONG_RUN_CHARMS } from '../content/charms.js';
import { pick, toolTrailLabel } from '../lib/text.js';
import { turnController } from './turnController.js';
import { useTurnSelector } from './turnStore.js';
import { getUiState } from './uiStore.js';
const DELAY_MS = 8_000;
const INTERVAL_MS = 10_000;
const MAX_CHARMS_PER_TOOL = 2;
export function useLongRunToolCharms() {
  const $ = _c(4);
  const tools = useTurnSelector(_temp);
  let t0;
  if ($[0] === Symbol.for("react.memo_cache_sentinel")) {
    t0 = new Map();
    $[0] = t0;
  } else {
    t0 = $[0];
  }
  const slots = useRef(t0);
  let t1;
  let t2;
  if ($[1] !== tools) {
    t1 = () => {
      if (!getUiState().busy || !tools.length) {
        slots.current.clear();
        return;
      }
      const tick = () => {
        if (!getUiState().busy) {
          slots.current.clear();
          return;
        }
        const now = Date.now();
        const liveIds = new Set(tools.map(_temp2));
        for (const key of Array.from(slots.current.keys())) {
          if (!liveIds.has(key)) {
            slots.current.delete(key);
          }
        }
        for (const tool of tools) {
          if (!tool.startedAt || now - tool.startedAt < DELAY_MS) {
            continue;
          }
          const slot = slots.current.get(tool.id) ?? {
            count: 0,
            lastAt: 0
          };
          if (slot.count >= MAX_CHARMS_PER_TOOL || now - slot.lastAt < INTERVAL_MS) {
            continue;
          }
          slots.current.set(tool.id, {
            count: slot.count + 1,
            lastAt: now
          });
          turnController.pushActivity(`${pick(LONG_RUN_CHARMS)} (${toolTrailLabel(tool.name)} · ${Math.round((now - tool.startedAt) / 1000)}s)`);
        }
      };
      tick();
      const id = setInterval(tick, 1000);
      return () => clearInterval(id);
    };
    t2 = [tools];
    $[1] = tools;
    $[2] = t1;
    $[3] = t2;
  } else {
    t1 = $[2];
    t2 = $[3];
  }
  useEffect(t1, t2);
}
function _temp2(t) {
  return t.id;
}
function _temp(state) {
  return state.tools;
}