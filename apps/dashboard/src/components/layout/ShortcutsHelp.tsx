// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import React from 'react';
import { X } from 'lucide-react';
import { SHORTCUT_LABELS, type ShortcutKey } from '@/hooks/useKeyboardShortcuts';
import { Z } from '@/components/ui/overlayZ';
import { useFocusTrap } from '@/hooks/useFocusTrap';
import { Button } from "@/components/ui/Button";
import { Kbd } from "@/components/ui/Kbd";

interface Props {
  isOpen: boolean;
  onClose: () => void;
}

/**
 * Keyboard shortcuts help overlay — press `?` to open.
 * Research (micro_interactions_2026): "The `?` key opens a searchable shortcuts overlay —
 * near-universal convention (Linear, Gmail, GitHub)."
 */
export function ShortcutsHelp({ isOpen, onClose }: Props) {
  // Tab-cycle focus trap + initial focus on open. Replaces the unguarded
  // dialog that let Tab walk into background content.
  const trapRef = useFocusTrap<HTMLDivElement>(onClose, isOpen);

  // Group shortcuts by category
  const groups = (Object.entries(SHORTCUT_LABELS) as [ShortcutKey, typeof SHORTCUT_LABELS[ShortcutKey]][]).reduce(
    (acc, [, meta]) => {
      if (!acc[meta.group]) acc[meta.group] = [];
      acc[meta.group]!.push(meta);
      return acc;
    },
    {} as Record<string, (typeof SHORTCUT_LABELS[ShortcutKey])[]>
  );

  if (!isOpen) return null;

  return (
    <>
      <div
        onClick={onClose}
        className="fixed inset-0 bg-foreground/30 dark:bg-black/72 backdrop-blur-sm"
        style={{ zIndex: Z.modalBackdrop }}
      />
      <div
        className="fixed inset-0 flex items-start justify-center pt-[18vh] px-4 pointer-events-none"
        style={{ zIndex: Z.modal }}
      >
        <div
          ref={trapRef}
          role="dialog"
          aria-modal="true"
          aria-label="Keyboard shortcuts"
          className="pointer-events-auto w-full max-w-[520px] overflow-hidden rounded-xl border border-border bg-card text-card-foreground shadow-2xl"
          onClick={(e) => e.stopPropagation()}
        >
              {/* Header */}
              <div className="flex items-center justify-between px-5 py-4 border-b border-border">
                <div>
                  <h3 className="text-[0.9375rem] font-semibold text-foreground">Keyboard shortcuts</h3>
                  <p className="text-[0.71875rem] text-muted-foreground mt-0.5">Press <Kbd>?</Kbd> anytime to toggle this</p>
                </div>
                <Button
                  type="button"
                  onClick={onClose}
                  variant="ghost"
                  size="icon"
                  className="size-7"
                  aria-label="Close shortcuts"
                >
                  <X className="w-4 h-4" />
                </Button>
              </div>

              {/* Groups */}
              <div className="px-5 py-4 max-h-[55vh] overflow-y-auto">
                {Object.entries(groups).map(([group, items]) => (
                  <div key={group} className="mb-5 last:mb-0">
                    <div className="text-[0.625rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground mb-2.5">
                      {group}
                    </div>
                    <div className="flex flex-col gap-1.5">
                      {items.map((item) => (
                        <div key={item.label} className="flex items-center justify-between py-1">
                          <span className="text-[0.8125rem] text-foreground">{item.label}</span>
                          <div className="flex items-center gap-1">
                            {item.keys.map((k, i) => (
                              <React.Fragment key={k}>
                                <Kbd>{k}</Kbd>
                                {i < item.keys.length - 1 && (
                                  <span className="text-[0.625rem] text-muted-foreground font-medium">then</span>
                                )}
                              </React.Fragment>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>

              {/* Footer */}
              <div className="px-5 py-3 border-t border-border flex items-center justify-between text-[0.65625rem] text-muted-foreground">
                <span>
                  Shortcuts disabled when typing in a field.
                </span>
                <span style={{ color: 'var(--color-oxblood)' }} className="font-medium uppercase tracking-wider">
                  Juno33
                </span>
              </div>
        </div>
      </div>
    </>
  );
}
