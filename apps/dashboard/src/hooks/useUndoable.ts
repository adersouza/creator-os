import { useEffect, useRef } from 'react';
import { appToast } from '@/lib/toast';

/**
 * useUndoable — show a toast with an inline Undo + bind ⌘Z while it's live.
 *
 * Pattern: operator triggers an action (AI rephrase, schedule move, bulk
 * target toggle). The action runs immediately. Right after, call
 * `undo({ label, description, revert })`. A toast appears with an Undo
 * button; ⌘Z (or Ctrl+Z) also fires revert. When the toast auto-dismisses
 * (6s) or another undo is queued, the shortcut detaches.
 *
 * Single-level undo on purpose — no stack. If the operator rewrites, moves
 * the schedule, and rewrites again, only the last action is recoverable.
 * A stack would need an actual history surface; that's the Composer-wide
 * undo from #16(a) proper, out of scope here.
 *
 * Usage:
 *   const { undo } = useUndoable();
 *   const handleRephrase = async () => {
 *     const before = caption;
 *     setCaption(await aiRephrase(caption));
 *     undo({
 *       label: 'Caption rewritten with AI',
 *       description: `Voice: ${voice} · ${countWords(before)} → ${countWords(next)} words`,
 *       revert: () => setCaption(before),
 *     });
 *   };
 */

export interface UndoableOptions {
  label: string;
  description?: string | undefined;
  revert: () => void;
  /** Milliseconds the toast + shortcut stay live. Default 6000. */
  duration?: number | undefined;
}

export function useUndoable() {
  const activeRef = useRef<{ toastId: string | number; revert: () => void } | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Ignore when typing in an input/textarea/contenteditable — the
      // editor's own undo stack is the right surface there.
      const target = e.target as HTMLElement | null;
      if (target) {
        const tag = target.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || target.isContentEditable) return;
      }
      if (!(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== 'z') return;
      if (!activeRef.current) return;
      e.preventDefault();
      const { toastId, revert } = activeRef.current;
      revert();
      appToast.dismiss(toastId);
      activeRef.current = null;
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const undo = (opts: UndoableOptions) => {
    const duration = opts.duration ?? 6000;
    const toastId = appToast.info(opts.label, {
      description: opts.description,
      duration,
      action: {
        label: 'Undo',
        onClick: () => {
          opts.revert();
          activeRef.current = null;
        },
      },
      onDismiss: () => {
        if (activeRef.current?.toastId === toastId) activeRef.current = null;
      },
      onAutoClose: () => {
        if (activeRef.current?.toastId === toastId) activeRef.current = null;
      },
    });
    activeRef.current = { toastId, revert: opts.revert };
  };

  return { undo };
}
