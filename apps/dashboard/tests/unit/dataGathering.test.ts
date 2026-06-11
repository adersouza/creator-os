import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockFrom = vi.fn();

vi.mock("../../api/_lib/logger.js", () => ({
	logger: {
		debug: vi.fn(),
		info: vi.fn(),
		warn: vi.fn(),
		error: vi.fn(),
	},
	serializeError: (err: unknown) => String(err),
}));

vi.mock("../../api/_lib/supabase.js", () => ({
	getSupabaseAny: () => ({ from: mockFrom }),
}));

import {
	getCompetitorTopPostsForAI,
	getCompetitorTrendingPosts,
	getOwnEngagementPatterns,
	getOwnTopPerformingPosts,
	getRecentPostContext,
	getTrendingTopics,
} from "../../api/_lib/handlers/auto-post/dataGathering";

function query(data: unknown, error: unknown = null) {
	const result = { data, error };
	const q = {
		select: vi.fn(() => q),
		eq: vi.fn(() => q),
		or: vi.fn(() => q),
		in: vi.fn(() => q),
		not: vi.fn(() => q),
		neq: vi.fn(() => q),
		gte: vi.fn(() => q),
		gt: vi.fn(() => q),
		order: vi.fn(() => q),
		limit: vi.fn().mockResolvedValue(result),
		then: (resolve: (value: typeof result) => unknown) => Promise.resolve(result).then(resolve),
	};
	return q;
}

beforeEach(() => {
	vi.clearAllMocks();
	mockFrom.mockReset();
	vi.useFakeTimers();
	vi.setSystemTime(new Date("2026-05-05T12:00:00Z"));
	vi.spyOn(Math, "random").mockReturnValue(1);
});

afterEach(() => {
	vi.useRealTimers();
	vi.restoreAllMocks();
});

describe("dataGathering", () => {
	it("selects fresh competitor examples across competitors", async () => {
		const usedSourceQuery = query([{ source_content: "used copy" }]);
		mockFrom
			.mockReturnValueOnce(query([
				{ id: "c1", username: "alpha" },
				{ id: "c2", username: "beta" },
			]))
			.mockReturnValueOnce(usedSourceQuery)
			.mockReturnValueOnce(query([
				{ content: "My cousin", competitor_username: "alpha", engagement_score: 200, competitor_id: "c1" },
				{ content: "@fashionnova Joanna Stripe Terry Bucket Hat", competitor_username: "alpha", engagement_score: 190, competitor_id: "c1" },
				{ content: "used copy", competitor_username: "alpha", engagement_score: 100, competitor_id: "c1" },
				{ content: "would you date a girl who lifts?", competitor_username: "alpha", engagement_score: 90, media_type: "IMAGE", competitor_id: "c1" },
				{ content: "am i still cute after taking off my headset?", competitor_username: "beta", engagement_score: 80, competitor_id: "c2" },
				{ content: "girls who gatekeep music are elite", competitor_username: "alpha", engagement_score: 70, competitor_id: "c1" },
			]))
			.mockReturnValueOnce(query([
				{ content: "drop your top 3 late night songs", competitor_username: "beta", engagement_score: 10, competitor_id: "c2" },
			]));

		const posts = await getCompetitorTopPostsForAI("owner-1", 3, "workspace-1");

		expect(mockFrom).toHaveBeenCalledWith("competitors");
		expect(usedSourceQuery.in).toHaveBeenCalledWith("status", [
			"published",
			"pending",
			"queued",
		]);
		expect(posts.map((p) => p.content)).toEqual([
			"would you date a girl who lifts?",
			"am i still cute after taking off my headset?",
			"girls who gatekeep music are elite",
		]);
		expect(posts[0]).toMatchObject({
			username: "alpha",
			engagement: 90,
			media_type: "IMAGE",
			competitor_id: "c1",
		});
	});

	it("returns only competitor posts above baseline velocity and skips used source content", async () => {
		const usedSourceQuery = query([{ source_content: "already used" }]);
		mockFrom
			.mockReturnValueOnce(query([{ id: "c1", username: "alpha" }]))
			.mockReturnValueOnce(query([
				{
					content: "would you date a girl who is always at the gym?",
					competitor_id: "c1",
					competitor_username: "alpha",
					engagement_score: 300,
					published_at: "2026-05-05T09:00:00Z",
				},
				{
					content: "too normal",
					competitor_id: "c1",
					competitor_username: "alpha",
					engagement_score: 120,
					published_at: "2026-05-05T10:00:00Z",
				},
				{
					content: "already used",
					competitor_id: "c1",
					competitor_username: "alpha",
					engagement_score: 400,
					published_at: "2026-05-05T11:00:00Z",
				},
				{
					content: "Blessed Thursday yall",
					competitor_id: "c1",
					competitor_username: "alpha",
					engagement_score: 500,
					published_at: "2026-05-05T11:30:00Z",
				},
			]))
			.mockReturnValueOnce(query([
				{ competitor_id: "c1", engagement_score: 100 },
				{ competitor_id: "c1", engagement_score: 100 },
				{ competitor_id: "c1", engagement_score: 100 },
			]))
			.mockReturnValueOnce(usedSourceQuery);

		const trending = await getCompetitorTrendingPosts("owner-1", "workspace-1");

		expect(usedSourceQuery.in).toHaveBeenCalledWith("status", [
			"published",
			"pending",
			"queued",
		]);
		expect(trending).toHaveLength(1);
		expect(trending[0]).toMatchObject({
			content: "would you date a girl who is always at the gym?",
			username: "alpha",
			engagement: 300,
			competitor_id: "c1",
			hoursOld: 3,
		});
		expect(trending[0].velocity).toBe(100);
	});

	it("combines forecast topics with hot competitor questions", async () => {
		mockFrom
			.mockReturnValueOnce(query([
				{ rising_topics: ["dating apps", "late night", "dating apps"] },
				{ rising_topics: ["gym crush"] },
			]))
			.mockReturnValueOnce(query([{ id: "c1" }]))
			.mockReturnValueOnce(query([
				{ content: "what are we all watching tonight?" },
				{ content: "too short?" },
			]));

		const topics = await getTrendingTopics("owner-1", "workspace-1");

		expect(topics).toEqual([
			"dating apps",
			"late night",
			"gym crush",
			"what are we all watching tonight?",
		]);
	});

	it("maps own top-performing post rows into prompt examples", async () => {
		mockFrom.mockReturnValueOnce(query([
			{
				content: "best question?",
				views_count: 500,
				replies_count: 12,
				likes_count: 40,
				published_at: "2026-05-04T12:00:00Z",
				accounts: { username: "acct" },
			},
		]));

		const posts = await getOwnTopPerformingPosts("owner-1", ["acct-1"], 5);

		expect(posts).toEqual([
			{
				content: "best question?",
				username: "acct",
				views: 500,
				replies: 12,
				likes: 40,
				publishedAt: "2026-05-04T12:00:00Z",
			},
		]);
	});

	it("computes engagement patterns from enough own posts", async () => {
		const posts = Array.from({ length: 10 }, (_, i) => ({
			content: i % 2 === 0 ? `question ${i}? 😊` : `statement ${i} with longer copy`,
			views_count: 100 + i * 10,
			replies_count: i,
			published_at: `2026-05-04T0${i % 3}:00:00Z`,
		}));
		mockFrom.mockReturnValueOnce(query(posts));

		const patterns = await getOwnEngagementPatterns(["acct-1"]);

		expect(patterns).toMatchObject({
			totalPosts: 10,
			questionAvgViews: 140,
			statementAvgViews: 150,
			emojiPostAvgViews: 140,
			noEmojiPostAvgViews: 150,
		});
		expect(patterns?.bestHours).toEqual([2, 0, 1]);
		expect(patterns?.avgLengthWinners).toBeGreaterThan(0);
	});

	it("returns recent content, lengths, post times, and topic tags", async () => {
		const recentQuery = query([
			{
				content: "recent one",
				posted_at: "2026-05-05T10:00:00Z",
				topic_tag: "Dating & Relationships",
			},
			{ content: "pending two", posted_at: null, topic_tag: "" },
		]);
		mockFrom.mockReturnValueOnce(recentQuery);

		const context = await getRecentPostContext("workspace-1");

		expect(recentQuery.in).toHaveBeenCalledWith("status", [
			"published",
			"pending",
			"queued",
		]);
		expect(context.recentContents).toEqual(["recent one", "pending two"]);
		expect(context.recentLengths).toEqual([10, 11]);
		expect(context.recentPostTimes).toEqual([new Date("2026-05-05T10:00:00Z")]);
		expect(context.recentTopicTags).toEqual(["Dating & Relationships"]);
	});
});
