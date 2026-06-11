import type React from "react";
import { cn } from "@/lib/utils";

// One pill to rule them all. Migrated: RoleBadge (Team), TypePill
// (ContentLibrary), StatusPill (Reports), JobStatusPill (Autopilot).
// Intentionally NOT migrated: NetworkPill + PlatformBadge (use
// network-brand colors: aurora/meridian/harbor/vale, not the editorial
// health palette); PlatformPills + TimeframePills (segmented controls,
// different pattern); CounterPill (progress-based color at 90% threshold).
//
// Tone semantics are locked to the CLAUDE.md editorial health palette:
//   good  → sage       · idle    → neutral grey
//   warn  → warm gold  · critical → danger red
//   ink   → monochrome button · info → neutral label
// Use `tone` for the visual register, `size` for density. Never use raw
// tailwind text-{color} utilities to color badges elsewhere — they drift.

type Tone =
	| "ink" // near-black button / nav active (monochrome heavy-lifter)
	| "info" // neutral label (muted grey on subtle bg)
	| "good" // sage — success, positive delta
	| "warn" // warm gold — drifting, attention
	| "critical" // danger red — failed, flagged, invalid
	| "idle" // neutral grey — inactive, muted
	| "oxblood" // brand/live whisper — owner, selected, milestones
	| "ghost"; // transparent — counter/time pills

type Size = "xs" | "sm" | "md";

export interface StatusPillProps extends React.HTMLAttributes<HTMLSpanElement> {
	tone?: Tone | undefined;
	size?: Size | undefined;
	/** Optional leading dot — 2s pulse when `live` is set. */
	dot?: boolean | undefined;
	live?: boolean | undefined;
	icon?: React.ReactNode | undefined;
	/** Override the intrinsic tone color for the dot/icon. Rarely needed. */
	accent?: string | undefined;
}

const SIZE_CLASSES: Record<Size, string> = {
	xs: "h-[18px] px-1.5 text-[0.625rem] tracking-[0.08em]",
	sm: "h-[22px] px-2 text-[0.75rem]",
	md: "h-6 px-2.5 text-[0.8125rem]",
};

/**
 * Tones resolve to CSS vars so light/dark both work. Ghost/ink use muted/
 * foreground; the editorial palette tones route through color-mix for
 * backgrounds so they never read as stoplight primary.
 */
function toneStyle(tone: Tone): React.CSSProperties {
	switch (tone) {
		case "ink":
			return {
				color: "var(--color-background)",
				backgroundColor: "var(--color-foreground)",
			};
		case "info":
			return {
				color: "var(--color-muted-foreground)",
				backgroundColor: "var(--color-muted)",
			};
		case "good":
			return {
				color: "var(--color-health-good)",
				backgroundColor:
					"color-mix(in srgb, var(--color-health-good) 12%, transparent)",
			};
		case "warn":
			return {
				color: "var(--color-health-warn)",
				backgroundColor:
					"color-mix(in srgb, var(--color-health-warn) 12%, transparent)",
			};
		case "critical":
			return {
				color: "var(--color-critical)",
				backgroundColor:
					"color-mix(in srgb, var(--color-critical) 12%, transparent)",
			};
		case "idle":
			return {
				color: "var(--color-health-idle)",
				backgroundColor:
					"color-mix(in srgb, var(--color-health-idle) 14%, transparent)",
			};
		case "oxblood":
			return {
				color: "var(--color-live)",
				backgroundColor:
					"color-mix(in srgb, var(--color-live) 10%, transparent)",
			};
		default:
			return {
				color: "var(--color-muted-foreground)",
				backgroundColor: "transparent",
			};
	}
}

export function StatusPill({
	tone = "info",
	size = "sm",
	dot,
	live,
	icon,
	accent,
	className,
	style,
	children,
	...rest
}: StatusPillProps) {
	const resolved = toneStyle(tone);
	const dotColor = accent || resolved.color;
	return (
		<span
			className={cn(
				"app-control-text inline-flex items-center gap-1.5 rounded-full whitespace-nowrap",
				"border border-transparent",
				tone === "ghost" && "border-border",
				size === "xs" && "text-[0.625rem] font-semibold uppercase tracking-[0.08em]",
				SIZE_CLASSES[size],
				className,
			)}
			style={{ ...resolved, ...style }}
			{...rest}
		>
			{dot && (
				<span
					className={cn(
						"flex items-center justify-center shrink-0",
						live && "animate-pulse",
						tone === "good" ||
							tone === "warn" ||
							tone === "critical" ||
							tone === "idle"
							? "w-3 h-3 rounded-full text-[0.5rem] font-bold text-white"
							: "w-1.5 h-1.5 rounded-full",
					)}
					style={{ backgroundColor: dotColor as string }}
					aria-hidden="true"
				>
					{tone === "good"
						? "✓"
						: tone === "warn"
							? "!"
							: tone === "critical"
								? "×"
								: tone === "idle"
									? "—"
									: null}
				</span>
			)}
			{icon && (
				<span className="inline-flex shrink-0" aria-hidden="true">
					{icon}
				</span>
			)}
			{children}
		</span>
	);
}
