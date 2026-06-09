import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Box, Link, Text } from '@ector/ink';
import { memo, useMemo } from 'react';
import { ensureEmojiPresentation } from '../../lib/emoji.js';
import { MdInline, renderTable } from './components/MdInline/index.js';
import { BULLET_RE, DEF_RE, FOOTNOTE_RE, HEADING_RE, HR_RE, indentDepth, isTableDivider, listContinuationLine, NUMBERED_RE, QUOTE_RE, SETEXT_RE, splitRow, TASK_RE } from './lib/blockRegex.js';
import { cacheBucket, cacheGet, cacheSet } from './lib/mdCache.js';
import { normalizeMdText } from './lib/normalizeMdText.js';
import { fenceFollowsListItem, parseFenceBlock, renderFenceBox } from './lib/renderFence.js';
import { safeLinkUrl } from './lib/safeUrl.js';
import { AUDIO_DIRECTIVE_RE, MEDIA_LINE_RE } from './regex.js';
export { AUDIO_DIRECTIVE_RE, GIT_HASH_RE, INLINE_RE, MEDIA_LINE_RE, stripInlineMarkup } from './regex.js';
function MdImpl({
  compact,
  t,
  text,
  width
}) {
  const nodes_0 = useMemo(() => {
    const bucket = cacheBucket(t);
    const cacheKey = `${compact ? '1' : '0'}|${width ?? ''}|${text}`;
    const cached = cacheGet(bucket, cacheKey);
    if (cached) {
      return cached;
    }
    const lines = ensureEmojiPresentation(normalizeMdText(text)).split('\n');
    const nodes = [];
    let prevKind = null;
    let i = 0;
    const gap = () => {
      if (nodes.length && prevKind !== 'blank') {
        nodes.push(_jsx(Text, {
          children: " "
        }, `gap-${nodes.length}`));
        prevKind = 'blank';
      }
    };
    const start = kind => {
      if (prevKind && prevKind !== 'blank' && prevKind !== kind) {
        gap();
      }
      prevKind = kind;
    };
    const appendListFence = (key, listIndent) => {
      if (!fenceFollowsListItem(lines, i, listIndent)) {
        return;
      }
      const childFence = parseFenceBlock(lines, i);
      start('code');
      nodes.push(_jsx(Box, {
        paddingLeft: 2,
        children: renderFenceBox(key, childFence, t, Md, compact, width)
      }, `${key}-fence`));
      i = childFence.nextIndex;
    };
    while (i < lines.length) {
      const line = lines[i];
      const key_0 = nodes.length;
      if (!line.trim()) {
        if (!compact) {
          gap();
        }
        i++;
        continue;
      }
      if (AUDIO_DIRECTIVE_RE.test(line)) {
        i++;
        continue;
      }
      const media = line.match(MEDIA_LINE_RE)?.[1];
      if (media) {
        start('paragraph');
        const mediaUrl = safeLinkUrl(media);
        nodes.push(_jsxs(Text, {
          color: t.color.dim,
          children: ['▸ ', mediaUrl ? _jsx(Link, {
            url: mediaUrl,
            children: _jsx(Text, {
              color: t.color.cyan,
              underline: true,
              children: media
            })
          }) : _jsx(Text, {
            color: t.color.label,
            children: media
          })]
        }, key_0));
        i++;
        continue;
      }
      const parsedFence = parseFenceBlock(lines, i);
      if (parsedFence) {
        if (['md', 'markdown'].includes(parsedFence.lang)) {
          start('paragraph');
          nodes.push(_jsx(Md, {
            compact: compact,
            t: t,
            text: parsedFence.block.join('\n'),
            width: width
          }, key_0));
        } else {
          start('code');
          nodes.push(_jsx(Box, {
            paddingLeft: 2,
            children: renderFenceBox(key_0, parsedFence, t, Md, compact, width)
          }, key_0));
        }
        i = parsedFence.nextIndex;
        continue;
      }
      if (line.trim().startsWith('$$')) {
        const mathStart = i;
        const block = [];
        let closed = false;
        for (let j = i + 1; j < lines.length; j++) {
          if (lines[j].trim().startsWith('$$')) {
            closed = true;
            i = j + 1;
            break;
          }
          block.push(lines[j]);
        }
        if (closed) {
          start('code');
          nodes.push(_jsxs(Box, {
            flexDirection: "column",
            paddingLeft: 2,
            children: [_jsx(Text, {
              color: t.color.cyan,
              children: "\u2500 math"
            }), block.map((l, j_0) => _jsx(Text, {
              color: t.color.label,
              children: l
            }, j_0))]
          }, key_0));
          continue;
        }
        start('paragraph');
        nodes.push(_jsx(MdInline, {
          t: t,
          text: line
        }, key_0));
        for (let k = 0; k < block.length; k++) {
          nodes.push(_jsx(MdInline, {
            t: t,
            text: block[k]
          }, `${key_0}-math-${k}`));
        }
        i = mathStart + 1 + block.length;
        continue;
      }
      const heading = line.match(HEADING_RE)?.[2];
      if (heading) {
        start('heading');
        nodes.push(_jsx(MdInline, {
          bold: true,
          t: t,
          text: heading,
          tone: "heading"
        }, key_0));
        i++;
        continue;
      }
      if (i + 1 < lines.length && SETEXT_RE.test(lines[i + 1])) {
        start('heading');
        nodes.push(_jsx(MdInline, {
          bold: true,
          t: t,
          text: line.trim(),
          tone: "heading"
        }, key_0));
        i += 2;
        continue;
      }
      if (HR_RE.test(line)) {
        start('rule');
        nodes.push(_jsx(Text, {
          color: t.color.border,
          children: '─'.repeat(36)
        }, key_0));
        i++;
        continue;
      }
      const footnote = line.match(FOOTNOTE_RE);
      if (footnote) {
        start('list');
        nodes.push(_jsx(MdInline, {
          prefix: `[${footnote[1]}] `,
          t: t,
          text: footnote[2] ?? ''
        }, key_0));
        i++;
        while (i < lines.length && /^\s{2,}\S/.test(lines[i])) {
          nodes.push(_jsx(Box, {
            paddingLeft: 2,
            children: _jsx(MdInline, {
              t: t,
              text: lines[i].trim()
            })
          }, `${key_0}-cont-${i}`));
          i++;
        }
        continue;
      }
      if (i + 1 < lines.length && DEF_RE.test(lines[i + 1])) {
        start('list');
        nodes.push(_jsx(MdInline, {
          bold: true,
          t: t,
          text: line.trim(),
          tone: "heading"
        }, key_0));
        i++;
        while (i < lines.length) {
          const def = lines[i].match(DEF_RE)?.[1];
          if (!def) {
            break;
          }
          nodes.push(_jsx(MdInline, {
            prefix: " \u00B7 ",
            t: t,
            text: def
          }, `${key_0}-def-${i}`));
          i++;
        }
        continue;
      }
      const bullet = line.match(BULLET_RE);
      if (bullet) {
        start('list');
        const task = bullet[2].match(TASK_RE);
        const marker = task ? task[1].toLowerCase() === 'x' ? '☑' : '☐' : '•';
        const listIndent_0 = indentDepth(bullet[1]);
        const prefix = `${' '.repeat(listIndent_0 * 2)}${marker} `;
        let body = (task ? task[2] : bullet[2]).trim();
        i++;
        while (i < lines.length && listContinuationLine(lines[i])) {
          body += ` ${lines[i].trim()}`;
          i++;
        }
        nodes.push(_jsx(MdInline, {
          prefix: prefix,
          t: t,
          text: body
        }, key_0));
        appendListFence(key_0, listIndent_0);
        continue;
      }
      const numbered = line.match(NUMBERED_RE);
      if (numbered) {
        start('list');
        const listIndent_1 = indentDepth(numbered[1]);
        const prefix_0 = `${' '.repeat(listIndent_1 * 2)}${numbered[2]}. `;
        let body_0 = numbered[3].trim();
        i++;
        while (i < lines.length && listContinuationLine(lines[i])) {
          body_0 += ` ${lines[i].trim()}`;
          i++;
        }
        nodes.push(_jsx(MdInline, {
          prefix: prefix_0,
          t: t,
          text: body_0
        }, key_0));
        appendListFence(key_0, listIndent_1);
        continue;
      }
      if (QUOTE_RE.test(line)) {
        start('quote');
        const quoteLines = [];
        while (i < lines.length && QUOTE_RE.test(lines[i])) {
          const prefix_1 = lines[i].match(QUOTE_RE)?.[0] ?? '';
          quoteLines.push({
            depth: (prefix_1.match(/>/g) ?? []).length,
            text: lines[i].slice(prefix_1.length)
          });
          i++;
        }
        nodes.push(_jsx(Box, {
          flexDirection: "column",
          children: quoteLines.map((ql, qi) => _jsx(MdInline, {
            prefix: `${' '.repeat(Math.max(0, ql.depth - 1) * 2)}│ `,
            t: t,
            text: ql.text
          }, qi))
        }, key_0));
        continue;
      }
      if (line.includes('|') && i + 1 < lines.length && isTableDivider(lines[i + 1])) {
        start('table');
        const rows = [splitRow(line)];
        for (i += 2; i < lines.length && lines[i].includes('|') && lines[i].trim(); i++) {
          rows.push(splitRow(lines[i]));
        }
        nodes.push(renderTable(key_0, rows, t, MdInline, width));
        continue;
      }
      if (/^<\/?details\b/i.test(line)) {
        i++;
        continue;
      }
      const summary = line.match(/^<summary>(.*?)<\/summary>$/i)?.[1];
      if (summary) {
        start('paragraph');
        nodes.push(_jsxs(Text, {
          children: [_jsx(Text, {
            color: t.color.cyan,
            children: "\u25B6 "
          }), _jsx(Text, {
            bold: true,
            color: t.color.cyan,
            children: summary
          })]
        }, key_0));
        i++;
        continue;
      }
      if (/^<\/?[^>]+>$/.test(line.trim())) {
        start('paragraph');
        nodes.push(_jsx(Text, {
          color: t.color.dim,
          children: line.trim()
        }, key_0));
        i++;
        continue;
      }
      if (line.includes('|') && line.trim().startsWith('|')) {
        start('table');
        const rows_0 = [];
        while (i < lines.length && lines[i].trim().startsWith('|')) {
          const row = lines[i].trim();
          if (!/^[|\s:-]+$/.test(row)) {
            rows_0.push(splitRow(row));
          }
          i++;
        }
        if (rows_0.length) {
          nodes.push(renderTable(key_0, rows_0, t, MdInline, width));
        }
        continue;
      }
      start('paragraph');
      nodes.push(_jsx(MdInline, {
        t: t,
        text: line
      }, key_0));
      i++;
    }
    cacheSet(bucket, cacheKey, nodes);
    return nodes;
  }, [compact, t, text, width]);
  return _jsx(Box, {
    flexDirection: "column",
    children: nodes_0
  });
}
export const Md = memo(MdImpl);