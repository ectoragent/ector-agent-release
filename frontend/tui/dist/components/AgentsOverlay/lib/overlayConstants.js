export const SORT_ORDER = ['depth-first', 'tools-desc', 'duration-desc', 'status'];
export const FILTER_ORDER = ['all', 'running', 'failed', 'leaf'];
export const SORT_LABEL = {
  'depth-first': 'ordem de spawn',
  'duration-desc': 'mais lentos',
  status: 'estado',
  'tools-desc': 'mais ativos'
};
export const FILTER_LABEL = {
  all: 'todos',
  failed: 'falhos',
  leaf: 'folhas',
  running: 'em execução'
};
export const STATUS_PT = {
  completed: 'concluído',
  failed: 'falhou',
  running: 'executando',
  queued: 'na fila',
  interrupted: 'Interrompido por você'
};
const STATUS_RANK = {
  failed: 0,
  interrupted: 1,
  running: 2,
  queued: 3,
  completed: 4
};
export const SORT_COMPARATORS = {
  'depth-first': (a, b) => a.item.depth - b.item.depth || a.item.index - b.item.index,
  'tools-desc': (a, b) => b.aggregate.totalTools - a.aggregate.totalTools,
  'duration-desc': (a, b) => b.aggregate.totalDuration - a.aggregate.totalDuration,
  status: (a, b) => STATUS_RANK[a.item.status] - STATUS_RANK[b.item.status]
};
export const FILTER_PREDICATES = {
  all: () => true,
  leaf: n => n.children.length === 0,
  running: n => n.item.status === 'running' || n.item.status === 'queued',
  failed: n => n.item.status === 'failed' || n.item.status === 'interrupted'
};
export const STATUS_GLYPH = {
  running: {
    color: t => t.color.cyan,
    glyph: '●'
  },
  queued: {
    color: t => t.color.dim,
    glyph: '○'
  },
  completed: {
    color: t => t.color.statusGood,
    glyph: '✓'
  },
  interrupted: {
    color: t => t.color.warn,
    glyph: '■'
  },
  failed: {
    color: t => t.color.error,
    glyph: '✗'
  }
};
// Heatmap palette — cold → hot, resolved against the active theme.
export const heatPalette = t => [t.color.border, t.color.cyan, t.color.title, t.color.warn, t.color.error];