export const THINK_SPIN_FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];
export const TOOL_SPIN_FRAMES = ['⠂', '⠄', '⠂', '⠁'];
export const SPIN_INTERVAL_MS = 80;
export const fmtElapsed = ms => {
  const sec = Math.max(0, ms) / 1000;
  return sec < 10 ? `${sec.toFixed(1)}s` : `${Math.round(sec)}s`;
};
export const nextTreeRails = (rails, branch) => [...rails, branch === 'mid'];
/** Rails passed into a panel body — drop the sentinel `false` from a closing section. */
export const treeItemRails = rails => rails.length > 0 && rails[rails.length - 1] === false ? rails.slice(0, -1) : rails;
export const treeLead = (rails, branch) => `${rails.map(on => on ? '│ ' : '  ').join('')}${branch === 'mid' ? '├ ' : '└ '}`;
/** Continuation gutter for a second line under the same branch (technical subline). */
export const treeSublineLead = (rails, branch) => {
  const spine = rails.map(on => on ? '│ ' : '  ').join('');
  const thru = branch === 'mid' ? '│ ' : '  ';
  return (spine + thru).padEnd(treeLead(rails, branch).length, ' ');
};
export function toolTrailRailColor(groupColor, t) {
  if (groupColor === t.color.error) {
    return t.color.error;
  }
  if (groupColor === t.color.warn) {
    return t.color.warn;
  }
  return t.color.cyan;
}