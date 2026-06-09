import { describe, expect, it } from 'vitest';
import { backgroundMessageParts, introMsg, isIntroDismissInteraction, sessionHistoryItems, withoutIntro } from './messages.js';
const info = {
  model: 'test',
  tools: {},
  skills: {},
  version: '1.0'
};
describe('backgroundMessageParts', () => {
  it('splits gateway background prefix from markdown body', () => {
    expect(backgroundMessageParts('[bg abc] **hi**')).toEqual({
      label: '[bg abc]',
      body: '**hi**'
    });
    expect(backgroundMessageParts('bg abc started')).toBeNull();
  });
});
describe('intro banner helpers', () => {
  it('detects user-facing interactions that dismiss the intro', () => {
    expect(isIntroDismissInteraction({
      role: 'user',
      text: 'hi'
    })).toBe(true);
    expect(isIntroDismissInteraction({
      kind: 'slash',
      role: 'system',
      text: '/help'
    })).toBe(true);
    expect(isIntroDismissInteraction({
      kind: 'panel',
      panelData: {
        sections: [],
        title: 'x'
      },
      role: 'system',
      text: ''
    })).toBe(true);
    expect(isIntroDismissInteraction(introMsg(info))).toBe(false);
    expect(isIntroDismissInteraction({
      role: 'system',
      text: 'queued'
    })).toBe(false);
  });
  it('strips intro rows from history', () => {
    const intro = introMsg(info);
    const user = {
      role: 'user',
      text: 'hi'
    };
    expect(withoutIntro([intro, user])).toEqual([user]);
  });
  it('omits intro when session already has transcript rows', () => {
    const rows = [{
      role: 'user',
      text: 'prior'
    }];
    expect(sessionHistoryItems(info, rows)).toEqual(rows);
    expect(sessionHistoryItems(info, [])).toEqual([introMsg(info)]);
    expect(sessionHistoryItems(null, [])).toEqual([]);
  });
});