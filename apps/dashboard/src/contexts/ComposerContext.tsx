import { createContext, useContext } from 'react';

/* =========================================================================
   ComposerContext — exposes the app-level composer modal toggle so any
   descendant can open the `C` composer without route navigation.
   Provider lives in Layout where the modal state is owned.

   Dirty-state wiring: the Composer body reports its unsaved-work status
   + a saveDraft callback via setDirtyState(). Layout uses those to gate
   the modal close path behind a three-button confirm dialog (Keep
   editing / Discard / Save draft & close).
   ========================================================================= */

interface ComposerCtx {
  isOpen: boolean;
  open: () => void;
  /** Raw close — ignores the dirty guard. Use for successful publish/save
   *  paths where the work is already persisted. */
  close: () => void;
  /** Guarded close — shows the confirm dialog if the composer reports
   *  dirty state. Use for user-initiated close paths (Esc, X, backdrop). */
  requestClose: () => void;
  /** Composer body registers its dirty boolean + optional saveDraft fn.
   *  Pass (false) with no saveDraft on unmount to clear the guard. */
  setDirtyState: (
    dirty: boolean,
    saveDraft?: (() => Promise<void> | void) | null,
  ) => void;
}

export const ComposerContext = createContext<ComposerCtx>({
  isOpen: false,
  open: () => {},
  close: () => {},
  requestClose: () => {},
  setDirtyState: () => {},
});

export const useComposer = () => useContext(ComposerContext);
