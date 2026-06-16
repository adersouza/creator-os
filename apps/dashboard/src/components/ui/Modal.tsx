import { X } from "lucide-react";
import { Dialog } from "radix-ui";
import { AnimatePresence, motion } from "motion/react";
import React from "react";
import { useBodyScrollLock } from "@/hooks/useBodyScrollLock";
import { cn } from "@/lib/utils";
import { Z } from "./overlayZ";

/**
 * Centered modal primitive. Replaces the three ad-hoc modal patterns
 * (ComposerModal inline, PostAutopsyModal inline, destructive confirms).
 * Motion matches the landing-page signature: `translateY(8px) + scale(0.96)`
 * → `0/1` over 150ms on cubic-bezier(0.23, 1, 0.32, 1). Respects
 * `prefers-reduced-motion` via motion/react's MotionConfig inheritance.
 */
export interface ModalProps {
	open: boolean;
	onClose: () => void;
	title?: React.ReactNode | undefined;
	description?: React.ReactNode | undefined;
	children?: React.ReactNode | undefined;
	footer?: React.ReactNode | undefined;
	/** Max width class — default max-w-lg, pass 'max-w-2xl' etc. for wider content. */
	maxWidthClass?: string | undefined;
	/** Set true to hide the default close button (still closes on backdrop/Esc). */
	hideCloseButton?: boolean | undefined;
	ariaLabel?: string | undefined;
	/** Optional backdrop override for lighter context-preserving modals. */
	backdropClassName?: string | undefined;
	/** Optional panel override for feature-specific modal surfaces. */
	panelClassName?: string | undefined;
	/** Optional body override when a modal needs an internal scroll/flex layout. */
	bodyClassName?: string | undefined;
	/** Optional fixed container override for full-screen or edge-to-edge modals. */
	containerClassName?: string | undefined;
	/** Disable the default frosted panel blur when content readability matters. */
	disablePanelBlur?: boolean | undefined;
}

const EASE = [0.23, 1, 0.32, 1] as const;

export function Modal({
	open,
	onClose,
	title,
	description,
	children,
	footer,
	maxWidthClass = "max-w-lg",
	hideCloseButton,
	ariaLabel,
	backdropClassName,
	panelClassName,
	bodyClassName,
	containerClassName,
	disablePanelBlur,
}: ModalProps) {
	useControlledDialogFocusRestore(open);
	// iOS-correct body scroll lock — overflow:hidden alone is not enough on
	// mobile Safari, so this hook uses position:fixed + scrollY restore.
	useBodyScrollLock(open);

	if (typeof document === "undefined") return null;

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
						<div
							className={cn(
								"fixed inset-0 flex items-center justify-center px-4 py-8",
								containerClassName,
							)}
							style={{ zIndex: Z.modal }}
						>
							<Dialog.Overlay asChild forceMount>
								<motion.div
									initial={{ opacity: 0 }}
									animate={{ opacity: 1 }}
									exit={{ opacity: 0 }}
									transition={{ duration: 0.15, ease: EASE }}
									className={
										backdropClassName ??
										"absolute inset-0 bg-foreground/30 dark:bg-black/72 backdrop-blur-sm"
									}
									style={{ zIndex: Z.modalBackdrop }}
								/>
							</Dialog.Overlay>
							<Dialog.Content asChild forceMount>
								<motion.div
									aria-label={
										ariaLabel || (typeof title === "string" ? title : "Dialog")
									}
									{...(description ? {} : { "aria-describedby": undefined })}
									initial={{ opacity: 0, y: 8, scale: 0.96 }}
									animate={{ opacity: 1, y: 0, scale: 1 }}
									exit={{ opacity: 0, y: 8, scale: 0.96 }}
									transition={{ duration: 0.18, ease: EASE }}
									className={cn(
										"relative w-full bg-card border border-border rounded-2xl shadow-2xl",
										"focus:outline-none",
										maxWidthClass,
										panelClassName,
									)}
									style={
										disablePanelBlur
											? {}
											: {
													WebkitBackdropFilter: "blur(20px) saturate(150%)",
													backdropFilter: "blur(20px) saturate(150%)",
												}
									}
								>
									{(title || !hideCloseButton) && (
										<div className="flex items-start gap-3 px-6 pt-5 pb-3 border-b border-border">
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
														<div className="text-[0.78125rem] text-muted-foreground mt-1 leading-relaxed">
															{description}
														</div>
													</Dialog.Description>
												)}
											</div>
											{!hideCloseButton && (
												<Dialog.Close asChild>
													<button
														type="button"
														aria-label="Close dialog"
														className="w-10 h-10 rounded-md inline-flex items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground transition-colors shrink-0 -mr-1 outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)]"
													>
														<X className="w-4 h-4" />
													</button>
												</Dialog.Close>
											)}
										</div>
									)}
									<div className={cn("px-6 py-5", bodyClassName)}>
										{children}
									</div>
									{footer && (
										<div className="px-6 py-4 border-t border-border flex items-center justify-end gap-2">
											{footer}
										</div>
									)}
								</motion.div>
							</Dialog.Content>
						</div>
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
				document.activeElement instanceof HTMLElement
					? document.activeElement
					: null;
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
