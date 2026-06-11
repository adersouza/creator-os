import { beforeEach, describe, expect, it, vi } from "vitest";

const mockSearchTrends = vi.fn();
const mockGenerateTrendPost = vi.fn();
const mockGetUserAIConfig = vi.fn();
const mockGetUserTier = vi.fn();
const mockFilterTrends = vi.fn();
const mockGetTodayPostCount = vi.fn();
const mockIsAlreadyDiscovered = vi.fn();
const mockHasTrendDecayed = vi.fn();
const mockShouldScanGroup = vi.fn();
const mockScoreTrendAcceleration = vi.fn();
const mockSelectFormat = vi.fn();
const mockLoggerInfo = vi.fn();
const mockLoggerWarn = vi.fn();
const mockLoggerError = vi.fn();

vi.mock("../../api/_lib/grokSearch.js", () => ({
	searchTrends: (...args: unknown[]) => mockSearchTrends(...args),
}));

vi.mock("../../api/_lib/logger.js", () => ({
	logger: {
		info: (...args: unknown[]) => mockLoggerInfo(...args),
		warn: (...args: unknown[]) => mockLoggerWarn(...args),
		error: (...args: unknown[]) => mockLoggerError(...args),
		debug: vi.fn(),
	},
}));

vi.mock("../../api/_lib/tierGate.js", () => ({
	getUserTier: (...args: unknown[]) => mockGetUserTier(...args),
}));

vi.mock("../../api/_lib/handlers/auto-post/contentSelection.js", () => ({
	getUserAIConfig: (...args: unknown[]) => mockGetUserAIConfig(...args),
}));

vi.mock("../../api/_lib/handlers/trend-pipeline/generator.js", () => ({
	generateTrendPost: (...args: unknown[]) => mockGenerateTrendPost(...args),
}));

vi.mock("../../api/_lib/handlers/trend-pipeline/formatWeights.js", () => ({
	selectFormat: (...args: unknown[]) => mockSelectFormat(...args),
}));

vi.mock("../../api/_lib/handlers/trend-pipeline/filterTrends.js", () => ({
	filterTrends: (...args: unknown[]) => mockFilterTrends(...args),
	getTodayPostCount: (...args: unknown[]) => mockGetTodayPostCount(...args),
	hasTrendDecayed: (...args: unknown[]) => mockHasTrendDecayed(...args),
	isAlreadyDiscovered: (...args: unknown[]) => mockIsAlreadyDiscovered(...args),
	scoreTrendAcceleration: (...args: unknown[]) => mockScoreTrendAcceleration(...args),
	shouldScanGroup: (...args: unknown[]) => mockShouldScanGroup(...args),
}));

const BASE_CONFIG = {
	id: "cfg-1",
	account_group_id: "group-1",
	user_id: "user-1",
	enabled: true,
	keywords: ["gaming"],
	scan_frequency_hours: 4,
	daily_post_cap: 3,
	blocklist: [],
	content_preferences: {},
	last_scan_at: null,
	created_at: new Date().toISOString(),
	updated_at: new Date().toISOString(),
};

const FILTERED_TREND = {
	topic: "Fortnite Toy Story Cups",
	context: "toy story collab is spiking",
	relevanceScore: 92,
	topicHash: "hash-1",
	accelerationScore: 2.7,
	trendShape: "spike" as const,
	isHighPriority: true,
};

function createDbMock(options?: {
	queueInsertError?: string | null;
	discoveryInsertError?: string | null;
}) {
	const discoveryInserts: Record<string, unknown>[] = [];
	const queueInserts: Record<string, unknown>[] = [];
	const updatePayloads: Record<string, unknown>[] = [];

	const db = {
		from(table: string) {
			if (table === "account_groups") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							single: vi.fn().mockResolvedValue({
								data: {
									name: "Group One",
									voice_profile: null,
									account_ids: ["acct-1"],
								},
							}),
						}),
					}),
				};
			}

			if (table === "auto_post_group_config") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							maybeSingle: vi.fn().mockResolvedValue({
								data: { workspace_id: "ws-1" },
							}),
						}),
					}),
				};
			}

			if (table === "auto_post_queue") {
				return {
					insert: vi.fn((payload: Record<string, unknown>) => {
						queueInserts.push(payload);
						return {
							select: vi.fn().mockReturnValue({
								single: vi.fn().mockResolvedValue(
									options?.queueInsertError
										? {
												data: null,
												error: { message: options.queueInsertError },
											}
										: {
												data: { id: "queue-1" },
												error: null,
											},
								),
							}),
						};
					}),
				};
			}

			if (table === "trend_discoveries") {
				return {
					insert: vi.fn(async (payload: Record<string, unknown>) => {
						discoveryInserts.push(payload);
						return options?.discoveryInsertError
							? { error: { message: options.discoveryInsertError } }
							: { error: null };
					}),
				};
			}

			if (table === "trending_topic_config") {
				return {
					update: vi.fn((payload: Record<string, unknown>) => {
						updatePayloads.push(payload);
						return {
							eq: vi.fn().mockResolvedValue({ error: null }),
						};
					}),
				};
			}

			throw new Error(`Unexpected table ${table}`);
		},
	};

	return { db, discoveryInserts, queueInserts, updatePayloads };
}

describe("trend pipeline scanner", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockGetUserTier.mockResolvedValue("empire");
		mockShouldScanGroup.mockReturnValue(true);
		mockGetTodayPostCount.mockResolvedValue(0);
		mockSearchTrends.mockResolvedValue([{ topic: "raw", context: "raw", relevanceScore: 99 }]);
		mockFilterTrends.mockReturnValue([FILTERED_TREND]);
		mockIsAlreadyDiscovered.mockResolvedValue(false);
		mockHasTrendDecayed.mockResolvedValue(false);
		mockScoreTrendAcceleration.mockReturnValue({
			accelerationScore: FILTERED_TREND.accelerationScore,
			trendShape: FILTERED_TREND.trendShape,
			isHighPriority: FILTERED_TREND.isHighPriority,
		});
		mockSelectFormat.mockReturnValue("hot_take");
		mockGenerateTrendPost.mockResolvedValue("generated trend post");
		mockGetUserAIConfig.mockResolvedValue({
			provider: "gemini",
			apiKey: "test-key",
			model: "gemini-2.5-flash",
		});
	});

	it("does not record a discovery or count a queued post when queue insert fails", async () => {
		const { processOneGroup } = await import(
			"../../api/_lib/handlers/trend-pipeline/scanner"
		);
		const { db, discoveryInserts, queueInserts } = createDbMock({
			queueInsertError: "insert failed",
		});

		const result = await processOneGroup(db, BASE_CONFIG);

		expect(queueInserts).toHaveLength(1);
		expect(discoveryInserts).toHaveLength(0);
		expect(result.postsQueued).toBe(0);
		expect(mockLoggerError).toHaveBeenCalledWith(
			"[trend-scanner] Failed to insert auto_post_queue",
			expect.objectContaining({
				groupId: "group-1",
				topic: FILTERED_TREND.topic,
			}),
		);
	});

	it("records queued discoveries only after queue insert succeeds", async () => {
		const { processOneGroup } = await import(
			"../../api/_lib/handlers/trend-pipeline/scanner"
		);
		const { db, discoveryInserts, queueInserts } = createDbMock();

		const result = await processOneGroup(db, BASE_CONFIG);

		expect(queueInserts).toHaveLength(1);
		expect(discoveryInserts).toHaveLength(1);
		expect(discoveryInserts[0]).toEqual(
			expect.objectContaining({
				account_group_id: "group-1",
				user_id: "user-1",
				topic: FILTERED_TREND.topic,
				topic_hash: FILTERED_TREND.topicHash,
				status: "needs_review",
			}),
		);
		expect(queueInserts[0]).toEqual(
			expect.objectContaining({
				status: "needs_review",
				pool_status: "available",
				metadata: expect.objectContaining({
					approval: expect.objectContaining({
						reason: "trend_generated_requires_review",
					}),
				}),
			}),
		);
		expect(result.postsQueued).toBe(1);
	});
});
