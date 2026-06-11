import { toast as sonnerToast } from 'sonner';
import type { ExternalToast } from 'sonner';

/**
 * App-facing toast API. Thin wrapper over sonner so we can swap themes or
 * the underlying lib without grepping 16 files. Call sites should import
 * from here instead of `sonner` directly.
 *
 * Add new default descriptors (e.g., timings, dismissible presets) in one
 * place — keep app-wide tone consistent with CLAUDE.md's "editorial, not
 * stoplight" register.
 *
 * We re-export sonner's full `ExternalToast` as `ToastOptions` so call
 * sites still get `icon`, `cancel`, `action`, `className`, etc. without
 * us having to re-declare the whole surface.
 */
export type ToastOptions = ExternalToast;

export const appToast = {
  success(message: string, opts?: ToastOptions) {
    return sonnerToast.success(message, opts);
  },
  error(message: string, opts?: ToastOptions) {
    return sonnerToast.error(message, opts);
  },
  info(message: string, opts?: ToastOptions) {
    return sonnerToast(message, opts);
  },
  warn(message: string, opts?: ToastOptions) {
    return sonnerToast.warning(message, opts);
  },
  loading(message: string, opts?: ToastOptions) {
    return sonnerToast.loading(message, opts);
  },
  dismiss(id?: string | number) {
    return sonnerToast.dismiss(id);
  },
  /**
   * Low-level escape hatch when none of the typed variants fit (custom JSX,
   * promise toast, etc). Prefer the typed variants wherever possible.
   */
  raw: sonnerToast,
};
