/** Rótulo de severidade em pt-BR para o prompt de aprovação. */
const SEVERITY_LABEL_PT = {
  CRITICAL: 'CRÍTICA',
  CRÍTICA: 'CRÍTICA',
  HIGH: 'ALTA',
  ALTA: 'ALTA',
  MEDIUM: 'MÉDIA',
  MÉDIA: 'MÉDIA',
  MEDIA: 'MÉDIA',
  MED: 'MÉDIA',
  LOW: 'BAIXA',
  BAIXA: 'BAIXA',
  WARN: 'AVISO',
  WARNING: 'AVISO',
  AVISO: 'AVISO',
  INFO: 'INFO'
};
/** Exibe severidade em português (aceita entrada já traduzida ou em inglês). */
export const severityDisplayLabel = sev => {
  const key = sev.trim().toUpperCase();
  return key ? SEVERITY_LABEL_PT[key] ?? sev.trim().toUpperCase() : '';
};