import { Bell } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/Button";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { Sigil33 } from "@/components/ui/Sigil33";
import { cn } from "@/lib/utils";

interface MobileTopBarProps {
	title: ReactNode;
	subtitle?: ReactNode;
	rightSlot?: ReactNode;
	/** Optional eyebrow above the title (e.g., live-status pulse). */
	eyebrow?: ReactNode;
	/** Sticky-strip glass treatment. Defaults to true. */
	sticky?: boolean;
	className?: string | undefined;
}

/**
 * Generic mobile top bar used by Calendar / Inbox / Accounts. Renders a glass
 * strip that sits flush with the shell's horizontal padding (-mx-4 px-4).
 * Apply `sticky=false` only if a surface needs an inline header.
 */
export function MobileTopBar({
	title,
	subtitle,
	rightSlot,
	eyebrow,
	sticky = true,
	className,
}: MobileTopBarProps) {
	return (
		<NovaCard
			className={cn("-mx-4 mb-3 rounded-none border-x-0 border-t-0 shadow-sm", sticky && "sticky top-0 z-20", className)}
			contentClassName="px-4 py-3"
		>
			{eyebrow ? <div className="mb-1.5">{eyebrow}</div> : null}
			<div className="flex items-baseline justify-between gap-3">
				<div className="min-w-0">
					<div className="text-[1.125rem] font-semibold tracking-[-0.02em] text-foreground truncate">
						{title}
					</div>
					{subtitle ? (
						<div className="text-[0.6875rem] text-muted-foreground mt-0.5 truncate">
							{subtitle}
						</div>
					) : null}
				</div>
				{rightSlot ? (
					<div className="shrink-0 flex items-center gap-1.5">{rightSlot}</div>
				) : null}
			</div>
		</NovaCard>
	);
}

interface MobileBrandTopBarProps {
	onOpenActivity: () => void;
	statusLabel: string;
	statusTone: "good" | "warn";
	/** Brand mark + word mark live in this slot. Defaults to "Juno33 / Operator". */
	brandLabel?: ReactNode;
}

/**
 * Dashboard-only top bar — sigil + Juno33/Operator + health pill + bell.
 * Mirrors the original `MobileTopBar` from MobileOverview.tsx so visual
 * identity stays unchanged.
 */
export function MobileBrandTopBar({
	onOpenActivity,
	statusLabel,
	statusTone,
	brandLabel,
}: MobileBrandTopBarProps) {
	return (
		<div className="mobile-home-topbar flex items-center justify-between py-2">
			<div className="flex items-center gap-2 text-foreground">
				<span className="mobile-home-sigil inline-flex items-center justify-center">
					<Sigil33 size={22} />
				</span>
				<div className="leading-tight">
					{brandLabel ?? (
						<>
							<span className="block text-[0.875rem] font-semibold tracking-tight">
								Juno33
							</span>
							<span className="block text-[0.625rem] font-semibold uppercase tracking-[0.13em] text-muted-foreground">
								Operator
							</span>
						</>
					)}
				</div>
			</div>
			<div className="flex items-center gap-2">
				{statusTone === "warn" ? (
					<Link
						to="/accounts?status=flagged"
						className="mobile-health-pill"
						title={statusLabel}
					>
						<span
							role="img"
							className="w-[6px] h-[6px] rounded-full"
							style={{ backgroundColor: "var(--color-oxblood)" }}
							aria-label={statusLabel}
						/>
						<span className="max-w-[88px] truncate">Needs review</span>
					</Link>
				) : (
					<span className="mobile-health-pill" title={statusLabel}>
						<span
							role="img"
							className="w-[6px] h-[6px] rounded-full"
							style={{ backgroundColor: "var(--color-gold)" }}
							aria-label={statusLabel}
						/>
						<span className="max-w-[88px] truncate">Healthy</span>
					</span>
				)}
				<Button
					type="button"
					onClick={onOpenActivity}
					aria-label="Activity"
					variant="ghost"
					size="icon"
					className="size-11 rounded-full"
				>
					<span className="mobile-icon-button w-[32px] h-[32px] rounded-full bg-muted border border-border flex items-center justify-center text-muted-foreground">
						<Bell className="w-3.5 h-3.5" />
					</span>
				</Button>
			</div>
		</div>
	);
}
