export type KpiKey =
	| "views"
	| "peopleReached"
	| "engagementRate"
	| "followerGrowth"
	| "linkClicks"
	| "engagements"
	| "saves"
	| "shares"
	| "replies"
	| "scheduledPosts";

export type KpiDeltaDirection = "up" | "down" | "flat";

type KpiPresentation = {
	label: string;
	description: string;
	chartTitle?: string;
	chartDescription?: string;
};

export const KPI_PRESENTATION: Record<KpiKey, KpiPresentation> = {
	views: {
		label: "Views",
		description: "Best available views or reach for this scope.",
		chartTitle: "Views trend",
		chartDescription: "Daily views or reach for the selected platform and scope.",
	},
	peopleReached: {
		label: "People reached",
		description: "Audience reached across selected accounts.",
	},
	engagementRate: {
		label: "Engagement rate",
		description: "Engagements divided by people reached.",
	},
	followerGrowth: {
		label: "Follower growth",
		description: "Follower movement across the selected window.",
	},
	linkClicks: {
		label: "Link clicks",
		description: "Traffic sent from social posts into owned links.",
	},
	engagements: {
		label: "Engagements",
		description: "Likes, comments, replies, saves, shares, reposts, and quotes.",
	},
	saves: {
		label: "Saves",
		description: "Posts saved for later by the audience.",
	},
	shares: {
		label: "Shares",
		description: "Shares, sends, reposts, and quote-style distribution.",
	},
	replies: {
		label: "Replies",
		description: "Comments and reply volume.",
	},
	scheduledPosts: {
		label: "Scheduled posts",
		description: "Posts already queued across the active scope.",
	},
};

export function kpiLabel(key: KpiKey) {
	return KPI_PRESENTATION[key].label;
}

export function kpiDescription(key: KpiKey) {
	return KPI_PRESENTATION[key].description;
}

export function formatCompact(value: number | null | undefined) {
	const safeValue = Number(value ?? 0);
	return new Intl.NumberFormat("en", {
		notation: "compact",
		maximumFractionDigits: Math.abs(safeValue) >= 1000 ? 1 : 0,
	}).format(safeValue);
}

export function formatPercent(
	value: number | null | undefined,
	unavailableLabel = "Unavailable",
) {
	if (value == null || Number.isNaN(value)) return unavailableLabel;
	return `${Math.round(value * 10) / 10}%`;
}

export function formatDelta(value: number | null | undefined, suffix = "%") {
	if (value == null || Number.isNaN(value)) return "No prior";
	const rounded = Math.round(value * 10) / 10;
	return `${rounded > 0 ? "+" : ""}${rounded}${suffix}`;
}

export function deltaDirection(
	value: number | null | undefined,
): KpiDeltaDirection {
	if (value == null || Number.isNaN(value) || Math.abs(value) < 0.1) {
		return "flat";
	}
	return value > 0 ? "up" : "down";
}
