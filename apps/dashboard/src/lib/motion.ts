/**
 * Motion animation tokens for use with framer-motion.
 * These are the JS equivalents of the CSS custom properties.
 */

export const springs = {
	/** Interactive elements: buttons, toggles, drag */
	snappy: { type: "spring" as const, stiffness: 400, damping: 25 },
	/** Panels, modals, larger elements */
	gentle: { type: "spring" as const, stiffness: 250, damping: 25 },
	/** Layout shifts: list reordering */
	smooth: { type: "spring" as const, stiffness: 200, damping: 25 },
	/** Toggle switch */
	toggle: { type: "spring" as const, stiffness: 400, damping: 28 },
	/** Command palette — very snappy */
	command: { type: "spring" as const, stiffness: 400, damping: 30 },
} as const;

export const eases = {
	/** General purpose — fastest-feeling */
	default: [0.2, 0, 0, 1] as const,
	/** Elements entering the screen */
	enter: [0, 0, 0.2, 1] as const,
	/** Elements leaving the screen */
	exit: [0.4, 0, 1, 1] as const,
	/** Symmetric transitions */
	inOut: [0.4, 0, 0.2, 1] as const,
	/** Slight overshoot (CSS-only spring approximation) */
	overshoot: [0.34, 1.56, 0.64, 1] as const,
} as const;

export const durations = {
	instant: 0.05, // 50ms — state changes
	fast: 0.1, // 100ms — hover, active
	normal: 0.2, // 200ms — transitions
	moderate: 0.3, // 300ms — panels, modals
	slow: 0.5, // 500ms — complex animations
	chart: 0.8, // 800ms — data viz
} as const;

// ---------------------------------------------------------------------------
// Design Bible §9.1 — Shared spring configs (used by dashboard widgets)
// ---------------------------------------------------------------------------

/** Default: card hovers, list items */
export const springConfig = {
	type: "spring" as const,
	stiffness: 300,
	damping: 25,
	mass: 0.8,
};

/** Modals, panels, page transitions */
export const smoothConfig = {
	type: "spring" as const,
	stiffness: 200,
	damping: 30,
	mass: 1,
};

/** Toggles, buttons, micro-interactions — capped at CLAUDE.md's 400 ceiling. */
export const snappyConfig = {
	type: "spring" as const,
	stiffness: 400,
	damping: 28,
	mass: 0.5,
};

// ---------------------------------------------------------------------------
// Design Bible §9.3 — tripled.work Dashboard stagger pattern
// ---------------------------------------------------------------------------

/** Parent container: staggers children with 0.1s delay */
export const containerVariants = {
	hidden: { opacity: 0 },
	visible: {
		opacity: 1,
		transition: {
			staggerChildren: 0.03, // Accelerated for snappier dashboard loads
		},
	},
};

/** Child item: fades in + slides up 20px */
export const itemVariants = {
	hidden: { opacity: 0, y: 20 },
	visible: {
		opacity: 1,
		y: 0,
		transition: springConfig,
	},
};

export const REVEAL = {
	initial: { opacity: 0, y: 20, filter: 'blur(9px)' },
	animate: { opacity: 1, y: 0, filter: 'blur(0px)' },
	transition: { duration: 0.65, ease: [0.23, 1, 0.32, 1] as const },
} as const;

/** Stagger step: 80ms per item, 6-item cap per CLAUDE.md. */
export const REVEAL_STAGGER_MS = 80;
export const REVEAL_STAGGER_CAP = 6;

/** Preset transitions for common patterns */
export const transitions = {
	/** Page route crossfade */
	page: { duration: 0.15, ease: eases.default },
	/** Modal enter */
	modalEnter: { ...springs.gentle, opacity: { duration: 0.2 } },
	/** Modal exit — faster than enter */
	modalExit: { duration: 0.15, ease: eases.exit },
	/** Sidebar slide */
	sidebar: { ...springs.gentle, opacity: { duration: 0.2 } },
	/** Command palette */
	command: { ...springs.command, opacity: { duration: 0.12 } },
	/** List item stagger (use with delay: i * 0.03) */
	stagger: { duration: 0.2, ease: eases.default },
	/** Chart draw-in */
	chart: { duration: 0.8, ease: eases.default, delay: 0.2 },
	/** Number count-up */
	countUp: { duration: 0.8, ease: eases.default },
} as const;
