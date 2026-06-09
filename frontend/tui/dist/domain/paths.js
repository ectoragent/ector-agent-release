export const shortCwd = (cwd, max = 28) => {
  const h = process.env.HOME;
  const p = h && cwd.startsWith(h) ? `~${cwd.slice(h.length)}` : cwd;
  return p.length <= max ? p : `…${p.slice(-(max - 1))}`;
};
export const fmtCwdBranch = (cwd, branch, max = 40) => {
  if (!branch) {
    return shortCwd(cwd, max);
  }
  const tag = ` (${branch.length > 16 ? `…${branch.slice(-15)}` : branch})`;
  return `${shortCwd(cwd, Math.max(8, max - tag.length))}${tag}`;
};
const branchTagForStatus = (branch, maxInner = 20) => {
  const b = branch.trim();
  if (!b.length) {
    return '';
  }
  const inner = b.length <= maxInner ? b : `${b.slice(0, maxInner - 1)}…`;
  return ` (${inner})`;
};
/**
 * Caminho + branch para a barra de status (texto longo).
 * O truncamento visual fica no componente com `truncate-start`, preservando o fim (pasta + branch).
 */
export const statusBarCwd = (cwd, branch) => {
  const h = process.env.HOME;
  const p = h && cwd.startsWith(h) ? `~${cwd.slice(h.length)}` : cwd;
  const br = typeof branch === 'string' ? branch.trim() : '';
  if (!br) {
    return p;
  }
  return `${p}${branchTagForStatus(br)}`;
};
/**
 * Versão compacta do diretório atual: apenas o nome da pasta + branch.
 * Útil para hints inline onde o caminho completo polui visualmente.
 */
export const compactCwd = (cwd, branch) => {
  const trimmed = cwd.replace(/\/+$/, '');
  const seg = trimmed.split('/').filter(Boolean).pop() ?? (trimmed || '/');
  const br = typeof branch === 'string' ? branch.trim() : '';
  if (!br) {
    return seg;
  }
  return `${seg}${branchTagForStatus(br)}`;
};