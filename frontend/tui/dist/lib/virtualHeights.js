import { backgroundMessageParts } from '../domain/messages.js';
import { SPEAKER_LINE_RESERVE_COLS, TOOL_BLOCK_MARGIN_LEFT, TRANSCRIPT_CARD_HORIZONTAL_GUTTER, TRANSCRIPT_CARD_VERTICAL_PAD, transcriptContentCols } from '../domain/transcriptLayout.js';
import { boundedHistoryRenderText, stripAnsi } from './text.js';
const hashText = text => {
  let h = 5381;
  for (let i = 0; i < text.length; i++) {
    h = (h << 5) + h ^ text.charCodeAt(i);
  }
  return (h >>> 0).toString(36);
};
export const messageHeightKey = msg => {
  const todoSig = msg.todos?.map(t => `${t.status}:${t.content}`).join('\u0001') ?? '';
  const panelSig = msg.panelData?.sections.map(s => `${s.title ?? ''}:${s.text?.length ?? 0}:${s.items?.length ?? 0}:${s.rows?.length ?? 0}`).join('\u0001') ?? '';
  const introSig = msg.kind === 'intro' ? msg.info?.version ?? '' : '';
  return [msg.role, msg.kind ?? '', hashText([msg.text, msg.thinking ?? '', msg.tools?.join('\n') ?? '', todoSig, panelSig, introSig].join('\0'))].join(':');
};
export const wrappedLines = (text, width) => {
  const w = Math.max(1, width);
  return text.split('\n').reduce((n, line) => n + Math.max(1, Math.ceil(line.length / w)), 0);
};
export const estimatedMsgHeight = (msg, cols, {
  compact,
  details,
  limitHistory = false
}) => {
  if (msg.kind === 'intro') {
    return msg.info?.version ? 9 : 5;
  }
  if (msg.kind === 'panel') {
    return Math.max(3, (msg.panelData?.sections.length ?? 1) * 2 + 1);
  }
  if (msg.kind === 'trail' && msg.todos?.length) {
    if (msg.todoCollapsedByDefault) {
      return 2 + TRANSCRIPT_CARD_VERTICAL_PAD;
    }
    return Math.max(2, msg.todos.length + 2) + TRANSCRIPT_CARD_VERTICAL_PAD;
  }
  const nest = details && !!(msg.tools?.length || msg.thinking && msg.thinking.trim()) ? TOOL_BLOCK_MARGIN_LEFT : 0;
  const transcriptChrome = msg.role === 'user' || msg.role === 'assistant' ? SPEAKER_LINE_RESERVE_COLS : 5;
  const cardHorizontalGutter = msg.role === 'user' || msg.role === 'assistant' ? 0 : TRANSCRIPT_CARD_HORIZONTAL_GUTTER;
  const layoutCols = transcriptContentCols(cols);
  const bodyWidth = Math.max(20, layoutCols - transcriptChrome - nest - cardHorizontalGutter);
  const legacyBg = msg.kind !== 'background' ? backgroundMessageParts(msg.text) : null;
  const text = msg.role === 'assistant' && limitHistory ? boundedHistoryRenderText(msg.text) : msg.text;
  const mdBody = msg.kind === 'background' ? limitHistory ? boundedHistoryRenderText(msg.text) : msg.text : legacyBg ? limitHistory ? boundedHistoryRenderText(legacyBg.body) : legacyBg.body : text;
  // Slash vindo do Rich: medir sem ANSI para o virtualizer não subestimar linhas (scroll cortado).
  const wrapSource = msg.kind === 'slash' ? stripAnsi(text || '').replace(/\r\n/g, '\n') : mdBody || ' ';
  let h = wrappedLines(wrapSource, bodyWidth);
  if (!compact && (msg.role === 'assistant' || msg.kind === 'background' || legacyBg)) {
    h += Math.min(6, (mdBody.match(/\n\s*\n/g) ?? []).length);
  }
  if (details) {
    h += (msg.tools?.length ?? 0) + wrappedLines(msg.thinking ?? '', bodyWidth);
  }
  if (msg.role === 'user' || msg.kind === 'diff') {
    h += 2;
  } else if (msg.kind === 'slash') {
    // Margem para bordas Rich / linhas em branco no fim do buffer.
    h += 2;
  }
  const cardVerticalPad = msg.role === 'user' || msg.role === 'assistant' ? 0 : TRANSCRIPT_CARD_VERTICAL_PAD;
  return Math.max(1, h) + cardVerticalPad;
};