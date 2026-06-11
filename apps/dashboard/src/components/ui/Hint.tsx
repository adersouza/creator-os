import type React from 'react';
import { X } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from '@/lib/utils';

/**
 * Hint — two variants for persistent, first-time operator hints.
 *
 * HintPill: floats bottom-right, pulsing dot, calm editorial tone. Best for
 *   global affordances the operator might discover later (⌘K, theme toggle).
 * HintBanner: inline, tied to the page it appears on, persistent until × tap.
 *   Best for feature-specific hints (drag-to-reorder on Calendar, AI rephrase
 *   in Composer).
 *
 * Both pair with useFirstTimeHint(id) for one-shot semantics + multi-tab sync.
 */

interface HintPillProps {
  show: boolean;
  onDismiss: () => void;
  children: React.ReactNode;
  /** 'bottom-right' (default) or 'bottom-left' — pick a corner that's clear
   *  of other chrome on the host page. */
  corner?: 'bottom-right' | 'bottom-left' | undefined;
}

export function HintPill({ show, onDismiss, children, corner = 'bottom-right' }: HintPillProps) {
  return (
    <AnimatePresence>
      {show && (
        <motion.div
          initial={{ opacity: 0, y: 16, scale: 0.96 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 12, scale: 0.96 }}
          transition={{ duration: 0.22, ease: [0.23, 1, 0.32, 1] }}
          className={cn(
            'fixed z-[60] flex items-center gap-2',
            'pl-3 pr-1.5 py-1.5 rounded-full',
            'bg-card border',
            'shadow-[0_6px_16px_color-mix(in_srgb,var(--color-foreground)_8%,transparent)]',
            'text-[0.71875rem] text-muted-foreground',
            corner === 'bottom-right' ? 'right-5 bottom-5' : 'left-5 bottom-5',
          )}
          style={{ borderColor: 'color-mix(in srgb, var(--color-oxblood) 30%, var(--color-border))' }}
          role="status"
          aria-live="polite"
        >
          <span
            className="w-1.5 h-1.5 rounded-full"
            style={{ background: 'var(--color-oxblood)', animation: 'hint-pulse 2s ease infinite' }}
            aria-hidden="true"
          />
          <span className="whitespace-nowrap">{children}</span>
          <button
            type="button"
            onClick={onDismiss}
            aria-label="Dismiss tip"
            className="w-8 h-8 rounded-full inline-flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood-strong)]"
          >
            <X className="w-3 h-3" />
          </button>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

interface HintBannerProps {
  show: boolean;
  onDismiss: () => void;
  children: React.ReactNode;
  className?: string | undefined;
}

export function HintBanner({ show, onDismiss, children, className }: HintBannerProps) {
  return (
    <AnimatePresence initial={false}>
      {show && (
        <motion.div
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.2, ease: [0.23, 1, 0.32, 1] }}
          className={className}
        >
          <div
            className={cn(
              'flex items-center gap-2.5 pr-2 py-2.5 pl-2 rounded-lg',
              'bg-[color-mix(in_srgb,var(--color-oxblood)_8%,var(--color-card))]',
              'ring-1 ring-inset ring-[color-mix(in_srgb,var(--color-oxblood)_18%,transparent)]',
              'text-[0.78125rem] text-muted-foreground',
            )}
            role="status"
            aria-live="polite"
          >
            <div className="flex-1 leading-relaxed pl-1">{children}</div>
            <button
              type="button"
              onClick={onDismiss}
              aria-label="Dismiss tip"
              className="w-8 h-8 rounded-md inline-flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)] shrink-0"
            >
              <X className="w-3 h-3" />
            </button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
