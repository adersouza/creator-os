export type CommandSection =
  | 'Recent'
  | 'Accounts'
  | 'Create'
  | 'Navigate'
  | 'Current Page'
  | 'Reports'
  | 'System';

export type CommandScope = 'global' | 'route' | 'account' | 'system';

export interface CommandDefinition {
  id: string;
  title: string;
  subtitle?: string | undefined;
  section: CommandSection;
  keywords?: string[] | undefined;
  shortcut?: string | undefined;
  scope?: CommandScope | undefined;
  disabledReason?: string | undefined;
}

export const COMMAND_RECENTS_KEY = 'juno33-cmdk-recents';
export const COMMAND_RECENTS_MAX = 5;

const SECTION_ORDER: CommandSection[] = [
  'Recent',
  'Accounts',
  'Create',
  'Current Page',
  'Navigate',
  'Reports',
  'System',
];

export function loadRecentCommandIds(storage: Storage | undefined = getStorage()): string[] {
  if (!storage) return [];
  try {
    const raw = storage.getItem(COMMAND_RECENTS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed.filter((x): x is string => typeof x === 'string').slice(0, COMMAND_RECENTS_MAX)
      : [];
  } catch {
    return [];
  }
}

export function pushRecentCommandId(id: string, storage: Storage | undefined = getStorage()): string[] {
  if (!storage) return [];
  const next = [id, ...loadRecentCommandIds(storage).filter((x) => x !== id)].slice(0, COMMAND_RECENTS_MAX);
  try {
    storage.setItem(COMMAND_RECENTS_KEY, JSON.stringify(next));
  } catch {
    /* Recents are best-effort. */
  }
  return next;
}

export function getRecentCommands<T extends CommandDefinition>(
  commands: T[],
  recentIds: string[],
): T[] {
  return recentIds
    .map((id) => commands.find((command) => command.id === id))
    .filter((command): command is T => command !== undefined)
    .map((command) => ({ ...command, section: 'Recent' as const }));
}

export function filterAndRankCommands<T extends CommandDefinition>(
  commands: T[],
  query: string,
): T[] {
  const normalizedQuery = normalize(query);
  if (!normalizedQuery) return commands;

  return commands
    .map((command) => ({ command, score: scoreCommand(command, normalizedQuery) }))
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score || a.command.title.localeCompare(b.command.title))
    .map((item) => item.command);
}

export function groupCommandsBySection<T extends CommandDefinition>(
  commands: T[],
): Array<[CommandSection, T[]]> {
  const groups = new Map<CommandSection, T[]>();
  for (const command of commands) {
    const list = groups.get(command.section) ?? [];
    list.push(command);
    groups.set(command.section, list);
  }
  return SECTION_ORDER
    .map((section) => [section, groups.get(section) ?? []] as [CommandSection, T[]])
    .filter(([, items]) => items.length > 0);
}

function scoreCommand(command: CommandDefinition, normalizedQuery: string): number {
  const title = normalize(command.title);
  const subtitle = normalize(command.subtitle ?? '');
  const section = normalize(command.section);
  const keywords = normalize((command.keywords ?? []).join(' '));
  const haystack = `${title} ${subtitle} ${section} ${keywords}`.trim();

  if (title === normalizedQuery) return 120;
  if (title.startsWith(normalizedQuery)) return 100;
  if (title.includes(normalizedQuery)) return 85;
  if (haystack.includes(normalizedQuery)) return 65;

  const queryTokens = normalizedQuery.split(' ').filter(Boolean);
  if (queryTokens.length > 1 && queryTokens.every((token) => haystack.includes(token))) return 55;
  if (isSubsequence(normalizedQuery.replace(/\s+/g, ''), title.replace(/\s+/g, ''))) return 38;
  if (isSubsequence(normalizedQuery.replace(/\s+/g, ''), haystack.replace(/\s+/g, ''))) return 24;
  return 0;
}

function normalize(value: string): string {
  return value
    .toLowerCase()
    .replace(/^@/, '')
    .replace(/[^\p{L}\p{N}@._\-\s/]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function isSubsequence(needle: string, haystack: string): boolean {
  if (!needle) return true;
  let cursor = 0;
  for (const char of haystack) {
    if (char === needle[cursor]) cursor += 1;
    if (cursor === needle.length) return true;
  }
  return false;
}

function getStorage(): Storage | undefined {
  return typeof window === 'undefined' ? undefined : window.localStorage;
}
