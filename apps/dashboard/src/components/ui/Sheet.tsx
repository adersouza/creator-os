import React from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { AnimatePresence, motion } from 'motion/react';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useBodyScrollLock } from '@/hooks/useBodyScrollLock';
import { Z } from './overlayZ';

/**
 * Right-side slide-over. Replaces the ad-hoc patterns in the Activity panel
 * and the Account detail drawer. Slides in from the right on desktop, rises
 * from the bottom on mobile (CLAUDE.md mobile spec: "bottom sheet on phone").
 */
export interface SheetProps {
  open: boolean;
  onClose: () => void;
  title?: React.ReactNode | undefined;
  description?: React.ReactNode | undefined;
  children?: React.ReactNode | undefined;
  /** Desktop width class. Defaults to w-[360px]. */
  widthClass?: string | undefined;
  /** Set true to hide the default close button. */
  hideCloseButton?: boolean | undefined;
  /** 'right' (default) or 'bottom' for mobile-style sheets. */
  side?: 'right' | 'bottom' | undefined;
  ariaLabel?: string | undefined;
  panelClassName?: string | undefined;
}

const EASE = [0.23, 1, 0.32, 1] as const;

export function Sheet({
  open,
  onClose,
  title,
  description,
  children,
  widthClass = 'w-full sm:w-[360px]',
  hideCloseButton,
  side = 'right',
  ariaLabel,
  panelClassName,
}: SheetProps) {
  useControlledDialogFocusRestore(open);
  // iOS Safari ignores body { overflow: hidden }; useBodyScrollLock pins
  // body via position:fixed and restores scrollY on close.
  useBodyScrollLock(open);

  if (typeof document === 'undefined') return null;

  const sideMotion = side === 'bottom'
    ? {
        initial: { y: '100%', opacity: 0 },
        animate: { y: 0, opacity: 1 },
        exit: { y: '100%', opacity: 0 },
      }
    : {
        initial: { x: 360, opacity: 0 },
        animate: { x: 0, opacity: 1 },
        exit: { x: 360, opacity: 0 },
      };

  const sidePosition = side === 'bottom'
    ? 'fixed inset-x-0 bottom-0 max-h-[90dvh] pb-[env(safe-area-inset-bottom,0)]'
    : 'fixed top-0 right-0 h-dvh';

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) onClose();
      }}
    >
      <AnimatePresence>
        {open && (
          <Dialog.Portal forceMount>
            <Dialog.Overlay asChild forceMount>
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15, ease: EASE }}
                className="fixed inset-0 bg-foreground/25 dark:bg-black/64 backdrop-blur-sm"
                style={{ zIndex: Z.sheetBackdrop }}
              />
            </Dialog.Overlay>
            <Dialog.Content asChild forceMount>
              <motion.div
                aria-label={ariaLabel || (typeof title === 'string' ? title : 'Panel')}
                {...(description ? {} : { 'aria-describedby': undefined })}
                initial={sideMotion.initial}
                animate={sideMotion.animate}
                exit={sideMotion.exit}
                transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
                className={cn(
                  'bg-card border-border shadow-2xl flex flex-col outline-none',
                  side === 'right' ? 'border-l' : 'border-t rounded-t-2xl',
                  sidePosition,
                  widthClass,
                  panelClassName,
                )}
                style={{
                  zIndex: Z.sheet,
                  WebkitBackdropFilter: 'blur(20px) saturate(150%)',
                  backdropFilter: 'blur(20px) saturate(150%)',
                }}
              >
                {!title && (
                  <Dialog.Title className="sr-only">
                    {ariaLabel || 'Panel'}
                  </Dialog.Title>
                )}
                {side === 'bottom' && (
                  <div
                    className="mx-auto mt-2 mb-1 h-1 w-10 rounded-full td-muted-dot shrink-0"
                    aria-hidden="true"
                  />
                )}
                {(title || !hideCloseButton) && (
                  <div className="flex items-start gap-3 px-5 py-4 border-b border-border">
                    <div className="flex-1 min-w-0">
                      {title && (
                        <Dialog.Title asChild>
                          <div className="text-[0.9375rem] font-medium text-foreground tracking-[-0.01em]">
                            {title}
                          </div>
                        </Dialog.Title>
                      )}
                      {description && (
                        <Dialog.Description asChild>
                          <div className="text-[0.75rem] text-muted-foreground mt-0.5 leading-relaxed">
                            {description}
                          </div>
                        </Dialog.Description>
                      )}
                    </div>
                    {!hideCloseButton && (
                      <Dialog.Close asChild>
                        <button
                          type="button"
                          aria-label="Close panel"
                          className="w-10 h-10 rounded-md inline-flex items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground transition-colors shrink-0 -mr-1 outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)]"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      </Dialog.Close>
                    )}
                  </div>
                )}
                <div className="flex-1 overflow-y-auto">{children}</div>
              </motion.div>
            </Dialog.Content>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  );
}

function useControlledDialogFocusRestore(open: boolean) {
  const restoreRef = React.useRef<HTMLElement | null>(null);
  const wasOpenRef = React.useRef(false);

  React.useEffect(() => {
    if (open && !wasOpenRef.current) {
      restoreRef.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
    }
    if (!open && wasOpenRef.current) {
      const target = restoreRef.current;
      requestAnimationFrame(() => {
        if (target && document.contains(target)) target.focus();
      });
    }
    wasOpenRef.current = open;
  }, [open]);
}
