/**
 * Canonical ECTOR palette — shared by Ink TUI and web dashboard.
 * Dashboard imports this file via Vite alias `@ector/theme-tokens`.
 *
 * Alinhado à paleta do dashboard web (prints de referência).
 */
export const ECTOR_ACCENT = '#21ADE4';
/** Primary on light backgrounds — same hue as {@link ECTOR_ACCENT}. */
export const ECTOR_ACCENT_LIGHT = ECTOR_ACCENT;
export const ECTOR_ACCENT_GLOW_DARK = 'rgba(33, 173, 228, 0.25)';
export const ECTOR_ACCENT_GLOW_LIGHT = 'rgba(33, 173, 228, 0.14)';
export const ECTOR_SECONDARY_ACCENT = '#38BDF8';
export const ECTOR_SECONDARY_ACCENT_LIGHT = '#45C5EB';
export const ECTOR_WARM_GLOW_DARK = 'rgba(33, 173, 228, 0.20)';
export const ECTOR_WARM_GLOW_LIGHT = 'rgba(33, 173, 228, 0.08)';
/** Ink TUI `selectionBg` — active row / list highlight. */
export const ECTOR_SELECTION_BG = 'rgba(33, 173, 228, 0.16)';
export const ECTOR_SELECTION_BG_LIGHT = 'rgba(33, 173, 228, 0.12)';
/** Subtle primary tint for icon badges and chips (not full `bg-primary`). */
export const ECTOR_PRIMARY_MUTED_BG = 'rgba(33, 173, 228, 0.10)';
export const ECTOR_PRIMARY_MUTED_BG_LIGHT = 'rgba(33, 173, 228, 0.08)';
/** Dashboard sidebar — item ativo: ciano sólido (texto branco via `text-primary-foreground`). */
export const ECTOR_SIDEBAR_ACTIVE_BG = ECTOR_ACCENT;
export const ECTOR_SIDEBAR_HOVER_BG = 'rgba(33, 173, 228, 0.12)';
export const ECTOR_SIDEBAR_BORDER_DARK = 'rgba(148, 163, 184, 0.12)';
export const ECTOR_SIDEBAR_BORDER_LIGHT = '#E5E7EB';
export const ECTOR_SIDEBAR_LABEL_DARK = '#FFFFFF';
export const ECTOR_SIDEBAR_LABEL_LIGHT = '#475569';
export const ECTOR_SIDEBAR_FG_MUTED_DARK = '#FFFFFF';
export const ECTOR_SIDEBAR_FG_MUTED_LIGHT = '#334155';
export const ECTOR_SIDEBAR_HOVER_BG_LIGHT = 'rgba(33, 173, 228, 0.07)';
/** @deprecated Use {@link ECTOR_SIDEBAR_BORDER_DARK} or theme-specific border in dashboard. */
export const ECTOR_SIDEBAR_BORDER = ECTOR_SIDEBAR_BORDER_DARK;
/** @deprecated Use {@link ECTOR_SIDEBAR_LABEL_DARK} or theme-specific label in dashboard. */
export const ECTOR_SIDEBAR_LABEL = ECTOR_SIDEBAR_LABEL_DARK;
/** @deprecated Use {@link ECTOR_SIDEBAR_FG_MUTED_DARK} or theme-specific muted in dashboard. */
export const ECTOR_SIDEBAR_FG_MUTED = ECTOR_SIDEBAR_FG_MUTED_DARK;
export const ECTOR_WEB_BG = '#060B13';
export const ECTOR_WEB_FG = '#FFFFFF';
export const ECTOR_WEB_MID = '#94A3B8';
export const ECTOR_WEB_MUTED = '#94A3B8';
export const ECTOR_WEB_BORDER = '#1E293B';
export const ECTOR_WEB_SURFACE = '#121620';
export const ECTOR_WEB_CARD = '#121620';
export const ECTOR_WEB_COMPOSER_BG = '#121620';
export const ECTOR_WEB_CODE_BG = '#121620';
export const ECTOR_WEB_SURFACE_HOVER = '#1A2332';
/** Ink TUI `statusBarMeta` / composer footer — warmer than UI muted. */
export const ECTOR_WEB_FOOTER_MUTED_DARK = '#B8B2AC';
export const ECTOR_WEB_FOOTER_MUTED_LIGHT = '#57534E';
export const ECTOR_WEB_BG_LIGHT = '#FFFFFF';
export const ECTOR_WEB_FG_LIGHT = '#1A1A1A';
export const ECTOR_WEB_MUTED_LIGHT = '#3F3F46';
export const ECTOR_WEB_BORDER_LIGHT = '#D1D5DB';
/** Hairline borders on light panels (tool cards, chips). */
export const ECTOR_WEB_BORDER_SUBTLE_LIGHT = '#E5E9EF';
export const ECTOR_WEB_CARD_LIGHT = '#FFFFFF';
/** Panels/cards on light canvas — stronger separation than canvas bg. */
export const ECTOR_WEB_SURFACE_LIGHT = '#F6F8FA';
/** Config modal nav — softer than {@link ECTOR_WEB_SURFACE_LIGHT}. */
export const ECTOR_CONFIG_NAV_BG_LIGHT = '#F6F8FA';
/** Form controls on light panels — white fill on card/modal. */
export const ECTOR_FIELD_BG_LIGHT = '#FFFFFF';
/** Gateway/channel status pills on light UI (ex. «Parado»). */
export const ECTOR_STATUS_PILL_BG_LIGHT = '#F3F4F6';
export const ECTOR_STATUS_PILL_FG_LIGHT = '#4B5563';
export const ECTOR_WEB_SURFACE_HOVER_LIGHT = '#EEF1F5';
export const ECTOR_WEB_CODE_BG_LIGHT = '#F0F3F6';
export const ECTOR_SUCCESS_LIGHT = '#24915b';
export const ECTOR_SUCCESS_BG_LIGHT = '#D1E7D9';
export const ECTOR_SUCCESS_BORDER_LIGHT = 'rgba(4, 120, 87, 0.18)';
export const ECTOR_SUCCESS_DARK = '#10B981';
/**
 * Tone-on-tone chips (light theme) — soft desaturated bg + dark fg.
 * Success bg is the reference chroma/lightness for the other variants.
 */
export const ECTOR_CHIP_PRIMARY_BG_LIGHT = '#D1E3EB';
export const ECTOR_CHIP_PRIMARY_FG_LIGHT = '#0B5270';
export const ECTOR_CHIP_SUCCESS_BG_LIGHT = '#D1E7D9';
export const ECTOR_CHIP_SUCCESS_FG_LIGHT = '#24915b';
export const ECTOR_CHIP_DESTRUCTIVE_BG_LIGHT = '#E7D1D5';
export const ECTOR_CHIP_DESTRUCTIVE_FG_LIGHT = '#8B2E35';
export const ECTOR_CHIP_WARNING_BG_LIGHT = '#E7E2D1';
export const ECTOR_CHIP_WARNING_FG_LIGHT = '#7A5C18';
export const ECTOR_CHIP_NEUTRAL_BG_LIGHT = '#E3E4E6';
export const ECTOR_CHIP_NEUTRAL_FG_LIGHT = '#3F4246';
/** Shadcn `secondary` / `accent` surfaces. */
export const ECTOR_THEME_SECONDARY_SURFACE_DARK = ECTOR_WEB_SURFACE;
export const ECTOR_THEME_ACCENT_SURFACE_DARK = ECTOR_WEB_SURFACE_HOVER;
export const ECTOR_THEME_SECONDARY_SURFACE_LIGHT = '#E0F2FE';
export const ECTOR_THEME_ACCENT_SURFACE_LIGHT = '#E0F2FE';
/** Legacy accent hex values normalized to {@link ECTOR_ACCENT}. */
export const ECTOR_LEGACY_ACCENT_HEX = new Set(['#0ea5e9', '#00d1ff', '#21ade4', '#00b8e6', '#00B8E6', '#26a6d1']);