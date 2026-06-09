import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Box, Text } from '@ector/ink';
import { highlightLine, resolveFenceHighlightLang } from '../../../lib/syntax.js';
import { FENCE_CLOSE_RE, FENCE_RE } from './blockRegex.js';
import { fenceCodeHeaderText } from './fenceLangLabel.js';
import { mdCode } from './mdInlineStyles.js';
export const parseFenceBlock = (lines, start) => {
  const open = lines[start]?.match(FENCE_RE);
  if (!open) {
    return null;
  }
  const char = open[1][0];
  const len = open[1].length;
  const lang = open[2].trim().toLowerCase().replace(/`+$/g, '').split(/\s+/)[0];
  const block = [];
  let i = start + 1;
  for (; i < lines.length; i++) {
    const close = lines[i].match(FENCE_CLOSE_RE)?.[1];
    if (close && close[0] === char && close.length >= len) {
      return {
        block,
        char,
        lang,
        len,
        nextIndex: i + 1
      };
    }
    block.push(lines[i]);
  }
  return {
    block,
    char,
    lang,
    len,
    nextIndex: i
  };
};
const formatLineNumber = (n, width) => String(n).padStart(width, ' ');
const renderHighlightedTokens = (line, lang, t) => _jsx(Text, {
  children: highlightLine(line, lang, t, 'fence').map(([color, text], kk) => _jsx(Text, {
    color: color || t.color.codeFg,
    children: text
  }, kk))
});
const renderFenceCodeLine = (lineIndex, line, lineNo, gutterWidth, lang, t, highlighted, isDiff) => {
  const trim = line.trimStart();
  const add = isDiff && trim.startsWith('+') && !trim.startsWith('+++');
  const del = isDiff && trim.startsWith('-') && !trim.startsWith('---');
  const hunk = isDiff && trim.startsWith('@@');
  const fileHdr = isDiff && (trim.startsWith('---') || trim.startsWith('+++'));
  return _jsxs(Box, {
    flexDirection: "row",
    children: [_jsx(Box, {
      flexShrink: 0,
      marginRight: 1,
      width: gutterWidth + 1,
      children: _jsx(Text, {
        color: t.color.codeLineNum,
        children: formatLineNumber(lineNo, gutterWidth)
      })
    }), highlighted ? renderHighlightedTokens(line, lang, t) : _jsx(Text, {
      backgroundColor: add ? t.color.diffAdded : del ? t.color.diffRemoved : undefined,
      color: add ? t.color.diffAddedWord : del ? t.color.diffRemovedWord : hunk || fileHdr ? t.color.codeComment : t.color.codeFg,
      dimColor: isDiff && !add && !del && !hunk && !fileHdr && (trim.startsWith(' ') || trim === ''),
      children: line
    })]
  }, lineIndex);
};
/** One-line fences render as inline code — no gutter, label, or code panel. */
export const isSingleLineFence = fence => fence.block.length === 1 && !['md', 'markdown'].includes(fence.lang);
const renderInlineFenceLine = (line, lang, t, isDiff) => {
  if (isDiff) {
    const trim = line.trimStart();
    const add = trim.startsWith('+') && !trim.startsWith('+++');
    const del = trim.startsWith('-') && !trim.startsWith('---');
    return _jsx(Text, {
      backgroundColor: add ? t.color.diffAdded : del ? t.color.diffRemoved : undefined,
      color: add ? t.color.diffAddedWord : del ? t.color.diffRemovedWord : t.color.codeFg,
      wrap: "wrap",
      children: line
    });
  }
  const highlightLang = resolveFenceHighlightLang(lang);
  const highlighted = highlightLang !== 'diff' && !['md', 'markdown'].includes(highlightLang) && lang !== 'diff';
  if (highlighted) {
    return _jsx(Text, {
      backgroundColor: t.color.completionBg,
      wrap: "wrap",
      children: renderHighlightedTokens(line, highlightLang, t)
    });
  }
  return mdCode(t, line);
};
export const renderFenceBox = (key, fence, t, Md, compact, width) => {
  const {
    block,
    lang
  } = fence;
  if (['md', 'markdown'].includes(lang)) {
    return _jsx(Md, {
      compact: compact,
      t: t,
      text: block.join('\n'),
      width: width
    }, key);
  }
  if (isSingleLineFence(fence)) {
    return _jsx(Box, {
      marginTop: 1,
      width: width,
      children: renderInlineFenceLine(block[0], lang, t, lang === 'diff')
    }, key);
  }
  const isDiff = lang === 'diff';
  const highlightLang = resolveFenceHighlightLang(lang);
  const highlighted = !isDiff && highlightLang !== 'diff' && !['md', 'markdown'].includes(highlightLang);
  const headerText = fenceCodeHeaderText(lang);
  const gutterWidth = Math.max(2, String(block.length).length);
  return _jsxs(Box, {
    flexDirection: "column",
    marginTop: 1,
    width: width,
    children: [headerText ? _jsx(Box, {
      marginBottom: 1,
      children: _jsx(Text, {
        color: t.color.codeLangLabel,
        children: headerText
      })
    }) : null, _jsx(Box, {
      backgroundColor: t.color.codeBg,
      flexDirection: "column",
      paddingX: 1,
      paddingY: 1,
      width: width,
      children: block.map((l, j) => renderFenceCodeLine(j, l, j + 1, gutterWidth, highlightLang, t, highlighted, isDiff))
    })]
  }, key);
};
export const fenceFollowsListItem = (lines, index, listIndent) => {
  if (index >= lines.length) {
    return false;
  }
  const next = lines[index];
  if (!FENCE_RE.test(next)) {
    return false;
  }
  const lead = next.match(/^(\s*)/)?.[1] ?? '';
  return Math.floor(lead.replace(/\t/g, '  ').length / 2) <= listIndent + 1;
};