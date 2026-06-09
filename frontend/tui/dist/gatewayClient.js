import { spawn } from 'node:child_process';
import { EventEmitter } from 'node:events';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { delimiter, dirname, join, resolve } from 'node:path';
import { createInterface } from 'node:readline';
import { CircularBuffer } from './lib/circularBuffer.js';
const MAX_GATEWAY_LOG_LINES = 200;
const MAX_LOG_LINE_BYTES = 4096;
const MAX_BUFFERED_EVENTS = 2000;
const MAX_LOG_PREVIEW = 240;
const STARTUP_TIMEOUT_MS = Math.max(5000, parseInt(process.env.ECTOR_TUI_STARTUP_TIMEOUT_MS ?? '15000', 10) || 15000);
const REQUEST_TIMEOUT_MS = Math.max(30000, parseInt(process.env.ECTOR_TUI_RPC_TIMEOUT_MS ?? '120000', 10) || 120000);
const SHUTDOWN_GRACE_MS = Math.max(1000, parseInt(process.env.ECTOR_TUI_GATEWAY_SHUTDOWN_GRACE_MS ?? '5000', 10) || 5000);
const truncateLine = line => line.length > MAX_LOG_LINE_BYTES ? `${line.slice(0, MAX_LOG_LINE_BYTES)}… [truncated ${line.length} bytes]` : line;
/** Repo root for ``PYTHONPATH`` / venv discovery (``tui_gateway`` lives here, not under ``frontend/tui``). */
export function resolveEctorPythonSrcRoot(startDir = import.meta.dirname) {
  const anchors = [startDir, process.cwd(), process.env.ECTOR_CWD ?? ''].filter(Boolean);
  for (const anchor of anchors) {
    let dir = resolve(anchor);
    for (let i = 0; i < 16; i++) {
      if (existsSync(join(dir, 'tui_gateway', 'entry.py'))) {
        return dir;
      }
      const parent = dirname(dir);
      if (parent === dir) {
        break;
      }
      dir = parent;
    }
  }
  return resolve(startDir, '../../../');
}
const macosBundlePythonPath = () => {
  if (process.platform !== 'darwin') {
    return undefined;
  }
  const ectorHome = process.env.ECTOR_HOME?.trim() || join(homedir(), '.ector');
  const bundled = join(ectorHome, 'Ector.app', 'Contents', 'MacOS', 'Ector');
  return existsSync(bundled) ? bundled : undefined;
};
/**
 * The TUI gateway macOS bundle is a relocated CPython: it needs ``Contents/lib/libpython*.dylib``
 * plus ``Contents/.python-prefix`` (see ``ector_cli/macos_bundle.py``). Older installs only had
 * the Mach-O stub, which crashes immediately — do not prefer that over a project venv.
 *
 * @internal exported for unit tests
 */
export function isMacosBundleGatewayComplete(bundledExe) {
  if (!existsSync(bundledExe)) {
    return false;
  }
  const contentsDir = join(dirname(bundledExe), '..');
  const prefixFile = join(contentsDir, '.python-prefix');
  const libDir = join(contentsDir, 'lib');
  if (!existsSync(prefixFile) || !existsSync(libDir)) {
    return false;
  }
  try {
    const names = readdirSync(libDir);
    return names.some(n => n.startsWith('libpython') && n.endsWith('.dylib'));
  } catch {
    return false;
  }
}
/**
 * Validate user-provided interpreter overrides from ECTOR_PYTHON/PYTHON.
 *
 * Bare commands like "python3" are allowed (resolved via PATH by spawn).
 * Explicit paths must exist; stale values (e.g. "$PWD/venv/bin/python3" from a
 * different directory) are ignored so we can fall back to project venv/bundle.
 */
export function isConfiguredPythonCandidate(configured) {
  const value = configured.trim();
  if (!value) {
    return false;
  }
  const looksLikePath = value.includes('/') || value.includes('\\');
  return looksLikePath ? existsSync(value) : true;
}
const resolvePython = root => {
  const configured = process.env.ECTOR_PYTHON?.trim() || process.env.PYTHON?.trim();
  if (configured && isConfiguredPythonCandidate(configured)) {
    return configured;
  }
  const venv = process.env.VIRTUAL_ENV?.trim();
  const venvCandidates = [venv && resolve(venv, 'bin/python'), venv && resolve(venv, 'Scripts/python.exe'), resolve(root, '.venv/bin/python'), resolve(root, '.venv/bin/python3'), resolve(root, 'venv/bin/python'), resolve(root, 'venv/bin/python3'), resolve(process.cwd(), '.venv/bin/python'), resolve(process.cwd(), '.venv/bin/python3'), resolve(process.cwd(), 'venv/bin/python'), resolve(process.cwd(), 'venv/bin/python3')].filter(p => Boolean(p));
  const venvHit = venvCandidates.find(p => existsSync(p));
  const bundled = macosBundlePythonPath();
  const bundleOk = bundled && isMacosBundleGatewayComplete(bundled);
  if (venvHit) {
    return venvHit;
  }
  if (bundleOk) {
    return bundled;
  }
  return process.platform === 'win32' ? 'python' : 'python3';
};
const asGatewayEvent = value => value && typeof value === 'object' && !Array.isArray(value) && typeof value.type === 'string' ? value : null;
export class GatewayClient extends EventEmitter {
  proc = null;
  reqId = 0;
  logs = new CircularBuffer(MAX_GATEWAY_LOG_LINES);
  pending = new Map();
  bufferedEvents = new CircularBuffer(MAX_BUFFERED_EVENTS);
  pendingExit;
  ready = false;
  readyTimer = null;
  subscribed = false;
  stdoutRl = null;
  stderrRl = null;
  constructor() {
    super();
    // useInput / createGatewayEventHandler can legitimately attach many
    // listeners. Default 10-cap triggers spurious warnings.
    this.setMaxListeners(0);
  }
  publish(ev) {
    if (ev.type === 'gateway.ready') {
      this.ready = true;
      if (this.readyTimer) {
        clearTimeout(this.readyTimer);
        this.readyTimer = null;
      }
    }
    if (this.subscribed) {
      return void this.emit('event', ev);
    }
    this.bufferedEvents.push(ev);
  }
  start() {
    const root = process.env.ECTOR_PYTHON_SRC_ROOT?.trim() || resolveEctorPythonSrcRoot();
    const python = resolvePython(root);
    const cwd = process.env.ECTOR_CWD || root;
    const env = {
      ...process.env
    };
    const pyPath = env.PYTHONPATH?.trim();
    env.PYTHONPATH = pyPath ? `${root}${delimiter}${pyPath}` : root;
    if (!env.PYTHONHOME?.trim() && python.includes('Ector.app/Contents/MacOS/Ector')) {
      const ectorHome = process.env.ECTOR_HOME?.trim() || join(homedir(), '.ector');
      const prefixFile = join(ectorHome, 'Ector.app', 'Contents', '.python-prefix');
      if (existsSync(prefixFile)) {
        try {
          const home = readFileSync(prefixFile, 'utf8').trim();
          if (home) {
            env.PYTHONHOME = home;
          }
        } catch {
          // fall through — spawn may fail and surface in gateway.stderr
        }
      }
    }
    this.ready = false;
    this.bufferedEvents.clear();
    this.pendingExit = undefined;
    this.stdoutRl?.close();
    this.stderrRl?.close();
    this.stdoutRl = null;
    this.stderrRl = null;
    if (this.proc && !this.proc.killed && this.proc.exitCode === null) {
      this.proc.kill();
    }
    if (this.readyTimer) {
      clearTimeout(this.readyTimer);
    }
    this.readyTimer = setTimeout(() => {
      if (this.ready) {
        return;
      }
      this.pushLog(`[startup] timed out waiting for gateway.ready (python=${python}, cwd=${cwd})`);
      this.publish({
        type: 'gateway.start_timeout',
        payload: {
          cwd,
          python
        }
      });
    }, STARTUP_TIMEOUT_MS);
    this.proc = spawn(python, ['-m', 'tui_gateway.entry'], {
      cwd,
      env,
      stdio: ['pipe', 'pipe', 'pipe']
    });
    this.stdoutRl = createInterface({
      input: this.proc.stdout
    });
    this.stdoutRl.on('line', raw => {
      try {
        this.dispatch(JSON.parse(raw));
      } catch {
        const preview = raw.trim().slice(0, MAX_LOG_PREVIEW) || '(empty line)';
        this.pushLog(`[protocol] malformed stdout: ${preview}`);
        this.publish({
          type: 'gateway.protocol_error',
          payload: {
            preview
          }
        });
      }
    });
    this.stderrRl = createInterface({
      input: this.proc.stderr
    });
    this.stderrRl.on('line', raw => {
      const line = truncateLine(raw.trim());
      if (!line) {
        return;
      }
      this.pushLog(line);
      this.publish({
        type: 'gateway.stderr',
        payload: {
          line
        }
      });
    });
    this.proc.on('error', err => {
      this.pushLog(`[spawn] ${err.message}`);
      this.rejectPending(new Error(`gateway error: ${err.message}`));
      this.publish({
        type: 'gateway.stderr',
        payload: {
          line: `[spawn] ${err.message}`
        }
      });
    });
    this.proc.on('exit', code => {
      if (this.readyTimer) {
        clearTimeout(this.readyTimer);
        this.readyTimer = null;
      }
      this.rejectPending(new Error(`gateway exited${code === null ? '' : ` (${code})`}`));
      if (this.subscribed) {
        this.emit('exit', code);
      } else {
        this.pendingExit = code;
      }
    });
  }
  dispatch(msg) {
    const id = msg.id;
    const p = id ? this.pending.get(id) : undefined;
    if (p) {
      this.settle(p, msg.error ? this.toError(msg.error) : null, msg.result);
      return;
    }
    if (msg.method === 'event') {
      const ev = asGatewayEvent(msg.params);
      if (ev) {
        this.publish(ev);
      }
    }
  }
  toError(raw) {
    const err = raw;
    return new Error(typeof err?.message === 'string' ? err.message : 'falha na requisição');
  }
  settle(p, err, result) {
    clearTimeout(p.timeout);
    this.pending.delete(p.id);
    if (err) {
      p.reject(err);
    } else {
      p.resolve(result);
    }
  }
  pushLog(line) {
    this.logs.push(truncateLine(line));
  }
  rejectPending(err) {
    for (const p of this.pending.values()) {
      clearTimeout(p.timeout);
      p.reject(err);
    }
    this.pending.clear();
  }
  // Arrow class-field — stable identity, so `setTimeout(this.onTimeout, …, id)`
  // doesn't allocate a bound function per request.
  onTimeout = id => {
    const p = this.pending.get(id);
    if (p) {
      this.pending.delete(id);
      p.reject(new Error(`timeout: ${p.method}`));
    }
  };
  drain() {
    this.subscribed = true;
    for (const ev of this.bufferedEvents.drain()) {
      this.emit('event', ev);
    }
    if (this.pendingExit !== undefined) {
      const code = this.pendingExit;
      this.pendingExit = undefined;
      this.emit('exit', code);
    }
  }
  getLogTail(limit = 20) {
    return this.logs.tail(Math.max(1, limit)).join('\n');
  }
  request(method, params = {}) {
    if (!this.proc?.stdin || this.proc.killed || this.proc.exitCode !== null) {
      this.start();
    }
    if (!this.proc?.stdin) {
      return Promise.reject(new Error('gateway not running'));
    }
    const id = `r${++this.reqId}`;
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(this.onTimeout, REQUEST_TIMEOUT_MS, id);
      timeout.unref?.();
      this.pending.set(id, {
        id,
        method,
        reject,
        resolve: v => resolve(v),
        timeout
      });
      try {
        this.proc.stdin.write(JSON.stringify({
          id,
          jsonrpc: '2.0',
          method,
          params
        }) + '\n');
      } catch (e) {
        const pending = this.pending.get(id);
        if (pending) {
          clearTimeout(pending.timeout);
          this.pending.delete(id);
        }
        reject(e instanceof Error ? e : new Error(String(e)));
      }
    });
  }
  kill() {
    const proc = this.proc;
    if (!proc || proc.killed || proc.exitCode !== null) {
      return;
    }
    if (proc.stdin && !proc.stdin.destroyed) {
      proc.stdin.end();
    }
    setTimeout(() => {
      if (!proc.killed && proc.exitCode === null) {
        proc.kill();
      }
    }, SHUTDOWN_GRACE_MS).unref?.();
  }
}