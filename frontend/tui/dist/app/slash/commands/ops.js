import { applyDelegationStatus, getDelegationState } from '../../delegationStore.js';
import { patchOverlayState } from '../../overlayStore.js';
import { getSpawnHistory, pushDiskSnapshot, setDiffPair } from '../../spawnHistoryStore.js';
export const opsCommands = [{
  aliases: ['tasks'],
  help: 'open the spawn-tree dashboard (live audit + kill/pause controls)',
  name: 'agents',
  run: (arg, ctx) => {
    const sub = arg.trim().toLowerCase();
    // Stay compatible with the gateway `/agents [pause|resume|status]` CLI —
    // explicit subcommands skip the overlay and act directly so scripts and
    // multi-step flows can drive it without entering interactive mode.
    if (sub === 'pause' || sub === 'resume' || sub === 'unpause') {
      const paused = sub === 'pause';
      ctx.gateway.gw.request('delegation.pause', {
        paused
      }).then(r => {
        applyDelegationStatus({
          paused: r?.paused
        });
        ctx.transcript.sys(`delegation · ${r?.paused ? 'paused' : 'resumed'}`);
      }).catch(ctx.guardedErr);
      return;
    }
    if (sub === 'status') {
      const d = getDelegationState();
      ctx.transcript.sys(`delegation · ${d.paused ? 'paused' : 'active'} · caps d${d.maxSpawnDepth ?? '?'}/${d.maxConcurrentChildren ?? '?'}`);
      return;
    }
    patchOverlayState({
      agents: true,
      agentsInitialHistoryIndex: 0
    });
  }
}, {
  help: 'replay a completed spawn tree · `/replay [N|last|list|load <path>]`',
  name: 'replay',
  run: (arg, ctx) => {
    const history = getSpawnHistory();
    const raw = arg.trim();
    const lower = raw.toLowerCase();
    // ── Disk-backed listing ─────────────────────────────────────
    if (lower === 'list' || lower === 'ls') {
      ctx.gateway.rpc('spawn_tree.list', {
        limit: 30,
        session_id: ctx.sid ?? 'default'
      }).then(ctx.guarded(r => {
        const entries = r.entries ?? [];
        if (!entries.length) {
          return ctx.transcript.sys('no archived spawn trees on disk for this session');
        }
        const rows = entries.map(e => {
          const ts = e.finished_at ? new Date(e.finished_at * 1000).toLocaleString() : '?';
          const label = e.label || `${e.count} subagents`;
          return [`${ts} · ${e.count}×`, `${label}\n  ${e.path}`];
        });
        ctx.transcript.panel('Archived spawn trees', [{
          rows
        }]);
      })).catch(ctx.guardedErr);
      return;
    }
    // ── Disk-backed load by path ─────────────────────────────────
    if (lower.startsWith('load ')) {
      const path = raw.slice(5).trim();
      if (!path) {
        return ctx.transcript.sys('usage: /replay load <path>');
      }
      ctx.gateway.rpc('spawn_tree.load', {
        path
      }).then(ctx.guarded(r => {
        if (!r.subagents?.length) {
          return ctx.transcript.sys('snapshot empty or unreadable');
        }
        // Push onto the in-memory history so the overlay picks it up
        // by index 1 just like any other snapshot.
        pushDiskSnapshot(r, path);
        patchOverlayState({
          agents: true,
          agentsInitialHistoryIndex: 1
        });
      })).catch(ctx.guardedErr);
      return;
    }
    // ── In-memory nav (same-session) ─────────────────────────────
    if (!history.length) {
      return ctx.transcript.sys('no completed spawn trees this session · try /replay list');
    }
    let index = 1;
    if (raw && lower !== 'last') {
      const parsed = parseInt(raw, 10);
      if (Number.isNaN(parsed) || parsed < 1 || parsed > history.length) {
        return ctx.transcript.sys(`replay: index out of range 1..${history.length} · use /replay list for disk`);
      }
      index = parsed;
    }
    patchOverlayState({
      agents: true,
      agentsInitialHistoryIndex: index
    });
  }
}, {
  help: 'diff two completed spawn trees · `/replay-diff <baseline> <candidate>` (indexes from /replay list or history N)',
  name: 'replay-diff',
  run: (arg, ctx) => {
    const parts = arg.trim().split(/\s+/).filter(Boolean);
    if (parts.length !== 2) {
      return ctx.transcript.sys('usage: /replay-diff <a> <b>  (e.g. /replay-diff 1 2 for last two)');
    }
    const [a, b] = parts;
    const history = getSpawnHistory();
    const resolve = token => {
      const n = parseInt(token, 10);
      if (Number.isFinite(n) && n >= 1 && n <= history.length) {
        return history[n - 1] ?? null;
      }
      return null;
    };
    const baseline = resolve(a);
    const candidate = resolve(b);
    if (!baseline || !candidate) {
      return ctx.transcript.sys(`replay-diff: could not resolve indices · history has ${history.length} entries`);
    }
    setDiffPair({
      baseline,
      candidate
    });
    patchOverlayState({
      agents: true,
      agentsInitialHistoryIndex: 0
    });
  }
}, {
  help: 'browse, inspect, install skills',
  name: 'skills',
  run: (arg, ctx) => {
    const text = arg.trim();
    if (!text) {
      return patchOverlayState({
        skillsHub: true
      });
    }
    const [sub, ...rest] = text.split(/\s+/);
    const query = rest.join(' ').trim();
    const {
      rpc
    } = ctx.gateway;
    const {
      panel,
      sys
    } = ctx.transcript;
    if (sub === 'list') {
      rpc('skills.manage', {
        action: 'list'
      }).then(ctx.guarded(r => {
        const cats = Object.entries(r.skills ?? {}).sort();
        if (!cats.length) {
          return sys('no skills available');
        }
        panel('Skills', cats.map(([title, items]) => ({
          items,
          title
        })));
      })).catch(ctx.guardedErr);
      return;
    }
    if (sub === 'inspect') {
      if (!query) {
        return sys('usage: /skills inspect <name>');
      }
      rpc('skills.manage', {
        action: 'inspect',
        query
      }).then(ctx.guarded(r => {
        const info = r.info ?? {};
        if (!info.name) {
          return sys(`unknown skill: ${query}`);
        }
        const rows = [['Name', String(info.name)], ['Category', String(info.category ?? '')], ['Path', String(info.path ?? '')]];
        const sections = [{
          rows
        }];
        if (info.description) {
          sections.push({
            text: String(info.description)
          });
        }
        panel('Skill', sections);
      })).catch(ctx.guardedErr);
      return;
    }
    if (sub === 'search') {
      if (!query) {
        return sys('usage: /skills search <query>');
      }
      rpc('skills.manage', {
        action: 'search',
        query
      }).then(ctx.guarded(r => {
        const results = r.results ?? [];
        if (!results.length) {
          return sys(`no results for: ${query}`);
        }
        panel(`Search: ${query}`, [{
          rows: results.map(s => [s.name, s.description ?? ''])
        }]);
      })).catch(ctx.guardedErr);
      return;
    }
    if (sub === 'install') {
      if (!query) {
        return sys('usage: /skills install <name or url>');
      }
      sys(`installing ${query}…`);
      rpc('skills.manage', {
        action: 'install',
        query
      }).then(ctx.guarded(r => sys(r.installed ? `installed ${r.name ?? query}` : 'install failed'))).catch(ctx.guardedErr);
      return;
    }
    if (sub === 'browse') {
      const pageNum = query ? parseInt(query, 10) : 1;
      if (Number.isNaN(pageNum) || pageNum < 1) {
        return sys('usage: /skills browse [page]  (page must be a positive number)');
      }
      sys('fetching community skills (scans 6 sources, may take ~15s)…');
      rpc('skills.manage', {
        action: 'browse',
        page: pageNum
      }).then(ctx.guarded(r => {
        const items = r.items ?? [];
        if (!items.length) {
          return sys(`no skills on page ${pageNum}${r.total ? ` (total ${r.total})` : ''}`);
        }
        const rows = items.map(s => [s.trust ? `${s.name} · ${s.trust}` : s.name, String(s.description ?? '').slice(0, 160)]);
        const footer = [];
        if (r.page && r.total_pages) {
          footer.push(`page ${r.page} of ${r.total_pages}`);
        }
        if (r.total) {
          footer.push(`${r.total} skills total`);
        }
        if (r.page && r.total_pages && r.page < r.total_pages) {
          footer.push(`/skills browse ${r.page + 1} for more`);
        }
        panel(`Browse Skills${pageNum > 1 ? ` — p${pageNum}` : ''}`, [{
          rows
        }, ...(footer.length ? [{
          text: footer.join(' · ')
        }] : [])]);
      })).catch(ctx.guardedErr);
      return;
    }
    sys('usage: /skills [list | inspect <n> | install <n> | search <q> | browse [page]]');
  }
}, {
  help: 'enable or disable tools (client-side history reset on change)',
  name: 'tools',
  run: (arg, ctx, cmd) => {
    const [subcommand, ...names] = arg.trim().split(/\s+/).filter(Boolean);
    if (subcommand !== 'disable' && subcommand !== 'enable') {
      ctx.gateway.rpc('tools.list', {
        session_id: ctx.sid
      }).then(ctx.guarded(r => {
        const items = r.toolsets ?? [];
        if (!items.length) {
          return ctx.transcript.sys('no toolsets');
        }
        ctx.transcript.panel('Toolsets', [{
          rows: items.map(t => [t.enabled === false ? `✖ ${t.name}` : `✔ ${t.name}`, `${t.tool_count ?? 0} tools · ${t.description ?? ''}`])
        }]);
      })).catch(ctx.guardedErr);
      return;
    }
    if (!names.length) {
      ctx.transcript.sys(`usage: /tools ${subcommand} <name> [name ...]`);
      ctx.transcript.sys(`built-in toolset: /tools ${subcommand} web`);
      ctx.transcript.sys(`MCP tool: /tools ${subcommand} github:create_issue`);
      return;
    }
    ctx.gateway.rpc('tools.configure', {
      action: subcommand,
      names,
      session_id: ctx.sid
    }).then(ctx.guarded(r => {
      if (r.info) {
        ctx.session.setSessionStartedAt(Date.now());
        ctx.session.resetVisibleHistory(r.info);
      }
      if (r.changed?.length) {
        ctx.transcript.sys(`${subcommand === 'disable' ? 'disabled' : 'enabled'}: ${r.changed.join(', ')}`);
      }
      if (r.unknown?.length) {
        ctx.transcript.sys(`unknown toolsets: ${r.unknown.join(', ')}`);
      }
      if (r.missing_servers?.length) {
        ctx.transcript.sys(`missing MCP servers: ${r.missing_servers.join(', ')}`);
      }
      if (r.reset) {
        ctx.transcript.sys('session reset. new tool configuration is active.');
      }
    })).catch(ctx.guardedErr);
  }
}];