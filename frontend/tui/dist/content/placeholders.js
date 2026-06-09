import { pick } from '../lib/text.js';
export const PLACEHOLDERS = ['Digite sua mensagem ou /help…', 'Em que posso ajudar?', 'Pergunte o que quiser…', 'Descreva o que precisa…', '/help — comandos e atalhos', 'Peça ideias, um plano ou um exemplo…', 'Cole código ou texto para analisar…'];
export const PLACEHOLDER = pick(PLACEHOLDERS);
/** Shown in the composer while a turn is in flight. */
export const BUSY_INTERRUPT_PLACEHOLDER = 'Esc para interromper…';