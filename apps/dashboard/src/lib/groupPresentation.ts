// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
const GROUP_COLOR_PALETTE = [
  'var(--color-oxblood)',
  'var(--color-harbor)',
  'var(--color-gold)',
  'var(--color-ink)',
  '#6B5C8E',
  '#C54D2E',
] as const;

const UNASSIGNED_KEYS = new Set(['unassigned', '__ungrouped__', '__all_accounts__', 'default']);

function hashString(value: string): number {
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash * 33 + value.charCodeAt(i)) >>> 0;
  }
  return hash;
}

function titleCase(value: string): string {
  return value
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ');
}

export function groupColorFromId(id: string | null | undefined): string {
  if (!id || UNASSIGNED_KEYS.has(id)) return '#6B6B70';
  return GROUP_COLOR_PALETTE[hashString(id) % GROUP_COLOR_PALETTE.length]!;
}

export function groupLabelFromId(
  id: string | null | undefined,
  fallback?: string | null,
): string {
  if (fallback?.trim()) return fallback.trim();
  if (!id || UNASSIGNED_KEYS.has(id)) return 'Unassigned';
  if (/^[0-9a-f]{8}-[0-9a-f-]{27}$/i.test(id)) {
    return `Group ${id.slice(0, 8)}`;
  }
  return titleCase(id.replace(/[_-]+/g, ' '));
}
