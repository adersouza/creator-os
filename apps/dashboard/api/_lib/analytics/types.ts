export interface PostInsights {
	views: number;
	likes: number;
	replies: number;
	reposts: number;
	quotes: number;
	shares: number;
}

export interface IGPostInsights {
	impressions: number;
	reach: number;
	likes: number;
	comments: number;
	shares: number;
	saved: number;
	plays: number;
	video_views: number;
	reposts: number;
	reels_skip_rate: number;
	crossposted_views: number;
}

export type CacheableAlert = {
	id: string;
	alert_type: string;
	severity: string;
	title: string;
	description: string;
	data: Record<string, unknown> | null;
	created_at: string | null;
};

export interface RefreshResult {
	success: boolean;
	postsUpdated: number;
	skipped?: boolean | undefined;
	error?: string | undefined;
}
