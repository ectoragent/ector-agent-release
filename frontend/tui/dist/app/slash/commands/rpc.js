export const rpcCommands = [{
  aliases: ['cfg'],
  help: 'show current configuration',
  name: 'config',
  run: (arg, ctx) => {
    if (arg.trim()) {
      return ctx.transcript.sys('usage: /config');
    }
    ctx.gateway.rpc('config.show', {
      session_id: ctx.sid
    }).then(ctx.guarded(r => {
      const sections = (r.sections ?? []).map(s => ({
        rows: s.rows,
        title: s.title
      }));
      ctx.transcript.panel('Config', sections.length ? sections : [{
        text: '(empty)'
      }]);
    })).catch(ctx.guardedErr);
  }
}, {
  help: 'list or manage cron jobs',
  name: 'cron',
  run: (arg, ctx) => {
    const parts = arg.trim().split(/\s+/).filter(Boolean);
    const sub = (parts[0] ?? 'list').toLowerCase();
    const {
      rpc
    } = ctx.gateway;
    if (sub === 'list' || sub === 'ls') {
      rpc('cron.manage', {
        action: 'list',
        session_id: ctx.sid
      }).then(ctx.guarded(r => {
        const jobs = r.jobs ?? [];
        if (!jobs.length) {
          return ctx.transcript.sys('no cron jobs');
        }
        ctx.transcript.panel('Cron jobs', [{
          rows: jobs.map(j => [j.name || j.id || '?', [j.schedule, j.status].filter(Boolean).join(' · ')])
        }]);
      })).catch(ctx.guardedErr);
      return;
    }
    ctx.transcript.sys('usage: /cron list');
  }
}, {
  help: 'git checkpoints — list, restore, diff',
  name: 'rollback',
  run: (arg, ctx) => {
    const parts = arg.trim().split(/\s+/).filter(Boolean);
    const sub = (parts[0] ?? 'list').toLowerCase();
    const {
      rpc
    } = ctx.gateway;
    const sid = ctx.sid;
    if (sub === 'list' || sub === 'ls' || !parts.length) {
      rpc('rollback.list', {
        session_id: sid
      }).then(ctx.guarded(r => {
        if (r.enabled === false) {
          return ctx.transcript.sys('rollback disabled for this session');
        }
        const cps = r.checkpoints ?? [];
        if (!cps.length) {
          return ctx.transcript.sys('no checkpoints');
        }
        ctx.transcript.panel('Checkpoints', [{
          rows: cps.map(c => [(c.hash ?? '').slice(0, 12), [c.timestamp, c.message].filter(Boolean).join(' · ')])
        }]);
      })).catch(ctx.guardedErr);
      return;
    }
    if (sub === 'restore' && parts[1]) {
      rpc('rollback.restore', {
        hash: parts[1],
        session_id: sid
      }).then(ctx.guarded(r => ctx.transcript.sys(r.success ? r.message || 'restored' : r.message || 'restore failed'))).catch(ctx.guardedErr);
      return;
    }
    if (sub === 'diff' && parts[1]) {
      rpc('rollback.diff', {
        hash: parts[1],
        session_id: sid
      }).then(ctx.guarded(r => {
        const body = r.rendered || r.diff || r.stat || '(no diff)';
        ctx.transcript.page(body, 'Rollback diff');
      })).catch(ctx.guardedErr);
      return;
    }
    ctx.transcript.sys('usage: /rollback [list|restore <hash>|diff <hash>]');
  }
}, {
  help: 'list installed plugins',
  name: 'plugins',
  run: (arg, ctx) => {
    if (arg.trim()) {
      return ctx.transcript.sys('usage: /plugins');
    }
    ctx.gateway.rpc('plugins.list', {
      session_id: ctx.sid
    }).then(ctx.guarded(r => {
      const plugins = r.plugins ?? [];
      if (!plugins.length) {
        return ctx.transcript.sys('no plugins installed');
      }
      ctx.transcript.panel('Plugins', [{
        rows: plugins.map(p => [p.enabled === false ? `✖ ${p.name}` : `✔ ${p.name}`, p.version ? `v${p.version}` : ''])
      }]);
    })).catch(ctx.guardedErr);
  }
}, {
  help: 'browser CDP connection',
  name: 'browser',
  run: (arg, ctx) => {
    const parts = arg.trim().split(/\s+/).filter(Boolean);
    const sub = (parts[0] ?? 'status').toLowerCase();
    const {
      rpc
    } = ctx.gateway;
    if (sub === 'status' || !parts.length) {
      rpc('browser.manage', {
        action: 'status',
        session_id: ctx.sid
      }).then(ctx.guarded(r => {
        const line = r.connected ? `browser connected${r.url ? `: ${r.url}` : ''}` : 'browser not connected';
        ctx.transcript.sys(line);
      })).catch(ctx.guardedErr);
      return;
    }
    if (sub === 'connect') {
      const url = parts[1] || 'http://localhost:9222';
      rpc('browser.manage', {
        action: 'connect',
        session_id: ctx.sid,
        url
      }).then(ctx.guarded(r => ctx.transcript.sys(r.message || (r.connected ? 'connected' : 'connect failed')))).catch(ctx.guardedErr);
      return;
    }
    if (sub === 'disconnect') {
      rpc('browser.manage', {
        action: 'disconnect',
        session_id: ctx.sid
      }).then(ctx.guarded(r => ctx.transcript.sys(r.message || 'disconnected'))).catch(ctx.guardedErr);
      return;
    }
    ctx.transcript.sys('usage: /browser [status|connect [url]|disconnect]');
  }
}, {
  help: 'active profile and ECTOR_HOME',
  name: 'profile',
  run: (arg, ctx) => {
    if (arg.trim()) {
      return ctx.transcript.sys('usage: /profile');
    }
    ctx.gateway.rpc('profile.show', {
      session_id: ctx.sid
    }).then(ctx.guarded(r => {
      if (r.sections?.length) {
        ctx.transcript.panel('Profile', r.sections);
      } else if (r.text) {
        ctx.transcript.sys(r.text);
      }
    })).catch(ctx.guardedErr);
  }
}, {
  aliases: ['gateway'],
  help: 'messaging gateway platform status',
  name: 'platforms',
  run: (arg, ctx) => {
    if (arg.trim()) {
      return ctx.transcript.sys('usage: /platforms');
    }
    ctx.gateway.rpc('platforms.status', {
      session_id: ctx.sid
    }).then(ctx.guarded(r => {
      const text = r.text || (r.rows ?? []).map(([a, b]) => `${a} ${b}`.trim()).join('\n');
      text.includes('\n') ? ctx.transcript.page(text, 'Platforms') : ctx.transcript.sys(text || '(no output)');
    })).catch(ctx.guardedErr);
  }
}, {
  help: 'Google Gemini Code Assist quota',
  name: 'gquota',
  run: (arg, ctx) => {
    ctx.gateway.rpc('gquota.show', {
      session_id: ctx.sid
    }).then(ctx.guarded(r => ctx.transcript.page(r.text || '(no output)', 'Gemini quota'))).catch(ctx.guardedErr);
  }
}, {
  help: 'list available toolsets',
  name: 'toolsets',
  run: (arg, ctx) => {
    if (arg.trim()) {
      return ctx.transcript.sys('usage: /toolsets');
    }
    ctx.gateway.rpc('toolsets.list', {
      session_id: ctx.sid
    }).then(ctx.guarded(r => {
      const items = r.toolsets ?? [];
      if (!items.length) {
        return ctx.transcript.sys('no toolsets');
      }
      ctx.transcript.panel('Toolsets', [{
        rows: items.map(t => [t.name, `${t.tool_count ?? 0} tools · ${t.description ?? ''}`])
      }]);
    })).catch(ctx.guardedErr);
  }
}, {
  help: 'reload MCP servers from config',
  name: 'reload-mcp',
  run: (arg, ctx) => {
    if (arg.trim()) {
      return ctx.transcript.sys('usage: /reload-mcp');
    }
    ctx.gateway.rpc('reload.mcp', {
      session_id: ctx.sid
    }).then(ctx.guarded(r => ctx.transcript.sys(r?.status ? `MCP ${r.status}` : 'MCP reloaded'))).catch(ctx.guardedErr);
  }
}, {
  help: 'reload .env into this session',
  name: 'reload',
  run: (arg, ctx) => {
    if (arg.trim()) {
      return ctx.transcript.sys('usage: /reload');
    }
    ctx.gateway.rpc('cli.exec', {
      argv: ['config', 'reload-env']
    }).then(ctx.guarded(r => ctx.transcript.sys(r?.output?.trim() || 'reload requested'))).catch(ctx.guardedErr);
  }
}, {
  help: 'format agent state (destructive)',
  name: 'reset',
  run: (arg, ctx) => {
    const parts = arg.trim().split(/\s+/).filter(Boolean);
    const argv = ['reset'];
    if (parts[0]?.toLowerCase() === 'hard' || parts[0]?.toLowerCase() === '--hard') {
      argv.push('--hard');
    }
    ctx.transcript.sys('running `ector reset`…');
    ctx.gateway.rpc('cli.exec', {
      argv
    }).then(ctx.guarded(r => {
      if (r.blocked && r.hint) {
        return ctx.transcript.sys(r.hint);
      }
      ctx.transcript.sys(r.output?.trim() || 'reset finished');
    })).catch(ctx.guardedErr);
  }
}, {
  aliases: ['snap'],
  help: 'configuration snapshots',
  name: 'snapshot',
  run: (arg, ctx) => {
    const parts = arg.trim().split(/\s+/).filter(Boolean);
    const sub = parts[0]?.toLowerCase() ?? 'list';
    const argv = ['backup', 'snapshot', sub, ...parts.slice(1)];
    ctx.gateway.rpc('cli.exec', {
      argv
    }).then(ctx.guarded(r => {
      if (r.blocked && r.hint) {
        return ctx.transcript.sys(r.hint);
      }
      const text = r.output?.trim() || '(no output)';
      text.length > 180 ? ctx.transcript.page(text, 'Snapshot') : ctx.transcript.sys(text);
    })).catch(ctx.guardedErr);
  }
}];