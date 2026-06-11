import React from "react";
import { X, AlertCircle, Sparkles, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuthUser } from "@/hooks/useAuthUser";

export type BannerTone = "info" | "warn" | "critical";

type BannerAction =
	| { label: string; onClick: () => void; href?: never }
	| { label: string; href: string; onClick?: never };

interface InlineBannerProps {
	tone?: BannerTone | undefined;
	icon?: "sparkle" | "clock" | "alert" | undefined;
	title: React.ReactNode;
	description?: React.ReactNode | undefined;
	action?: BannerAction | undefined;
	dismissKey?: string | undefined;
	className?: string | undefined;
}

function isBannerDismissed(storageKey: string | null): boolean {
	if (!storageKey) return false;
	try {
		const raw = localStorage.getItem(storageKey);
		if (!raw) return false;
		const { until } = JSON.parse(raw) as { until: number };
		return until > Date.now();
	} catch {
		return false;
	}
}

const ICON = {
	sparkle: Sparkles,
	clock: Clock,
	alert: AlertCircle,
};

export function InlineBanner({
	tone = "info",
	icon = "alert",
	title,
	description,
	action,
	dismissKey,
	className,
}: InlineBannerProps) {
	const authUser = useAuthUser();
	const storageKey = dismissKey
		? authUser?.id
			? `juno33-banner:${dismissKey}:${authUser.id}`
			: `juno33-banner:${dismissKey}`
		: null;
	const [dismissed, setDismissed] = React.useState(() =>
		isBannerDismissed(storageKey),
	);

	React.useEffect(() => {
		setDismissed(isBannerDismissed(storageKey));
	}, [storageKey]);

	if (dismissed) return null;

	const Icon = ICON[icon];
	const toneStyle: React.CSSProperties =
		tone === "critical"
			? {
					backgroundColor:
						"color-mix(in srgb, var(--color-critical) 8%, transparent)",
					borderColor:
						"color-mix(in srgb, var(--color-critical) 28%, transparent)",
				}
			: tone === "warn"
				? {
						backgroundColor:
							"color-mix(in srgb, var(--color-warning) 10%, transparent)",
						borderColor:
							"color-mix(in srgb, var(--color-warning) 32%, transparent)",
					}
				: {};

	const accentColor =
		tone === "critical"
			? "var(--color-critical)"
			: tone === "warn"
				? "var(--color-warning)"
				: "var(--color-foreground)";

	const handleDismiss = () => {
		if (storageKey) {
			try {
				// hide for 24 h
				localStorage.setItem(
					storageKey,
					JSON.stringify({ until: Date.now() + 24 * 60 * 60 * 1000 }),
				);
			} catch {
				/* ignore */
			}
		}
		setDismissed(true);
	};

	return (
		<div
			role="status"
			className={cn(
				"flex items-start gap-3 rounded-md border px-4 py-3 mb-3",
				tone === "info" && "bg-card border-border",
				className,
			)}
			style={toneStyle}
		>
			<Icon
				className="w-4 h-4 mt-0.5 shrink-0"
				style={{ color: accentColor }}
				aria-hidden="true"
			/>
			<div className="flex-1 min-w-0">
				<div className="text-[0.8125rem] font-medium text-foreground">
					{title}
				</div>
				{description && (
					<div className="mt-0.5 text-[0.75rem] text-muted-foreground leading-[1.5]">
						{description}
					</div>
				)}
			</div>
			{action &&
				("href" in action ? (
					<a
						href={action.href}
						className="shrink-0 inline-flex items-center h-8 px-3 rounded-md text-[0.75rem] font-semibold transition-colors outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)]"
						style={{
							color: accentColor,
							border: `1px solid ${accentColor}`,
						}}
					>
						{action.label}
					</a>
				) : (
					<button
						type="button"
						onClick={action.onClick}
						className="shrink-0 inline-flex items-center h-8 px-3 rounded-md text-[0.75rem] font-semibold transition-colors outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)]"
						style={{
							color: accentColor,
							border: `1px solid ${accentColor}`,
						}}
					>
						{action.label}
					</button>
				))}
			{dismissKey && (
				<button
					type="button"
					onClick={handleDismiss}
					aria-label="Dismiss banner"
					className="shrink-0 w-7 h-7 rounded-md inline-flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
				>
					<X className="w-3.5 h-3.5" aria-hidden="true" />
				</button>
			)}
		</div>
	);
}
