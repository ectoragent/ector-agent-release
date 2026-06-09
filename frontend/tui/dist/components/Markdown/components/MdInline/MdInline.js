import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Box, Link, Text } from '@ector/ink';
import { prepareInlineText, splitProtectedText } from '../../lib/inlineTokens.js';
import { mdAccent, renderBacktick, renderBoldSpan } from '../../lib/mdInlineStyles.js';
import { safeLinkUrl } from '../../lib/safeUrl.js';
import { computeTableColumnWidths, formatTableCell, tableFrameWidth, tableHorizontalRule } from '../../lib/tableLayout.js';
import { INLINE_RE, stripInlineMarkup } from '../../regex.js';
const renderAutolink = (k, t, raw) => {
  const url = safeLinkUrl(raw);
  if (!url) {
    return _jsx(Text, {
      color: t.color.label,
      children: raw
    }, k);
  }
  return _jsx(Link, {
    url: url,
    children: _jsx(Text, {
      color: t.color.cyan,
      underline: true,
      children: raw.replace(/^mailto:/, '')
    })
  }, k);
};
/** INLINE_RE on a plain segment only — never runs across placeholders. */
const renderPlainSegment = (plain, t, keyBase, tone) => {
  if (!plain) {
    return [];
  }
  const parts = [];
  let last = 0;
  for (const m of plain.matchAll(INLINE_RE)) {
    const i = m.index ?? 0;
    if (i > last) {
      parts.push(_jsx(Text, {
        children: plain.slice(last, i)
      }, keyBase + parts.length));
    }
    const k = keyBase + parts.length;
    if (m[1] && m[2]) {
      parts.push(_jsxs(Text, {
        color: t.color.dim,
        children: ["[image: ", m[1], "] ", m[2]]
      }, k));
    } else if (m[3] && m[4]) {
      const url = safeLinkUrl(m[4]);
      if (url) {
        parts.push(_jsx(Link, {
          url: url,
          children: _jsx(Text, {
            color: t.color.cyan,
            underline: true,
            children: m[3]
          })
        }, k));
      } else {
        parts.push(_jsx(Text, {
          color: t.color.cyan,
          children: m[3]
        }, k));
        if (m[4] !== m[3]) {
          parts.push(_jsxs(Text, {
            color: t.color.dim,
            children: [' ', "(", m[4], ")"]
          }, k + 1));
        }
      }
    } else if (m[5]) {
      parts.push(renderAutolink(k, t, m[5]));
    } else if (m[6]) {
      parts.push(_jsx(Text, {
        color: t.color.dim,
        strikethrough: true,
        children: m[6]
      }, k));
    } else if (m[7]) {
      parts.push(_jsx(Text, {
        children: renderBacktick(t, m[7])
      }, k));
    } else if (m[8] ?? m[9]) {
      parts.push(_jsx(Text, {
        children: renderBoldSpan(t, m[8] ?? m[9], tone)
      }, k));
    } else if (m[10] ?? m[11]) {
      parts.push(_jsx(Text, {
        color: tone === 'heading' ? t.color.label : undefined,
        italic: true,
        children: m[10] ?? m[11]
      }, k));
    } else if (m[12]) {
      parts.push(_jsx(Text, {
        backgroundColor: t.color.diffAdded,
        color: t.color.diffAddedWord,
        children: m[12]
      }, k));
    } else if (m[13]) {
      parts.push(_jsxs(Text, {
        color: t.color.dim,
        children: ["[", m[13], "]"]
      }, k));
    } else if (m[14]) {
      parts.push(_jsxs(Text, {
        color: t.color.dim,
        children: ["^", m[14]]
      }, k));
    } else if (m[15]) {
      parts.push(_jsxs(Text, {
        color: t.color.dim,
        children: ["_", m[15]]
      }, k));
    } else if (m[16]) {
      parts.push(_jsx(Text, {
        children: mdAccent(t, m[16])
      }, k));
    } else if (m[17]) {
      const url = m[17].replace(/[),.;:!?]+$/g, '');
      parts.push(renderAutolink(k, t, url));
      if (url.length < m[17].length) {
        parts.push(_jsx(Text, {
          children: m[17].slice(url.length)
        }, k + 1));
      }
    }
    last = i + m[0].length;
  }
  if (last < plain.length) {
    parts.push(_jsx(Text, {
      children: plain.slice(last)
    }, keyBase + parts.length));
  }
  if (!parts.length) {
    parts.push(_jsx(Text, {
      children: plain
    }, keyBase));
  }
  return parts;
};
const renderProtectSegments = (segments, protect, t, opts = {}) => {
  const {
    inBold = false,
    tone = 'body'
  } = opts;
  const parts = [];
  let key = 0;
  for (const seg of segments) {
    if (seg.kind === 'plain') {
      if (inBold) {
        const plain = seg.text;
        if (plain) {
          parts.push(_jsx(Text, {
            children: renderBoldSpan(t, plain, tone)
          }, key++));
        }
      } else {
        parts.push(...renderPlainSegment(seg.text, t, key, tone));
        key += 32;
      }
      continue;
    }
    if (seg.kind === 'code') {
      const inner = protect.codes[seg.index] ?? '';
      parts.push(_jsx(Text, {
        children: renderBacktick(t, inner, inBold)
      }, key++));
      continue;
    }
    const inner = protect.bolds[seg.index] ?? '';
    parts.push(...renderProtectSegments(splitProtectedText(inner), protect, t, {
      inBold: true,
      tone
    }));
    key += 32;
  }
  return parts;
};
function TableDataRow({
  frameDim,
  isHeader,
  row,
  t,
  widths
}) {
  const cellColor = isHeader ? t.color.cyan : t.color.text;
  return _jsx(Box, {
    flexDirection: "row",
    children: [_jsx(Text, {
      color: frameDim,
      dim: true,
      children: "\u2502"
    }, "l"), ...row.flatMap((cell, ci) => [_jsx(Text, {
      bold: isHeader,
      color: cellColor,
      wrap: "truncate-end",
      children: ` ${formatTableCell(cell, widths[ci] ?? 3)} `
    }, `c${ci}`), _jsx(Text, {
      color: frameDim,
      dim: true,
      children: "\u2502"
    }, `r${ci}`)])]
  });
}
export function renderTable(k, rows, t, _Inline, maxWidth) {
  if (!rows.length) {
    return null;
  }
  const widths = computeTableColumnWidths(rows, maxWidth);
  const frameDim = t.color.border;
  const rule = join => tableHorizontalRule(widths, join);
  const nodes = [_jsx(Text, {
    color: frameDim,
    dim: true,
    wrap: "truncate-end",
    children: `┌${rule('┬')}┐`
  }, "top")];
  for (const [ri, row] of rows.entries()) {
    nodes.push(_jsx(TableDataRow, {
      frameDim: frameDim,
      isHeader: ri === 0,
      row: row,
      t: t,
      widths: widths
    }, `row-${ri}`));
    if (ri < rows.length - 1) {
      nodes.push(_jsx(Text, {
        color: frameDim,
        dim: true,
        wrap: "truncate-end",
        children: `├${rule('┼')}┤`
      }, `sep-${ri}`));
    }
  }
  nodes.push(_jsx(Text, {
    color: frameDim,
    dim: true,
    wrap: "truncate-end",
    children: `└${rule('┴')}┘`
  }, "bot"));
  const frameWidth = tableFrameWidth(widths);
  return _jsx(Box, {
    flexDirection: "column",
    width: maxWidth ?? frameWidth,
    children: nodes
  }, k);
}
export function MdInline({
  bold,
  prefix,
  t,
  text,
  tone = 'body'
}) {
  const protect = prepareInlineText(text);
  const segments = splitProtectedText(protect.text);
  const effectiveTone = tone === 'heading' || bold ? 'heading' : 'body';
  const parts = renderProtectSegments(segments, protect, t, {
    inBold: Boolean(bold),
    tone: effectiveTone
  });
  const leading = prefix ? [_jsx(Text, {
    color: t.color.dim,
    children: prefix
  }, "md-prefix")] : [];
  if (!parts.length && !leading.length) {
    return _jsx(Text, {
      children: text
    });
  }
  if (!parts.length) {
    return _jsx(Text, {
      wrap: "wrap",
      children: leading
    });
  }
  return _jsx(Text, {
    wrap: "wrap",
    children: [...leading, ...parts]
  });
}
export { stripInlineMarkup };