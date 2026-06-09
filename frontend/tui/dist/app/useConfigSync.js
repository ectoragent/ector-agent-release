import { c as _c } from "react/compiler-runtime";
import { useEffect, useRef } from 'react';
import { resolveDetailsMode, resolveSections } from '../domain/details.js';
import { asRpcResult } from '../lib/rpc.js';
import { turnController } from './turnController.js';
import { patchUiState } from './uiStore.js';
const STATUSBAR_ALIAS = {
  bottom: 'bottom',
  off: 'off',
  on: 'top',
  top: 'top'
};
export const normalizeStatusBar = raw => raw === false ? 'off' : typeof raw === 'string' ? STATUSBAR_ALIAS[raw.trim().toLowerCase()] ?? 'top' : 'top';
const MTIME_POLL_MS = 5000;
const quietRpc = async (gw, method, params = {}) => {
  try {
    return asRpcResult(await gw.request(method, params));
  } catch {
    return null;
  }
};
export const applyDisplay = (cfg, setBell) => {
  const d = cfg?.config?.display ?? {};
  setBell(!!d.bell_on_complete);
  patchUiState({
    compact: !!d.tui_compact,
    detailsMode: resolveDetailsMode(d),
    detailsModeCommandOverride: false,
    inlineDiffs: d.inline_diffs !== false,
    mouseTracking: d.tui_mouse !== false,
    sections: resolveSections(d.sections),
    showCost: !!d.show_cost,
    showReasoning: !!d.show_reasoning,
    statusBar: normalizeStatusBar(d.tui_statusbar),
    streaming: d.streaming !== false
  });
};
export function useConfigSync(t0) {
  const $ = _c(11);
  const {
    gw,
    setBellOnComplete,
    setVoiceEnabled,
    sid
  } = t0;
  const mtimeRef = useRef(0);
  let t1;
  let t2;
  if ($[0] !== gw || $[1] !== setBellOnComplete || $[2] !== setVoiceEnabled || $[3] !== sid) {
    t1 = () => {
      if (!sid) {
        return;
      }
      quietRpc(gw, "voice.toggle", {
        action: "status"
      }).then(r => setVoiceEnabled(!!r?.enabled));
      quietRpc(gw, "config.get", {
        key: "mtime"
      }).then(r_0 => {
        mtimeRef.current = Number(r_0?.mtime ?? 0);
      });
      quietRpc(gw, "config.get", {
        key: "full"
      }).then(r_1 => applyDisplay(r_1, setBellOnComplete));
    };
    t2 = [gw, setBellOnComplete, setVoiceEnabled, sid];
    $[0] = gw;
    $[1] = setBellOnComplete;
    $[2] = setVoiceEnabled;
    $[3] = sid;
    $[4] = t1;
    $[5] = t2;
  } else {
    t1 = $[4];
    t2 = $[5];
  }
  useEffect(t1, t2);
  let t3;
  let t4;
  if ($[6] !== gw || $[7] !== setBellOnComplete || $[8] !== sid) {
    t3 = () => {
      if (!sid) {
        return;
      }
      const id = setInterval(() => {
        quietRpc(gw, "config.get", {
          key: "mtime"
        }).then(r_2 => {
          const next = Number(r_2?.mtime ?? 0);
          if (!mtimeRef.current) {
            if (next) {
              mtimeRef.current = next;
            }
            return;
          }
          if (!next || next === mtimeRef.current) {
            return;
          }
          mtimeRef.current = next;
          quietRpc(gw, "reload.mcp", {
            session_id: sid
          }).then(_temp);
          quietRpc(gw, "config.get", {
            key: "full"
          }).then(r_4 => applyDisplay(r_4, setBellOnComplete));
        });
      }, MTIME_POLL_MS);
      return () => clearInterval(id);
    };
    t4 = [gw, setBellOnComplete, sid];
    $[6] = gw;
    $[7] = setBellOnComplete;
    $[8] = sid;
    $[9] = t3;
    $[10] = t4;
  } else {
    t3 = $[9];
    t4 = $[10];
  }
  useEffect(t3, t4);
}
function _temp(r_3) {
  return r_3 && turnController.pushActivity("MCP reloaded after config change");
}