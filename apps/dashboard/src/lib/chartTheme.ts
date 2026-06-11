// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Centralized Recharts theme tokens. All chart components should reference
 * these instead of hardcoding hex. Values map to CSS custom properties in
 * index.css so charts adapt to dark/light automatically.
 */

export const chartTheme = {
	/** Axis tick + label styling */
	axis: {
		tick: "var(--color-label-secondary, currentColor)",
		line: "var(--color-border, currentColor)",
	},

	/** CartesianGrid stroke */
	grid: {
		stroke:
			"var(--color-chart-grid, var(--color-border, rgba(128,128,128,0.1)))",
	},

	/** Tooltip surface — glass chrome per CLAUDE.md (sticky-nav recipe scaled down) */
	tooltip: {
		bg: "var(--color-card, rgba(255,255,255,0.94))",
		text: "var(--color-foreground, #0A0A0B)",
		border: "var(--color-border, rgba(10,10,11,0.1))",
		/** Apply via contentStyle — Recharts doesn't expose backdrop-filter directly but
		 *  bg uses a translucent token so Recharts' own border blends with substrate. */
		contentStyle: {
			background: "var(--color-surface-popover, rgba(255, 255, 255, 0.94))",
			backdropFilter: "blur(20px) saturate(150%)",
			WebkitBackdropFilter: "blur(20px) saturate(150%)",
			border:
				"0.5px solid var(--color-surface-stroke-strong, rgba(10, 10, 11, 0.1))",
			borderRadius: 10,
			padding: "8px 10px",
			fontSize: 12,
			boxShadow: "var(--shadow-card, 0 8px 24px rgba(10,10,11,0.1))",
			color: "var(--color-foreground)",
		} as const,
		contentStyleDark: {
			background: "var(--color-surface-popover, rgba(20, 20, 22, 0.92))",
			backdropFilter: "blur(20px) saturate(140%)",
			WebkitBackdropFilter: "blur(20px) saturate(140%)",
			border:
				"0.5px solid var(--color-surface-stroke-strong, rgba(255, 255, 255, 0.12))",
			borderRadius: 10,
			padding: "8px 10px",
			fontSize: 12,
			boxShadow: "var(--shadow-card, 0 8px 24px rgba(0,0,0,0.4))",
			color: "var(--color-foreground)",
		} as const,
	},

	/** OKLCH-backed categorical palette. */
	categorical: [
		"var(--color-chart-1)",
		"var(--color-chart-2)",
		"var(--color-chart-3)",
		"var(--color-chart-4)",
		"var(--color-chart-5)",
		"var(--color-chart-6)",
	],

	/** Semantic chart colors. */
	semantic: {
		positive: "var(--color-chart-positive)",
		warning: "var(--color-chart-warning)",
		danger: "var(--color-chart-danger)",
		info: "var(--color-chart-info)",
		area: "var(--color-chart-area)",
	},

	/** Network palette — shifts lightness, not hue, across modes. */
	networks: {
		aurora: "var(--color-aurora)",
		meridian: "var(--color-meridian)",
		harbor: "var(--color-harbor)",
		vale: "var(--color-vale)",
	},

	/** Semantic — for single-series charts (EQS hero etc.) */
	primary: {
		stroke: "var(--color-ink, #1A1A1C)",
		strokeDark: "var(--color-chart-ink, #E8E4E0)",
		strokeDarkOpacity: 0.8,
		accent: "var(--color-live)",
	},

	/** Sparkline defaults per CLAUDE.md — thin, tabular-feeling. */
	sparkline: {
		stroke: "var(--color-foreground)",
		strokeWidth: 1.4,
		fillOpacity: 0.12,
		strokeOpacityDark: 0.8,
	},

	/** Reusable tick prop objects — spread directly onto <XAxis> / <YAxis> */
	tickStyle: (fontSize = 10) =>
		({ fill: "var(--color-label-secondary, currentColor)", fontSize }) as const,
} as const;

/** Network color by key — resolves to the CSS custom property (mode-aware). */
export function networkColor(
	network: "aurora" | "meridian" | "harbor" | "vale",
): string {
	return chartTheme.networks[network];
}

/**
 * Multi-series stroke pairings — pairs color AND dash pattern so colorblind
 * users + grayscale printouts still decode series. Index 0 is always solid
 * ink (primary). Apply to <Line> in Recharts or similar.
 */
const SERIES_STYLES = [
	{ stroke: "var(--color-foreground)", strokeDasharray: undefined },
	{ stroke: "var(--color-chart-4)", strokeDasharray: "6 4" },
	{ stroke: "var(--color-chart-2)", strokeDasharray: "2 2" },
	{ stroke: "var(--color-chart-5)", strokeDasharray: "8 3 2 3" },
] as const;

export function seriesStroke(index: number): {
	stroke: string;
	strokeDasharray: string | undefined;
} {
	return SERIES_STYLES[index % SERIES_STYLES.length]!;
}
