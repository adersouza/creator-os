import { forwardRef, type HTMLAttributes, type ReactNode } from "react";

/**
 * MicroBadge — h-[18px] uppercase-tracking label pill. Distinct from
 * StatusPill (which carries color-coded semantics like "Published" /
 * "Failed"). MicroBadge is a neutral or tinted typographic label —
 * e.g. "THREADS", "EXPIRED", "SESSION", "ADMIN".
 *
 * Tones:
 *   muted     — bg-muted / text-muted-foreground (default, used for slugs)
 *   ox        — selected/live 10% / selected text
 *   gold      — warning 10% / warning text
 *   negative  — critical 10% / critical text
 *   positive  — positive 10% / positive text
 */

export type MicroBadgeTone =
	| "muted"
	| "ox"
	| "gold"
	| "negative"
	| "health-good";

interface MicroBadgeProps extends HTMLAttributes<HTMLSpanElement> {
	tone?: MicroBadgeTone | undefined;
	/** Optional left glyph — e.g. a dot or icon. */
	leading?: ReactNode | undefined;
	children: ReactNode;
}

const TONE_CLASS: Record<MicroBadgeTone, string> = {
	muted: "bg-muted text-muted-foreground",
	ox: "text-[var(--color-selected)]",
	gold: "text-[var(--color-warning)]",
	negative: "text-[var(--color-critical)]",
	"health-good": "text-[var(--color-health-good)]",
};

const TONE_STYLE: Partial<Record<MicroBadgeTone, React.CSSProperties>> = {
	ox: {
		backgroundColor:
			"color-mix(in srgb, var(--color-selected) 10%, transparent)",
	},
	gold: {
		backgroundColor:
			"color-mix(in srgb, var(--color-warning) 10%, transparent)",
	},
	negative: {
		backgroundColor:
			"color-mix(in srgb, var(--color-critical) 10%, transparent)",
	},
	"health-good": {
		backgroundColor:
			"color-mix(in srgb, var(--color-health-good) 12%, transparent)",
	},
};

export const MicroBadge = forwardRef<HTMLSpanElement, MicroBadgeProps>(
	function MicroBadge(
		{ tone = "muted", leading, className = "", children, style, ...rest },
		ref,
	) {
		const toneStyle = TONE_STYLE[tone];
		return (
			<span
				ref={ref}
				className={`inline-flex h-[18px] items-center gap-1 rounded-full px-1.5 text-[0.625rem] font-semibold uppercase tracking-[0.08em] ${TONE_CLASS[tone]} ${className}`}
				style={{ ...toneStyle, ...style }}
				{...rest}
			>
				{leading}
				{children}
			</span>
		);
	},
);
