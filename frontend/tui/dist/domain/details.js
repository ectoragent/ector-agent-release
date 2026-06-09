const MODES = ['hidden', 'collapsed', 'expanded'];
export const SECTION_NAMES = ['thinking', 'tools', 'subagents', 'activity'];
// Out-of-the-box per-section defaults — applied when the user hasn't pinned
// an explicit override and layered ABOVE the global details_mode:
//
//   - thinking: hidden — chain-of-thought is opt-in; the default chat reads
//     as final answers + tool calls only (`/details thinking expanded` to
//     stream it again).
//   - tools: expanded — tool calls stay visible in the live transcript.
//   - activity: hidden — ambient meta (gateway hints, terminal-parity
//     nudges, background notifications) is noise for typical use.  Tool
//     failures still render inline on the failing tool row, and ambient
//     errors/warnings surface via the floating-alert backstop when every
//     panel resolves to hidden.
//   - subagents: not set — falls through to the global details_mode so
//     Spawn trees stay under a chevron until a delegation actually happens.
//
// Opt out of any of these with `display.sections.<name>` in config.yaml
// or at runtime via `/details <name> collapsed|hidden`.
const SECTION_DEFAULTS = {
  thinking: 'hidden',
  tools: 'expanded',
  activity: 'hidden'
};
const THINKING_FALLBACK = {
  collapsed: 'collapsed',
  full: 'expanded',
  truncated: 'collapsed'
};
const norm = v => String(v ?? '').trim().toLowerCase();
export const parseDetailsMode = v => MODES.find(m => m === norm(v)) ?? null;
export const isSectionName = v => typeof v === 'string' && SECTION_NAMES.includes(v);
export const resolveDetailsMode = d => parseDetailsMode(d?.details_mode) ?? THINKING_FALLBACK[norm(d?.thinking_mode)] ?? 'collapsed';
// Build SectionVisibility from a free-form blob.  Unknown section names and
// invalid modes are dropped silently — partial overrides are intentional, so
// missing keys fall through to SECTION_DEFAULTS / global at lookup time.
export const resolveSections = raw => raw && typeof raw === 'object' && !Array.isArray(raw) ? Object.fromEntries(Object.entries(raw).map(([k, v]) => [k, parseDetailsMode(v)]).filter(([k, m]) => !!m && isSectionName(k))) : {};
// Effective mode for one section: explicit override → global command mode →
// built-in live-stream defaults → global config mode.
//
// The `commandOverride` flag is set for in-session `/details <mode>` changes.
// That command should immediately apply to every section, including sections
// with built-in defaults like tools=expanded, thinking=hidden, activity=hidden. On
// startup/config sync we keep those defaults layered above the persisted global
// config unless the user pins explicit per-section overrides.
export const sectionMode = (name, global, sections, commandOverride = false) => sections?.[name] ?? (commandOverride ? global : SECTION_DEFAULTS[name] ?? global);
export const nextDetailsMode = m => MODES[(MODES.indexOf(m) + 1) % MODES.length];