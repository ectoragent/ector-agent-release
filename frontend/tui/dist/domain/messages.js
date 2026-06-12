import { LONG_MSG, MAX_HISTORY } from '../config/limits.js';
import { buildToolTrailLine, fmtK, inferToolFailedFromResult, toolFailureHeadline } from '../lib/text.js';
export const introMsg = info => ({
  info,
  kind: 'intro',
  role: 'system',
  text: ''
});
/** `[bg <task_id>] …` — notificação de processo em background (gateway `background.complete`). */
export const backgroundMessageParts = text => {
  const m = text.match(/^\[bg ([^\]]+)\]\s?([\s\S]*)$/);
  return m ? {
    label: `[bg ${m[1]}]`,
    body: m[2] ?? ''
  } : null;
};
/** User-facing actions that hide the intro banner (first message, slash, panel, shell, …). */
export const isIntroDismissInteraction = msg => msg.kind !== 'intro' && (msg.role === 'user' || msg.kind === 'slash' || msg.kind === 'panel');
export const withoutIntro = items => items.filter(m => m.kind !== 'intro');
/** Cap transcript length — same policy as live append in useMainApp. */
export const capTranscriptHistory = items => {
  if (items.length <= MAX_HISTORY) {
    return items;
  }
  return items[0]?.kind === 'intro' ? [items[0], ...items.slice(-(MAX_HISTORY - 1))] : items.slice(-MAX_HISTORY);
};
/** Fresh session shows intro; resumed/compressed transcripts with rows do not. */
export const sessionHistoryItems = (info, messages) => {
  if (messages.length > 0) {
    return messages;
  }
  return info ? [introMsg(info)] : [];
};
export const imageTokenMeta = info => {
  const {
    width,
    height,
    token_estimate: t
  } = info ?? {};
  return [width && height ? `${width}x${height}` : '', (t ?? 0) > 0 ? `~${fmtK(t)} tok` : ''].filter(Boolean).join(' · ');
};
export const attachedImageNotice = info => {
  const meta = imageTokenMeta(info);
  const label = info?.name ? `📎 Attached image: ${info.name}` : '📎 Attached image';
  return `${label}${meta ? ` · ${meta}` : ''}`;
};
export const userDisplay = text => {
  if (text.length <= LONG_MSG) {
    return text;
  }
  const first = text.split('\n')[0]?.trim() ?? '';
  const words = first.split(/\s+/).filter(Boolean);
  const prefix = (words.length > 1 ? words.slice(0, 4).join(' ') : first).slice(0, 80);
  return `${prefix || '(message)'} [long message]`;
};
export const toTranscriptMessages = rows => {
  if (!Array.isArray(rows)) {
    return [];
  }
  const out = [];
  let pending = [];
  for (const row of rows) {
    if (!row || typeof row !== 'object') {
      continue;
    }
    const {
      context,
      kind,
      name,
      role,
      technical,
      text,
      turn_timing: turnTimingRaw
    } = row;
    if (kind === 'turnTiming' && turnTimingRaw) {
      const startedAt = Number(turnTimingRaw.started_at);
      const completedAt = Number(turnTimingRaw.completed_at);
      if (Number.isFinite(startedAt) && Number.isFinite(completedAt)) {
        const startedMs = startedAt < 10_000_000_000 ? startedAt * 1000 : startedAt;
        const completedMs = completedAt < 10_000_000_000 ? completedAt * 1000 : completedAt;
        out.push({
          kind: 'turnTiming',
          role: 'system',
          text: typeof text === 'string' ? text : '',
          turnTiming: {
            startedAt: startedMs,
            completedAt: completedMs
          }
        });
      }
      continue;
    }
    if (role === 'tool') {
      const ctx = (context ?? '').trim();
      const tech = (technical ?? '').trim();
      const resultText = (typeof text === 'string' ? text : '').trim();
      const toolName = name ?? 'tool';
      const failed = inferToolFailedFromResult(toolName, resultText);
      const note = failed ? toolFailureHeadline(toolName, resultText) ?? (tech && tech !== ctx ? tech : undefined) : tech && tech !== ctx ? tech : undefined;
      pending.push(buildToolTrailLine(toolName, ctx, failed, note));
      continue;
    }
    if (typeof text !== 'string' || !text.trim()) {
      continue;
    }
    if (role === 'assistant') {
      for (const line of pending) {
        out.push({
          kind: 'trail',
          role: 'system',
          text: '',
          tools: [line]
        });
      }
      pending = [];
      out.push({
        role,
        text
      });
    } else if (role === 'user' || role === 'system') {
      out.push({
        role,
        text
      });
      pending = [];
    }
  }
  return out;
};
export const fmtDuration = ms => {
  const t = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(t / 3600);
  const m = Math.floor(t % 3600 / 60);
  const s = t % 60;
  return h > 0 ? `${h}h ${m}m` : m > 0 ? `${m}m ${s}s` : `${s}s`;
};