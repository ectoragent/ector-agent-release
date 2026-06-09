/** Rótulo curto da linguagem exibido acima do bloco de código (fora do container). */
const FENCE_LANG_DISPLAY = {
  bash: 'BASH',
  diff: 'DIFF',
  go: 'GO',
  javascript: 'JS',
  js: 'JS',
  json: 'JSON',
  jsonc: 'JSON',
  markdown: 'MD',
  md: 'MD',
  plaintext: 'TEXT',
  py: 'PY',
  php: 'PHP',
  python: 'PY',
  java: 'JAVA',
  kotlin: 'KT',
  kt: 'KT',
  ruby: 'RB',
  rb: 'RUBY',
  cpp: 'C++',
  c: 'C',
  css: 'CSS',
  html: 'HTML',
  xml: 'XML',
  rs: 'RUST',
  rust: 'RUST',
  sh: 'SH',
  shell: 'SH',
  sql: 'SQL',
  text: 'TEXT',
  ts: 'TS',
  tsx: 'TSX',
  typescript: 'TS',
  txt: 'TEXT',
  yaml: 'YAML',
  yml: 'YAML',
  zsh: 'ZSH'
};
export const fenceLangDisplayLabel = lang => {
  const key = lang.trim().toLowerCase().split(/\s+/)[0] ?? '';
  return key ? FENCE_LANG_DISPLAY[key] ?? key.toUpperCase() : '';
};
/** Cabeçalho acima do bloco fenced (ex.: "Código TS"). */
export const fenceCodeHeaderText = lang => {
  const label = fenceLangDisplayLabel(lang);
  return label ? `Código ${label}` : '';
};