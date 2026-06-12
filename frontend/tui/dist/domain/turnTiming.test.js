import { describe, expect, it } from 'vitest';
import { formatInteractionFooter, normalizeEpochMs, turnTimingMsg } from './turnTiming.js';
describe('turnTiming', () => {
  it('normalizes epoch seconds to ms', () => {
    expect(normalizeEpochMs(1_700_000_000)).toBe(1_700_000_000_000);
  });
  it('formats compact footer', () => {
    const startedAt = Date.UTC(2026, 5, 12, 14, 40, 0);
    const completedAt = startedAt + 135_000;
    expect(formatInteractionFooter({
      startedAt,
      completedAt
    })).toMatch(/^2m 15s · /);
  });
  it('builds turnTiming messages', () => {
    const msg = turnTimingMsg(1_000, 136_000);
    expect(msg.kind).toBe('turnTiming');
    expect(msg.turnTiming?.completedAt).toBe(136_000);
    expect(msg.text).toContain('·');
  });
});