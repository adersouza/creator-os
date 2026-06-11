import type { ComponentType } from "react";
import { Link } from "react-router-dom";

interface AnalyticsActionLinkProps {
	to: string;
	label: string;
	icon?: ComponentType<{ className?: string }> | undefined;
	tone?: "primary" | "neutral" | "warning" | undefined;
}

export function AnalyticsActionLink({
	to,
	label,
	icon: Icon,
	tone = "neutral",
}: AnalyticsActionLinkProps) {
	return (
		<Link
			to={to}
			className={
				"analytics-action-link " +
				(tone === "primary"
					? "analytics-action-link-primary"
					: tone === "warning"
						? "analytics-action-link-warning"
						: "")
			}
		>
			{Icon ? <Icon className="h-3 w-3" /> : null}
			<span>{label}</span>
		</Link>
	);
}
