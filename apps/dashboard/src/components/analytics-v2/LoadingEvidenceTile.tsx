// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { EvidenceCard } from '@/components/ui/EvidenceCard';
import { Skeleton } from '@/components/ui/Skeleton';
import { EvidenceTileHeader } from './EvidenceTileHeader';

interface Props {
  index?: number | undefined;
  title: string;
  hint?: string | undefined;
  eyebrow?: string | undefined;
  variant?: 'bars' | 'bullet' | 'funnel' | 'heatmap' | 'line' | 'list' | 'network' | 'table' | 'thread-tree' | undefined;
}

export function LoadingEvidenceTile({
  index,
  title,
  hint,
  eyebrow,
  variant = 'bars',
}: Props) {
  return (
    <EvidenceCard
      state="loading"
      className="analytics-evidence-tile analytics-evidence-tile-loading h-full w-full flex flex-col p-0"
      contentClassName="flex h-full flex-1 flex-col"
    >
      <EvidenceTileHeader index={index} eyebrow={eyebrow} title={title} hint={hint} />
      <div className="flex-1 px-6 pb-5">
        {variant === 'funnel' ? <FunnelSkeleton /> : null}
        {variant === 'line' ? <LineSkeleton /> : null}
        {variant === 'bullet' ? <BulletSkeleton /> : null}
        {variant === 'list' ? <ListSkeleton /> : null}
        {variant === 'network' ? <NetworkSkeleton /> : null}
        {variant === 'table' ? <TableSkeleton /> : null}
        {variant === 'heatmap' || variant === 'thread-tree' || variant === 'bars' ? <BarsSkeleton /> : null}
      </div>
    </EvidenceCard>
  );
}

function BarsSkeleton() {
  return (
    <div className="flex h-full min-h-[150px] flex-col justify-center gap-3">
      {[72, 56, 84, 44, 64].map((width, index) => (
        <div key={width} className="flex items-center gap-3">
          <Skeleton className="h-3 w-16 rounded" />
          <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
            <Skeleton
              className="h-full rounded-full bg-primary/20"
              style={{ width: `${width}%`, animationDelay: `${index * 80}ms` }}
            />
          </div>
          <Skeleton className="h-3 w-10 rounded" />
        </div>
      ))}
    </div>
  );
}

function FunnelSkeleton() {
  return (
    <div className="flex h-full min-h-[170px] flex-col justify-center gap-3">
      {[94, 76, 58, 36].map((width, index) => (
        <div
          key={width}
          className="h-8 rounded-md border border-dashed border-border bg-muted"
          style={{
            width: `${width}%`,
            marginLeft: `${index * 4}%`,
            animationDelay: `${index * 90}ms`,
          }}
        />
      ))}
      <div className="mt-2 grid grid-cols-3 gap-2">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-12 rounded-md border border-border/70" />
        ))}
      </div>
    </div>
  );
}

function LineSkeleton() {
  return (
    <div className="flex h-full min-h-[170px] flex-col justify-center">
      <svg
        viewBox="0 0 420 150"
        role="img"
        aria-label="Loading trend chart"
        className="h-[170px] w-full rounded-md border border-border/70 bg-muted/20"
      >
        {[34, 74, 114].map((y) => (
          <line key={y} x1="20" x2="400" y1={y} y2={y} stroke="var(--color-border)" opacity="0.7" />
        ))}
        <path
          d="M 22 104 C 76 72, 112 92, 164 54 S 262 68, 310 40 S 374 52, 398 32"
          fill="none"
          stroke="var(--color-oxblood)"
          strokeWidth="3"
          strokeLinecap="round"
          opacity="0.22"
        />
        <path
          d="M 22 118 C 78 86, 128 112, 178 72 S 274 84, 324 52 S 374 66, 398 48"
          fill="none"
          stroke="var(--color-gold)"
          strokeWidth="2"
          strokeDasharray="5 5"
          strokeLinecap="round"
          opacity="0.28"
        />
      </svg>
    </div>
  );
}

function BulletSkeleton() {
  return (
    <div className="flex h-full min-h-[170px] flex-col justify-center gap-5">
      <div className="rounded-lg border border-border/70 bg-muted/15 p-4">
        <div className="mb-4 flex items-end justify-between gap-4">
          <div>
            <Skeleton className="mb-2 h-3 w-24 rounded-full" />
            <Skeleton className="h-9 w-28 rounded-md bg-primary/15" />
          </div>
          <Skeleton className="h-7 w-20 rounded-full border border-border" />
        </div>
        <div className="relative h-8 rounded-full bg-muted/35">
          <div className="absolute inset-y-1 left-[18%] w-px bg-border" />
          <div className="absolute inset-y-1 left-[52%] w-px bg-border" />
          <div className="absolute inset-y-1 left-[78%] w-px bg-border" />
          <Skeleton className="absolute left-[62%] top-1/2 h-11 w-1 -translate-y-1/2 rounded-full bg-primary/25" />
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-12 rounded-md border border-border/70 bg-card/35 p-3">
            <Skeleton className="h-2 w-2/3 rounded-full" />
            <Skeleton className="mt-2 h-2 w-1/2 rounded-full" />
          </div>
        ))}
      </div>
    </div>
  );
}

function ListSkeleton() {
  return (
    <div className="flex h-full min-h-[170px] flex-col justify-center gap-3">
      <div className="grid grid-cols-3 gap-2">
        {[78, 46, 58].map((width) => (
          <div key={width} className="rounded-md border border-border/70 bg-card/35 p-3">
            <Skeleton className="h-7 rounded-md bg-primary/15" style={{ width: `${width}%` }} />
            <Skeleton className="mt-2 h-2 w-16 rounded-full" />
          </div>
        ))}
      </div>
      <div className="flex flex-col gap-2">
        {[68, 84, 56, 74].map((width, index) => (
          <div key={width} className="flex items-center gap-3 rounded-md border border-border/70 bg-card/35 px-3 py-2">
            <Skeleton className="h-6 w-6 rounded-full" />
            <div className="min-w-0 flex-1">
              <Skeleton
                className="h-2.5 rounded-full"
                style={{ width: `${width}%`, animationDelay: `${index * 80}ms` }}
              />
            </div>
            <Skeleton className="h-2.5 w-10 rounded-full bg-primary/20" />
          </div>
        ))}
      </div>
    </div>
  );
}

function NetworkSkeleton() {
  const nodes = [
    { x: 23, y: 45, r: 7 },
    { x: 38, y: 28, r: 5 },
    { x: 51, y: 56, r: 8 },
    { x: 66, y: 36, r: 6 },
    { x: 78, y: 61, r: 5 },
  ];
  const links = [
    [0, 1],
    [0, 2],
    [1, 3],
    [2, 3],
    [2, 4],
    [3, 4],
  ] as const;
  return (
    <div className="grid min-h-[220px] gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(220px,0.7fr)]">
      <div className="rounded-lg border border-border/70 bg-muted/20 p-4">
        <svg viewBox="0 0 100 86" className="h-full min-h-[190px] w-full" role="img" aria-label="Loading network map">
          <defs>
            <radialGradient id="loadingNetworkGlow" cx="50%" cy="50%" r="55%">
              <stop offset="0%" stopColor="var(--color-meridian)" stopOpacity="0.14" />
              <stop offset="100%" stopColor="var(--color-meridian)" stopOpacity="0" />
            </radialGradient>
          </defs>
          <circle cx="50" cy="43" r="34" fill="url(#loadingNetworkGlow)" />
          {links.map(([a, b]) => (
            <line
              key={`${a}-${b}`}
              x1={nodes[a]!.x}
              y1={nodes[a]!.y}
              x2={nodes[b]!.x}
              y2={nodes[b]!.y}
              stroke="var(--color-border)"
              strokeWidth="1"
              opacity="0.75"
            />
          ))}
          {nodes.map((node, index) => (
            <circle
              key={index}
              cx={node.x}
              cy={node.y}
              r={node.r}
              fill={index % 2 === 0 ? 'var(--color-oxblood)' : 'var(--color-meridian)'}
              opacity="0.28"
            />
          ))}
        </svg>
      </div>
      <div className="flex flex-col justify-center gap-3">
        {[84, 62, 74].map((width) => (
          <div key={width} className="rounded-md border border-border/70 bg-card/40 p-3">
            <div className="mb-2 flex items-center justify-between gap-3">
              <Skeleton className="h-2.5 w-24 rounded-full" />
              <Skeleton className="h-2.5 w-10 rounded-full" />
            </div>
            <Skeleton className="h-2 rounded-full bg-primary/20" style={{ width: `${width}%` }} />
          </div>
        ))}
      </div>
    </div>
  );
}

function TableSkeleton() {
  return (
    <div className="min-h-[220px] overflow-hidden rounded-lg border border-border/70 bg-muted/15 p-4">
      <div className="grid min-w-0 grid-cols-[minmax(0,1.1fr)_minmax(0,2fr)_minmax(0,0.8fr)_minmax(0,0.8fr)] gap-2 sm:gap-4 border-b border-border pb-3">
        {[90, 72, 58, 66].map((width, index) => (
          <Skeleton
            key={index}
            className="h-2 rounded-full"
            style={{ width: `${width}%` }}
          />
        ))}
      </div>
      <div className="flex flex-col gap-3 pt-4">
        {Array.from({ length: 6 }).map((_, row) => (
          <div key={row} className="grid min-w-0 grid-cols-[minmax(0,1.1fr)_minmax(0,2fr)_minmax(0,0.8fr)_minmax(0,0.8fr)] items-center gap-2 sm:gap-4">
            <Skeleton className="h-2.5 rounded-full" style={{ width: `${58 + (row % 3) * 10}%` }} />
            <div className="flex min-w-0 gap-1 overflow-hidden">
              {[0, 1, 2].map((chip) => (
                <Skeleton
                  key={chip}
                  className="h-5 shrink rounded-full border border-border"
                  style={{ width: `${48 + ((row + chip) % 3) * 18}px` }}
                />
              ))}
            </div>
            <Skeleton className="ml-auto h-2.5 w-10 rounded-full bg-primary/20" />
            <Skeleton className="ml-auto h-2.5 w-14 rounded-full" />
          </div>
        ))}
      </div>
    </div>
  );
}
