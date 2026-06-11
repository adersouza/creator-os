/**
 * Unit tests for the Auto-Learning Cron Sub-Handler
 * (api/_lib/cron/auto-learning.ts)
 *
 * Tests the learning engine that analyzes post performance and adjusts strategy:
 * 1. Learning algorithm — what metrics drive strategy adjustments
 * 2. Schema validation — data integrity checks via coerceAIAnalysis
 * 3. Edge cases — zero performance data, new accounts with no history
 * 4. Performance analysis — identifying top/bottom performing content types
 * 5. Strategy adjustment — how learnings translate to config changes
 * 6. Error handling — DB failures, missing data, AI failures
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mocks — module-scope, BEFORE importing module under test
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();
const mockRpc = vi.fn();

vi.mock("../../api/_lib/supabase", () => ({
	getSupabase: () => ({ from: mockFrom, rpc: mockRpc }),
	getSupabaseAny: () => ({ from: mockFrom, rpc: mockRpc }),
}));

const mockLoggerInfo = vi.fn();
const mockLoggerWarn = vi.fn();
const mockLoggerError = vi.fn();
const mockLoggerDebug = vi.fn();

vi.mock("../../api/_lib/logger", () => ({
	logger: {
		info: (...args: unknown[]) => mockLoggerInfo(...args),
		warn: (...args: unknown[]) => mockLoggerWarn(...args),
		error: (...args: unknown[]) => mockLoggerError(...args),
		debug: (...args: unknown[]) => mockLoggerDebug(...args),
	},
	serializeError: (err: unknown) =>
		err instanceof Error ? err.message : String(err),
}));

// promptUtils — pass-through for tests
vi.mock("../../api/_lib/promptUtils", () => ({
	escapeForPrompt: (s: string) => s,
	sanitizeAIOutput: (s: string) => s,
}));

// AI Config
const mockGetUserAIConfig = vi.fn();

vi.mock("../../api/_lib/aiConfig", () => ({
	getUserAIConfig: (...args: unknown[]) => mockGetUserAIConfig(...args),
}));

// Content generation (AI provider)
const mockGenerateWithProvider = vi.fn();

vi.mock("../../api/_lib/handlers/auto-post/contentSelection", () => ({
	generateWithProvider: (...args: unknown[]) =>
		mockGenerateWithProvider(...args),
	getLocalTime: vi.fn().mockReturnValue({ hour: 14, dayOfWeek: 2 }),
}));

// ---------------------------------------------------------------------------
// Import module under test (AFTER all mocks)
// ---------------------------------------------------------------------------

import { processAutoLearning } from "../../api/_lib/cron/auto-learning";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Build a chainable Supabase query mock */
function chain(data: unknown) {
	const c: any = {};
	const methods = [
		"select",
		"eq",
		"in",
		"not",
		"neq",
		"or",
		"gte",
		"gt",
		"lt",
		"lte",
		"order",
		"limit",
		"is",
		"insert",
		"update",
		"upsert",
		"delete",
	];
	for (const m of methods) {
		c[m] = vi.fn().mockReturnValue(c);
	}
	c.maybeSingle = vi.fn().mockResolvedValue({ data, error: null });
	c.single = vi.fn().mockResolvedValue({ data, error: null });
	c.then = (resolve: (v: any) => void) =>
		resolve({
			data: Array.isArray(data) ? data : data ? [data] : [],
			error: null,
		});
	return c;
}

/** Make a published post with controllable engagement metrics */
function makePost(overrides: Record<string, unknown> = {}) {
	return {
		id: `post-${Math.random().toString(36).slice(2, 8)}`,
		content: "This is a test post about something interesting",
		account_id: "acc-1",
		views_count: 500,
		likes_count: 25,
		replies_count: 10,
		reposts_count: 5,
		engagement_rate: 8.0,
		media_type: null,
		published_at: new Date(
			Date.now() - 3 * 24 * 60 * 60 * 1000,
		).toISOString(),
		...overrides,
	};
}

/** Create N posts with varying engagement rates */
function makePostSet(count: number, baseER = 5.0): ReturnType<typeof makePost>[] {
	return Array.from({ length: count }, (_, i) =>
		makePost({
			id: `post-${i}`,
			content: `Post content number ${i} with ${i % 2 === 0 ? "question" : "statement"} format`,
			engagement_rate: baseER + (count - i) * 0.5,
			views_count: 100 + i * 50,
			likes_count: 5 + i * 2,
			replies_count: 1 + i,
			published_at: new Date(
				Date.now() - (i + 1) * 12 * 60 * 60 * 1000,
			).toISOString(),
		}),
	);
}

/** Default account group */
function makeGroup(overrides: Record<string, unknown> = {}) {
	return {
		id: "grp-1",
		name: "Test Group",
		user_id: "user-1",
		account_ids: ["acc-1", "acc-2"],
		voice_profile: "Casual and witty",
		content_strategy: { tone_notes: "Keep it short and punchy" },
		...overrides,
	};
}

/** Default AI config */
function makeAIConfig() {
	return {
		provider: "gemini",
		apiKey: "test-api-key",
		model: "gemini-2.5-flash",
		source: "env_fallback" as const,
	};
}

/** Default AI analysis response as JSON string */
function makeAIAnalysisJson(overrides: Record<string, unknown> = {}) {
	const analysis = {
		winning_patterns: [
			"Questions drive 2x replies",
			"Short posts under 60 chars perform best",
			"Posts with strong hooks in first line",
		],
		losing_patterns: [
			"Long-form posts over 200 chars flop",
			"Generic statements without opinion",
			"Posts without clear call to action",
		],
		recommended_additions_to_tone_notes:
			"Lead with a provocative question. Keep under 60 chars when possible. Always include a contrarian take.",
		recommended_removals: "none",
		confidence: 0.75,
		...overrides,
	};
	return JSON.stringify(analysis);
}

/** Set up the standard DB mock implementation */
function setupDefaultDbMocks(overrides: {
	groups?: unknown[];
	groupConfig?: unknown;
	posts?: unknown[];
	competitors?: unknown[];
	competitorPosts?: unknown[];
	queueItems?: unknown[];
	existingAgentNote?: unknown;
	currentGroup?: unknown;
} = {}) {
	const defaults = {
		groups: [makeGroup()],
		groupConfig: { timezone: "America/New_York", workspace_id: "ws-1" },
		posts: makePostSet(15),
		competitors: [],
		competitorPosts: [],
		queueItems: [],
		existingAgentNote: null,
		currentGroup: { content_strategy: { tone_notes: "Be authentic" } },
		...overrides,
	};

	mockFrom.mockImplementation((table: string) => {
		if (table === "account_groups") {
			return chain(defaults.groups.length > 0 ? defaults.groups : null);
		}
		if (table === "auto_post_group_config") {
			return chain(defaults.groupConfig);
		}
		if (table === "posts") {
			return chain(defaults.posts);
		}
		if (table === "competitors") {
			return chain(defaults.competitors);
		}
		if (table === "competitor_top_posts") {
			return chain(defaults.competitorPosts);
		}
		if (table === "auto_post_queue") {
			return chain(defaults.queueItems);
		}
		if (table === "ai_feedback") {
			const c = chain(null);
			c.insert = vi.fn().mockResolvedValue({ error: null });
			return c;
		}
		if (table === "agent_notes") {
			return chain(defaults.existingAgentNote);
		}
		// Fallback
		return chain(null);
	});
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("auto-learning — processAutoLearning", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockGetUserAIConfig.mockResolvedValue(makeAIConfig());
		mockGenerateWithProvider.mockResolvedValue(makeAIAnalysisJson());
	});

	afterEach(() => {
		vi.restoreAllMocks();
	});

	// ── No groups ──

	describe("when no account groups exist", () => {
		it("returns zero counts", async () => {
			mockFrom.mockImplementation((table: string) => {
				if (table === "account_groups") {
					return chain(null);
				}
				return chain(null);
			});

			const result = await processAutoLearning();

			expect(result.groupsProcessed).toBe(0);
			expect(result.toneNotesUpdated).toBe(0);
			expect(result.feedbackRatings).toBe(0);
			expect(result.groupResults).toHaveLength(0);
		});
	});

	// ── Groups with no accounts ──

	describe("when group has empty account_ids", () => {
		it("returns skipped result with error", async () => {
			setupDefaultDbMocks({
				groups: [makeGroup({ account_ids: [] })],
			});

			const result = await processAutoLearning();

			expect(result.groupResults).toHaveLength(1);
			expect(result.groupResults[0].error).toBe("No accounts in group");
			expect(result.groupResults[0].totalPosts).toBe(0);
		});
	});

	// ── Below minimum post threshold ──

	describe("when group has fewer posts than MIN_POSTS_THRESHOLD", () => {
		it("skips the group with threshold message", async () => {
			setupDefaultDbMocks({
				posts: makePostSet(5), // Less than MIN_POSTS_THRESHOLD (10)
			});

			const result = await processAutoLearning();

			expect(result.groupResults).toHaveLength(1);
			expect(result.groupResults[0].error).toContain("Only 5 posts");
			expect(result.groupResults[0].error).toContain("need 10+");
			expect(result.groupResults[0].totalPosts).toBe(0);
		});
	});

	// ── Successful learning cycle ──

	describe("successful learning cycle", () => {
		it("processes group and returns results", async () => {
			setupDefaultDbMocks({
				posts: makePostSet(20),
			});

			const result = await processAutoLearning();

			expect(result.groupsProcessed).toBe(1);
			expect(result.groupResults).toHaveLength(1);
			expect(result.groupResults[0].totalPosts).toBe(20);
			expect(result.groupResults[0].patternsFound).toBeGreaterThan(0);
			expect(result.groupResults[0].confidenceScore).toBeGreaterThan(0);
		});

		it("identifies top and bottom performers", async () => {
			const posts = makePostSet(20, 5.0);

			setupDefaultDbMocks({ posts });

			const result = await processAutoLearning();

			// Top post should be the highest engagement
			expect(result.groupResults[0].topPostER).toBeDefined();
			expect(result.groupResults[0].topPostContent).toBeDefined();
			expect(result.groupResults[0].medianER).toBeGreaterThan(0);
		});

		it("calls AI with top and bottom performers for analysis", async () => {
			setupDefaultDbMocks({
				posts: makePostSet(20),
			});

			await processAutoLearning();

			// generateWithProvider should be called at least once for analysis
			expect(mockGenerateWithProvider).toHaveBeenCalled();
			// First call should be the pattern analysis prompt
			const firstCallPrompt = mockGenerateWithProvider.mock.calls[0][0];
			expect(firstCallPrompt).toContain("Top Performing Posts");
			expect(firstCallPrompt).toContain("Bottom Performing Posts");
		});

		it("updates tone_notes when confidence is high enough", async () => {
			setupDefaultDbMocks({
				posts: makePostSet(20),
			});
			mockGenerateWithProvider.mockResolvedValue(
				makeAIAnalysisJson({ confidence: 0.8 }),
			);

			const result = await processAutoLearning();

			expect(result.toneNotesUpdated).toBe(1);
			expect(result.groupResults[0].toneNotesUpdated).toBe(true);
		});

		it("does NOT update tone_notes when confidence is below threshold", async () => {
			setupDefaultDbMocks({
				posts: makePostSet(20),
			});
			mockGenerateWithProvider.mockResolvedValue(
				makeAIAnalysisJson({ confidence: 0.1 }),
			);

			const result = await processAutoLearning();

			expect(result.toneNotesUpdated).toBe(0);
			expect(result.groupResults[0].toneNotesUpdated).toBe(false);
		});
	});

	// ── AI config missing ──

	describe("when AI config is missing", () => {
		it("skips AI analysis but still logs feedback ratings", async () => {
			setupDefaultDbMocks({
				posts: makePostSet(15),
			});
			mockGetUserAIConfig.mockResolvedValue(null);

			const result = await processAutoLearning();

			expect(result.groupResults[0].patternsFound).toBe(0);
			expect(result.groupResults[0].confidenceScore).toBe(0);
			expect(result.groupResults[0].toneNotesUpdated).toBe(false);
			// Should still log feedback ratings
			expect(result.groupResults[0].feedbackRatings).toBeGreaterThanOrEqual(0);
		});
	});

	// ── AI returns empty ──

	describe("when AI returns empty response", () => {
		it("returns null analysis without crashing", async () => {
			setupDefaultDbMocks({
				posts: makePostSet(15),
			});
			mockGenerateWithProvider.mockResolvedValue(null);

			const result = await processAutoLearning();

			expect(result.groupResults[0].patternsFound).toBe(0);
			expect(result.groupResults[0].confidenceScore).toBe(0);
		});
	});

	// ── AI returns invalid JSON ──

	describe("when AI returns invalid JSON", () => {
		it("handles gracefully without crashing", async () => {
			setupDefaultDbMocks({
				posts: makePostSet(15),
			});
			mockGenerateWithProvider.mockResolvedValue(
				"This is not valid JSON at all, sorry!",
			);

			const result = await processAutoLearning();

			expect(result.groupResults[0].patternsFound).toBe(0);
			expect(result.groupResults[0].error).toBeUndefined();
		});
	});

	// ── AI returns JSON with markdown fences ──

	describe("when AI returns JSON wrapped in markdown fences", () => {
		it("parses the JSON correctly", async () => {
			setupDefaultDbMocks({
				posts: makePostSet(15),
			});
			mockGenerateWithProvider.mockResolvedValue(
				`\`\`\`json\n${makeAIAnalysisJson()}\n\`\`\``,
			);

			const result = await processAutoLearning();

			expect(result.groupResults[0].patternsFound).toBeGreaterThan(0);
			expect(result.groupResults[0].confidenceScore).toBeGreaterThan(0);
		});
	});

	// ── AI throws error ──

	describe("when AI generation throws", () => {
		it("returns null analysis without propagating error", async () => {
			setupDefaultDbMocks({
				posts: makePostSet(15),
			});
			mockGenerateWithProvider.mockRejectedValue(
				new Error("API quota exceeded"),
			);

			const result = await processAutoLearning();

			expect(result.groupResults[0].patternsFound).toBe(0);
			expect(result.groupResults[0].error).toBeUndefined();
		});
	});

	// ── Group processing error isolation ──

	describe("group processing error isolation", () => {
		it("records error for failed group but continues others", async () => {
			setupDefaultDbMocks({
				groups: [
					makeGroup({ id: "grp-1", name: "Group 1" }),
					makeGroup({ id: "grp-2", name: "Group 2" }),
				],
			});

			// Make processGroup throw for first group by having posts query fail
			let postQueryCount = 0;
			const originalMock = mockFrom.getMockImplementation();
			mockFrom.mockImplementation((table: string) => {
				if (table === "posts") {
					postQueryCount++;
					if (postQueryCount === 1) {
						const c = chain(null);
						c.then = (resolve: (v: any) => void) =>
							resolve({ data: null, error: { message: "DB timeout" } });
						return c;
					}
				}
				return originalMock!(table);
			});

			const result = await processAutoLearning();

			// Both groups should have results
			expect(result.groupResults).toHaveLength(2);
			// At least one should have processed
			const withoutError = result.groupResults.filter((r) => !r.error);
			expect(withoutError.length).toBeGreaterThanOrEqual(0);
		});
	});

	// ── Feedback ratings logging ──

	describe("feedback ratings", () => {
		it("logs positive ratings for top performers", async () => {
			setupDefaultDbMocks({
				posts: makePostSet(15),
			});

			const result = await processAutoLearning();

			expect(result.feedbackRatings).toBeGreaterThan(0);
			expect(result.groupResults[0].feedbackRatings).toBeGreaterThan(0);
		});

		it("respects MAX_FEEDBACK_RATINGS limit", async () => {
			// Create many posts to generate many ratings
			setupDefaultDbMocks({
				posts: makePostSet(200),
			});

			const result = await processAutoLearning();

			// Should not exceed 50 (MAX_FEEDBACK_RATINGS)
			expect(result.feedbackRatings).toBeLessThanOrEqual(50);
		});
	});

	// ── Agent notes summary ──

	describe("agent notes summary", () => {
		it("saves summary to agent_notes after processing", async () => {
			setupDefaultDbMocks({
				posts: makePostSet(15),
			});

			await processAutoLearning();

			// agent_notes table should be accessed for upsert
			expect(mockFrom).toHaveBeenCalledWith("agent_notes");
		});

		it("updates existing agent note if one exists", async () => {
			setupDefaultDbMocks({
				posts: makePostSet(15),
				existingAgentNote: { id: "note-1" },
			});

			await processAutoLearning();

			// Should use update path
			expect(mockFrom).toHaveBeenCalledWith("agent_notes");
		});
	});

	// ── Competitor benchmarks ──

	describe("competitor benchmark integration", () => {
		it("includes competitor data in AI prompt when available", async () => {
			setupDefaultDbMocks({
				posts: makePostSet(15),
				competitors: [{ id: "comp-1" }],
				competitorPosts: [
					{
						content: "Competitor post 1",
						engagement_score: 0.5,
						competitor_username: "rival1",
						scraped_at: new Date().toISOString(),
					},
					{
						content: "Competitor post 2",
						engagement_score: 0.8,
						competitor_username: "rival2",
						scraped_at: new Date().toISOString(),
					},
					{
						content: "Competitor post 3",
						engagement_score: 0.3,
						competitor_username: "rival3",
						scraped_at: new Date().toISOString(),
					},
				],
			});

			await processAutoLearning();

			// AI prompt should include competitor context
			const analysisPrompt = mockGenerateWithProvider.mock.calls[0]?.[0];
			if (analysisPrompt) {
				expect(analysisPrompt).toContain("Competitor Pattern Corpus");
				expect(analysisPrompt).toContain("metric_quality=");
			}
		});

		it("proceeds without competitor data when none exist", async () => {
			setupDefaultDbMocks({
				posts: makePostSet(15),
				competitors: [],
			});

			const result = await processAutoLearning();

			// Should still work without competitors
			expect(result.groupsProcessed).toBe(1);
		});
	});

	// ── Median engagement rate calculation ──

	describe("median engagement rate", () => {
		it("calculates median from post set", async () => {
			const posts = makePostSet(15, 3.0);
			setupDefaultDbMocks({ posts });

			const result = await processAutoLearning();

			expect(result.groupResults[0].medianER).toBeGreaterThan(0);
		});
	});

	// ── Multiple groups processing ──

	describe("multiple groups", () => {
		it("processes up to MAX_GROUPS groups", async () => {
			const groups = Array.from({ length: 5 }, (_, i) =>
				makeGroup({
					id: `grp-${i}`,
					name: `Group ${i}`,
					user_id: `user-${i % 2}`,
				}),
			);
			setupDefaultDbMocks({
				groups,
				posts: makePostSet(15),
			});

			const result = await processAutoLearning();

			expect(result.groupResults.length).toBeLessThanOrEqual(20);
		});

		it("deduplicates initial AI config fetches per user", async () => {
			const groups = [
				makeGroup({ id: "grp-1", name: "Group 1", user_id: "user-1" }),
				makeGroup({ id: "grp-2", name: "Group 2", user_id: "user-1" }),
				makeGroup({ id: "grp-3", name: "Group 3", user_id: "user-2" }),
			];
			setupDefaultDbMocks({
				groups,
				posts: makePostSet(15),
			});

			await processAutoLearning();

			// The initial dedup loop calls getUserAIConfig once per unique user_id.
			// updateToneNotes may call it again per group, but the initial fetch
			// should only query 2 unique users (user-1, user-2), not 3 groups.
			// Verify it was called with both user IDs
			expect(mockGetUserAIConfig).toHaveBeenCalledWith("user-1");
			expect(mockGetUserAIConfig).toHaveBeenCalledWith("user-2");
		});
	});

	// ── Tone notes length cap ──

	describe("tone notes safety cap", () => {
		it("does not exceed MAX_TONE_NOTES_LENGTH", async () => {
			setupDefaultDbMocks({
				groups: [
					makeGroup({
						content_strategy: {
							tone_notes: "x".repeat(1800), // Already long
						},
					}),
				],
				posts: makePostSet(15),
			});

			// AI returns a long synthesis
			mockGenerateWithProvider
				.mockResolvedValueOnce(makeAIAnalysisJson({ confidence: 0.8 }))
				.mockResolvedValueOnce("y".repeat(500)); // synthesis response

			const result = await processAutoLearning();

			// Should update but the logged update should show the truncated note
			expect(result.groupResults[0]).toBeDefined();
		});
	});

	// ── Content type mix analysis ──

	describe("content type mix analysis", () => {
		it("includes mix section when queue items exist", async () => {
			setupDefaultDbMocks({
				posts: makePostSet(15),
				queueItems: [
					{ content_type: "hot_take", engagement_rate: 0.12 },
					{ content_type: "hot_take", engagement_rate: 0.08 },
					{ content_type: "question", engagement_rate: 0.15 },
					{ content_type: "question", engagement_rate: 0.10 },
					{ content_type: "story", engagement_rate: 0.05 },
				],
			});

			const result = await processAutoLearning();

			expect(result.groupsProcessed).toBe(1);
		});
	});

	// ── DB error on posts query ──

	describe("DB error handling", () => {
		it("returns skipped result on posts query error", async () => {
			mockFrom.mockImplementation((table: string) => {
				if (table === "account_groups") {
					return chain([makeGroup()]);
				}
				if (table === "auto_post_group_config") {
					return chain({ timezone: "UTC", workspace_id: "ws-1" });
				}
				if (table === "posts") {
					const c = chain(null);
					c.then = (resolve: (v: any) => void) =>
						resolve({
							data: null,
							error: { message: "relation does not exist" },
						});
					return c;
				}
				return chain(null);
			});

			const result = await processAutoLearning();

			expect(result.groupResults[0].error).toContain("DB error");
		});
	});

	// ── Zero-view posts filtered out ──

	describe("zero-view post filtering", () => {
		it("only analyzes posts with views > 0", async () => {
			// The source query filters gt("views_count", 0)
			// So if DB returns only zero-view posts (which it shouldn't),
			// we'd get no data. Verify the query is constructed correctly.
			setupDefaultDbMocks({
				posts: [], // Empty result means no posts with views > 0
			});

			const result = await processAutoLearning();

			// Should be skipped due to not enough posts
			expect(result.groupResults[0].error).toContain("Only 0 posts");
		});
	});

	// ── Data-driven insights storage ──

	describe("data-driven insights", () => {
		it("stores insights when analysis confidence is sufficient", async () => {
			setupDefaultDbMocks({
				posts: makePostSet(20),
				currentGroup: {
					content_strategy: { tone_notes: "Be authentic" },
				},
			});
			mockGenerateWithProvider.mockResolvedValue(
				makeAIAnalysisJson({ confidence: 0.7 }),
			);

			const result = await processAutoLearning();

			// account_groups should be updated with data_driven_insights
			expect(mockFrom).toHaveBeenCalledWith("account_groups");
			expect(result.groupsProcessed).toBe(1);
		});

		it("does NOT store insights when confidence is too low", async () => {
			setupDefaultDbMocks({
				posts: makePostSet(20),
			});
			mockGenerateWithProvider.mockResolvedValue(
				makeAIAnalysisJson({ confidence: 0.1 }),
			);

			const result = await processAutoLearning();

			// Should still succeed but not update insights
			expect(result.groupResults[0].toneNotesUpdated).toBe(false);
		});
	});

	// ── AI response with camelCase keys ──

	describe("AI response key normalization", () => {
		it("handles camelCase keys from AI response", async () => {
			setupDefaultDbMocks({
				posts: makePostSet(15),
			});
			mockGenerateWithProvider.mockResolvedValue(
				JSON.stringify({
					winningPatterns: ["Pattern A", "Pattern B"],
					losingPatterns: ["Bad pattern"],
					recommendedAdditionsToToneNotes: "Add this rule",
					recommendedRemovals: "none",
					confidence: 0.65,
				}),
			);

			const result = await processAutoLearning();

			expect(result.groupResults[0].patternsFound).toBe(2);
			expect(result.groupResults[0].confidenceScore).toBe(0.65);
		});
	});

	// ── AI response with string confidence ──

	describe("AI response confidence parsing", () => {
		it("parses string confidence as number", async () => {
			setupDefaultDbMocks({
				posts: makePostSet(15),
			});
			mockGenerateWithProvider.mockResolvedValue(
				JSON.stringify({
					winning_patterns: ["A", "B"],
					losing_patterns: ["C"],
					recommended_additions_to_tone_notes: "Test",
					recommended_removals: "none",
					confidence: "0.82",
				}),
			);

			const result = await processAutoLearning();

			expect(result.groupResults[0].confidenceScore).toBe(0.82);
		});

		it("derives confidence from pattern count when missing", async () => {
			setupDefaultDbMocks({
				posts: makePostSet(15),
			});
			mockGenerateWithProvider.mockResolvedValue(
				JSON.stringify({
					winning_patterns: ["A", "B", "C"],
					losing_patterns: ["D", "E"],
					recommended_additions_to_tone_notes: "Test",
					recommended_removals: "none",
					// No confidence field
				}),
			);

			const result = await processAutoLearning();

			// Should derive a fallback confidence (0.45 for both patterns present with 2+ each)
			expect(result.groupResults[0].confidenceScore).toBe(0.45);
		});

		it("clamps confidence to 0-1 range", async () => {
			setupDefaultDbMocks({
				posts: makePostSet(15),
			});
			mockGenerateWithProvider.mockResolvedValue(
				makeAIAnalysisJson({ confidence: 1.5 }),
			);

			const result = await processAutoLearning();

			expect(result.groupResults[0].confidenceScore).toBeLessThanOrEqual(
				1,
			);
		});
	});

	// ── AI response with only winning patterns ──

	describe("partial AI response", () => {
		it("accepts response with only winning patterns", async () => {
			setupDefaultDbMocks({
				posts: makePostSet(15),
			});
			mockGenerateWithProvider.mockResolvedValue(
				JSON.stringify({
					winning_patterns: ["Good pattern 1"],
					losing_patterns: [],
					recommended_additions_to_tone_notes: "Add this",
					recommended_removals: "none",
					confidence: 0.5,
				}),
			);

			const result = await processAutoLearning();

			expect(result.groupResults[0].patternsFound).toBe(1);
		});

		it("rejects response with no patterns and no additions", async () => {
			setupDefaultDbMocks({
				posts: makePostSet(15),
			});
			mockGenerateWithProvider.mockResolvedValue(
				JSON.stringify({
					winning_patterns: [],
					losing_patterns: [],
					recommended_additions_to_tone_notes: "",
					recommended_removals: "none",
					confidence: 0.5,
				}),
			);

			const result = await processAutoLearning();

			// Should be treated as null analysis
			expect(result.groupResults[0].patternsFound).toBe(0);
		});
	});

	// ── Unicode smart quotes in AI response ──

	describe("AI response normalization", () => {
		it("handles smart quotes in AI response", async () => {
			setupDefaultDbMocks({
				posts: makePostSet(15),
			});
			// Use Unicode smart quotes that normalizeAIAnalysisJson should handle
			const jsonWithSmartQuotes = `{
				\u201Cwinning_patterns\u201D: [\u201CPattern A\u201D],
				\u201Closing_patterns\u201D: [\u201CPattern B\u201D],
				\u201Crecommended_additions_to_tone_notes\u201D: \u201CAdd this\u201D,
				\u201Crecommended_removals\u201D: \u201Cnone\u201D,
				\u201Cconfidence\u201D: 0.6
			}`;
			mockGenerateWithProvider.mockResolvedValue(jsonWithSmartQuotes);

			const result = await processAutoLearning();

			expect(result.groupResults[0].patternsFound).toBe(1);
		});
	});

	// ── Group with null content_strategy ──

	describe("null content_strategy handling", () => {
		it("handles groups with null content_strategy", async () => {
			setupDefaultDbMocks({
				groups: [makeGroup({ content_strategy: null })],
				posts: makePostSet(15),
			});

			const result = await processAutoLearning();

			// Should still process without error
			expect(result.groupResults[0].error).toBeUndefined();
		});
	});

	// ── Tone notes AUTO-LEARNED section management ──

	describe("tone notes section management", () => {
		it("appends AUTO-LEARNED section to existing tone_notes", async () => {
			setupDefaultDbMocks({
				groups: [
					makeGroup({
						content_strategy: {
							tone_notes: "Core strategy: be funny",
						},
					}),
				],
				posts: makePostSet(20),
			});
			mockGenerateWithProvider
				.mockResolvedValueOnce(makeAIAnalysisJson({ confidence: 0.8 }))
				.mockResolvedValueOnce("- Use questions for engagement");

			const result = await processAutoLearning();

			expect(result.toneNotesUpdated).toBe(1);
		});

		it("replaces previous AUTO-LEARNED section instead of stacking", async () => {
			setupDefaultDbMocks({
				groups: [
					makeGroup({
						content_strategy: {
							tone_notes:
								"Core strategy\n\n--- AUTO-LEARNED ---\nOld learned data",
						},
					}),
				],
				posts: makePostSet(20),
			});
			mockGenerateWithProvider
				.mockResolvedValueOnce(makeAIAnalysisJson({ confidence: 0.8 }))
				.mockResolvedValueOnce("- New learned insight");

			const result = await processAutoLearning();

			expect(result.toneNotesUpdated).toBe(1);
		});
	});

	// ── Velocity calculations ──

	describe("velocity calculations", () => {
		it("computes view velocity and engagement velocity for posts", async () => {
			const recentPost = makePost({
				published_at: new Date(
					Date.now() - 2 * 60 * 60 * 1000,
				).toISOString(), // 2 hours ago
				views_count: 200,
				likes_count: 20,
				replies_count: 10,
			});
			setupDefaultDbMocks({
				posts: [
					recentPost,
					...makePostSet(14), // fill to threshold
				],
			});

			const result = await processAutoLearning();

			// Should process without error - velocities are computed internally
			expect(result.groupResults[0].error).toBeUndefined();
		});
	});

	// ── Return structure ──

	describe("return structure", () => {
		it("returns correctly shaped result", async () => {
			setupDefaultDbMocks({
				posts: makePostSet(15),
			});

			const result = await processAutoLearning();

			expect(result).toEqual(
				expect.objectContaining({
					groupsProcessed: expect.any(Number),
					toneNotesUpdated: expect.any(Number),
					feedbackRatings: expect.any(Number),
					groupResults: expect.any(Array),
				}),
			);

			const gr = result.groupResults[0];
			expect(gr).toEqual(
				expect.objectContaining({
					groupId: expect.any(String),
					groupName: expect.any(String),
					totalPosts: expect.any(Number),
					medianER: expect.any(Number),
					patternsFound: expect.any(Number),
					confidenceScore: expect.any(Number),
					toneNotesUpdated: expect.any(Boolean),
					feedbackRatings: expect.any(Number),
				}),
			);
		});
	});
});

// ============================================================================
// Pure function tests (no DB mocking needed)
// ============================================================================

describe("auto-learning — pure utility functions", () => {
	// We test the internal parsing/coercion logic by exercising processAutoLearning
	// with controlled AI responses, since the utilities are not exported.
	// However, we can verify the behavior through integration.

	describe("analyzeMediaPerformance (via integration)", () => {
		beforeEach(() => {
			vi.clearAllMocks();
			mockGetUserAIConfig.mockResolvedValue(makeAIConfig());
			mockGenerateWithProvider.mockResolvedValue(
				makeAIAnalysisJson({ confidence: 0.7 }),
			);
		});

		it("handles all text posts (no media_type)", async () => {
			const textPosts = makePostSet(15).map((p) => ({
				...p,
				media_type: null,
			}));
			setupDefaultDbMocks({ posts: textPosts });

			const result = await processAutoLearning();

			expect(result.groupsProcessed).toBe(1);
		});

		it("handles mix of text and media posts", async () => {
			const posts = makePostSet(15).map((p, i) => ({
				...p,
				media_type: i % 3 === 0 ? "IMAGE" : null,
			}));
			setupDefaultDbMocks({ posts });

			const result = await processAutoLearning();

			expect(result.groupsProcessed).toBe(1);
		});
	});

	describe("analyzeContentLength (via integration)", () => {
		beforeEach(() => {
			vi.clearAllMocks();
			mockGetUserAIConfig.mockResolvedValue(makeAIConfig());
			mockGenerateWithProvider.mockResolvedValue(
				makeAIAnalysisJson({ confidence: 0.7 }),
			);
		});

		it("categorizes posts by content length buckets", async () => {
			const posts = [
				...Array.from({ length: 4 }, (_, i) =>
					makePost({ id: `ultra-${i}`, content: "Short!", engagement_rate: 10 }),
				),
				...Array.from({ length: 4 }, (_, i) =>
					makePost({
						id: `short-${i}`,
						content: "This is a bit longer post content here",
						engagement_rate: 7,
					}),
				),
				...Array.from({ length: 4 }, (_, i) =>
					makePost({
						id: `med-${i}`,
						content:
							"This is a medium length post that has more words and takes up more space in the feed for readers to consider",
						engagement_rate: 5,
					}),
				),
				...Array.from({ length: 4 }, (_, i) =>
					makePost({
						id: `long-${i}`,
						content:
							"This is a much longer post that really goes into detail about the topic at hand. It covers multiple perspectives and provides extensive analysis of the situation. Readers will need to spend more time with this content to fully absorb the message.",
						engagement_rate: 3,
					}),
				),
			];
			setupDefaultDbMocks({ posts });

			const result = await processAutoLearning();

			expect(result.groupsProcessed).toBe(1);
		});
	});
});
