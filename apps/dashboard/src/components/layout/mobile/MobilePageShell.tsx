import { RefreshCw } from "lucide-react";
import type { ReactNode } from "react";
import { usePullToRefresh } from "@/hooks/usePullToRefresh";
import { cn } from "@/lib/utils";

interface MobilePageShellProps {
	topBar?: ReactNode;
	onPullRefresh?: (() => unknown | Promise<unknown>) | undefined;
	/**
	 * When true, applies the local mobile Nova surface class. Set on Dashboard
	 * mobile because it renders up to `lg:hidden` (1023px).
	 */
	localOperatorMaterial?: boolean;
	/**
	 * Tailwind breakpoint at which to hide the shell. `md` matches sibling
	 * desktop views gated with `hidden md:block` (Calendar / Inbox / Accounts).
	 * `lg` matches Dashboard mobile. Defaults to `md`.
	 */
	hideAt?: "md" | "lg";
	children: ReactNode;
	className?: string | undefined;
}

export function MobilePageShell({
	topBar,
	onPullRefresh,
	localOperatorMaterial = false,
	hideAt = "md",
	children,
	className,
}: MobilePageShellProps) {
	return (
		<div
			className={cn(
				"mobile-app-page px-4 pt-3 pb-[100px]",
				hideAt === "md" ? "md:hidden" : "lg:hidden",
				localOperatorMaterial && "mobile-nova-surface",
				className,
			)}
			style={{ overscrollBehaviorY: "contain" }}
		>
			{onPullRefresh ? <PullRefreshLayer onRefresh={onPullRefresh} /> : null}
			{topBar}
			{children}
		</div>
	);
}

function PullRefreshLayer({
	onRefresh,
}: {
	onRefresh: () => unknown | Promise<unknown>;
}) {
	const { isPulling, pullDistance, isRefreshing } = usePullToRefresh({
		onRefresh,
		threshold: 72,
	});
	const indicatorActive = isPulling || isRefreshing;
	const indicatorOffset = isRefreshing ? 56 : pullDistance;
	const reachedThreshold = pullDistance >= 72;
	return (
		<PullIndicator
			active={indicatorActive}
			offset={indicatorOffset}
			ready={reachedThreshold}
			spinning={isRefreshing}
		/>
	);
}

function PullIndicator({
	active,
	offset,
	ready,
	spinning,
}: {
	active: boolean;
	offset: number;
	ready: boolean;
	spinning: boolean;
}) {
	const opacity = Math.min(offset / 48, 1);
	return (
		<div
			aria-hidden={!active}
			className="pointer-events-none fixed left-1/2 z-30 flex items-center justify-center"
			style={{
				top: "calc(env(safe-area-inset-top, 0px) + 8px)",
				transform: `translate(-50%, ${Math.max(offset - 24, 0)}px)`,
				opacity: active ? opacity : 0,
				transition: spinning ? "transform 200ms ease-out" : undefined,
			}}
		>
			<div
				className="w-9 h-9 rounded-full bg-card border border-border shadow-[0_2px_8px_color-mix(in_srgb,var(--color-foreground)_12%,transparent)] flex items-center justify-center"
				style={{
					color:
						ready || spinning
							? "var(--color-oxblood)"
							: "var(--color-label-tertiary, currentColor)",
				}}
			>
				<RefreshCw
					aria-hidden="true"
					className={spinning ? "w-4 h-4 animate-spin" : "w-4 h-4"}
					strokeWidth={1.75}
					style={{
						transform: spinning
							? undefined
							: `rotate(${Math.min(offset * 4, 360)}deg)`,
						transition: spinning ? undefined : "transform 80ms linear",
					}}
				/>
			</div>
		</div>
	);
}
