import { lazy, Suspense } from "react";
import { Modal } from "@/components/ui/Modal";

// Lazy — Composer.tsx is ~3700 lines. Static-importing it here (Layout →
// ComposerModal → Composer) dragged the page into the main chunk even
// though the /composer route is already React.lazy()'d in App.tsx. Split
// it out so the initial bundle doesn't ship the editor until the user
// actually presses C.
const Composer = lazy(() =>
	import("@/pages/Composer").then((m) => ({ default: m.Composer })),
);

/* =========================================================================
   ComposerModal — primary entry for new posts via `C` shortcut
   Per CLAUDE.md: Composer is a modal, not a sidebar page. The /composer
   route still renders the full-page version for direct-link access.
   ========================================================================= */

interface Props {
	isOpen: boolean;
	onClose: () => void;
}

export function ComposerModal({ isOpen, onClose }: Props) {
	return (
		<Modal
			open={isOpen}
			onClose={onClose}
			title={
				<span className="inline-flex items-center gap-2">
					<span
						className="size-1.5 rounded-full bg-[color:var(--color-oxblood)]"
						aria-hidden="true"
					/>
					Composer
				</span>
			}
			description="New post"
			ariaLabel="Composer"
			maxWidthClass="max-w-none"
			containerClassName="p-0 md:px-4 md:py-8"
			panelClassName="flex h-dvh w-full overflow-hidden rounded-none border-0 bg-background md:h-[90vh] md:w-[min(1200px,94vw)] md:rounded-2xl md:border md:border-border"
			bodyClassName="flex-1 min-h-0 overflow-y-auto p-0"
			disablePanelBlur
		>
			<Suspense
				fallback={
					<div className="flex h-full items-center justify-center text-[0.8125rem] text-muted-foreground">
						Loading composer…
					</div>
				}
			>
				<Composer />
			</Suspense>
		</Modal>
	);
}
