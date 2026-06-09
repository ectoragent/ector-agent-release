export const OPTS = ['once', 'session', 'always', 'deny'];
export const LABELS = {
  always: 'Permitir sempre',
  deny: 'Negar',
  once: 'Permitir uma vez',
  session: 'Permitir nesta sessão'
};
export const OPT_HINTS = {
  always: 'aprova este padrão em todas as sessões',
  deny: 'rejeita e informa o agente para não tentar de novo',
  once: 'libera apenas a próxima execução',
  session: 'libera por toda esta sessão'
};
export const CMD_PREVIEW_LINES = 10;