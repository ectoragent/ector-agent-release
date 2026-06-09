import { HISTORY_RENDER_MAX_CHARS, HISTORY_RENDER_MAX_LINES, LIVE_RENDER_MAX_CHARS, LIVE_RENDER_MAX_LINES, LIVE_RENDER_TABLE_MAX_CHARS, LIVE_RENDER_TABLE_MAX_LINES, THINKING_COT_MAX } from '../config/limits.js';
/** PT — linhas de status removidas por `cleanThinkingText`. */
const THINKING_STRIP_VERBS_PT = ['pensando', 'refletindo', 'considerando', 'cogitando', 'deliberando', 'matutando', 'processando', 'raciocinando', 'analisando', 'computando', 'sintetizando', 'formulando', 'estruturando ideias'];
/** EN legado em trilhas de raciocínio do modelo. */
const LEGACY_EN_THINKING_VERBS = ['pondering', 'contemplating', 'musing', 'cogitating', 'ruminating', 'deliberating', 'mulling', 'reflecting', 'processing', 'reasoning', 'analyzing', 'computing', 'synthesizing', 'formulating', 'brainstorming'];
const THINKING_STRIP_VERBS = [...new Set([...THINKING_STRIP_VERBS_PT, ...LEGACY_EN_THINKING_VERBS])];
const ESC = String.fromCharCode(27);
const ANSI_RE = new RegExp(`${ESC}\\[[0-9;]*m`, 'g');
const WS_RE = /\s+/g;
export const stripAnsi = s => s.replace(ANSI_RE, '');
export const hasAnsi = s => s.includes(`${ESC}[`) || s.includes(`${ESC}]`);
const renderEstimateLine = line => {
  const trimmed = line.trim();
  if (trimmed.startsWith('|')) {
    return trimmed.split('|').filter(Boolean).map(cell => cell.trim()).join('  ');
  }
  return line.replace(/!\[(.*?)\]\(([^)\s]+)\)/g, '[image: $1]').replace(/\[(.+?)\]\((https?:\/\/[^\s)]+)\)/g, '$1').replace(/`([^`]+)`/g, '$1').replace(/\*\*(.+?)\*\*/g, '$1').replace(/(?<!\w)__(.+?)__(?!\w)/g, '$1').replace(/\*(.+?)\*/g, '$1').replace(/(?<!\w)_(.+?)_(?!\w)/g, '$1').replace(/~~(.+?)~~/g, '$1').replace(/==(.+?)==/g, '$1').replace(/\[\^([^\]]+)\]/g, '[$1]').replace(/^#{1,6}\s+/, '').replace(/^\s*[-*+]\s+\[( |x|X)\]\s+/, (_m, checked) => `• [${checked.toLowerCase() === 'x' ? 'x' : ' '}] `).replace(/^\s*[-*+]\s+/, '• ').replace(/^\s*(\d+)\.\s+/, '$1. ').replace(/^\s*(?:>\s*)+/, '│ ');
};
export const compactPreview = (s, max) => {
  const one = s.replace(WS_RE, ' ').trim();
  return !one ? '' : one.length > max ? one.slice(0, max - 1) + '…' : one;
};
export const estimateTokensRough = text => !text ? 0 : text.length + 3 >> 2;
export const edgePreview = (s, head = 16, tail = 28) => {
  const one = s.replace(WS_RE, ' ').trim().replace(/\]\]/g, '] ]');
  return !one ? '' : one.length <= head + tail + 4 ? one : `${one.slice(0, head).trimEnd()}.. ${one.slice(-tail).trimStart()}`;
};
export const pasteTokenLabel = (text, lineCount) => {
  const preview = edgePreview(text);
  if (!preview) {
    return `[[ [${fmtK(lineCount)} linhas] ]]`;
  }
  const [head = preview, tail = ''] = preview.split('.. ', 2);
  return tail ? `[[ ${head.trimEnd()}.. [${fmtK(lineCount)} linhas] .. ${tail.trimStart()} ]]` : `[[ ${preview} [${fmtK(lineCount)} linhas] ]]`;
};
const THINKING_STATUS_RE = new RegExp(`^(?:${THINKING_STRIP_VERBS.join('|')})\\.{0,3}$`, 'i');
const THINKING_STATUS_CHUNK_RE = new RegExp(`[^A-Za-z\n]+\\s*(?:${THINKING_STRIP_VERBS.join('|')})\\.{0,3}\\s*`, 'giu');
export const cleanThinkingText = reasoning => reasoning.split('\n').map(line => line.replace(THINKING_STATUS_CHUNK_RE, '').trim()).filter(line => line && !THINKING_STATUS_RE.test(line.replace(/\.\.\.$/, '').trim())).join('\n').replace(/([^\n])(?=\*\*[^*\n][^\n]*?\*\*)/g, '$1\n\n').replace(/\n{3,}/g, '\n\n').trim();
export const thinkingPreview = (reasoning, mode, max = THINKING_COT_MAX) => {
  const raw = cleanThinkingText(reasoning);
  return !raw || mode === 'collapsed' ? '' : mode === 'full' ? raw : compactPreview(raw.replace(WS_RE, ' '), max);
};
const looksLikeMarkdownTable = text => text.includes('|') && /^\s*\|.+\|/m.test(text);
export const boundedLiveRenderText = (text, {
  maxChars = LIVE_RENDER_MAX_CHARS,
  maxLines = LIVE_RENDER_MAX_LINES
} = {}) => {
  const table = looksLikeMarkdownTable(text);
  return boundedRenderText(text, 'trecho ao vivo', {
    maxChars: table ? Math.min(maxChars, LIVE_RENDER_TABLE_MAX_CHARS) : maxChars,
    maxLines: table ? Math.min(maxLines, LIVE_RENDER_TABLE_MAX_LINES) : maxLines
  });
};
export const boundedHistoryRenderText = (text, {
  maxChars = HISTORY_RENDER_MAX_CHARS,
  maxLines = HISTORY_RENDER_MAX_LINES
} = {}) => boundedRenderText(text, 'trecho', {
  maxChars,
  maxLines
});
const boundedRenderText = (text, labelPrefix, {
  maxChars,
  maxLines
}) => {
  if (text.length <= maxChars && text.split('\n', maxLines + 1).length <= maxLines) {
    return text;
  }
  let start = 0;
  let idx = text.length;
  for (let seen = 0; seen < maxLines && idx > 0; seen++) {
    idx = text.lastIndexOf('\n', idx - 1);
    start = idx < 0 ? 0 : idx + 1;
    if (idx < 0) {
      break;
    }
  }
  const lineStart = start;
  start = Math.max(lineStart, text.length - maxChars);
  if (start > lineStart) {
    const nextBreak = text.indexOf('\n', start);
    if (nextBreak >= 0 && nextBreak < text.length - 1) {
      start = nextBreak + 1;
    }
  }
  const tail = text.slice(start).trimStart();
  const omittedLines = countNewlines(text, start);
  const omittedChars = Math.max(0, text.length - tail.length);
  const label = omittedLines > 0 ? `[${labelPrefix}; omitidas ${fmtK(omittedLines)} linhas / ${fmtK(omittedChars)} caracteres]\n` : `[${labelPrefix}; omitidos ${fmtK(omittedChars)} caracteres]\n`;
  return `${label}${tail}`;
};
const countNewlines = (text, end) => {
  let count = 0;
  for (let i = 0; i < end; i++) {
    if (text.charCodeAt(i) === 10) {
      count++;
    }
  }
  return count;
};
export const stripTrailingPasteNewlines = text => /[^\n]/.test(text) ? text.replace(/\n+$/, '') : text;
/** Rótulo curto do tipo de ferramenta (linha principal no painel Ferramentas). */
export const toolKindLabel = name => {
  const key = name.trim().toLowerCase();
  if (!key) {
    return 'Ferramenta';
  }
  return TOOL_LABELS_PT[key] ?? fallbackToolKindLabel(key);
};
/** @deprecated Use {@link toolKindLabel}. */
export const toolTrailLabel = toolKindLabel;
const TOOL_LABELS_PT = {
  // Web
  web_search: 'Pesquisa na web',
  web_extract: 'Extração de conteúdo',
  web_crawl: 'Rastreamento do site',
  // Terminal e processos
  shell: 'Comando no terminal',
  terminal: 'Comando no terminal',
  process: 'Processo em segundo plano',
  // Arquivos
  read_file: 'Leitura de arquivo',
  write_file: 'Escrita de arquivo',
  edit_file: 'Edição de arquivo',
  patch: 'Patch em arquivo',
  search_files: 'Busca de arquivos',
  list_files: 'Listagem de arquivos',
  search: 'Busca no projeto',
  // Código e delegação
  execute_code: 'Execução de código',
  delegate_task: 'Delegação de tarefa',
  mixture_of_agents: 'Raciocínio em conjunto',
  // Sessão, memória e planejamento
  session_search: 'Busca na sessão',
  memory: 'Memória',
  todo: 'Lista de tarefas',
  // Wiser (legado ask_user / clarify)
  wiser: 'Pergunta ao usuário',
  ask_user: 'Pergunta ao usuário',
  clarify: 'Pergunta ao usuário',
  // Skills
  skills_list: 'Listagem de skills',
  skill_view: 'Skill',
  skill_manage: 'Gerenciamento de skill',
  // Mídia
  vision_analyze: 'Analisando imagem',
  image_generate: 'Gerando imagem',
  text_to_speech: 'Gerando áudio',
  // Browser
  browser_navigate: 'Navegação',
  browser_snapshot: 'Snapshot da página',
  browser_scroll: 'Rolagem da página',
  browser_click: 'Clique na página',
  browser_type: 'Digitação na página',
  browser_back: 'Voltar na página',
  browser_forward: 'Avançar na página',
  browser_reload: 'Recarregar página',
  browser_wait: 'Aguardar página',
  browser_press: 'Tecla na página',
  browser_get_images: 'Imagens da página',
  browser_vision: 'Visão da página',
  browser_console: 'Console do navegador',
  browser_cdp: 'CDP do navegador',
  browser_dialog: 'Diálogo do navegador',
  // Automação e mensagens
  cronjob: 'Gerenciando agendamento',
  send_message: 'Enviando mensagem',
  gateway_inspect: 'Verificando canais de mensagem',
  // Home Assistant
  ha_list_entities: 'Listando entidades',
  ha_get_state: 'Consultando estado',
  ha_list_services: 'Listando serviços',
  ha_call_service: 'Chamando serviço',
  // RL
  rl_list_environments: 'Listando ambientes RL',
  rl_select_environment: 'Selecionando ambiente RL',
  rl_get_current_config: 'Lendo configuração RL',
  rl_edit_config: 'Editando configuração RL',
  rl_start_training: 'Iniciando treino RL',
  rl_check_status: 'Verificando treino RL',
  rl_stop_training: 'Parando treino RL',
  rl_get_results: 'Obtendo resultados RL',
  rl_list_runs: 'Listando execuções RL',
  rl_test_inference: 'Testando inferência RL',
  // Discord (opcional)
  discord: 'Discord',
  discord_admin: 'Discord (admin)'
};
const TOOL_FALLBACK_VERB_PT = {
  list: 'Listando',
  get: 'Obtendo',
  read: 'Lendo',
  write: 'Escrevendo',
  search: 'Buscando',
  execute: 'Executando',
  call: 'Chamando',
  send: 'Enviando',
  edit: 'Editando',
  patch: 'Aplicando patch',
  create: 'Criando',
  delete: 'Removendo',
  add: 'Adicionando',
  select: 'Selecionando',
  start: 'Iniciando',
  stop: 'Parando',
  check: 'Verificando',
  test: 'Testando',
  query: 'Consultando',
  reply: 'Respondendo',
  analyze: 'Analisando',
  generate: 'Gerando',
  navigate: 'Navegando',
  snapshot: 'Capturando snapshot',
  click: 'Clicando',
  type: 'Digitando',
  scroll: 'Rolando',
  press: 'Pressionando tecla',
  vision: 'Analisando com visão',
  console: 'Lendo console',
  dialog: 'Tratando diálogo',
  cdp: 'Usando CDP',
  extract: 'Extraindo',
  crawl: 'Rastreando',
  delegate: 'Delegando',
  manage: 'Gerenciando',
  view: 'Abrindo',
  run: 'Executando',
  train: 'Treinando'
};
const TOOL_FALLBACK_NOUN_PT = {
  code: 'código',
  task: 'tarefa',
  file: 'arquivo',
  files: 'arquivos',
  session: 'sessão',
  memory: 'memória',
  message: 'mensagem',
  entities: 'entidades',
  services: 'serviços',
  state: 'estado',
  service: 'serviço',
  config: 'configuração',
  results: 'resultados',
  runs: 'execuções',
  environments: 'ambientes',
  environment: 'ambiente',
  inference: 'inferência',
  training: 'treino',
  status: 'status',
  comment: 'comentário',
  comments: 'comentários',
  replies: 'respostas',
  doc: 'documento',
  drive: 'drive',
  group: 'grupo',
  members: 'membros',
  sticker: 'figurinha',
  dm: 'mensagem direta',
  info: 'informações'
};
/** Rótulo PT para ferramentas MCP/plugins sem entrada explícita no mapa. */
function fallbackToolKindLabel(name) {
  if (name.startsWith('mcp_')) {
    return 'Ferramenta MCP';
  }
  if (name.startsWith('rl_')) {
    const tail = name.slice(3).split('_').filter(Boolean).map(p => TOOL_FALLBACK_NOUN_PT[p] ?? p).join(' ');
    return tail ? `Treinamento RL · ${tail}` : 'Treinamento RL';
  }
  if (name.startsWith('ha_')) {
    const parts = name.slice(3).split('_').filter(Boolean);
    const verb = parts[0] ?? '';
    const prefix = TOOL_FALLBACK_VERB_PT[verb] ?? 'Home Assistant';
    const tail = parts.slice(1).map(p => TOOL_FALLBACK_NOUN_PT[p] ?? p).join(' ');
    return tail ? `${prefix} ${tail}` : prefix;
  }
  if (name.startsWith('browser_')) {
    const action = name.slice('browser_'.length);
    const mapped = TOOL_LABELS_PT[`browser_${action}`];
    if (mapped) {
      return mapped;
    }
  }
  const parts = name.split('_').filter(Boolean);
  const verb = parts[0] ?? '';
  const prefix = TOOL_FALLBACK_VERB_PT[verb];
  if (prefix) {
    const tail = parts.slice(1).map(p => TOOL_FALLBACK_NOUN_PT[p] ?? p).join(' ');
    return tail ? `${prefix} ${tail}` : prefix;
  }
  const titleCased = parts.map(p => TOOL_FALLBACK_NOUN_PT[p] ?? p).map(w => w ? w[0].toUpperCase() + w.slice(1) : w).join(' ');
  return titleCased || name;
}
const LEGACY_TERMINAL_KIND = 'Executando comando';
const LEGACY_TERMINAL_KINDS = new Set([LEGACY_TERMINAL_KIND, 'Comando no terminal', 'Vou executar um comando no terminal']);
const _VOU_PREFIX_RE = /^vou\s+(\S+)(.*)$/i;
const _ESTOU_GERUND_RE = /^estou\s+(\S+)(.*)$/i;
/** Normaliza preview humano: mantém gerúndios do backend; suaviza legado ``Vou …``. */
const humanizeToolContextPt = context => {
  const trimmed = String(context ?? '').trim();
  if (!trimmed) {
    return '';
  }
  const vou = trimmed.match(_VOU_PREFIX_RE);
  if (vou) {
    const inf = vou[1].toLowerCase();
    const rest = vou[2].trim().replace(/^[,:\-–—]\s*/, '');
    if (inf.endsWith('ar') && inf.length > 2) {
      const gerund = `${inf.slice(0, -2)}ando`;
      return rest ? `${gerund[0].toUpperCase() + gerund.slice(1)} ${rest}` : gerund[0].toUpperCase() + gerund.slice(1);
    }
    if (inf.endsWith('er') && inf.length > 2) {
      const gerund = `${inf.slice(0, -2)}endo`;
      return rest ? `${gerund[0].toUpperCase() + gerund.slice(1)} ${rest}` : gerund[0].toUpperCase() + gerund.slice(1);
    }
    if (inf.endsWith('ir') && inf.length > 2) {
      const gerund = `${inf.slice(0, -2)}indo`;
      return rest ? `${gerund[0].toUpperCase() + gerund.slice(1)} ${rest}` : gerund[0].toUpperCase() + gerund.slice(1);
    }
    if (rest) {
      return rest[0].toUpperCase() + rest.slice(1);
    }
  }
  const estou = trimmed.match(_ESTOU_GERUND_RE);
  if (estou) {
    const word = estou[1].replace(/[.,:;!?]+$/, '');
    const rest = estou[2].trim().replace(/^[,:\-–—]\s*/, '');
    if (/^(?:\w+ando|\w+endo|\w+indo)$/i.test(word)) {
      const label = word[0].toUpperCase() + word.slice(1);
      return rest ? `${label} ${rest}` : label;
    }
  }
  if (isToolTechnicalSubline(trimmed)) {
    return trimmed;
  }
  return trimmed;
};
/** Título a partir de ``ferramenta: argumento`` quando não há descrição humana. */
const headlineFromTechnicalLine = (toolName, line) => {
  const trimmed = line.trim();
  const match = trimmed.match(/^([a-z][\w]*):\s*(.+)$/i);
  if (!match) {
    return '';
  }
  const tool = (toolName || match[1]).toLowerCase();
  const payload = match[2].trim();
  if (!payload) {
    return '';
  }
  if (tool === 'terminal' || tool === 'shell' || tool === 'process') {
    return payload;
  }
  if (tool === 'skill_view' || tool === 'skills_list' || tool === 'skill_manage') {
    return payload;
  }
  if (tool.startsWith('browser_') || tool.startsWith('read_') || tool.startsWith('write_') || tool.startsWith('edit_')) {
    return payload;
  }
  return payload;
};
export const toolContextLine = (context = '', max = 64) => compactPreview(humanizeToolContextPt(context), max);
export const formatToolCallParts = (name, context = '') => ({
  kind: toolKindLabel(name),
  context: toolContextLine(context)
});
/** Rótulo curto para o usuário: descrição/preview quando existir, senão o nome da ferramenta legível. */
export const formatToolCall = (name, context = '') => {
  const {
    kind,
    context: preview
  } = formatToolCallParts(name, context);
  return preview || kind;
};
const LEGACY_KIND_QUOTED_RE = /^(.+)\("(.+)"\)$/;
const GENERIC_TOOL_KIND = 'Ferramenta';
/** Infere tipo + contexto a partir de uma linha de trilha concluída (sem duração nem ✓/✗). */
export const resolveToolCallPartsFromResult = (toolName, call, detail = '') => {
  const trimmedDetail = detail.trim();
  if (trimmedDetail && !isToolTechnicalSubline(trimmedDetail)) {
    return {
      kind: toolName ? toolKindLabel(toolName) : inferKindFromCallLabel(call),
      context: humanizeToolContextPt(trimmedDetail)
    };
  }
  const quoted = call.match(LEGACY_KIND_QUOTED_RE);
  if (quoted) {
    const legacyKind = quoted[1].trim();
    const preview = quoted[2].trim();
    if (LEGACY_TERMINAL_KINDS.has(legacyKind) || legacyKind === toolKindLabel('terminal')) {
      return {
        kind: toolKindLabel('terminal'),
        context: humanizeToolContextPt(preview)
      };
    }
    return {
      kind: legacyKind,
      context: humanizeToolContextPt(preview)
    };
  }
  if (toolName) {
    const {
      kind
    } = formatToolCallParts(toolName, '');
    const modern = formatToolCall(toolName, call);
    if (call === kind || call === modern) {
      return {
        kind,
        context: call === kind ? '' : call
      };
    }
    return {
      kind,
      context: humanizeToolContextPt(call)
    };
  }
  const inferredKind = inferKindFromCallLabel(call);
  if (inferredKind && inferredKind === call) {
    return {
      kind: inferredKind,
      context: ''
    };
  }
  return {
    kind: inferredKind || GENERIC_TOOL_KIND,
    context: humanizeToolContextPt(call)
  };
};
/** `terminal: git status` — resumo técnico colapsável na linha secundária. */
export const isToolTechnicalSubline = line => /^[a-z][\w]*:\s/.test(line.trim());
/** Linhas para o painel Ferramentas: título = o que está a fazer; subtítulo = resumo técnico. */
export const toolCallDisplayLines = (toolName, call, detail = '', technical = '') => {
  const tech = (technical || detail).trim();
  const callIsTechnical = isToolTechnicalSubline(call);
  const techIsTechnical = isToolTechnicalSubline(tech);
  const {
    kind,
    context
  } = resolveToolCallPartsFromResult(toolName, callIsTechnical ? '' : call, techIsTechnical ? '' : detail);
  const note = techIsTechnical ? '' : detail.trim();
  const genericKind = kind === GENERIC_TOOL_KIND;
  let headline = context || (!genericKind ? kind : call) || kind;
  if (callIsTechnical || techIsTechnical && !context) {
    const fromTech = headlineFromTechnicalLine(toolName, tech || call);
    headline = context || fromTech || kind;
  }
  if (headline && headline !== kind && !callIsTechnical) {
    headline = humanizeToolContextPt(headline);
  }
  let subline = '';
  if (tech && isToolTechnicalSubline(tech)) {
    subline = tech;
  } else if (note && note !== context && note !== headline) {
    subline = note;
  }
  if (subline === headline) {
    subline = '';
  }
  return {
    headline,
    subline
  };
};
/** Título humano + linha técnica para um passo do painel Ferramentas. */
export const toolStepDisplay = (toolName, callLabel, tech, parsedDetail = '') => {
  const callForDisplay = isToolTechnicalSubline(callLabel) ? '' : callLabel;
  return toolCallDisplayLines(toolName, callForDisplay, isToolTechnicalSubline(tech) ? '' : parsedDetail, tech);
};
const inferKindFromCallLabel = call => {
  for (const label of Object.values(TOOL_LABELS_PT)) {
    if (call === label) {
      return label;
    }
  }
  if (call === LEGACY_TERMINAL_KIND || call.startsWith(`${LEGACY_TERMINAL_KIND}(`) || LEGACY_TERMINAL_KINDS.has(call)) {
    return toolKindLabel('terminal');
  }
  return '';
};
const TOOL_TRAIL_TECHNICAL_MAX = 160;
export const buildToolTrailLine = (name, context, error, note, duration) => {
  const call = formatToolCall(name, context);
  const noteTrim = (note ?? '').trim();
  const detail = noteTrim ? isToolTechnicalSubline(noteTrim) ? compactPreview(noteTrim, TOOL_TRAIL_TECHNICAL_MAX) : compactPreview(noteTrim, 72) : '';
  const took = duration !== undefined ? ` (${duration.toFixed(1)}s)` : '';
  const includeDetail = Boolean(detail && detail !== call);
  return `${call}${took}${includeDetail ? ` :: ${detail}` : ''} ${error ? '✗' : '✓'}`;
};
export const isToolTrailResultLine = line => line.endsWith(' ✓') || line.endsWith(' ✗');
export const inferToolNameFromTechnical = line => {
  const match = line.trim().match(/^([a-z][\w]*):/i);
  return match?.[1];
};
export const parseToolTrailResultLine = line => {
  if (!isToolTrailResultLine(line)) {
    return null;
  }
  const mark = line.endsWith(' ✗') ? '✗' : '✓';
  const body = line.slice(0, -2).trimEnd();
  const [call, detail] = body.split(' :: ', 2);
  if (detail != null) {
    const toolName = inferToolNameFromTechnical(detail) ?? inferToolNameFromTechnical(call);
    return {
      call,
      detail,
      mark,
      toolName
    };
  }
  const legacy = body.indexOf(': ');
  if (legacy > 0) {
    const head = body.slice(0, legacy).trim();
    const tail = body.slice(legacy + 2).trim();
    // `terminal: git status ✓` (sem ` :: `) — linha inteira é resumo técnico
    if (/^[a-z][\w]*$/i.test(head) && tail) {
      return {
        call: '',
        detail: body,
        mark,
        toolName: head
      };
    }
    return {
      call: head,
      detail: tail,
      mark
    };
  }
  return {
    call: body,
    detail: '',
    mark
  };
};
export const splitToolDuration = call => {
  const match = call.match(/^(.*?)( \(\d+(?:\.\d)?s\))$/);
  return match ? {
    label: match[1],
    duration: match[2]
  } : {
    label: call,
    duration: ''
  };
};
export const isAnalyzingToolOutputLine = line => line === 'analyzing tool output…' || line === 'Analisando saída da ferramenta…';
export const isTransientTrailLine = line => line.startsWith('drafting ') || line.startsWith('Rascunhando ') || isAnalyzingToolOutputLine(line);
const sameToolTrailGroupLegacy = (label, entry) => entry === `${label} ✓` || entry === `${label} ✗` || entry.startsWith(`${label}(`) || entry.startsWith(`${label} ::`) || entry.startsWith(`${label}:`);
const sameToolTrailGroupByTool = (name, context, entry) => {
  const label = toolKindLabel(name);
  const preview = compactPreview(context, 64);
  const modern = formatToolCall(name, context);
  const legacyFull = preview ? `${label}("${preview}")` : label;
  const legacyTerminal = (name === 'terminal' || name === 'shell') && preview ? `${LEGACY_TERMINAL_KIND}("${preview}")` : '';
  const markLen = entry.endsWith(' ✓') || entry.endsWith(' ✗') ? 2 : 0;
  const body = markLen ? entry.slice(0, -markLen) : entry;
  const [call] = body.split(' :: ', 2);
  const callNoDur = call.replace(/\s+\(\d+(?:\.\d+)?s\)\s*$/, '').trim();
  if (sameToolTrailGroupLegacy(label, entry)) {
    return true;
  }
  const normalizedEntry = humanizeToolContextPt(callNoDur);
  const normalizedModern = humanizeToolContextPt(modern);
  return callNoDur === modern || normalizedEntry === normalizedModern || callNoDur === legacyFull || legacyTerminal !== '' && callNoDur === legacyTerminal;
};
export function sameToolTrailGroup(a, b, c) {
  if (c !== undefined) {
    return sameToolTrailGroupByTool(a, b, c);
  }
  return sameToolTrailGroupLegacy(a, b);
}
/* eslint-enable no-redeclare */
export const lastCotTrailIndex = trail => {
  for (let i = trail.length - 1; i >= 0; i--) {
    if (!isToolTrailResultLine(trail[i])) {
      return i;
    }
  }
  return -1;
};
export const estimateRows = (text, w, compact = false) => {
  let fence = null;
  let rows = 0;
  for (const raw of text.split('\n')) {
    const line = stripAnsi(raw);
    const maybeFence = line.match(/^\s*(`{3,}|~{3,})(.*)$/);
    if (maybeFence) {
      const marker = maybeFence[1];
      const lang = maybeFence[2].trim();
      if (!fence) {
        fence = {
          char: marker[0],
          len: marker.length
        };
        if (lang) {
          rows += Math.ceil((lang.length || 1) / w);
        }
      } else if (marker[0] === fence.char && marker.length >= fence.len) {
        fence = null;
      }
      continue;
    }
    const inCode = Boolean(fence);
    const trimmed = line.trim();
    if (!inCode && trimmed.startsWith('|') && /^[|\s:-]+$/.test(trimmed)) {
      continue;
    }
    const rendered = inCode ? line : renderEstimateLine(line);
    if (compact && !rendered.trim()) {
      continue;
    }
    rows += Math.ceil((rendered.length || 1) / w);
  }
  return Math.max(1, rows);
};
export const flat = r => Object.values(r).flat();
const COMPACT_NUMBER = new Intl.NumberFormat('en-US', {
  maximumFractionDigits: 1,
  notation: 'compact'
});
export const fmtK = n => COMPACT_NUMBER.format(n).replace(/[KMBT]$/, s => s.toLowerCase());
export const pick = a => a[Math.floor(Math.random() * a.length)];
export const isPasteBackedText = text => /\[\[paste:\d+(?:[^\n]*?)\]\]|\[paste #\d+ (?:attached|excerpt)(?:[^\n]*?)\]/.test(text);