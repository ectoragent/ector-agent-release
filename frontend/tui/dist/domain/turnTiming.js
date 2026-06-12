import { fmtDuration } from './messages.js';
export function normalizeEpochMs(ts) {
  return ts < 10_000_000_000 ? ts * 1000 : ts;
}
export function formatCompletionClock(endMs) {
  const date = new Date(normalizeEpochMs(endMs));
  if (Number.isNaN(date.getTime())) return '';
  const now = new Date();
  const sameDay = date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate();
  const options = sameDay ? {
    hour: '2-digit',
    minute: '2-digit'
  } : {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit'
  };
  return new Intl.DateTimeFormat('pt-BR', options).format(date);
}
export function formatInteractionFooter(timing) {
  const elapsed = fmtDuration(timing.completedAt - timing.startedAt);
  const clock = formatCompletionClock(timing.completedAt);
  if (!elapsed && !clock) return '';
  if (!clock) return elapsed;
  if (!elapsed) return clock;
  return `${elapsed} · ${clock}`;
}
export function turnTimingMsg(startedAt, completedAt) {
  return {
    kind: 'turnTiming',
    role: 'system',
    text: formatInteractionFooter({
      startedAt,
      completedAt
    }),
    turnTiming: {
      startedAt,
      completedAt
    }
  };
}