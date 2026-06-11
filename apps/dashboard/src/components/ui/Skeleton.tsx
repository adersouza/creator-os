import type React from 'react';
import { cn } from '@/lib/utils';

interface SkeletonProps extends React.ComponentProps<'div'> {
  className?: string | undefined;
  key?: React.Key | undefined;
}

/**
 * Skeleton — CLAUDE.md compliant. 14px radius matches card token;
 * dark mode uses glass material instead of solid white/10.
 */
export function Skeleton({ className, ...props }: SkeletonProps) {
  return (
    // Individual bars are decorative shimmer; the wrapping page-level
    // skeleton carries the role="status" announcement so screen readers
    // hear "Loading" once per page, not once per bar.
    <div
      aria-hidden="true"
      className={cn(
        'relative overflow-hidden rounded-xl',
        'td-surface-subtle',
        'before:absolute before:inset-0 before:-translate-x-full',
        'before:animate-[juno-shimmer_1.4s_cubic-bezier(0.23,1,0.32,1)_infinite]',
        'before:bg-gradient-to-r before:from-transparent before:via-white/[0.08] before:to-transparent',
        'dark:before:via-white/[0.06]',
        className,
      )}
      {...props}
    />
  );
}

export function SkeletonChart({ className, ...props }: SkeletonProps) {
  return (
    <div
      className={cn(
        'card w-full h-[300px] flex items-end gap-2 p-6 relative overflow-hidden',
        className,
      )}
      {...props}
    >
      {[30, 60, 45, 80, 65, 100, 85].map((h, i) => (
        <Skeleton
          key={i}
          className="flex-1 rounded-t-sm"
          style={{ height: `${h}%` }}
        />
      ))}
    </div>
  );
}

export function SkeletonKPICard({ className, ...props }: SkeletonProps) {
  return (
    <div
      className={cn('card p-5 relative overflow-hidden', className)}
      {...props}
    >
      <div className="flex justify-between items-center mb-3">
        <Skeleton className="w-24 h-3 rounded-full" />
        <Skeleton className="w-1.5 h-1.5 rounded-full" />
      </div>
      <Skeleton className="w-28 h-8 mb-2 rounded-[8px]" />
      <Skeleton className="w-20 h-2.5 rounded-full" />
      <div className="mt-3 h-8">
        <Skeleton className="w-full h-full rounded-[6px]" />
      </div>
    </div>
  );
}

export function SkeletonList({ count = 3, className, ...props }: SkeletonProps & { count?: number | undefined }) {
  return (
    <div className={cn('space-y-3', className)} {...props}>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="w-9 h-9 rounded-full shrink-0" />
          <div className="flex-1 space-y-2">
            <Skeleton className="w-[60%] h-3" />
            <Skeleton className="w-[40%] h-2.5 opacity-70" />
          </div>
          <Skeleton className="w-14 h-5 rounded-full shrink-0" />
        </div>
      ))}
    </div>
  );
}
