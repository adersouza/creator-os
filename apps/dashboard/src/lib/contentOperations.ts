import type { TopPostRow } from "@/hooks/useTopPosts";

export interface ContentOperations {
	recentPosts: TopPostRow[];
	topPost: TopPostRow | null;
	winningPosts: TopPostRow[];
	reviewPosts: TopPostRow[];
	platformBreakdown: Array<{ label: string; count: number }>;
	totalReach: number;
	totalDiscovery: number;
	totalEngagement: number;
	medianReach: number;
	reviewThreshold: number;
	lowReachCount: number;
}

export function formatCompact(value: number) {
	if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
	if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
	return value.toLocaleString();
}

export function discoveryScore(post: TopPostRow) {
	return post.platform === "instagram" ? post.sends + post.saves : post.comments + post.sends;
}

export function engagementTotal(post: TopPostRow) {
	return post.likes + post.comments + post.sends + post.saves;
}

export function buildContentOperations(posts: TopPostRow[]): ContentOperations {
	const recentPosts = [...posts].sort(
		(a, b) => new Date(b.publishedAt).getTime() - new Date(a.publishedAt).getTime(),
	);
	const rankedPosts = [...posts].sort((a, b) => discoveryScore(b) - discoveryScore(a));
	const reachSorted = [...posts].sort((a, b) => a.reach - b.reach);
	const medianReach = posts.length === 0 ? 0 : reachSorted[Math.floor(posts.length / 2)]?.reach ?? 0;
	const reviewThreshold = Math.max(100, medianReach * 0.35);
	const reviewPosts = posts
		.filter((post) => post.reach < reviewThreshold)
		.sort((a, b) => a.reach - b.reach)
		.slice(0, 3);

	return {
		recentPosts,
		topPost: rankedPosts[0] ?? null,
		winningPosts: rankedPosts.slice(0, 3),
		reviewPosts,
		platformBreakdown: [
			{ label: "Threads", count: posts.filter((post) => post.platform === "threads").length },
			{ label: "Instagram", count: posts.filter((post) => post.platform === "instagram").length },
		],
		totalReach: posts.reduce((sum, post) => sum + post.reach, 0),
		totalDiscovery: posts.reduce((sum, post) => sum + discoveryScore(post), 0),
		totalEngagement: posts.reduce((sum, post) => sum + engagementTotal(post), 0),
		medianReach,
		reviewThreshold,
		lowReachCount: posts.filter((post) => post.reach < reviewThreshold).length,
	};
}
