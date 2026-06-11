// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { describe, expect, it } from 'vitest';
import {
  filterAndRankCommands,
  getRecentCommands,
  groupCommandsBySection,
  type CommandDefinition,
} from './commands';

const commands: CommandDefinition[] = [
  {
    id: 'nav-analytics',
    title: 'Go to Analytics',
    subtitle: 'Fleet performance',
    section: 'Navigate',
    keywords: ['metrics', 'reports'],
  },
  {
    id: 'account-aurora',
    title: 'Switch to @aurora.core',
    subtitle: 'Instagram · Launch group',
    section: 'Accounts',
    keywords: ['Aurora Core', 'Launch group', 'instagram'],
  },
  {
    id: 'create-post',
    title: 'Create post',
    section: 'Create',
    keywords: ['composer', 'draft'],
  },
];

describe('command filtering', () => {
  it('matches account handles, subtitles, and keywords', () => {
    expect(filterAndRankCommands(commands, 'aurora')[0]?.id).toBe('account-aurora');
    expect(filterAndRankCommands(commands, 'launch group')[0]?.id).toBe('account-aurora');
    expect(filterAndRankCommands(commands, 'metrics')[0]?.id).toBe('nav-analytics');
  });

  it('supports fuzzy subsequence matches for compact queries', () => {
    expect(filterAndRankCommands(commands, 'gtan')[0]?.id).toBe('nav-analytics');
  });

  it('treats handle-prefixed account searches as first-class lookup text', () => {
    expect(filterAndRankCommands(commands, '@aurora')[0]?.id).toBe('account-aurora');
  });
});

describe('command grouping and recents', () => {
  it('maps recent ids back to live commands and groups in stable order', () => {
    const recent = getRecentCommands(commands, ['create-post']);
    expect(recent).toHaveLength(1);
    expect(recent[0]!.section).toBe('Recent');

    const groups = groupCommandsBySection([...recent, ...commands]);
    expect(groups.map(([section]) => section)).toEqual(['Recent', 'Accounts', 'Create', 'Navigate']);
  });
});
