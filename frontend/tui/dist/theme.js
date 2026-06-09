// ── Color math ───────────────────────────────────────────────────────
function parseHex(h) {
  const m = /^#?([0-9a-f]{6})$/i.exec(h);
  if (!m) {
    return null;
  }
  const n = parseInt(m[1], 16);
  return [n >> 16 & 0xff, n >> 8 & 0xff, n & 0xff];
}
function mix(a, b, t) {
  const pa = parseHex(a);
  const pb = parseHex(b);
  if (!pa || !pb) {
    return a;
  }
  const lerp = i => Math.round(pa[i] + (pb[i] - pa[i]) * t);
  return '#' + (1 << 24 | lerp(0) << 16 | lerp(1) << 8 | lerp(2)).toString(16).slice(1);
}
// ── Defaults ─────────────────────────────────────────────────────────
const BRAND = {
  name: 'ECTOR',
  icon: '✦',
  prompt: '✦',
  welcome: 'Escreva em português ou use /help para ver comandos.',
  goodbye: 'Até logo!',
  tool: '┊',
  helpHeader: 'Comandos disponíveis'
};
import { ECTOR_ACCENT, ECTOR_LEGACY_ACCENT_HEX, ECTOR_SELECTION_BG, ECTOR_WEB_BG, ECTOR_WEB_BORDER, ECTOR_WEB_CARD, ECTOR_WEB_CODE_BG, ECTOR_WEB_COMPOSER_BG, ECTOR_WEB_FG, ECTOR_WEB_MID, ECTOR_WEB_MUTED, ECTOR_WEB_SURFACE } from './themeTokens.js';
const WEB_BG = ECTOR_WEB_BG;
const WEB_ACCENT = ECTOR_ACCENT;
const WEB_FG = ECTOR_WEB_FG;
const WEB_MID = ECTOR_WEB_MID;
const WEB_MUTED = ECTOR_WEB_MUTED;
const WEB_COMPOSER_BG = ECTOR_WEB_COMPOSER_BG;
const WEB_CODE_BG = ECTOR_WEB_CODE_BG;
const WEB_SURFACE = ECTOR_WEB_SURFACE;
const WEB_CARD = ECTOR_WEB_CARD;
const WEB_BORDER = ECTOR_WEB_BORDER;
const WEB_FOOTER_MUTED = '#B8B2AC';
const WEB_ERROR = '#EF4444';
const WEB_WARN = '#F59E0B';
const WEB_OK = '#22c55e';
/** Syntax highlight em fences markdown (paleta GitHub dark; fundo = WEB_CODE_BG). */
const ECTOR_CODE_FG = '#e6edf3';
const ECTOR_CODE_COMMENT = '#7d8590';
const ECTOR_CODE_KEYWORD = '#ff7b72';
const ECTOR_CODE_STRING = '#a5d6ff';
const ECTOR_CODE_NUMBER = '#d2a8ff';
const ECTOR_CODE_LANG = '#79c0ff';
export const DARK_THEME = {
  color: {
    title: WEB_FG,
    cyan: WEB_ACCENT,
    border: WEB_BORDER,
    text: WEB_FG,
    dim: WEB_MUTED,
    completionBg: WEB_CODE_BG,
    completionCurrentBg: WEB_SURFACE,
    label: WEB_MID,
    ok: WEB_OK,
    error: WEB_ERROR,
    warn: WEB_WARN,
    prompt: WEB_FG,
    sessionLabel: WEB_MUTED,
    sessionBorder: WEB_BORDER,
    statusBg: WEB_BG,
    statusFg: WEB_FG,
    statusGood: WEB_ACCENT,
    statusWarn: WEB_WARN,
    statusBad: WEB_ERROR,
    statusCritical: '#991b1b',
    // Seleção sutil no fundo escuro (Ink aceita rgba como string).
    selectionBg: ECTOR_SELECTION_BG,
    // Dark-theme diff palette: deep muted bg tinted with the success/error
    // hues (à la GitHub dark), with brighter foreground for the changed
    // words so they still pop on the dark transcript surface.
    diffAdded: mix(WEB_BG, WEB_OK, 0.18),
    diffRemoved: mix(WEB_BG, WEB_ERROR, 0.18),
    diffAddedWord: mix(WEB_OK, WEB_FG, 0.25),
    diffRemovedWord: mix(WEB_ERROR, WEB_FG, 0.25),
    shellDollar: WEB_ACCENT,
    composerBorder: WEB_BORDER,
    composerSurface: WEB_COMPOSER_BG,
    /** Same as composerSurface — avoids a seam between input and footer in OpenTUI. */
    composerChrome: WEB_COMPOSER_BG,
    inputPlaceholder: mix(WEB_FOOTER_MUTED, WEB_BG, 0.45),
    statusBarSubtle: WEB_FOOTER_MUTED,
    statusBarMeta: WEB_FOOTER_MUTED,
    statusReady: WEB_ACCENT,
    transcriptCardBg: WEB_CARD,
    transcriptCardBorder: WEB_BORDER,
    bubbleUserBg: '#202020',
    bubbleAssistantBg: WEB_SURFACE,
    bubbleUserBorder: WEB_ACCENT,
    bubbleAssistantBorder: mix(WEB_ACCENT, WEB_BORDER, 0.15),
    codeBg: WEB_CODE_BG,
    codeFg: ECTOR_CODE_FG,
    codeComment: ECTOR_CODE_COMMENT,
    codeKeyword: ECTOR_CODE_KEYWORD,
    codeString: ECTOR_CODE_STRING,
    codeNumber: ECTOR_CODE_NUMBER,
    codeLineNum: ECTOR_CODE_COMMENT,
    codeLangLabel: ECTOR_CODE_LANG
  },
  brand: BRAND,
  bannerLogo: '',
  bannerHero: ''
};
/** TUI is dark-only; kept for tests that still import the name. */
export const LIGHT_THEME = DARK_THEME;
/** @deprecated Light mode removed — always false. ECTOR_TUI_LIGHT is ignored. */
export function detectLightMode(_env = process.env) {
  return false;
}
export const DEFAULT_THEME = DARK_THEME;
// ── Skin → Theme ─────────────────────────────────────────────────────
export function fromSkin(colors, branding, bannerLogo = '', bannerHero = '', toolPrefix = '', helpHeader = '') {
  const d = DEFAULT_THEME;
  const c = k => colors[k];
  const normAccent = v => {
    const x = (v ?? '').trim();
    if (!x) {
      return undefined;
    }
    if (ECTOR_LEGACY_ACCENT_HEX.has(x.toLowerCase())) {
      return ECTOR_ACCENT;
    }
    return x;
  };
  const normSelection = v => {
    const x = (v ?? '').trim();
    if (!x) {
      return undefined;
    }
    if (x === 'rgba(14,165,233,0.14)' || x === 'rgba(0,209,255,0.14)' || x === 'rgba(33,173,228,0.14)') {
      return ECTOR_SELECTION_BG;
    }
    return x;
  };
  // Mantém o TUI com um único "primário" (ciano). A skin pode tentar
  // sobrescrever o accent; normalizamos e garantimos consistência.
  const cyan = normAccent(c('ui_accent')) ?? normAccent(c('banner_accent')) ?? d.color.cyan;
  const dim = c('banner_dim') ?? d.color.dim;
  return {
    color: {
      title: c('banner_title') ?? d.color.title,
      cyan,
      border: c('banner_border') ?? d.color.border,
      text: c('banner_text') ?? d.color.text,
      dim,
      completionBg: c('completion_menu_bg') ?? d.color.completionBg,
      completionCurrentBg: c('completion_menu_current_bg') ?? d.color.completionCurrentBg,
      label: c('ui_label') ?? d.color.label,
      ok: c('ui_ok') ?? d.color.ok,
      error: c('ui_error') ?? d.color.error,
      warn: c('ui_warn') ?? d.color.warn,
      prompt: c('prompt') ?? c('banner_text') ?? d.color.prompt,
      sessionLabel: c('session_label') ?? dim,
      sessionBorder: c('session_border') ?? dim,
      statusBg: d.color.statusBg,
      statusFg: d.color.statusFg,
      statusGood: c('ui_ok') ?? d.color.statusGood,
      statusWarn: c('ui_warn') ?? d.color.statusWarn,
      statusBad: d.color.statusBad,
      statusCritical: d.color.statusCritical,
      selectionBg: normSelection(c('selection_bg')) ?? d.color.selectionBg,
      diffAdded: d.color.diffAdded,
      diffRemoved: d.color.diffRemoved,
      diffAddedWord: d.color.diffAddedWord,
      diffRemovedWord: d.color.diffRemovedWord,
      shellDollar: c('shell_dollar') ?? d.color.shellDollar,
      composerBorder: c('composer_border') ?? d.color.composerBorder,
      composerSurface: c('composer_surface') ?? d.color.composerSurface,
      composerChrome: c('composer_chrome') ?? d.color.composerChrome,
      inputPlaceholder: c('input_placeholder') ?? d.color.inputPlaceholder,
      statusBarSubtle: c('status_bar_subtle') ?? d.color.statusBarSubtle,
      statusBarMeta: c('status_bar_meta') ?? d.color.statusBarMeta,
      statusReady: c('status_ready') ?? d.color.statusReady,
      transcriptCardBg: c('transcript_card_bg') ?? d.color.transcriptCardBg,
      transcriptCardBorder: c('transcript_card_border') ?? d.color.transcriptCardBorder,
      bubbleUserBg: c('bubble_user_bg') ?? d.color.bubbleUserBg,
      bubbleAssistantBg: c('bubble_assistant_bg') ?? d.color.bubbleAssistantBg,
      bubbleUserBorder: c('bubble_user_border') ?? d.color.bubbleUserBorder,
      bubbleAssistantBorder: c('bubble_assistant_border') ?? d.color.bubbleAssistantBorder,
      codeBg: c('code_bg') ?? d.color.codeBg,
      codeFg: c('code_fg') ?? d.color.codeFg,
      codeComment: c('code_comment') ?? d.color.codeComment,
      codeKeyword: c('code_keyword') ?? d.color.codeKeyword,
      codeString: c('code_string') ?? d.color.codeString,
      codeNumber: c('code_number') ?? d.color.codeNumber,
      codeLineNum: c('code_line_num') ?? d.color.codeLineNum,
      codeLangLabel: c('code_lang_label') ?? d.color.codeLangLabel
    },
    brand: {
      name: branding.agent_name ?? d.brand.name,
      icon: d.brand.icon,
      prompt: branding.prompt_symbol ?? d.brand.prompt,
      welcome: branding.welcome ?? d.brand.welcome,
      goodbye: branding.goodbye ?? d.brand.goodbye,
      tool: toolPrefix || d.brand.tool,
      helpHeader: branding.help_header ?? (helpHeader || d.brand.helpHeader)
    },
    bannerLogo,
    bannerHero
  };
}