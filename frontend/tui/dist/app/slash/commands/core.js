import { NO_CONFIRM_DESTRUCTIVE } from '../../../config/env.js';
import { dailyFortune, randomFortune } from '../../../content/fortunes.js';
import { HOTKEYS } from '../../../content/hotkeys.js';
import { strings } from '../../../content/strings.js';
import { STATUS } from '../../../content/uiStatus.js';
import { isSectionName, nextDetailsMode, parseDetailsMode, SECTION_NAMES } from '../../../domain/details.js';
import { copyTextToSystemClipboard } from '../../../lib/clipboard.js';
import { configureDetectedTerminalKeybindings, configureTerminalKeybindings } from '../../../lib/terminalSetup.js';
import { patchOverlayState } from '../../overlayStore.js';
import { patchUiState } from '../../uiStore.js';
const flagFromArg = (arg, current) => {
  if (!arg) {
    return !current;
  }
  const mode = arg.trim().toLowerCase();
  if (mode === 'on') {
    return true;
  }
  if (mode === 'off') {
    return false;
  }
  if (mode === 'toggle') {
    return !current;
  }
  return null;
};
const RESET_WORDS = new Set(['reset', 'clear', 'default']);
const CYCLE_WORDS = new Set(['cycle', 'toggle']);
const DETAILS_USAGE = strings.slash.detailsUsage;
const DETAILS_SECTION_USAGE = strings.slash.detailsSectionUsage;
export const coreCommands = [{
  help: 'list commands + hotkeys',
  name: 'help',
  run: (_arg, ctx) => {
    const sections = (ctx.local.catalog?.categories ?? []).map(cat => ({
      rows: cat.pairs,
      title: cat.name
    }));
    if (ctx.local.catalog?.skillCount) {
      sections.push({
        text: `${ctx.local.catalog.skillCount} skill commands available — /skills to browse`
      });
    }
    sections.push({
      rows: [['/details [hidden|collapsed|expanded|cycle]', 'set global agent detail visibility mode'], ['/details <section> [hidden|collapsed|expanded|reset]', 'override one section (thinking/tools/subagents/activity)'], ['/fortune [random|daily]', 'show a random or daily local fortune']],
      title: 'TUI'
    }, {
      rows: HOTKEYS,
      title: 'Hotkeys'
    });
    ctx.transcript.panel(ctx.ui.theme.brand.helpHeader, sections);
  }
}, {
  aliases: ['exit', 'q'],
  help: 'exit ECTOR',
  name: 'quit',
  run: (_arg, ctx) => ctx.session.die()
}, {
  aliases: ['scroll'],
  help: 'toggle mouse/wheel tracking [on|off|toggle]',
  name: 'mouse',
  run: (arg, ctx) => {
    const current = ctx.ui.mouseTracking;
    const next = flagFromArg(arg, current);
    if (next === null) {
      return ctx.transcript.sys(strings.slash.mouseUsage);
    }
    patchUiState({
      mouseTracking: next
    });
    ctx.gateway.rpc('config.set', {
      key: 'mouse',
      value: next ? 'on' : 'off'
    }).catch(() => {});
    queueMicrotask(() => ctx.transcript.sys(strings.slash.mouseTracking(next)));
  }
}, {
  aliases: ['new'],
  help: 'start a new session',
  name: 'clear',
  run: (_arg, ctx, cmd) => {
    if (ctx.session.guardBusySessionSwitch('switch sessions')) {
      return;
    }
    const isNew = cmd.startsWith('/new');
    const commit = () => {
      patchUiState({
        status: STATUS.forgingSession
      });
      ctx.session.newSession(isNew ? 'new session started' : undefined);
    };
    if (NO_CONFIRM_DESTRUCTIVE) {
      return commit();
    }
    patchOverlayState({
      confirm: {
        cancelLabel: 'No, keep going',
        confirmLabel: isNew ? 'Yes, start a new session' : 'Yes, clear the session',
        danger: true,
        detail: 'This ends the current conversation and clears the transcript.',
        onConfirm: commit,
        title: isNew ? 'Start a new session?' : 'Clear the current session?'
      }
    });
  }
}, {
  help: 'resume a prior session',
  name: 'resume',
  run: (arg, ctx) => {
    if (ctx.session.guardBusySessionSwitch('switch sessions')) {
      return;
    }
    arg ? ctx.session.resumeById(arg) : patchOverlayState({
      picker: true
    });
  }
}, {
  help: 'toggle compact transcript',
  name: 'compact',
  run: (arg, ctx) => {
    const next = flagFromArg(arg, ctx.ui.compact);
    if (next === null) {
      return ctx.transcript.sys(strings.slash.compactUsage);
    }
    patchUiState({
      compact: next
    });
    ctx.gateway.rpc('config.set', {
      key: 'compact',
      value: next ? 'on' : 'off'
    }).catch(() => {});
    queueMicrotask(() => ctx.transcript.sys(strings.slash.compact(next)));
  }
}, {
  aliases: ['detail'],
  help: 'control agent detail visibility (global or per-section)',
  name: 'details',
  run: (arg, ctx) => {
    const {
      gateway,
      transcript,
      ui
    } = ctx;
    if (!arg) {
      gateway.rpc('config.get', {
        key: 'details_mode'
      }).then(r => {
        if (ctx.stale()) {
          return;
        }
        const mode = parseDetailsMode(r?.value) ?? ui.detailsMode;
        patchUiState({
          detailsMode: mode,
          detailsModeCommandOverride: false
        });
        const overrides = SECTION_NAMES.filter(s => ui.sections[s]).map(s => `${s}=${ui.sections[s]}`).join(' ');
        transcript.sys(`details: ${mode}${overrides ? `  (${overrides})` : ''}`);
      }).catch(() => !ctx.stale() && transcript.sys(`details: ${ui.detailsMode}`));
      return;
    }
    const [first, second] = arg.trim().toLowerCase().split(/\s+/);
    if (second && isSectionName(first)) {
      const reset = RESET_WORDS.has(second);
      const mode = reset ? null : parseDetailsMode(second);
      if (!reset && !mode) {
        return transcript.sys(DETAILS_SECTION_USAGE);
      }
      const {
        [first]: _drop,
        ...rest
      } = ui.sections;
      patchUiState({
        sections: mode ? {
          ...rest,
          [first]: mode
        } : rest
      });
      gateway.rpc('config.set', {
        key: `details_mode.${first}`,
        value: mode ?? ''
      }).catch(() => {});
      transcript.sys(strings.slash.detailsSection(first, mode ?? 'reset'));
      return;
    }
    const next = CYCLE_WORDS.has(first ?? '') ? nextDetailsMode(ui.detailsMode) : parseDetailsMode(first);
    if (!next) {
      return transcript.sys(DETAILS_USAGE);
    }
    patchUiState({
      detailsMode: next,
      detailsModeCommandOverride: true
    });
    gateway.rpc('config.set', {
      key: 'details_mode',
      value: next
    }).catch(() => {});
    transcript.sys(`details: ${next}`);
  }
}, {
  help: 'local fortune',
  name: 'fortune',
  run: (arg, ctx) => {
    const key = arg.trim().toLowerCase();
    if (!arg || key === 'random') {
      return ctx.transcript.sys(randomFortune());
    }
    if (['daily', 'stable', 'today'].includes(key)) {
      return ctx.transcript.sys(dailyFortune(ctx.sid));
    }
    ctx.transcript.sys(strings.slash.fortuneUsage);
  }
}, {
  help: 'copy selection or assistant message',
  name: 'copy',
  run: async (arg, ctx) => {
    const {
      sys
    } = ctx.transcript;
    if (!arg && ctx.composer.hasSelection) {
      const text = await ctx.composer.selection.copySelection();
      if (text) {
        return sys(strings.slash.copiedChars(text.length));
      } else {
        return sys(strings.slash.copyFailed);
      }
    }
    if (arg && Number.isNaN(parseInt(arg, 10))) {
      return sys(strings.slash.copyUsage);
    }
    const all = ctx.local.getHistoryItems().filter(m => m.role === 'assistant');
    const target = all[arg ? Math.min(parseInt(arg, 10), all.length) - 1 : all.length - 1];
    if (!target) {
      return sys(strings.slash.nothingToCopy);
    }
    copyTextToSystemClipboard(target.text);
    return sys(strings.slash.copiedChars(target.text.length));
  }
}, {
  help: 'attach clipboard image',
  name: 'paste',
  run: (arg, ctx) => arg ? ctx.transcript.sys(strings.slash.pasteUsage) : ctx.composer.paste()
}, {
  help: 'configure IDE terminal keybindings for multiline + undo/redo',
  name: 'terminal-setup',
  run: (arg, ctx) => {
    const target = arg.trim().toLowerCase();
    if (target && !['auto', 'cursor', 'vscode', 'windsurf'].includes(target)) {
      return ctx.transcript.sys(strings.slash.terminalSetupUsage);
    }
    const runner = !target || target === 'auto' ? configureDetectedTerminalKeybindings() : configureTerminalKeybindings(target);
    void runner.then(result => {
      if (ctx.stale()) {
        return;
      }
      ctx.transcript.sys(result.message);
      if (result.success && result.requiresRestart) {
        ctx.transcript.sys(strings.slash.terminalRestartHint);
      }
    }).catch(error => {
      if (!ctx.stale()) {
        ctx.transcript.sys(strings.slash.terminalSetupFailed(String(error)));
      }
    });
  }
}, {
  help: 'view gateway logs',
  name: 'logs',
  run: (arg, ctx) => {
    const text = ctx.gateway.gw.getLogTail(Math.min(80, Math.max(1, parseInt(arg, 10) || 20)));
    text ? ctx.transcript.page(text, 'Logs') : ctx.transcript.sys(strings.slash.logsEmpty);
  }
}, {
  help: 'view current transcript (user + assistant messages)',
  name: 'history',
  run: (arg, ctx) => {
    // The CLI-side `/history` runs in a detached slash-worker subprocess
    // that never sees the TUI's turns — it only surfaces whatever was
    // persisted before this process started.  Render the TUI's own
    // transcript so `/history` actually reflects what the user just did.
    const items = ctx.local.getHistoryItems().filter(m => m.role === 'user' || m.role === 'assistant');
    if (!items.length) {
      return ctx.transcript.sys('ainda não há conversa');
    }
    const preview = Math.max(80, parseInt(arg, 10) || 400);
    const lines = items.map((m, i) => {
      const tag = m.role === 'user' ? `Você #${i + 1}` : `Assistente #${i + 1}`;
      const body = m.text.trim() || (m.tools?.length ? `(${m.tools.length} chamada${m.tools.length === 1 ? '' : 's'} de ferramenta)` : '(vazio)');
      const clipped = body.length > preview ? `${body.slice(0, preview).trimEnd()}…` : body;
      return `[${tag}]\n${clipped}`;
    });
    ctx.transcript.page(lines.join('\n\n'), 'Histórico');
  }
}, {
  help: 'save the current transcript to JSON',
  name: 'save',
  run: (_arg, ctx) => {
    const hasConversation = ctx.local.getHistoryItems().some(m => m.role === 'user' || m.role === 'assistant' || m.role === 'tool');
    if (!hasConversation) {
      return ctx.transcript.sys('ainda não há conversa');
    }
    if (!ctx.sid) {
      return ctx.transcript.sys('nenhuma sessão ativa — nada para salvar');
    }
    ctx.gateway.rpc('session.save', {
      session_id: ctx.sid
    }).then(ctx.guarded(r => {
      const file = r?.file;
      if (file) {
        ctx.transcript.sys(`conversa salva em: ${file}`);
      } else {
        ctx.transcript.sys('falha ao salvar');
      }
    })).catch(ctx.guardedErr);
  }
}, {
  aliases: ['sb'],
  help: 'barra de status: top = resumo acima + pasta/voz abaixo do input; bottom = ambas abaixo; off',
  name: 'statusbar',
  run: (arg, ctx) => {
    const mode = arg.trim().toLowerCase();
    const toggle = ctx.ui.statusBar === 'off' ? 'top' : 'off';
    const next = !mode || mode === 'toggle' ? toggle : mode === 'on' || mode === 'top' ? 'top' : mode === 'off' || mode === 'bottom' ? mode : null;
    if (!next) {
      return ctx.transcript.sys('uso: /statusbar [on|off|top|bottom|toggle]');
    }
    patchUiState({
      statusBar: next
    });
    ctx.gateway.rpc('config.set', {
      key: 'statusbar',
      value: next
    }).catch(() => {});
    queueMicrotask(() => ctx.transcript.sys(`barra de status: ${next}`));
  }
}, {
  help: 'inspect or enqueue a message',
  name: 'queue',
  run: (arg, ctx) => {
    if (!arg) {
      return ctx.transcript.sys(strings.slash.queueCount(ctx.composer.queueRef.current.length));
    }
    ctx.composer.enqueue(arg);
    ctx.transcript.sys(strings.slash.queueEnqueued(`${arg.slice(0, 50)}${arg.length > 50 ? '…' : ''}`));
  }
}, {
  help: 'inject a message after the next tool call (no interrupt)',
  name: 'steer',
  run: (arg, ctx) => {
    const payload = arg?.trim() ?? '';
    if (!payload) {
      return ctx.transcript.sys(strings.slash.steerUsage);
    }
    // If the agent isn't running, fall back to the queue so the user's
    // message isn't lost — identical semantics to the gateway handler.
    if (!ctx.ui.busy || !ctx.sid) {
      ctx.composer.enqueue(payload);
      ctx.transcript.sys(strings.session.steerNoTurn(`${payload.slice(0, 50)}${payload.length > 50 ? '…' : ''}`));
      return;
    }
    ctx.gateway.rpc('session.steer', {
      session_id: ctx.sid,
      text: payload
    }).then(ctx.guarded(r => {
      if (r?.status === 'queued') {
        ctx.transcript.sys(strings.session.steerQueued(`${payload.slice(0, 50)}${payload.length > 50 ? '…' : ''}`));
      } else {
        ctx.transcript.sys(strings.session.steerRejected);
      }
    })).catch(ctx.guardedErr);
  }
}, {
  help: 'undo last exchange',
  name: 'undo',
  run: (_arg, ctx) => {
    if (!ctx.sid) {
      return ctx.transcript.sys(strings.session.nothingToUndo);
    }
    ctx.gateway.rpc('session.undo', {
      session_id: ctx.sid
    }).then(ctx.guarded(r => {
      if ((r.removed ?? 0) > 0) {
        ctx.transcript.setHistoryItems(prev => ctx.transcript.trimLastExchange(prev));
        ctx.transcript.sys(strings.session.undidMessages(r.removed ?? 0));
      } else {
        ctx.transcript.sys(strings.session.nothingToUndo);
      }
    }));
  }
}, {
  help: 'retry last user message',
  name: 'retry',
  run: (_arg, ctx) => {
    const last = ctx.local.getLastUserMsg();
    if (!last) {
      return ctx.transcript.sys(strings.session.nothingToRetry);
    }
    if (!ctx.sid) {
      return ctx.transcript.send(last);
    }
    ctx.gateway.rpc('session.undo', {
      session_id: ctx.sid
    }).then(ctx.guarded(r => {
      if ((r.removed ?? 0) <= 0) {
        return ctx.transcript.sys(strings.session.nothingToRetry);
      }
      ctx.transcript.setHistoryItems(prev => ctx.transcript.trimLastExchange(prev));
      ctx.transcript.send(last);
    }));
  }
}];