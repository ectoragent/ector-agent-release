import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Box, Text, useInput, useStdout } from '@ector/ink';
import { useEffect, useState } from 'react';
import { rpcErrorMessage } from '../../lib/rpc.js';
import { OverlayHint, useOverlayKeys, windowItems, windowOffset } from '../OverlayControls/index.js';
const VISIBLE = 12;
const MIN_WIDTH = 40;
const MAX_WIDTH = 90;
export function SkillsHub(t0) {
  const $ = _c(72);
  const {
    gw,
    onClose,
    t
  } = t0;
  let t1;
  if ($[0] === Symbol.for("react.memo_cache_sentinel")) {
    t1 = {};
    $[0] = t1;
  } else {
    t1 = $[0];
  }
  const [skillsByCat, setSkillsByCat] = useState(t1);
  const [selectedCat, setSelectedCat] = useState("");
  const [catIdx, setCatIdx] = useState(0);
  const [skillIdx, setSkillIdx] = useState(0);
  const [stage, setStage] = useState("category");
  const [info, setInfo] = useState(null);
  const [installing, setInstalling] = useState(false);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);
  const {
    stdout
  } = useStdout();
  const width = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, (stdout?.columns ?? 80) - 6));
  let t2;
  let t3;
  if ($[1] !== gw) {
    t2 = () => {
      gw.request("skills.manage", {
        action: "list"
      }).then(r => {
        setSkillsByCat(r?.skills ?? {});
        setErr("");
        setLoading(false);
      }).catch(e => {
        setErr(rpcErrorMessage(e));
        setLoading(false);
      });
    };
    t3 = [gw];
    $[1] = gw;
    $[2] = t2;
    $[3] = t3;
  } else {
    t2 = $[2];
    t3 = $[3];
  }
  useEffect(t2, t3);
  let t4;
  if ($[4] !== skillsByCat) {
    t4 = Object.keys(skillsByCat).sort();
    $[4] = skillsByCat;
    $[5] = t4;
  } else {
    t4 = $[5];
  }
  const cats = t4;
  let t5;
  if ($[6] !== selectedCat || $[7] !== skillsByCat) {
    t5 = selectedCat ? skillsByCat[selectedCat] ?? [] : [];
    $[6] = selectedCat;
    $[7] = skillsByCat;
    $[8] = t5;
  } else {
    t5 = $[8];
  }
  const skills = t5;
  const skillName = skills[skillIdx] ?? "";
  let t6;
  if ($[9] !== onClose || $[10] !== stage) {
    t6 = () => {
      if (stage === "actions") {
        setStage("skill");
        setInfo(null);
        setErr("");
        return;
      }
      if (stage === "skill") {
        setStage("category");
        setSkillIdx(0);
        return;
      }
      onClose();
    };
    $[9] = onClose;
    $[10] = stage;
    $[11] = t6;
  } else {
    t6 = $[11];
  }
  const back = t6;
  let t7;
  if ($[12] !== back || $[13] !== installing || $[14] !== onClose) {
    t7 = {
      disabled: installing,
      onBack: back,
      onClose
    };
    $[12] = back;
    $[13] = installing;
    $[14] = onClose;
    $[15] = t7;
  } else {
    t7 = $[15];
  }
  useOverlayKeys(t7);
  let t8;
  if ($[16] !== gw) {
    t8 = name => {
      setInfo(null);
      setErr("");
      gw.request("skills.manage", {
        action: "inspect",
        query: name
      }).then(r_0 => setInfo(r_0?.info ?? {
        name
      })).catch(e_0 => setErr(rpcErrorMessage(e_0)));
    };
    $[16] = gw;
    $[17] = t8;
  } else {
    t8 = $[17];
  }
  const inspect = t8;
  let t9;
  if ($[18] !== gw || $[19] !== onClose) {
    t9 = name_0 => {
      setInstalling(true);
      setErr("");
      gw.request("skills.manage", {
        action: "install",
        query: name_0
      }).then(() => onClose()).catch(e_1 => setErr(rpcErrorMessage(e_1))).finally(() => setInstalling(false));
    };
    $[18] = gw;
    $[19] = onClose;
    $[20] = t9;
  } else {
    t9 = $[20];
  }
  const install = t9;
  let t10;
  if ($[21] !== catIdx || $[22] !== cats || $[23] !== inspect || $[24] !== install || $[25] !== installing || $[26] !== skillIdx || $[27] !== skillName || $[28] !== skills || $[29] !== stage) {
    t10 = (ch, key) => {
      if (installing) {
        return;
      }
      if (stage === "actions") {
        if (key.return) {
          setStage("skill");
          setInfo(null);
          setErr("");
          return;
        }
        if (ch.toLowerCase() === "x" && skillName) {
          install(skillName);
          return;
        }
        if (ch.toLowerCase() === "i" && skillName) {
          inspect(skillName);
        }
        return;
      }
      const count = stage === "category" ? cats.length : skills.length;
      const sel = stage === "category" ? catIdx : skillIdx;
      const setSel = stage === "category" ? setCatIdx : setSkillIdx;
      if (key.upArrow && sel > 0) {
        setSel(_temp);
        return;
      }
      if (key.downArrow && sel < count - 1) {
        setSel(_temp2);
        return;
      }
      if (key.return) {
        if (stage === "category") {
          const cat = cats[catIdx];
          if (!cat) {
            return;
          }
          setSelectedCat(cat);
          setSkillIdx(0);
          setStage("skill");
          return;
        }
        const name_1 = skills[skillIdx];
        if (name_1) {
          setStage("actions");
          inspect(name_1);
        }
        return;
      }
      const n = ch === "0" ? 10 : parseInt(ch, 10);
      if (!Number.isNaN(n) && n >= 1 && n <= Math.min(10, count)) {
        const next = windowOffset(count, sel, VISIBLE) + n - 1;
        if (stage === "category") {
          const cat_0 = cats[next];
          if (cat_0) {
            setSelectedCat(cat_0);
            setCatIdx(next);
            setSkillIdx(0);
            setStage("skill");
          }
          return;
        }
        const name_2 = skills[next];
        if (name_2) {
          setSkillIdx(next);
          setStage("actions");
          inspect(name_2);
        }
      }
    };
    $[21] = catIdx;
    $[22] = cats;
    $[23] = inspect;
    $[24] = install;
    $[25] = installing;
    $[26] = skillIdx;
    $[27] = skillName;
    $[28] = skills;
    $[29] = stage;
    $[30] = t10;
  } else {
    t10 = $[30];
  }
  useInput(t10);
  if (loading) {
    let t11;
    if ($[31] !== t.color.dim) {
      t11 = _jsx(Text, {
        color: t.color.dim,
        children: "carregando\u2026"
      });
      $[31] = t.color.dim;
      $[32] = t11;
    } else {
      t11 = $[32];
    }
    return t11;
  }
  if (err && stage === "category") {
    let t11;
    if ($[33] !== err || $[34] !== t || $[35] !== width) {
      t11 = _jsxs(Box, {
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
      $[33] = err;
      $[34] = t;
      $[35] = width;
      $[36] = t11;
    } else {
      t11 = $[36];
    }
    return t11;
  }
  if (!cats.length) {
    let t11;
    if ($[37] !== t || $[38] !== width) {
      t11 = _jsxs(Box, {
        flexDirection: "column",
        width,
        children: [_jsx(Text, {
          color: t.color.dim,
          children: "nenhuma habilidade dispon\xEDvel"
        }), _jsx(OverlayHint, {
          t,
          children: "Esc/q fechar"
        })]
      });
      $[37] = t;
      $[38] = width;
      $[39] = t11;
    } else {
      t11 = $[39];
    }
    return t11;
  }
  if (stage === "category") {
    let t11;
    if ($[40] !== catIdx || $[41] !== cats || $[42] !== skillsByCat || $[43] !== t || $[44] !== width) {
      let t12;
      if ($[46] !== skillsByCat) {
        t12 = c => `${c} · ${skillsByCat[c]?.length ?? 0} itens`;
        $[46] = skillsByCat;
        $[47] = t12;
      } else {
        t12 = $[47];
      }
      const rows = cats.map(t12);
      const {
        items,
        offset
      } = windowItems(rows, catIdx, VISIBLE);
      let t13;
      if ($[48] !== catIdx || $[49] !== offset || $[50] !== t.color.cyan || $[51] !== t.color.dim) {
        t13 = (row, i) => {
          const idx = offset + i;
          return _jsxs(Text, {
            bold: catIdx === idx,
            color: catIdx === idx ? t.color.cyan : t.color.dim,
            inverse: catIdx === idx,
            wrap: "truncate-end",
            children: [catIdx === idx ? "\u25B8 " : "  ", i + 1, ". ", row]
          }, row);
        };
        $[48] = catIdx;
        $[49] = offset;
        $[50] = t.color.cyan;
        $[51] = t.color.dim;
        $[52] = t13;
      } else {
        t13 = $[52];
      }
      t11 = _jsxs(Box, {
        flexDirection: "column",
        width,
        children: [_jsx(Text, {
          bold: true,
          color: t.color.cyan,
          children: "Central de skills"
        }), _jsx(Text, {
          color: t.color.dim,
          children: "escolha uma categoria"
        }), offset > 0 && _jsxs(Text, {
          color: t.color.dim,
          children: [" \u2191 mais ", offset]
        }), items.map(t13), offset + VISIBLE < rows.length && _jsxs(Text, {
          color: t.color.dim,
          children: [" \u2193 mais ", rows.length - offset - VISIBLE]
        }), _jsx(OverlayHint, {
          t,
          children: "\u2191/\u2193 escolher \xB7 Enter abrir \xB7 1-9,0 r\xE1pido \xB7 Esc/q fechar"
        })]
      });
      $[40] = catIdx;
      $[41] = cats;
      $[42] = skillsByCat;
      $[43] = t;
      $[44] = width;
      $[45] = t11;
    } else {
      t11 = $[45];
    }
    return t11;
  }
  if (stage === "skill") {
    let t11;
    if ($[53] !== selectedCat || $[54] !== skillIdx || $[55] !== skills || $[56] !== t || $[57] !== width) {
      const {
        items: items_0,
        offset: offset_0
      } = windowItems(skills, skillIdx, VISIBLE);
      let t12;
      if ($[59] !== offset_0 || $[60] !== skillIdx || $[61] !== t.color.cyan || $[62] !== t.color.dim) {
        t12 = (row_0, i_0) => {
          const idx_0 = offset_0 + i_0;
          return _jsxs(Text, {
            bold: skillIdx === idx_0,
            color: skillIdx === idx_0 ? t.color.cyan : t.color.dim,
            inverse: skillIdx === idx_0,
            wrap: "truncate-end",
            children: [skillIdx === idx_0 ? "\u25B8 " : "  ", i_0 + 1, ". ", row_0]
          }, row_0);
        };
        $[59] = offset_0;
        $[60] = skillIdx;
        $[61] = t.color.cyan;
        $[62] = t.color.dim;
        $[63] = t12;
      } else {
        t12 = $[63];
      }
      t11 = _jsxs(Box, {
        flexDirection: "column",
        width,
        children: [_jsx(Text, {
          bold: true,
          color: t.color.cyan,
          children: selectedCat
        }), _jsxs(Text, {
          color: t.color.dim,
          children: [skills.length, " itens"]
        }), !skills.length ? _jsx(Text, {
          color: t.color.dim,
          children: "nenhuma habilidade nesta categoria"
        }) : null, offset_0 > 0 && _jsxs(Text, {
          color: t.color.dim,
          children: [" \u2191 mais ", offset_0]
        }), items_0.map(t12), offset_0 + VISIBLE < skills.length && _jsxs(Text, {
          color: t.color.dim,
          children: [" \u2193 mais ", skills.length - offset_0 - VISIBLE]
        }), _jsx(OverlayHint, {
          t,
          children: skills.length ? "\u2191/\u2193 escolher \xB7 Enter abrir \xB7 1-9,0 r\xE1pido \xB7 Esc voltar \xB7 q fechar" : "Esc voltar \xB7 q fechar"
        })]
      });
      $[53] = selectedCat;
      $[54] = skillIdx;
      $[55] = skills;
      $[56] = t;
      $[57] = width;
      $[58] = t11;
    } else {
      t11 = $[58];
    }
    return t11;
  }
  let t11;
  if ($[64] !== err || $[65] !== info || $[66] !== installing || $[67] !== selectedCat || $[68] !== skillName || $[69] !== t || $[70] !== width) {
    t11 = _jsxs(Box, {
      flexDirection: "column",
      width,
      children: [_jsx(Text, {
        bold: true,
        color: t.color.cyan,
        children: info?.name ?? skillName
      }), _jsx(Text, {
        color: t.color.dim,
        children: info?.category ?? selectedCat
      }), info?.description ? _jsx(Text, {
        color: t.color.text,
        children: info.description
      }) : null, info?.path ? _jsxs(Text, {
        color: t.color.dim,
        children: ["caminho: ", info.path]
      }) : null, !info && !err ? _jsx(Text, {
        color: t.color.dim,
        children: "carregando\u2026"
      }) : null, err ? _jsxs(Text, {
        color: t.color.label,
        children: ["erro: ", err]
      }) : null, installing ? _jsx(Text, {
        color: t.color.cyan,
        children: "instalando\u2026"
      }) : null, _jsx(OverlayHint, {
        t,
        children: "i reinspecionar \xB7 x reinstalar \xB7 Enter/Esc voltar \xB7 q fechar"
      })]
    });
    $[64] = err;
    $[65] = info;
    $[66] = installing;
    $[67] = selectedCat;
    $[68] = skillName;
    $[69] = t;
    $[70] = width;
    $[71] = t11;
  } else {
    t11 = $[71];
  }
  return t11;
}
function _temp2(v_0) {
  return v_0 + 1;
}
function _temp(v) {
  return v - 1;
}