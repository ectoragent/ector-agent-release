import { evictInkCaches } from '@ector/ink';
import { performHeapDump } from './memory.js';
const GB = 1024 ** 3;
export function startMemoryMonitor({
  criticalBytes = 2.5 * GB,
  highBytes = 1.5 * GB,
  intervalMs = 10_000,
  onCritical,
  onHigh
} = {}) {
  const dumped = new Set();
  const tick = async () => {
    const {
      heapUsed,
      rss
    } = process.memoryUsage();
    const level = heapUsed >= criticalBytes ? 'critical' : heapUsed >= highBytes ? 'high' : 'normal';
    if (level === 'normal') {
      return void dumped.clear();
    }
    if (dumped.has(level)) {
      return;
    }
    // Prune Ink content caches before dump/exit — half on 'high' (recoverable),
    // full on 'critical' (post-dump RSS reduction, keeps user running).
    evictInkCaches(level === 'critical' ? 'all' : 'half');
    dumped.add(level);
    const dump = await performHeapDump(level === 'critical' ? 'auto-critical' : 'auto-high').catch(() => null);
    const snap = {
      heapUsed,
      level,
      rss
    };
    (level === 'critical' ? onCritical : onHigh)?.(snap, dump);
  };
  const handle = setInterval(() => void tick(), intervalMs);
  handle.unref?.();
  return () => clearInterval(handle);
}