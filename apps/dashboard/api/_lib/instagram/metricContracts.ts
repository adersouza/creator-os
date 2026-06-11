import {
	POST_INSIGHT_METRICS,
	REEL_INSIGHT_METRICS,
	STORY_INSIGHT_METRICS,
} from "../metaApiConfig.js";

export const INSTAGRAM_METRICS_CONTRACT_VERSION =
	"instagram_metrics_contract_v1";

export type InstagramMetricSurface =
	| "reel"
	| "story"
	| "feed_single"
	| "feed_carousel";

type ContractOk = {
	ok: true;
	version: typeof INSTAGRAM_METRICS_CONTRACT_VERSION;
	surface: InstagramMetricSurface;
	igMediaType: "REELS" | "STORIES" | "IMAGE" | "CAROUSEL";
	metrics: string[];
	fallbackMetrics: string[];
};

type ContractBlocked = {
	ok: false;
	version: typeof INSTAGRAM_METRICS_CONTRACT_VERSION;
	blockers: string[];
	surface: InstagramMetricSurface | null;
	igMediaType: string | null;
};

export type InstagramMetricContract = ContractOk | ContractBlocked;

const SURFACE_BY_IG_MEDIA_TYPE: Record<string, InstagramMetricSurface> = {
	REELS: "reel",
	VIDEO: "feed_single",
	STORIES: "story",
	STORY: "story",
	IMAGE: "feed_single",
	CAROUSEL: "feed_carousel",
	CAROUSEL_ALBUM: "feed_carousel",
};

const IG_MEDIA_TYPE_BY_SURFACE: Record<InstagramMetricSurface, ContractOk["igMediaType"]> = {
	reel: "REELS",
	story: "STORIES",
	feed_single: "IMAGE",
	feed_carousel: "CAROUSEL",
};

const METRICS_BY_SURFACE: Record<InstagramMetricSurface, string> = {
	reel: REEL_INSIGHT_METRICS,
	story: STORY_INSIGHT_METRICS,
	feed_single: POST_INSIGHT_METRICS,
	feed_carousel: POST_INSIGHT_METRICS,
};

const FALLBACK_BY_SURFACE: Record<InstagramMetricSurface, string[]> = {
	reel: ["views", "reach", "likes", "comments"],
	story: ["views", "reach", "replies"],
	feed_single: ["views", "reach", "likes", "comments"],
	feed_carousel: ["views", "reach", "likes", "comments"],
};

export function resolveInstagramMetricContract(input: {
	contentSurface?: string | null | undefined;
	igMediaType?: string | null | undefined;
}): InstagramMetricContract {
	const surface = normalizeMetricSurface(input.contentSurface);
	const igMediaType = normalizeMetricMediaType(input.igMediaType);
	const resolvedSurface =
		surface || (igMediaType ? SURFACE_BY_IG_MEDIA_TYPE[igMediaType] : null) || null;
	const blockers: string[] = [];

	if (!resolvedSurface) blockers.push("content_surface_unresolvable");
	if (!igMediaType) blockers.push("ig_media_type_unresolvable");

	if (resolvedSurface && igMediaType) {
		const expected = IG_MEDIA_TYPE_BY_SURFACE[resolvedSurface];
		if (expected !== igMediaType) {
			blockers.push(`ig_media_type_surface_mismatch:${igMediaType}:${expected}`);
		}
	}

	if (blockers.length > 0 || !resolvedSurface || !igMediaType) {
		return {
			ok: false,
			version: INSTAGRAM_METRICS_CONTRACT_VERSION,
			blockers,
			surface: resolvedSurface,
			igMediaType,
		};
	}

	return {
		ok: true,
		version: INSTAGRAM_METRICS_CONTRACT_VERSION,
		surface: resolvedSurface,
		igMediaType: igMediaType as ContractOk["igMediaType"],
		metrics: splitMetrics(METRICS_BY_SURFACE[resolvedSurface]),
		fallbackMetrics: FALLBACK_BY_SURFACE[resolvedSurface],
	};
}

function normalizeMetricSurface(value: string | null | undefined): InstagramMetricSurface | null {
	const raw = String(value || "").trim().toLowerCase();
	if (!raw) return null;
	if (raw === "reel" || raw === "regular_reel" || raw === "trial_reel") return "reel";
	if (raw === "story" || raw === "stories") return "story";
	if (raw === "feed_single" || raw === "feed" || raw === "image") return "feed_single";
	if (raw === "feed_carousel" || raw === "carousel" || raw === "carousel_album") return "feed_carousel";
	return null;
}

function normalizeMetricMediaType(value: string | null | undefined): string | null {
	const raw = String(value || "").trim().toUpperCase();
	if (!raw) return null;
	if (raw === "REEL") return "REELS";
	if (raw === "STORY") return "STORIES";
	if (raw === "CAROUSEL_ALBUM") return "CAROUSEL";
	if (raw === "PHOTO") return "IMAGE";
	return raw;
}

function splitMetrics(value: string): string[] {
	return value.split(",").map((item) => item.trim()).filter(Boolean);
}
