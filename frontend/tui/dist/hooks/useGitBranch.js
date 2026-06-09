import { c as _c } from "react/compiler-runtime";
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { useEffect, useState } from 'react';
const TTL_MS = 15_000;
const TIMEOUT_MS = 500;
const pexec = promisify(execFile);
const cache = new Map();
const inflight = new Map();
const resolveBranch = async cwd => {
  try {
    const {
      stdout
    } = await pexec('git', ['-C', cwd, 'rev-parse', '--abbrev-ref', 'HEAD'], {
      timeout: TIMEOUT_MS
    });
    const b = stdout.trim();
    return !b || b === 'HEAD' ? null : b;
  } catch {
    return null;
  }
};
const fetchBranch = cwd => {
  const pending = inflight.get(cwd);
  if (pending) {
    return pending;
  }
  const p = resolveBranch(cwd).finally(() => inflight.delete(cwd));
  inflight.set(cwd, p);
  return p;
};
export function useGitBranch(cwd) {
  const $ = _c(5);
  let t0;
  if ($[0] !== cwd) {
    t0 = () => cache.get(cwd)?.branch ?? null;
    $[0] = cwd;
    $[1] = t0;
  } else {
    t0 = $[1];
  }
  const [branch, setBranch] = useState(t0);
  let t1;
  let t2;
  if ($[2] !== cwd) {
    t1 = () => {
      let cancelled = false;
      const tick = async () => {
        const hit = cache.get(cwd);
        if (hit && Date.now() - hit.at < TTL_MS) {
          if (!cancelled) {
            setBranch(hit.branch);
          }
          return;
        }
        const b = await fetchBranch(cwd);
        cache.set(cwd, {
          at: Date.now(),
          branch: b
        });
        if (!cancelled) {
          setBranch(b);
        }
      };
      tick();
      const id = setInterval(() => void tick(), TTL_MS);
      return () => {
        cancelled = true;
        clearInterval(id);
      };
    };
    t2 = [cwd];
    $[2] = cwd;
    $[3] = t1;
    $[4] = t2;
  } else {
    t1 = $[3];
    t2 = $[4];
  }
  useEffect(t1, t2);
  return branch;
}