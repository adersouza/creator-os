export type CompetitorMetricSource =
	| "official_profile_posts"
	| "apify_threads_post_scraper"
	| "instagram_business_discovery"
	| "manual_import"
	| "unknown";

export type CompetitorMetricQuality =
	| "stats_unavailable"
	| "partial_engagement"
	| "valid_engagement"
	| "scraper_estimated";

export interface CompetitorMetricInput {
	platform?: string | null | undefined;
	metricSource?: CompetitorMetricSource | null | undefined;
	viewCount?: number | null | undefined;
	likeCount?: number | null | undefined;
	replyCount?: number | null | undefined;
	repostCount?: number | null | undefined;
	commentsCount?: number | null | undefined;
	engagementScore?: number | null | undefined;
	enrichedAt?: string | null | undefined;
	checkedAt?: string | null | undefined;
}

export interface CompetitorMetricDecision {
	metric_source: CompetitorMetricSource;
	metric_quality: CompetitorMetricQuality;
	metric_quality_reason: string;
	last_metric_checked_at: string;
}

function toCount(value: number | null | undefined): number {
	return Number.isFinite(value) ? Math.max(0, Number(value)) : 0;
}

export function evaluateCompetitorMetricQuality(
	input: CompetitorMetricInput,
): CompetitorMetricDecision {
	const platform = input.platform || "threads";
	const source =
		input.metricSource ||
		(platform === "instagram"
			? "instagram_business_discovery"
			: input.enrichedAt
				? "apify_threads_post_scraper"
				: "official_profile_posts");

	const views = toCount(input.viewCount);
	const likes = toCount(input.likeCount);
	const replies = toCount(input.replyCount);
	const reposts = toCount(input.repostCount);
	const comments = toCount(input.commentsCount);
	const score = toCount(input.engagementScore);
	const hasEngagement = likes > 0 || replies > 0 || reposts > 0 || comments > 0;
	const checkedAt = input.checkedAt || input.enrichedAt || new Date().toISOString();
	const isScraperSource = source === "apify_threads_post_scraper";

	if (platform === "instagram" && (score > 0 || hasEngagement || views > 0)) {
		return {
			metric_source: source,
			metric_quality: "valid_engagement",
			metric_quality_reason: "instagram_business_discovery_metrics",
			last_metric_checked_at: checkedAt,
		};
	}

	if (isScraperSource && (views > 0 || score > 0 || hasEngagement)) {
		return {
			metric_source: source,
			metric_quality: "scraper_estimated",
			metric_quality_reason:
				views > 0
					? "scraper_estimated_views_present"
					: "scraper_estimated_engagement_without_views",
			last_metric_checked_at: checkedAt,
		};
	}

	if (views > 0) {
		return {
			metric_source: source,
			metric_quality: "valid_engagement",
			metric_quality_reason: "views_present",
			last_metric_checked_at: checkedAt,
		};
	}

	if (hasEngagement) {
		return {
			metric_source: source,
			metric_quality: "partial_engagement",
			metric_quality_reason: "engagement_present_without_views",
			last_metric_checked_at: checkedAt,
		};
	}

	return {
		metric_source: source,
		metric_quality: "stats_unavailable",
		metric_quality_reason: "official_threads_competitor_stats_unavailable",
		last_metric_checked_at: checkedAt,
	};
}

export interface CompetitorPatternInput {
	content?: string | null | undefined;
	topicTag?: string | null | undefined;
	followerCount?: number | null | undefined;
	mediaType?: string | null | undefined;
	publishedAt?: string | null | undefined;
	scrapedAt?: string | null | undefined;
}

function normalizeMediaStyle(mediaType?: string | null): string {
	const normalized = (mediaType || "TEXT").toUpperCase();
	if (normalized.includes("VIDEO")) return "video";
	if (normalized.includes("CAROUSEL")) return "carousel";
	if (normalized.includes("IMAGE") || normalized.includes("PHOTO"))
		return "image";
	if (normalized.includes("TEXT") || normalized === "NONE") return "text_only";
	return normalized.toLowerCase();
}

function postingHourOf(input: CompetitorPatternInput): number | null {
	const raw = input.publishedAt || input.scrapedAt;
	if (!raw) return null;
	const date = new Date(raw);
	if (!Number.isFinite(date.getTime())) return null;
	return date.getUTCHours();
}

export function classifyCompetitorPattern(input: CompetitorPatternInput) {
	const content = (input.content || "").trim();
	const lower = content.toLowerCase();
	const length = content.length;

	const content_length_bucket =
		length === 0
			? "empty"
			: length <= 40
				? "micro"
				: length <= 120
					? "short"
					: length <= 280
						? "medium"
						: "long";

	const hook_type = /\?$/.test(content)
		? "question"
		: /\b(unpopular opinion|hot take|be honest|controversial)\b/i.test(content)
			? "hot_take"
			: /^\s*(i|we|my|today|yesterday|last night)\b/i.test(content)
				? "personal_statement"
				: /\b(\d+\.|top \d+|reasons|ways)\b/i.test(content)
					? "list"
					: length <= 40
						? "short_statement"
						: "statement";

	const emotional_frame = /\b(lonely|miss|sad|cry|hurt|anxious|scared)\b/.test(
		lower,
	)
		? "vulnerable"
		: /\b(happy|excited|love|cute|pretty|sweet)\b/.test(lower)
			? "warm"
			: /\b(annoyed|mad|angry|hate|tired)\b/.test(lower)
				? "frustrated"
				: /\b(would you|do you|am i|be honest|tell me)\b/.test(lower)
					? "inviting"
					: "neutral";

	const cta_style = /\b(reply|comment|tell me|drop|send|dm)\b/.test(lower)
		? "explicit_reply"
		: content.includes("?")
			? "implicit_question"
			: "none";

	const controversy_level =
		/\b(unpopular opinion|hot take|controversial|hate|red flag|toxic)\b/.test(
			lower,
		)
			? "high"
			: /\b(be honest|would you|should i|is it weird)\b/.test(lower)
				? "medium"
				: "low";

	const reply_mechanism = /\b(would you|do you|am i|should i|be honest)\b/.test(
		lower,
	)
		? "direct_prompt"
		: /\?$/.test(content)
			? "question"
			: /\b(confession|i admit|not gonna lie)\b/.test(lower)
				? "confession"
				: "none";

	const followers = toCount(input.followerCount);
	const account_size_bucket =
		followers >= 100000
			? "100k_plus"
			: followers >= 50000
				? "50k_100k"
				: followers >= 10000
					? "10k_50k"
					: followers >= 1000
						? "1k_10k"
						: followers > 0
							? "under_1k"
							: "unknown";
	const media_style = normalizeMediaStyle(input.mediaType);
	const format_type =
		media_style === "video"
			? "video_post"
			: media_style === "image" || media_style === "carousel"
				? "media_post"
				: hook_type === "list"
					? "list_post"
					: hook_type === "question"
						? "question_post"
						: hook_type === "hot_take"
							? "hot_take_post"
							: "text_post";

	return {
		hook_type,
		topic_label: input.topicTag || "uncategorized",
		format_type,
		emotional_frame,
		cta_style,
		content_length_bucket,
		media_style,
		posting_hour: postingHourOf(input),
		controversy_level,
		reply_mechanism,
		account_size_bucket,
		benchmark_classified_at: new Date().toISOString(),
	};
}

export function hasValidCompetitorEngagement(
	metricQuality?: string | null,
): boolean {
	return (
		metricQuality === "valid_engagement" ||
		metricQuality === "scraper_estimated"
	);
}
