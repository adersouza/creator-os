import type React from 'react';
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'motion/react';
import { ChevronDown } from 'lucide-react';
import { Z } from './overlayZ';

/* =========================================================================
   FilterSelect — premium pill-style dropdown with signature motion
   ──────────────────────────────────────────────────────────────────────
   · Pill trigger: color dot + label + optional count badge + rotating chevron
   · Glass popover: landing blueprint recipe (blur + saturate + hairline)
   · Oxblood left-edge accent bar slides in on hover/focus — signature move
   · Staggered option reveal (30ms/item)
   · Checkmark draw-in stroke animation on active row
   · Keyboard: ↑↓ navigate · Enter select · Esc close · type-ahead first-letter
   ========================================================================= */

export interface FilterOption<T extends string> {
  value: T;
  label: string;
  /** Color dot (CSS color) shown left of label */
  dot?: string | undefined;
  /** Optional count/number shown right of label (e.g., "47") */
  count?: number | string | undefined;
  /** Optional small description under label */
  detail?: string | undefined;
}

export interface FilterSelectProps<T extends string> {
  value: T;
  onChange: (v: T) => void;
  options: FilterOption<T>[];
  /** Optional eyebrow label rendered above the trigger — "NETWORK" style */
  label?: string | undefined;
  /** Width of popover in px. Defaults to 220. */
  menuWidth?: number | undefined;
  /** Align popover to trigger. Defaults to 'start'. */
  align?: 'start' | 'end' | undefined;
  /** aria-label for the trigger */
  ariaLabel?: string | undefined;
}

export function FilterSelect<T extends string>({
  value,
  onChange,
  options,
  label,
  menuWidth = 220,
  align = 'start',
  ariaLabel,
}: FilterSelectProps<T>) {
  const [open, setOpen] = useState(false);
  const edgeLayoutId = `filter-select-edge-${useId()}`;
  const [focusIdx, setFocusIdx] = useState<number>(() =>
    Math.max(0, options.findIndex(o => o.value === value)),
  );
  const [menuPos, setMenuPos] = useState<{ top: number; left: number } | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const current = options.find(o => o.value === value) ?? options[0];

  // Recompute menu position from trigger's bounding rect
  const updatePosition = useCallback(() => {
    if (!triggerRef.current) return;
    const rect = triggerRef.current.getBoundingClientRect();
    const left = align === 'end'
      ? rect.right - menuWidth
      : rect.left;
    const top = rect.bottom + 6;
    const clampedLeft = Math.max(8, Math.min(left, window.innerWidth - menuWidth - 8));
    setMenuPos((prev) => {
      if (prev && prev.top === top && prev.left === clampedLeft) return prev;
      return { top, left: clampedLeft };
    });
  }, [align, menuWidth]);

  useLayoutEffect(() => {
    if (!open) return;
    updatePosition();
    const onScroll = () => updatePosition();
    const onResize = () => updatePosition();
    // Capture scroll from ANY ancestor, not just window
    window.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', onResize);
    };
  }, [open, updatePosition]);

  // Close on outside click — checks both trigger and portal-mounted menu
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node;
      if (rootRef.current?.contains(t)) return;
      if (menuRef.current?.contains(t)) return;
      setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  // Reset focus index when opening
  useEffect(() => {
    if (open) {
      setFocusIdx(Math.max(0, options.findIndex(o => o.value === value)));
    }
  }, [open, options, value]);

  // Keyboard navigation
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        setOpen(false);
        triggerRef.current?.focus();
        return;
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setFocusIdx(i => Math.min(options.length - 1, i + 1));
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setFocusIdx(i => Math.max(0, i - 1));
        return;
      }
      if (e.key === 'Home') {
        e.preventDefault();
        setFocusIdx(0);
        return;
      }
      if (e.key === 'End') {
        e.preventDefault();
        setFocusIdx(options.length - 1);
        return;
      }
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        const opt = options[focusIdx];
        if (opt) {
          onChange(opt.value);
          setOpen(false);
          triggerRef.current?.focus();
        }
        return;
      }
      // Type-ahead: first-letter match
      if (e.key.length === 1 && /\w/.test(e.key)) {
        const ch = e.key.toLowerCase();
        const nextIdx = options.findIndex((o, i) =>
          i > focusIdx && o.label.toLowerCase().startsWith(ch),
        );
        const fallbackIdx = options.findIndex(o => o.label.toLowerCase().startsWith(ch));
        const target = nextIdx >= 0 ? nextIdx : fallbackIdx;
        if (target >= 0) setFocusIdx(target);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, focusIdx, options, onChange]);

  const handleTriggerKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      setOpen(true);
    }
  };

  // Stagger delay per item — capped at 6 items (landing blueprint rule)
  const staggerFor = (i: number) => Math.min(i, 6) * 0.03;

  return (
    <div className="relative inline-block" ref={rootRef}>
      {label && (
        <div className="text-[0.625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1.5">
          {label}
        </div>
      )}
      <motion.button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen(o => !o)}
        onKeyDown={handleTriggerKeyDown}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel ?? current?.label}
        whileHover={{ y: -1 }}
        whileTap={{ y: 0 }}
        transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
        className={`group relative h-9 pl-3 pr-2.5 rounded-md bg-card border border-border inline-flex items-center gap-2 text-[0.78125rem] text-foreground transition-colors td-control-shadow hover:border-input ${open ? 'border-input' : ''}`}
      >
        {current?.dot && (
          <span
            className="w-1.5 h-1.5 rounded-full flex-shrink-0"
            style={{ background: current.dot }}
          />
        )}
        <span className="font-medium truncate">{current?.label}</span>
        {current?.count !== undefined && (
          <span className="text-[0.65625rem] font-semibold tabular-nums px-1.5 h-4 rounded inline-flex items-center bg-muted text-muted-foreground">
            {current.count}
          </span>
        )}
        <motion.span
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          className="text-muted-foreground flex-shrink-0"
        >
          <ChevronDown className="w-3 h-3" />
        </motion.span>
      </motion.button>

      {typeof document !== 'undefined' && createPortal(
        <AnimatePresence>
          {open && menuPos && (
            <motion.div
              ref={menuRef}
              role="listbox"
              aria-label={ariaLabel}
              initial={{ opacity: 0, y: -6, filter: 'blur(6px)' }}
              animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
              exit={{ opacity: 0, y: -6, filter: 'blur(6px)' }}
              transition={{ duration: 0.22, ease: [0.23, 1, 0.32, 1] }}
              className="rounded-xl p-1.5 filter-select-menu"
              style={{
                position: 'fixed',
                top: menuPos.top,
                left: menuPos.left,
                width: menuWidth,
                zIndex: Z.popover,
                // Glass recipe — landing blueprint chrome
                background: 'color-mix(in srgb, var(--color-card) 82%, transparent)',
                backdropFilter: 'blur(24px) saturate(160%)',
                WebkitBackdropFilter: 'blur(24px) saturate(160%)',
                border: '0.5px solid color-mix(in srgb, var(--color-foreground) 8%, transparent)',
                boxShadow: '0 12px 36px color-mix(in srgb, var(--color-foreground) 12%, transparent), 0 2px 6px color-mix(in srgb, var(--color-foreground) 4%, transparent), inset 0 1px 0 color-mix(in srgb, var(--color-card) 60%, transparent)',
              }}
            >
            {options.map((opt, i) => {
              const isActive = opt.value === value;
              const isFocused = focusIdx === i;
              return (
                <motion.button
                  key={opt.value}
                  type="button"
                  initial={{ opacity: 0, x: -4 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.22, ease: [0.23, 1, 0.32, 1], delay: staggerFor(i) }}
                  onClick={() => {
                    onChange(opt.value);
                    setOpen(false);
                    triggerRef.current?.focus();
                  }}
                  onMouseEnter={() => setFocusIdx(i)}
                  aria-selected={isActive}
                  role="option"
                  className={`relative w-full text-left pl-3 pr-2.5 py-2 rounded-md inline-flex items-start gap-2.5 transition-colors ${
                    isFocused
                      ? 'bg-foreground/[0.05] text-foreground'
                      : 'text-foreground hover:bg-foreground/[0.035]'
                  }`}
                >
                  {/* Oxblood left-edge accent bar — signature move */}
                  <AnimatePresence>
                    {isFocused && (
                      <motion.span
                        layoutId={edgeLayoutId}
                        className="absolute left-0 top-1.5 bottom-1.5 w-[2px] rounded-full"
                        style={{ backgroundColor: 'var(--color-oxblood)' }}
                        transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
                        aria-hidden="true"
                      />
                    )}
                  </AnimatePresence>
                  {opt.dot && (
                    <span
                      className="w-1.5 h-1.5 rounded-full flex-shrink-0 mt-[7px]"
                      style={{ background: opt.dot }}
                    />
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-baseline gap-2">
                      <span className="text-[0.78125rem] font-medium truncate flex-1">{opt.label}</span>
                      {opt.count !== undefined && (
                        <span className="text-[0.65625rem] tabular-nums text-muted-foreground flex-shrink-0">
                          {opt.count}
                        </span>
                      )}
                    </div>
                    {opt.detail && (
                      <div className="text-[0.6875rem] text-muted-foreground truncate mt-0.5">
                        {opt.detail}
                      </div>
                    )}
                  </div>
                  {/* Animated checkmark — draws in via stroke-dash */}
                  <div className="w-3.5 h-3.5 flex-shrink-0 mt-[3px]">
                    {isActive && <AnimatedCheck />}
                  </div>
                </motion.button>
              );
            })}
            </motion.div>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </div>
  );
}

/** Checkmark that draws in via stroke-dash on mount. */
function AnimatedCheck() {
  return (
    <svg viewBox="0 0 14 14" className="w-full h-full" fill="none" aria-hidden="true">
      <motion.path
        d="M3 7.5 L6 10.5 L11 4"
        stroke="var(--color-oxblood)"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: 1 }}
        transition={{ duration: 0.3, ease: [0.23, 1, 0.32, 1] }}
      />
    </svg>
  );
}

/** Dark-mode glass override consumed via className `filter-select-menu` + `.dark` */
export const FilterSelectDarkStyles = `
.dark .filter-select-menu {
  background: color-mix(in srgb, var(--color-card) 82%, transparent) !important;
  border-color: color-mix(in srgb, var(--color-card) 8%, transparent) !important;
  box-shadow:
    0 12px 36px color-mix(in srgb, var(--color-foreground) 50%, transparent),
    0 2px 6px color-mix(in srgb, var(--color-foreground) 30%, transparent),
    inset 0 1px 0 color-mix(in srgb, var(--color-card) 8%, transparent) !important;
}
`;
