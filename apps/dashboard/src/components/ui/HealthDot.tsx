

export type HealthState = 'good' | 'warning' | 'critical' | 'idle';

const GLYPH: Record<HealthState, string> = {
	good: '✓',
	warning: '⚠',
	critical: '✗',
	idle: '—',
};

const LABEL: Record<HealthState, string> = {
	good: 'Healthy',
	warning: 'Needs attention',
	critical: 'Critical',
	idle: 'Idle',
};

const COLOR: Record<HealthState, string> = {
	good: 'var(--color-health-good)',
	warning: 'var(--color-health-warn)',
	critical: 'var(--color-critical)',
	idle: 'var(--color-muted-foreground)',
};

interface Props {
	state: HealthState;
	/** Override label if context requires more detail (e.g. "@aurora.core needs attention"). */
	label?: string | undefined;
	/** Default 14. Bump to 16+ if the glyph needs to be legible from across the viewport. */
	size?: number | undefined;
	className?: string | undefined;
}

/**
 * Status indicator that pairs color with a glyph shape, per HIG
 * "never rely on color alone." aria-label reads the human state string.
 */
export function HealthDot({ state, label, size = 14, className }: Props) {
	return (
		<span
			role="img"
			aria-label={label ?? LABEL[state]}
			className={className}
			style={{
				display: 'inline-flex',
				alignItems: 'center',
				justifyContent: 'center',
				width: size,
				height: size,
				borderRadius: '50%',
				backgroundColor: COLOR[state],
				color: 'var(--color-primary-foreground)',
				fontSize: Math.round(size * 0.64),
				fontWeight: 700,
				lineHeight: 1,
				flexShrink: 0,
			}}
		>
			<span aria-hidden="true">{GLYPH[state]}</span>
		</span>
	);
}
