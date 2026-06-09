import { fmtK } from '../lib/text.js';
export const ZERO = {
  calls: 0,
  input: 0,
  output: 0,
  total: 0
};
/** Rótulo compacto de tokens para a barra de estado (ex. `12k/128k` ou `45k`). */
export function usageTokenLabel(usage) {
  if (usage.context_max) {
    return `${fmtK(usage.context_used ?? 0)}/${fmtK(usage.context_max)}`;
  }
  const sum = usage.total > 0 ? usage.total : (usage.input ?? 0) + (usage.output ?? 0);
  if (sum > 0) {
    return fmtK(sum);
  }
  return '';
}
/** Custo da sessão para a barra de estado (ex. `$0.042` ou `~$0.042`). */
export function usageCostLabel(usage) {
  if (typeof usage.cost_usd !== 'number') {
    return '';
  }
  const prefix = usage.cost_status === 'estimated' ? '~' : '';
  return `${prefix}$${usage.cost_usd.toFixed(3)}`;
}