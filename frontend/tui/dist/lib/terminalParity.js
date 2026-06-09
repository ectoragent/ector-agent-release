import { detectVSCodeLikeTerminal, isRemoteShellSession, shouldPromptForTerminalSetup } from './terminalSetup.js';
export function detectMacTerminalContext(env = process.env) {
  const termProgram = env['TERM_PROGRAM'] ?? '';
  return {
    isAppleTerminal: termProgram === 'Apple_Terminal' || !!env['TERM_SESSION_ID'],
    isRemote: isRemoteShellSession(env),
    isTmux: !!env['TMUX'],
    vscodeLike: detectVSCodeLikeTerminal(env)
  };
}
export async function terminalParityHints(env = process.env, options) {
  const ctx = detectMacTerminalContext(env);
  const hints = [];
  if (ctx.vscodeLike && (await shouldPromptForTerminalSetup({
    env,
    fileOps: options?.fileOps,
    homeDir: options?.homeDir
  }))) {
    hints.push({
      key: 'ide-setup',
      tone: 'info',
      message: `Detected ${ctx.vscodeLike} terminal · run /terminal-setup for best Cmd+Enter / undo parity`
    });
  }
  if (ctx.isAppleTerminal) {
    hints.push({
      key: 'apple-terminal',
      tone: 'warn',
      message: 'Apple Terminal detected · use /paste for image-only clipboard fallback, and try Ctrl+A / Ctrl+E / Ctrl+U if Cmd+←/→/⌫ gets rewritten'
    });
  }
  if (ctx.isTmux) {
    hints.push({
      key: 'tmux',
      tone: 'warn',
      message: 'tmux detected · clipboard copy/paste uses passthrough when available; allow-passthrough improves OSC52 reliability'
    });
  }
  if (ctx.isRemote) {
    hints.push({
      key: 'remote',
      tone: 'warn',
      message: 'SSH session detected · text clipboard can bridge via OSC52, but image clipboard and local screenshot paths still depend on the machine running Ector'
    });
  }
  return hints;
}