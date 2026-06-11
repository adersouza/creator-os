
import { STATUS_STYLE, type Status } from '@/components/calendar/shared';

const GLYPH: Record<Status, string> = {
	draft: '·',
	scheduled: '◷',
	published: '✓',
	failed: '✗',
	review: '?',
};

interface Props {
	status: Status;
	/** Default 10 — matches the existing 1.5×1.5 (6px) calendar micro-dot scale upward for glyph legibility. */
	size?: number | undefined;
	className?: string | undefined;
	/** Override the default status label (from STATUS_STYLE) if context requires more detail. */
	label?: string | undefined;
}

/**
 * Lifecycle status indicator for calendar posts. Pairs color with a glyph shape
 * so state is readable without color vision, and exposes a human label via aria.
 */
export function PostStatusDot({ status, size = 10, className, label }: Props) {
	const style = STATUS_STYLE[status];
	return (
		<span
			role="img"
			aria-label={label ?? style.label}
			className={className}
			style={{
				display: 'inline-flex',
				alignItems: 'center',
				justifyContent: 'center',
				width: size,
				height: size,
				borderRadius: '50%',
				backgroundColor: style.color,
				color: 'var(--color-primary-foreground)',
				fontSize: Math.round(size * 0.72),
				fontWeight: 700,
				lineHeight: 1,
				flexShrink: 0,
				animation: status === 'failed' ? 'live-pulse 2s infinite' : undefined,
			}}
		>
			<span aria-hidden="true">{GLYPH[status]}</span>
		</span>
	);
}
