import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Box, Text, useInput, useStdout } from '@ector/ink';
import { useEffect, useMemo, useState } from 'react';
import { asRpcResult, rpcErrorMessage } from '../../lib/rpc.js';
import { OverlayHint, useOverlayKeys, windowOffset } from '../OverlayControls/index.js';
const VISIBLE = 15;
const MIN_WIDTH = 60;
const MAX_WIDTH = 120;
/** Tempo relativo desde `started_at` (segundos unix). */
const timeAgo = ts => {
  const sec = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (sec < 45) {
    return 'agora';
  }
  const min = Math.floor(sec / 60);
  if (min < 60) {
    return min === 1 ? 'há 1 min' : `há ${min} min`;
  }
  const h = Math.floor(min / 60);
  if (h < 24) {
    return h === 1 ? 'há 1 h' : `há ${h} h`;
  }
  const d = Math.floor(h / 24);
  if (d === 1) {
    return 'ontem';
  }
  return `há ${d} d`;
};
const clip = (s, max) => {
  const one = s.replace(/\s+/g, ' ').trim();
  return one.length <= max ? one : one.slice(0, Math.max(0, max - 1)) + '…';
};
export function SessionPicker(t0) {
  const $ = _c(39);
  const {
    gw,
    onCancel,
    onSelect,
    t
  } = t0;
  let t1;
  if ($[0] === Symbol.for("react.memo_cache_sentinel")) {
    t1 = [];
    $[0] = t1;
  } else {
    t1 = $[0];
  }
  const [items, setItems] = useState(t1);
  const [err, setErr] = useState("");
  const [sel, setSel] = useState(0);
  const [loading, setLoading] = useState(true);
  const {
    stdout
  } = useStdout();
  const width = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, (stdout?.columns ?? 80) - 6));
  const titleMax = Math.max(16, width - 28);
  let t2;
  if ($[1] !== items || $[2] !== titleMax) {
    let t3;
    if ($[4] !== titleMax) {
      t3 = (s, i) => {
        const when = timeAgo(s.started_at);
        const title = clip(s.title || s.preview || "(sem t\xEDtulo)", titleMax);
        return `${String(i + 1).padStart(2)}. ${when} — ${title}`;
      };
      $[4] = titleMax;
      $[5] = t3;
    } else {
      t3 = $[5];
    }
    t2 = items.map(t3);
    $[1] = items;
    $[2] = titleMax;
    $[3] = t2;
  } else {
    t2 = $[3];
  }
  const rows = t2;
  let t3;
  if ($[6] !== onCancel) {
    t3 = {
      onClose: onCancel
    };
    $[6] = onCancel;
    $[7] = t3;
  } else {
    t3 = $[7];
  }
  useOverlayKeys(t3);
  let t4;
  let t5;
  if ($[8] !== gw) {
    t4 = () => {
      gw.request("session.list", {
        limit: 200
      }).then(raw => {
        const r = asRpcResult(raw);
        if (!r) {
          setErr("resposta inv\xE1lida: session.list");
          setLoading(false);
          return;
        }
        const sessions = (r.sessions ?? []).filter(_temp);
        setItems(sessions);
        setErr("");
        setLoading(false);
      }).catch(e => {
        setErr(rpcErrorMessage(e));
        setLoading(false);
      });
    };
    t5 = [gw];
    $[8] = gw;
    $[9] = t4;
    $[10] = t5;
  } else {
    t4 = $[9];
    t5 = $[10];
  }
  useEffect(t4, t5);
  let t6;
  if ($[11] !== items || $[12] !== onCancel || $[13] !== onSelect || $[14] !== sel) {
    t6 = (ch, key) => {
      if (key.escape || ch === "q") {
        return onCancel();
      }
      if (key.upArrow && sel > 0) {
        setSel(_temp2);
      }
      if (key.downArrow && sel < items.length - 1) {
        setSel(_temp3);
      }
      if (key.return && items[sel]) {
        onSelect(items[sel].id);
      }
      const n = parseInt(ch, 10);
      if (n >= 1 && n <= Math.min(9, items.length)) {
        onSelect(items[n - 1].id);
      }
    };
    $[11] = items;
    $[12] = onCancel;
    $[13] = onSelect;
    $[14] = sel;
    $[15] = t6;
  } else {
    t6 = $[15];
  }
  useInput(t6);
  if (loading) {
    let t7;
    if ($[16] !== t.color.dim) {
      t7 = _jsx(Text, {
        color: t.color.dim,
        children: "carregando sess\xF5es\u2026"
      });
      $[16] = t.color.dim;
      $[17] = t7;
    } else {
      t7 = $[17];
    }
    return t7;
  }
  if (err) {
    let t7;
    if ($[18] !== err || $[19] !== t || $[20] !== width) {
      t7 = _jsxs(Box, {
        flexDirection: "column",
        width,
        children: [_jsxs(Text, {
          color: t.color.label,
          children: ["erro: ", err]
        }), _jsx(OverlayHint, {
          t,
          children: "Esc/q fechar"
        })]
      });
      $[18] = err;
      $[19] = t;
      $[20] = width;
      $[21] = t7;
    } else {
      t7 = $[21];
    }
    return t7;
  }
  if (!items.length) {
    let t7;
    if ($[22] !== t || $[23] !== width) {
      t7 = _jsxs(Box, {
        flexDirection: "column",
        width,
        children: [_jsx(Text, {
          color: t.color.dim,
          children: "nenhuma sess\xE3o anterior"
        }), _jsx(OverlayHint, {
          t,
          children: "Esc/q fechar"
        })]
      });
      $[22] = t;
      $[23] = width;
      $[24] = t7;
    } else {
      t7 = $[24];
    }
    return t7;
  }
  let t7;
  if ($[25] !== items || $[26] !== rows || $[27] !== sel || $[28] !== t || $[29] !== width) {
    const offset = windowOffset(items.length, sel, VISIBLE);
    let t8;
    if ($[31] !== items || $[32] !== offset || $[33] !== sel || $[34] !== t.color.completionCurrentBg || $[35] !== t.color.cyan || $[36] !== t.color.dim || $[37] !== width) {
      t8 = (line, vi) => {
        const i_0 = offset + vi;
        const selected = sel === i_0;
        return _jsx(Box, {
          backgroundColor: selected ? t.color.completionCurrentBg : undefined,
          width,
          children: _jsx(Text, {
            bold: selected,
            color: selected ? t.color.cyan : t.color.dim,
            wrap: "truncate-end",
            children: selected ? `▸ ${line}` : `  ${line}`
          })
        }, items[i_0].id);
      };
      $[31] = items;
      $[32] = offset;
      $[33] = sel;
      $[34] = t.color.completionCurrentBg;
      $[35] = t.color.cyan;
      $[36] = t.color.dim;
      $[37] = width;
      $[38] = t8;
    } else {
      t8 = $[38];
    }
    t7 = _jsxs(Box, {
      flexDirection: "column",
      width,
      children: [_jsx(Text, {
        bold: true,
        color: t.color.cyan,
        wrap: "truncate-end",
        children: "Retomar sess\xE3o"
      }), offset > 0 ? _jsxs(Text, {
        color: t.color.dim,
        wrap: "truncate-end",
        children: ["\u2191 mais ", offset]
      }) : null, rows.slice(offset, offset + VISIBLE).map(t8), offset + VISIBLE < items.length ? _jsxs(Text, {
        color: t.color.dim,
        wrap: "truncate-end",
        children: ["\u2193 mais ", items.length - offset - VISIBLE]
      }) : null, _jsx(OverlayHint, {
        t,
        children: "\u2191/\u2193 escolher \xB7 Enter retomar \xB7 1-9 r\xE1pido \xB7 Esc/q fechar"
      })]
    });
    $[25] = items;
    $[26] = rows;
    $[27] = sel;
    $[28] = t;
    $[29] = width;
    $[30] = t7;
  } else {
    t7 = $[30];
  }
  return t7;
}
function _temp3(s_2) {
  return s_2 + 1;
}
function _temp2(s_1) {
  return s_1 - 1;
}
function _temp(s_0) {
  return !s_0.id.startsWith("bg_");
}