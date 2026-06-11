import { motion, AnimatePresence } from 'motion/react';
import * as AlertDialog from '@radix-ui/react-alert-dialog';
import { cn } from '@/lib/utils';
import { haptics } from '@/utils/haptics';
import { Button } from './Button';

export interface ConfirmDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void | Promise<void>;
  title: string;
  description: string;
  confirmLabel: string;
  cancelLabel?: string | undefined;
  destructive?: boolean | undefined;
  busy?: boolean | undefined;
  /** Optional third action, rendered as the primary CTA. When both onConfirm
   *  and onSecondary exist, the dialog renders three buttons: Cancel (ghost)
   *  / Confirm (usually destructive) / Secondary (primary). Used for
   *  "discard / save-and-close / keep editing" flows. */
  secondaryLabel?: string | undefined;
  onSecondary?: () => void | Promise<void> | undefined;
}

const EASE = [0.23, 1, 0.32, 1] as const;

export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel,
  cancelLabel = 'Cancel',
  destructive = false,
  busy = false,
  secondaryLabel,
  onSecondary,
}: ConfirmDialogProps) {
  return (
    <AlertDialog.Root
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && !busy) onClose();
      }}
    >
      <AnimatePresence>
        {open && (
          <AlertDialog.Portal forceMount>
            <AlertDialog.Overlay
              forceMount
              className="fixed inset-0 z-[110] td-overlay"
              style={{ backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)' }}
            />
            <AlertDialog.Content forceMount>
              <motion.div
                initial={{ opacity: 0, y: 8, scale: 0.96 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 8, scale: 0.96 }}
                transition={{ duration: open ? 0.4 : 0.2, ease: EASE }}
                className={cn(
                  'fixed left-1/2 top-1/2 z-[111] w-[min(440px,92vw)] -translate-x-1/2 -translate-y-1/2',
                  'bg-card border border-border rounded-2xl td-modal-shadow',
                  'focus:outline-none',
                )}
                style={{
                  backdropFilter: 'blur(20px) saturate(150%)',
                  WebkitBackdropFilter: 'blur(20px) saturate(150%)',
                }}
              >
                <div className="px-6 pt-5 pb-3">
                  <AlertDialog.Title className="text-[0.9375rem] font-medium text-foreground tracking-[-0.01em]">
                    {title}
                  </AlertDialog.Title>
                  <AlertDialog.Description className="text-[0.78125rem] text-muted-foreground mt-1.5 leading-relaxed">
                    {description}
                  </AlertDialog.Description>
                </div>
                <div className="px-6 pt-2 pb-5 flex items-center justify-end gap-2 flex-wrap">
                  <AlertDialog.Cancel asChild>
                    <Button
                      type="button"
                      variant={onSecondary ? 'ghost' : 'outline'}
                      disabled={busy}
                      className="h-9 text-sm"
                    >
                      {cancelLabel}
                    </Button>
                  </AlertDialog.Cancel>
                  <AlertDialog.Action asChild>
                    <Button
                      type="button"
                      variant={onSecondary ? 'outline' : 'default'}
                      disabled={busy}
                      onClick={(e) => {
                        e.preventDefault();
                        if (destructive) haptics.warning();
                        else haptics.light();
                        void onConfirm();
                      }}
                      className={cn(
                        'h-9 text-sm',
                        destructive &&
                          'bg-[var(--color-critical)] hover:bg-[var(--color-critical)] text-white border-transparent td-control-shadow',
                      )}
                    >
                      {busy ? 'Working…' : confirmLabel}
                    </Button>
                  </AlertDialog.Action>
                  {onSecondary && secondaryLabel && (
                    <AlertDialog.Action asChild>
                      <Button
                        type="button"
                        disabled={busy}
                        onClick={(e) => {
                          e.preventDefault();
                          haptics.light();
                          void onSecondary();
                        }}
                        className="h-9 text-sm"
                      >
                        {busy ? 'Working…' : secondaryLabel}
                      </Button>
                    </AlertDialog.Action>
                  )}
                </div>
              </motion.div>
            </AlertDialog.Content>
          </AlertDialog.Portal>
        )}
      </AnimatePresence>
    </AlertDialog.Root>
  );
}
