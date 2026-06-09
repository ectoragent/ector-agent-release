import { expandInlinePlaceholders, protectInlineSpans } from './lib/inlineTokens.js';
const MD_URL_RE = '((?:[^\\s()]|\\([^\\s()]*\\))+?)';
export const MEDIA_LINE_RE = /^\s*[`"']?MEDIA:\s*(\S+?)[`"']?\s*$/;
export const AUDIO_DIRECTIVE_RE = /^\s*\[\[audio_as_voice\]\]\s*$/;
/** Git object id (short or full) — matched after code spans are protected. */
export const GIT_HASH_RE = /\b[0-9a-f]{7,40}\b/gi;
export const INLINE_RE = new RegExp([`!\\[(.*?)\\]\\(${MD_URL_RE}\\)`, `\\[(.+?)\\]\\(${MD_URL_RE}\\)`, `<((?:https?:\\/\\/|mailto:)[^>\\s]+|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,})>`, `~~(.+?)~~`, `\`([^\\\`]+)\``, `\\*\\*(.+?)\\*\\*`, `(?<!\\w)__(.+?)__(?!\\w)`, `\\*(.+?)\\*`, `(?<!\\w)_(.+?)_(?!\\w)`, `==(.+?)==`, `\\[\\^([^\\]]+)\\]`, `\\^([^^\\s][^^]*?)\\^`, `~([A-Za-z0-9]{1,8})~`, `\\b[0-9a-f]{7,40}\\b`, `https?:\\/\\/[^\\s<]+`].join('|'), 'gi');
export const stripInlineMarkup = v => {
  const protected_ = protectInlineSpans(v);
  let out = expandInlinePlaceholders(protected_.text, protected_);
  return out.replace(/!\[(.*?)\]\(((?:[^\s()]|\([^\s()]*\))+?)\)/g, '[image: $1] $2').replace(/\[(.+?)\]\(((?:[^\s()]|\([^\s()]*\))+?)\)/g, '$1').replace(/<((?:https?:\/\/|mailto:)[^>\s]+|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})>/g, '$1').replace(/~~(.+?)~~/g, '$1').replace(/\*(.+?)\*/g, '$1').replace(/(?<!\w)_(.+?)_(?!\w)/g, '$1').replace(/==(.+?)==/g, '$1').replace(/\[\^([^\]]+)\]/g, '[$1]').replace(/\^([^^\s][^^]*?)\^/g, '^$1').replace(/~([A-Za-z0-9]{1,8})~/g, '_$1');
};