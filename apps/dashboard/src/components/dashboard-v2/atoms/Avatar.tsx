// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import {
  Avatar as ShadAvatar,
  AvatarFallback,
  AvatarImage,
} from '@/components/ui/Avatar';
import { cn } from '@/lib/utils';

interface Props {
  /** Optional seed — used to pick a gradient from the Juno palette. */
  seed?: string | undefined;
  /** Stored profile image URL. Falls back to the seeded gradient if it fails. */
  src?: string | null | undefined;
  size?: 'sm' | 'md' | undefined;
  /** Override the gradient endpoints (CSS colors). Wins over seed. */
  from?: string | undefined;
  to?: string | undefined;
  className?: string | undefined;
}

const PAIRS: Array<[string, string]> = [
  ['var(--color-oxblood-bar)', 'var(--color-gold)'],
  ['var(--color-negative)', 'var(--color-oxblood)'],
  ['var(--color-vale)', 'var(--color-oxblood)'],
  ['var(--color-gold)', 'var(--color-oxblood)'],
  ['var(--color-meridian)', 'var(--color-vale)'],
  ['var(--color-negative)', 'var(--color-gold)'],
];

function pickPair(seed: string): [string, string] {
  let h = 0;
  for (let i = 0; i < seed.length; i += 1) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return PAIRS[h % PAIRS.length]!;
}

export function Avatar({ seed, src, size = 'md', from, to, className }: Props) {
  let fromC = from;
  let toC = to;
  if (!fromC || !toC) {
    const pair = pickPair(seed ?? '');
    fromC = fromC ?? pair[0];
    toC = toC ?? pair[1];
  }
  const fallback = (seed ?? 'J').slice(0, 2).toUpperCase();

  return (
    <ShadAvatar
      className={cn(
        size === 'sm' ? 'size-7' : 'size-10',
        'border border-border bg-muted text-[0.625rem]',
        className,
      )}
      aria-hidden="true"
    >
      {src ? <AvatarImage src={src} referrerPolicy="no-referrer" /> : null}
      <AvatarFallback
        className="text-[0.625rem] text-primary-foreground"
        style={{ background: `linear-gradient(135deg, ${fromC}, ${toC})` }}
      >
        {fallback}
      </AvatarFallback>
    </ShadAvatar>
  );
}
