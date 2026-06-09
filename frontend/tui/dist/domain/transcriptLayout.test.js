import { describe, expect, it } from 'vitest';
import { TRANSCRIPT_INNER_PAD_LEFT, TRANSCRIPT_INNER_PAD_RIGHT, TRANSCRIPT_SCROLLBAR_GUTTER, transcriptContentCols } from './transcriptLayout.js';
describe('transcript layout', () => {
  it('reserves horizontal chrome for padding and scrollbar', () => {
    const cols = 80;
    const expected = cols - TRANSCRIPT_INNER_PAD_LEFT - TRANSCRIPT_INNER_PAD_RIGHT - TRANSCRIPT_SCROLLBAR_GUTTER;
    expect(transcriptContentCols(cols)).toBe(expected);
  });
});