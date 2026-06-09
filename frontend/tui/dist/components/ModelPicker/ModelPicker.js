import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Box, Text, useInput, useStdout } from '@ector/ink';
import { useEffect, useMemo, useState } from 'react';
import { providerDisplayNames } from '../../domain/providers.js';
import { asRpcResult, rpcErrorMessage } from '../../lib/rpc.js';
import { OverlayHint, useOverlayKeys, windowItems, windowOffset } from '../OverlayControls/index.js';
const VISIBLE = 12;
const MIN_WIDTH = 40;
const MAX_WIDTH = 90;
export function ModelPicker(t0) {
  const $ = _c(31);
  const {
    gw,
    onCancel,
    onSelect,
    sessionId,
    t
  } = t0;
  let t1;
  if ($[0] === Symbol.for("react.memo_cache_sentinel")) {
    t1 = [];
    $[0] = t1;
  } else {
    t1 = $[0];
  }
  const [providers, setProviders] = useState(t1);
  const [currentModel, setCurrentModel] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);
  const [persistGlobal, setPersistGlobal] = useState(false);
  const [providerIdx, setProviderIdx] = useState(0);
  const [modelIdx, setModelIdx] = useState(0);
  const [stage, setStage] = useState("provider");
  const {
    stdout
  } = useStdout();
  const width = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, (stdout?.columns ?? 80) - 6));
  let t2;
  let t3;
  if ($[1] !== gw || $[2] !== sessionId) {
    t2 = () => {
      gw.request("model.options", sessionId ? {
        session_id: sessionId
      } : {}).then(raw => {
        const r = asRpcResult(raw);
        if (!r) {
          setErr("resposta inv\xE1lida: model.options");
          setLoading(false);
          return;
        }
        const next = r.providers ?? [];
        setProviders(next);
        setCurrentModel(String(r.model ?? ""));
        setProviderIdx(Math.max(0, next.findIndex(_temp)));
        setModelIdx(0);
        setErr("");
        setLoading(false);
      }).catch(e => {
        setErr(rpcErrorMessage(e));
        setLoading(false);
      });
    };
    t3 = [gw, sessionId];
    $[1] = gw;
    $[2] = sessionId;
    $[3] = t2;
    $[4] = t3;
  } else {
    t2 = $[3];
    t3 = $[4];
  }
  useEffect(t2, t3);
  const provider = providers[providerIdx];
  const models = provider?.models ?? [];
  let t4;
  if ($[5] !== providers) {
    t4 = providerDisplayNames(providers);
    $[5] = providers;
    $[6] = t4;
  } else {
    t4 = $[6];
  }
  const names = t4;
  let t5;
  if ($[7] !== onCancel || $[8] !== stage) {
    t5 = () => {
      if (stage === "model") {
        setStage("provider");
        setModelIdx(0);
        return;
      }
      onCancel();
    };
    $[7] = onCancel;
    $[8] = stage;
    $[9] = t5;
  } else {
    t5 = $[9];
  }
  const back = t5;
  let t6;
  if ($[10] !== back || $[11] !== onCancel) {
    t6 = {
      onBack: back,
      onClose: onCancel
    };
    $[10] = back;
    $[11] = onCancel;
    $[12] = t6;
  } else {
    t6 = $[12];
  }
  useOverlayKeys(t6);
  useInput((ch, key) => {
    const count = stage === "provider" ? providers.length : models.length;
    const sel = stage === "provider" ? providerIdx : modelIdx;
    const setSel = stage === "provider" ? setProviderIdx : setModelIdx;
    if (key.upArrow && sel > 0) {
      setSel(_temp2);
      return;
    }
    if (key.downArrow && sel < count - 1) {
      setSel(_temp3);
      return;
    }
    if (key.return) {
      if (stage === "provider") {
        if (!provider) {
          return;
        }
        setStage("model");
        setModelIdx(0);
        return;
      }
      const model = models[modelIdx];
      if (provider && model) {
        onSelect(`${model} --provider ${provider.slug}${persistGlobal ? " --global" : ""}`);
      } else {
        setStage("provider");
      }
      return;
    }
    if (ch.toLowerCase() === "g") {
      setPersistGlobal(_temp4);
      return;
    }
    const n = ch === "0" ? 10 : parseInt(ch, 10);
    if (!Number.isNaN(n) && n >= 1 && n <= Math.min(10, count)) {
      const offset = windowOffset(count, sel, VISIBLE);
      if (stage === "provider") {
        const next_0 = offset + n - 1;
        if (providers[next_0]) {
          setProviderIdx(next_0);
        }
      } else {
        if (provider && models[offset + n - 1]) {
          onSelect(`${models[offset + n - 1]} --provider ${provider.slug}${persistGlobal ? " --global" : ""}`);
        }
      }
    }
  });
  if (loading) {
    let t7;
    if ($[13] !== t.color.dim) {
      t7 = _jsx(Text, {
        color: t.color.dim,
        children: "carregando modelos\u2026"
      });
      $[13] = t.color.dim;
      $[14] = t7;
    } else {
      t7 = $[14];
    }
    return t7;
  }
  if (err) {
    let t7;
    if ($[15] !== err || $[16] !== t) {
      t7 = _jsxs(Box, {
        flexDirection: "column",
        children: [_jsxs(Text, {
          color: t.color.label,
          children: ["erro: ", err]
        }), _jsx(OverlayHint, {
          t,
          children: "Esc/q fechar"
        })]
      });
      $[15] = err;
      $[16] = t;
      $[17] = t7;
    } else {
      t7 = $[17];
    }
    return t7;
  }
  if (!providers.length) {
    let t7;
    if ($[18] !== t) {
      t7 = _jsxs(Box, {
        flexDirection: "column",
        children: [_jsx(Text, {
          color: t.color.dim,
          children: "nenhum provedor autenticado"
        }), _jsx(OverlayHint, {
          t,
          children: "Esc/q fechar"
        })]
      });
      $[18] = t;
      $[19] = t7;
    } else {
      t7 = $[19];
    }
    return t7;
  }
  if (stage === "provider") {
    let t7;
    if ($[20] !== currentModel || $[21] !== names || $[22] !== persistGlobal || $[23] !== provider || $[24] !== providerIdx || $[25] !== providers || $[26] !== t || $[27] !== width) {
      let t8;
      if ($[29] !== names) {
        t8 = (p_0, i) => `${p_0.is_current ? "*" : " "} ${names[i]} · ${p_0.total_models ?? p_0.models?.length ?? 0} modelos`;
        $[29] = names;
        $[30] = t8;
      } else {
        t8 = $[30];
      }
      const rows = providers.map(t8);
      const {
        items,
        offset: offset_0
      } = windowItems(rows, providerIdx, VISIBLE);
      t7 = _jsxs(Box, {
        flexDirection: "column",
        width,
        children: [_jsx(Text, {
          bold: true,
          color: t.color.cyan,
          wrap: "truncate-end",
          children: "Escolher provedor"
        }), _jsxs(Text, {
          color: t.color.dim,
          wrap: "truncate-end",
          children: ["Modelo atual: ", currentModel || "(desconhecido)"]
        }), _jsx(Text, {
          color: t.color.label,
          wrap: "truncate-end",
          children: provider?.warning ? `aviso: ${provider.warning}` : " "
        }), _jsx(Text, {
          color: t.color.dim,
          wrap: "truncate-end",
          children: offset_0 > 0 ? ` ↑ mais ${offset_0}` : " "
        }), Array.from({
          length: VISIBLE
        }, (_, i_0) => {
          const row = items[i_0];
          const idx = offset_0 + i_0;
          return row ? _jsxs(Text, {
            bold: providerIdx === idx,
            color: providerIdx === idx ? t.color.cyan : t.color.dim,
            inverse: providerIdx === idx,
            wrap: "truncate-end",
            children: [providerIdx === idx ? "\u25B8 " : "  ", i_0 + 1, ". ", row]
          }, providers[idx]?.slug ?? `row-${idx}`) : _jsx(Text, {
            color: t.color.dim,
            wrap: "truncate-end",
            children: " "
          }, `pad-${i_0}`);
        }), _jsx(Text, {
          color: t.color.dim,
          wrap: "truncate-end",
          children: offset_0 + VISIBLE < rows.length ? ` ↓ mais ${rows.length - offset_0 - VISIBLE}` : " "
        }), _jsxs(Text, {
          color: t.color.dim,
          wrap: "truncate-end",
          children: ["persistir: ", persistGlobal ? "global" : "sess\xE3o", " \xB7 g alternar"]
        }), _jsx(OverlayHint, {
          t,
          children: "\u2191/\u2193 escolher \xB7 Enter confirmar \xB7 1-9,0 r\xE1pido \xB7 Esc/q fechar"
        })]
      });
      $[20] = currentModel;
      $[21] = names;
      $[22] = persistGlobal;
      $[23] = provider;
      $[24] = providerIdx;
      $[25] = providers;
      $[26] = t;
      $[27] = width;
      $[28] = t7;
    } else {
      t7 = $[28];
    }
    return t7;
  }
  const {
    items: items_0,
    offset: offset_1
  } = windowItems(models, modelIdx, VISIBLE);
  return _jsxs(Box, {
    flexDirection: "column",
    width,
    children: [_jsx(Text, {
      bold: true,
      color: t.color.cyan,
      wrap: "truncate-end",
      children: "Escolher modelo"
    }), _jsx(Text, {
      color: t.color.dim,
      wrap: "truncate-end",
      children: names[providerIdx] || "(provedor desconhecido)"
    }), _jsx(Text, {
      color: t.color.label,
      wrap: "truncate-end",
      children: provider?.warning ? `aviso: ${provider.warning}` : " "
    }), _jsx(Text, {
      color: t.color.dim,
      wrap: "truncate-end",
      children: offset_1 > 0 ? ` ↑ mais ${offset_1}` : " "
    }), Array.from({
      length: VISIBLE
    }, (__0, i_1) => {
      const row_0 = items_0[i_1];
      const idx_0 = offset_1 + i_1;
      if (!row_0) {
        return !models.length && i_1 === 0 ? _jsx(Text, {
          color: t.color.dim,
          wrap: "truncate-end",
          children: "nenhum modelo listado para este provedor"
        }, "empty") : _jsx(Text, {
          color: t.color.dim,
          wrap: "truncate-end",
          children: " "
        }, `pad-${i_1}`);
      }
      return _jsxs(Text, {
        bold: modelIdx === idx_0,
        color: modelIdx === idx_0 ? t.color.cyan : t.color.dim,
        inverse: modelIdx === idx_0,
        wrap: "truncate-end",
        children: [modelIdx === idx_0 ? "\u25B8 " : "  ", i_1 + 1, ". ", row_0]
      }, `${provider?.slug ?? "prov"}:${idx_0}:${row_0}`);
    }), _jsx(Text, {
      color: t.color.dim,
      wrap: "truncate-end",
      children: offset_1 + VISIBLE < models.length ? ` ↓ mais ${models.length - offset_1 - VISIBLE}` : " "
    }), _jsxs(Text, {
      color: t.color.dim,
      wrap: "truncate-end",
      children: ["persistir: ", persistGlobal ? "global" : "sess\xE3o", " \xB7 g alternar"]
    }), _jsx(OverlayHint, {
      t,
      children: models.length ? "\u2191/\u2193 escolher \xB7 Enter trocar \xB7 1-9,0 r\xE1pido \xB7 Esc voltar \xB7 q fechar" : "Enter/Esc voltar \xB7 q fechar"
    })]
  });
}
function _temp4(v_1) {
  return !v_1;
}
function _temp3(v_0) {
  return v_0 + 1;
}
function _temp2(v) {
  return v - 1;
}
function _temp(p) {
  return p.is_current;
}