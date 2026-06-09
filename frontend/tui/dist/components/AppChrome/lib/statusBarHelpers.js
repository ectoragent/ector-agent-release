export const HEART_COLORS = ['#ff5fa2', '#ff4d6d'];
export const effortLabel = effort => {
  const value = String(effort ?? '').trim().toLowerCase();
  return value && value !== 'medium' && value !== 'normal' && value !== 'default' ? value : '';
};
export const shortModelLabel = model => model.split('/').pop().replace(/^claude[-_]/, '').replace(/^anthropic[-_]/, '').replace(/[-_]/g, ' ').replace(/\b(\d+)\s+(\d+)\b/g, '$1.$2').trim();
export const modelLabel = (model, effort, fast) => [shortModelLabel(model), effortLabel(effort), fast ? 'rápido' : ''].filter(Boolean).join(' ');