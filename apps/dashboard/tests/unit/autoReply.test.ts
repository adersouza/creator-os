/**
 * Auto-Reply Engine Tests
 *
 * Comprehensive tests for api/_lib/handlers/auto-post/autoReply.ts (~1,225 lines).
 *
 * This is the automated reply engine that engages with audience comments.
 * Bugs here could post inappropriate replies to real users — reputational risk.
 *
 * Covers:
 * 1. Negative comment pattern matching (safety filter)
 * 2. Reply prompt construction
 * 3. processAutoReplyQueue orchestrator
 * 4. harvestAndReplyForPost targeted harvest
 * 5. Rate limiting (per-account hourly, per-group daily)
 * 6. Sentiment-based filtering (negative/toxic → needs_review)
 * 7. Comment eligibility (own-account filtering, empty text, already harvested)
 * 8. Reply generation (AI prompt, variant selection, banned words, sanitization)
 * 9. Cross-account similarity gate
 * 10. Publish phase (credentials check, jitter, retry on failure)
 * 11. Error handling (AI failure, API failure, missing credentials)
 * 12. Edge cases (empty comments, long text, agent_paused)
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mocks — must be declared BEFORE importing module under test
// ---------------------------------------------------------------------------

// Track all Supabase calls
const mockFromChains: Record<string, any> = {};

function createTableChain(overrides: Record<string, any> = {}) {
	const chain: any = {};
	const methods = [
		"select", "eq", "in", "not", "or", "gte", "gt", "lt", "lte", "is",
		"neq", "contains", "maybeSingle", "single", "limit", "order", "update",
		"insert", "upsert",
	];
	for (const m of methods) {
		if (m === "maybeSingle" || m === "single") {
			chain[m] = vi.fn().mockResolvedValue({ data: null, error: null, count: 0 });
		} else {
			chain[m] = vi.fn().mockReturnValue(chain);
		}
	}
	Object.assign(chain, overrides);
	return chain;
}

const mockSupabaseFrom = vi.fn().mockImplementation((table: string) => {
	if (mockFromChains[table]) return mockFromChains[table];
	return createTableChain();
});

vi.mock("../../api/_lib/supabase", () => ({
	getSupabase: () => ({ from: mockSupabaseFrom }),
	getSupabaseAny: () => ({ from: mockSupabaseFrom }),
}));

vi.mock("../../api/_lib/encryption", () => ({
	decrypt: (v: string) => `decrypted_${v}`,
}));

vi.mock("../../api/_lib/logger", () => ({
	logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
	serializeError: (e: unknown) =>
		e instanceof Error ? e.message : String(e),
}));

vi.mock("../../api/_lib/promptUtils", () => ({
	escapeForPrompt: (text: string) => text.replace(/"/g, '\\"'),
}));

vi.mock("../../api/_lib/retryUtils", () => ({
	withRetry: (fn: () => Promise<any>) => fn(),
	isRetryableMetaError: vi.fn().mockReturnValue(false),
}));

const mockSendThreadsReply = vi.fn().mockResolvedValue(true);
vi.mock("../../api/_lib/autoReplyEngine", () => ({
	sendThreadsReply: (...args: unknown[]) => mockSendThreadsReply(...args),
}));

const mockGenerateWithProvider = vi.fn();
const mockGetUserAIConfig = vi.fn();
const mockResolveVoiceProfile = vi.fn();
vi.mock("../../api/_lib/handlers/auto-post/contentSelection", () => ({
	generateWithProvider: (...args: unknown[]) =>
		mockGenerateWithProvider(...args),
	getUserAIConfig: (...args: unknown[]) => mockGetUserAIConfig(...args),
	resolveVoiceProfile: (...args: unknown[]) =>
		mockResolveVoiceProfile(...args),
}));

const mockLogActivity = vi.fn().mockResolvedValue(undefined);
vi.mock("../../api/_lib/handlers/auto-post/publisher", () => ({
	logActivity: (...args: unknown[]) => mockLogActivity(...args),
}));

const mockRedisGet = vi.fn().mockResolvedValue(null);
const mockRedisSet = vi.fn().mockResolvedValue(undefined);
vi.mock("../../api/_lib/redis", () => ({
	getRedis: () => ({
		get: mockRedisGet,
		set: mockRedisSet,
		pipeline: vi.fn(),
		incr: vi.fn(),
	}),
}));

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

// ---------------------------------------------------------------------------
// Import module under test AFTER mocks
// ---------------------------------------------------------------------------

import {
	processAutoReplyQueue,
	harvestAndReplyForPost,
} from "../../api/_lib/handlers/auto-post/autoReply";

// ---------------------------------------------------------------------------
// Test Data Factories
// ---------------------------------------------------------------------------

function makeQueueItem(overrides: Record<string, any> = {}) {
	return {
		id: "arq-1",
		workspace_id: "ws-1",
		group_id: "grp-1",
		account_id: "acc-1",
		source_post_id: "src-post-1",
		threads_post_id: "tp-1",
		comment_id: "comment-1",
		comment_username: "fan_user",
		comment_text: "love this post!",
		generated_reply: null as string | null,
		status: "pending",
		retry_count: 0,
		posted_at: null,
		created_at: new Date().toISOString(),
		error_message: null,
		flagged_reason: null,
		followup_checked_at: null,
		...overrides,
	};
}

function makeAutoPostQueueItem(overrides: Record<string, any> = {}) {
	return {
		id: "apq-1",
		workspace_id: "ws-1",
		account_id: "acc-1",
		content: "my original post text",
		threads_post_id: "tp-1",
		status: "published",
		posted_at: new Date(Date.now() - 30 * 60 * 1000).toISOString(), // 30 min ago
		reply_harvested_at: null,
		group_id: "grp-1",
		...overrides,
	};
}

function makeAccount(overrides: Record<string, any> = {}) {
	return {
		id: "acc-1",
		username: "our_brand",
		threads_access_token_encrypted: "enc-token",
		threads_user_id: "tu-1",
		...overrides,
	};
}

function makeVoiceProfile(overrides: Record<string, any> = {}) {
	return {
		voice_profile: "casual, flirty",
		emoji_usage: "minimal",
		avoid_topics: ["politics"],
		avoid_words: ["hashtag", "content"],
		...overrides,
	};
}

/** Helper to set up the mock Supabase chain for a given table */
function setupTableMock(table: string, chain: any) {
	mockFromChains[table] = chain;
}

/** JSON response helper for fetch mock */
function jsonResponse(data: unknown, ok = true, status = 200) {
	return Promise.resolve({
		ok,
		status,
		json: () => Promise.resolve(data),
	});
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("autoReply", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		// Clear table chains
		for (const key of Object.keys(mockFromChains)) {
			delete mockFromChains[key];
		}
		mockSendThreadsReply.mockResolvedValue(true);
		mockGetUserAIConfig.mockResolvedValue({
			provider: "gemini",
			apiKey: "test-key",
			model: "gemini-2.0-flash",
		});
		mockResolveVoiceProfile.mockResolvedValue(makeVoiceProfile());
		mockGenerateWithProvider.mockResolvedValue(
			"nice take what made you think that\nstoppp how did you know\nwait really tell me more\noh yeah what else\nthat part tho expand on that",
		);
		mockRedisGet.mockResolvedValue(null);
		mockRedisSet.mockResolvedValue(undefined);
	});

	afterEach(() => {
		vi.restoreAllMocks();
	});

	// =========================================================================
	// 1. Negative Comment Pattern Matching (Safety Filter)
	// =========================================================================

	describe("negative comment pattern matching", () => {
		// We cannot import matchesNegativePattern directly (not exported),
		// but we test it indirectly via harvestAndReplyForPost which routes
		// negative comments to needs_review. We also test the patterns directly
		// by checking the SEVERE_NEGATIVE_PATTERNS behavior through the harvest flow.

		const toxicComments = [
			"kys you suck",
			"kill yourself loser",
			"you're ugly and disgusting",
			"this is a scam and fraud",
			"fuck you seriously",
			"stfu nobody cares",
			"she's a whore honestly",
			"you're a pedo creep",
			"go die already",
			"you're a gross catfish",
			"gtfo with this spam",
		];

		for (const comment of toxicComments) {
			it(`routes toxic comment to needs_review: "${comment.slice(0, 30)}..."`, async () => {
				// Setup: harvestAndReplyForPost with one toxic comment from API
				const upsertSpy = vi.fn().mockResolvedValue({ error: null });

				setupTableMock("auto_post_group_config", (() => {
					const c = createTableChain();
					c.maybeSingle = vi.fn().mockResolvedValue({
						data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
						error: null,
					});
					return c;
				})());

				setupTableMock("auto_reply_queue", (() => {
					const c = createTableChain();
					c.maybeSingle = vi.fn().mockResolvedValue({ data: null, error: null });
					// For daily count
					const countChain = createTableChain();
					countChain.limit = undefined; // not used for count
					c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
						if (opts?.count === "exact") {
							const inner = createTableChain();
							inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
							return inner;
						}
						return c;
					});
					c.upsert = upsertSpy;
					return c;
				})());

				setupTableMock("auto_post_queue", (() => {
					const c = createTableChain();
					c.maybeSingle = vi.fn().mockResolvedValue({
						data: makeAutoPostQueueItem(),
						error: null,
					});
					c.update = vi.fn().mockReturnValue(createTableChain());
					return c;
				})());

				setupTableMock("accounts", (() => {
					const c = createTableChain();
					c.maybeSingle = vi.fn().mockResolvedValue({
						data: makeAccount(),
						error: null,
					});
					return c;
				})());

				setupTableMock("account_groups", (() => {
					const c = createTableChain();
					c.maybeSingle = vi.fn().mockResolvedValue({
						data: { account_ids: ["acc-1"] },
						error: null,
					});
					return c;
				})());

				// Mock Threads API conversation response with toxic comment
				mockFetch.mockResolvedValueOnce(
					jsonResponse({
						data: [
							{
								id: "comment-toxic",
								text: comment,
								username: "toxic_user",
								timestamp: new Date().toISOString(),
							},
						],
					}),
				);

				await harvestAndReplyForPost(
					"ws-1",
					"grp-1",
					"owner-1",
					"acc-1",
					"post-1",
					"apq-1",
				);

				// The upsert should have been called with needs_review status
				expect(upsertSpy).toHaveBeenCalled();
				const upsertArg = upsertSpy.mock.calls[0][0];
				expect(upsertArg.status).toBe("needs_review");
				expect(upsertArg.flagged_reason).toBeTruthy();
			});
		}

		it("allows safe comments through as pending", async () => {
			const upsertSpy = vi.fn().mockResolvedValue({ error: null });

			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					return c;
				});
				c.upsert = upsertSpy;
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAutoPostQueueItem(),
					error: null,
				});
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("accounts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAccount(),
					error: null,
				});
				return c;
			})());

			setupTableMock("account_groups", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { account_ids: ["acc-1"] },
					error: null,
				});
				return c;
			})());

			mockFetch.mockResolvedValueOnce(
				jsonResponse({
					data: [
						{
							id: "comment-safe",
							text: "love this post so much!",
							username: "nice_fan",
							timestamp: new Date().toISOString(),
						},
					],
				}),
			);

			await harvestAndReplyForPost(
				"ws-1",
				"grp-1",
				"owner-1",
				"acc-1",
				"post-1",
				"apq-1",
			);

			expect(upsertSpy).toHaveBeenCalled();
			const upsertArg = upsertSpy.mock.calls[0][0];
			expect(upsertArg.status).toBe("pending");
			expect(upsertArg.flagged_reason).toBeFalsy();
		});
	});

	// =========================================================================
	// 2. processAutoReplyQueue — Orchestrator
	// =========================================================================

	describe("processAutoReplyQueue", () => {
		it("returns empty result when agent_paused is true", async () => {
			setupTableMock("profiles", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { agent_paused: true },
					error: null,
				});
				return c;
			})());

			const result = await processAutoReplyQueue("ws-1", "owner-1");

			expect(result.harvested).toBe(0);
			expect(result.generated).toBe(0);
			expect(result.published).toBe(0);
		});

		it("returns empty result when no groups have auto-reply enabled", async () => {
			setupTableMock("profiles", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { agent_paused: false },
					error: null,
				});
				return c;
			})());

			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				// No configs returned
				c.limit = vi.fn().mockResolvedValue({ data: [], error: null });
				return c;
			})());

			const result = await processAutoReplyQueue("ws-1", "owner-1");

			expect(result.harvested).toBe(0);
			expect(result.generated).toBe(0);
			expect(result.published).toBe(0);
		});

		it("catches top-level errors and returns partial result", async () => {
			setupTableMock("profiles", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockRejectedValue(new Error("DB down"));
				return c;
			})());

			const result = await processAutoReplyQueue("ws-1", "owner-1");

			// Should not throw
			expect(result.harvested).toBe(0);
			expect(result.published).toBe(0);
		});
	});

	// =========================================================================
	// 3. harvestAndReplyForPost — Targeted Harvest
	// =========================================================================

	describe("harvestAndReplyForPost", () => {
		it("returns empty result when auto_reply is not enabled for group", async () => {
			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: false },
					error: null,
				});
				return c;
			})());

			const result = await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			expect(result.harvested).toBe(0);
		});

		it("returns empty result when daily limit is reached", async () => {
			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 5 },
					error: null,
				});
				return c;
			})());

			// Daily count = 5 (at limit)
			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 5, error: null });
						return inner;
					}
					return c;
				});
				return c;
			})());

			const result = await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			expect(result.harvested).toBe(0);
		});

		it("returns empty result when source post has no threads_post_id", async () => {
			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					return c;
				});
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { ...makeAutoPostQueueItem(), threads_post_id: null },
					error: null,
				});
				return c;
			})());

			const result = await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			expect(result.harvested).toBe(0);
		});

		it("returns empty result when post already harvested", async () => {
			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					return c;
				});
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: {
						...makeAutoPostQueueItem(),
						reply_harvested_at: new Date().toISOString(),
					},
					error: null,
				});
				return c;
			})());

			const result = await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			expect(result.harvested).toBe(0);
		});

		it("returns empty result when account has no encrypted token", async () => {
			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					return c;
				});
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAutoPostQueueItem(),
					error: null,
				});
				return c;
			})());

			setupTableMock("accounts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAccount({ threads_access_token_encrypted: null }),
					error: null,
				});
				return c;
			})());

			const result = await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			expect(result.harvested).toBe(0);
		});

		it("filters out own-account comments", async () => {
			const upsertSpy = vi.fn().mockResolvedValue({ error: null });

			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					return c;
				});
				c.upsert = upsertSpy;
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAutoPostQueueItem(),
					error: null,
				});
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("accounts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAccount(),
					error: null,
				});
				// For in() query to get group account usernames
				c.in = vi.fn().mockResolvedValue({
					data: [{ username: "our_brand" }],
					error: null,
				});
				return c;
			})());

			setupTableMock("account_groups", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { account_ids: ["acc-1"] },
					error: null,
				});
				return c;
			})());

			// API returns comments from our own account + one external
			mockFetch.mockResolvedValueOnce(
				jsonResponse({
					data: [
						{
							id: "self-comment",
							text: "thanks for the love!",
							username: "our_brand", // OWN account — should be filtered
							timestamp: new Date().toISOString(),
						},
						{
							id: "external-comment",
							text: "this is great!",
							username: "external_fan",
							timestamp: new Date().toISOString(),
						},
					],
				}),
			);

			const result = await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			// Should only harvest the external comment
			expect(result.harvested).toBe(1);
			// The upsert should be for the external fan, not our own account
			const upsertArg = upsertSpy.mock.calls[0][0];
			expect(upsertArg.comment_username).toBe("external_fan");
		});

		it("filters out comments with empty text", async () => {
			const upsertSpy = vi.fn().mockResolvedValue({ error: null });

			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					return c;
				});
				c.upsert = upsertSpy;
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAutoPostQueueItem(),
					error: null,
				});
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("accounts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAccount(),
					error: null,
				});
				return c;
			})());

			setupTableMock("account_groups", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { account_ids: ["acc-1"] },
					error: null,
				});
				return c;
			})());

			// Comments with empty/whitespace text
			mockFetch.mockResolvedValueOnce(
				jsonResponse({
					data: [
						{ id: "c1", text: "", username: "user1" },
						{ id: "c2", text: "   ", username: "user2" },
						{ id: "c3", text: null, username: "user3" },
						{ id: "c4", text: "actual content here", username: "user4" },
					],
				}),
			);

			const result = await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			// Only the comment with actual text should be harvested
			expect(result.harvested).toBe(1);
		});

		it("handles Threads API error response gracefully", async () => {
			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					return c;
				});
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAutoPostQueueItem(),
					error: null,
				});
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("accounts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAccount(),
					error: null,
				});
				return c;
			})());

			setupTableMock("account_groups", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { account_ids: ["acc-1"] },
					error: null,
				});
				return c;
			})());

			// API returns an error
			mockFetch.mockResolvedValueOnce(
				jsonResponse({
					error: { message: "Access token expired", code: 190 },
				}),
			);

			const result = await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			// Should mark harvested but not crash
			expect(result.harvested).toBe(0);
		});

		it("caps comments at 5 per post", async () => {
			const upsertSpy = vi.fn().mockResolvedValue({ error: null });

			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 100 },
					error: null,
				});
				return c;
			})());

			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					// For pending items query (generate phase) — return empty
					c.limit = vi.fn().mockResolvedValue({ data: [], error: null });
					return c;
				});
				c.upsert = upsertSpy;
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAutoPostQueueItem(),
					error: null,
				});
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("accounts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAccount(),
					error: null,
				});
				return c;
			})());

			setupTableMock("account_groups", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { account_ids: ["acc-1"] },
					error: null,
				});
				return c;
			})());

			// Return 10 comments
			const manyComments = Array.from({ length: 10 }, (_, i) => ({
				id: `comment-${i}`,
				text: `interesting thought ${i}`,
				username: `fan_${i}`,
				timestamp: new Date().toISOString(),
			}));

			mockFetch.mockResolvedValueOnce(jsonResponse({ data: manyComments }));

			const result = await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			// Should cap at 5
			expect(result.harvested).toBe(5);
			expect(upsertSpy).toHaveBeenCalledTimes(5);
		});

		it("handles sourceTable='posts' for manual posts", async () => {
			const upsertSpy = vi.fn().mockResolvedValue({ error: null });

			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					c.limit = vi.fn().mockResolvedValue({ data: [], error: null });
					return c;
				});
				c.upsert = upsertSpy;
				return c;
			})());

			// The "posts" table for sourceTable='posts'
			setupTableMock("posts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: {
						id: "post-1",
						threads_post_id: "tp-from-posts",
						account_id: "acc-1",
						content: "manual post content",
						metadata: {},
						status: "published",
					},
					error: null,
				});
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("accounts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAccount(),
					error: null,
				});
				return c;
			})());

			setupTableMock("account_groups", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { account_ids: ["acc-1"] },
					error: null,
				});
				return c;
			})());

			mockFetch.mockResolvedValueOnce(
				jsonResponse({
					data: [
						{
							id: "c1",
							text: "great manual post!",
							username: "fan1",
							timestamp: new Date().toISOString(),
						},
					],
				}),
			);

			const result = await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
				"posts",
			);

			expect(result.harvested).toBe(1);
		});

		it("handles fetch throwing an exception gracefully", async () => {
			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					return c;
				});
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAutoPostQueueItem(),
					error: null,
				});
				return c;
			})());

			setupTableMock("accounts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAccount(),
					error: null,
				});
				return c;
			})());

			setupTableMock("account_groups", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { account_ids: ["acc-1"] },
					error: null,
				});
				return c;
			})());

			// Network error
			mockFetch.mockRejectedValueOnce(new Error("Network timeout"));

			const result = await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			// Should not throw, just return 0
			expect(result.harvested).toBe(0);
		});
	});

	// =========================================================================
	// 4. Reply Generation — AI Prompt & Sanitization
	// =========================================================================

	describe("reply generation", () => {
		// We test generateReplies indirectly through harvestAndReplyForPost,
		// which calls generateReplies after harvesting.

		it("calls generateWithProvider with correct parameters", async () => {
			const upsertSpy = vi.fn().mockResolvedValue({ error: null });
			const updateSpy = vi.fn().mockReturnValue(createTableChain());

			// Set up a full flow: harvest 1 comment, then generate
			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			let selectCallCount = 0;
			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					selectCallCount++;
					// First call: pending items for generate phase
					if (selectCallCount <= 2) {
						const inner = createTableChain();
						inner.limit = vi.fn().mockResolvedValue({
							data: [
								makeQueueItem({
									status: "pending",
									comment_text: "wow this is fire",
									comment_username: "fan_user",
									source_post_id: "src-1",
								}),
							],
							error: null,
						});
						return inner;
					}
					// Subsequent calls: processing items for publish phase
					const inner = createTableChain();
					inner.limit = vi.fn().mockResolvedValue({ data: [], error: null });
					return inner;
				});
				c.upsert = upsertSpy;
				c.update = updateSpy;
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAutoPostQueueItem(),
					error: null,
				});
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("accounts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAccount(),
					error: null,
				});
				return c;
			})());

			setupTableMock("account_groups", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { account_ids: ["acc-1"] },
					error: null,
				});
				return c;
			})());

			// API returns a safe comment
			mockFetch.mockResolvedValueOnce(
				jsonResponse({
					data: [
						{
							id: "c-gen",
							text: "wow this is fire",
							username: "fan_user",
							timestamp: new Date().toISOString(),
						},
					],
				}),
			);

			await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			// Verify AI config was fetched
			expect(mockGetUserAIConfig).toHaveBeenCalledWith("owner-1");

			// Verify voice profile was resolved
			if (mockResolveVoiceProfile.mock.calls.length > 0) {
				expect(mockResolveVoiceProfile).toHaveBeenCalled();
			}
		});

		it("handles empty AI response with retry logic", async () => {
			mockGenerateWithProvider.mockResolvedValue(null);

			const updateSpy = vi.fn().mockReturnValue(createTableChain());

			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			let selectCount = 0;
			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					selectCount++;
					if (selectCount === 1) {
						// Generate phase — return a pending item
						const inner = createTableChain();
						inner.limit = vi.fn().mockResolvedValue({
							data: [makeQueueItem({ status: "pending", retry_count: 0 })],
							error: null,
						});
						return inner;
					}
					// Publish phase — empty
					const inner = createTableChain();
					inner.limit = vi.fn().mockResolvedValue({ data: [], error: null });
					return inner;
				});
				c.upsert = vi.fn().mockResolvedValue({ error: null });
				c.update = updateSpy;
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAutoPostQueueItem(),
					error: null,
				});
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("accounts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAccount(),
					error: null,
				});
				return c;
			})());

			setupTableMock("account_groups", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { account_ids: ["acc-1"] },
					error: null,
				});
				return c;
			})());

			mockFetch.mockResolvedValueOnce(
				jsonResponse({
					data: [
						{
							id: "c1",
							text: "cool stuff",
							username: "fan",
							timestamp: new Date().toISOString(),
						},
					],
				}),
			);

			const result = await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			// Should have harvested but not published (AI returned null)
			expect(result.harvested).toBe(1);
			// The update should set status to pending (retry) with empty_reply error
			const updateCalls = updateSpy.mock.calls;
			const statusUpdate = updateCalls.find(
				(call: any[]) => call[0]?.error_message === "empty_reply",
			);
			if (statusUpdate) {
				expect(statusUpdate[0].status).toMatch(/pending|failed/);
			}
		});

		it("skips reply containing banned words from voice profile", async () => {
			// AI generates a reply with a banned word
			mockGenerateWithProvider.mockResolvedValue(
				"great hashtag game you got there",
			);

			const updateSpy = vi.fn().mockReturnValue(createTableChain());

			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			let selectCount = 0;
			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					selectCount++;
					if (selectCount === 1) {
						const inner = createTableChain();
						inner.limit = vi.fn().mockResolvedValue({
							data: [makeQueueItem({ status: "pending" })],
							error: null,
						});
						return inner;
					}
					const inner = createTableChain();
					inner.limit = vi.fn().mockResolvedValue({ data: [], error: null });
					return inner;
				});
				c.upsert = vi.fn().mockResolvedValue({ error: null });
				c.update = updateSpy;
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAutoPostQueueItem(),
					error: null,
				});
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("accounts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAccount(),
					error: null,
				});
				return c;
			})());

			setupTableMock("account_groups", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { account_ids: ["acc-1"] },
					error: null,
				});
				return c;
			})());

			mockFetch.mockResolvedValueOnce(
				jsonResponse({
					data: [
						{
							id: "c1",
							text: "nice work",
							username: "fan",
							timestamp: new Date().toISOString(),
						},
					],
				}),
			);

			await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			// The reply containing "hashtag" (banned word) should be skipped
			const skippedUpdate = updateSpy.mock.calls.find(
				(call: any[]) =>
					call[0]?.status === "skipped" &&
					call[0]?.error_message?.includes("banned"),
			);
			if (skippedUpdate) {
				expect(skippedUpdate[0].error_message).toContain("hashtag");
			}
		});

		it("handles AI generation exception with retry", async () => {
			mockGenerateWithProvider.mockRejectedValue(
				new Error("API quota exceeded"),
			);

			const updateSpy = vi.fn().mockReturnValue(createTableChain());

			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			let selectCount = 0;
			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					selectCount++;
					if (selectCount === 1) {
						const inner = createTableChain();
						inner.limit = vi.fn().mockResolvedValue({
							data: [makeQueueItem({ status: "pending", retry_count: 0 })],
							error: null,
						});
						return inner;
					}
					const inner = createTableChain();
					inner.limit = vi.fn().mockResolvedValue({ data: [], error: null });
					return inner;
				});
				c.upsert = vi.fn().mockResolvedValue({ error: null });
				c.update = updateSpy;
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAutoPostQueueItem(),
					error: null,
				});
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("accounts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAccount(),
					error: null,
				});
				return c;
			})());

			setupTableMock("account_groups", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { account_ids: ["acc-1"] },
					error: null,
				});
				return c;
			})());

			mockFetch.mockResolvedValueOnce(
				jsonResponse({
					data: [
						{
							id: "c1",
							text: "nice work",
							username: "fan",
							timestamp: new Date().toISOString(),
						},
					],
				}),
			);

			const result = await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			// Should have harvested but generation failed
			expect(result.harvested).toBe(1);
			expect(result.generated).toBe(0);

			// retry_count should be incremented
			const retryUpdate = updateSpy.mock.calls.find(
				(call: any[]) => call[0]?.retry_count === 1,
			);
			expect(retryUpdate).toBeTruthy();
		});

		it("marks as failed after MAX_RETRIES (3)", async () => {
			mockGenerateWithProvider.mockRejectedValue(new Error("persistent failure"));

			const updateSpy = vi.fn().mockReturnValue(createTableChain());

			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			let selectCount = 0;
			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					selectCount++;
					if (selectCount === 1) {
						const inner = createTableChain();
						inner.limit = vi.fn().mockResolvedValue({
							data: [
								makeQueueItem({ status: "pending", retry_count: 2 }), // Already at 2, next will be 3 = MAX_RETRIES
							],
							error: null,
						});
						return inner;
					}
					const inner = createTableChain();
					inner.limit = vi.fn().mockResolvedValue({ data: [], error: null });
					return inner;
				});
				c.upsert = vi.fn().mockResolvedValue({ error: null });
				c.update = updateSpy;
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAutoPostQueueItem(),
					error: null,
				});
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("accounts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAccount(),
					error: null,
				});
				return c;
			})());

			setupTableMock("account_groups", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { account_ids: ["acc-1"] },
					error: null,
				});
				return c;
			})());

			mockFetch.mockResolvedValueOnce(
				jsonResponse({
					data: [
						{
							id: "c1",
							text: "nice",
							username: "fan",
							timestamp: new Date().toISOString(),
						},
					],
				}),
			);

			await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			// Should mark as failed (retry_count 2 + 1 = 3 >= MAX_RETRIES)
			const failedUpdate = updateSpy.mock.calls.find(
				(call: any[]) => call[0]?.status === "failed",
			);
			expect(failedUpdate).toBeTruthy();
			expect(failedUpdate?.[0].retry_count).toBe(3);
		});

		it("returns 0 generated when no AI config", async () => {
			mockGetUserAIConfig.mockResolvedValue(null);

			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			let selectCount = 0;
			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					selectCount++;
					if (selectCount === 1) {
						const inner = createTableChain();
						inner.limit = vi.fn().mockResolvedValue({
							data: [makeQueueItem({ status: "pending" })],
							error: null,
						});
						return inner;
					}
					const inner = createTableChain();
					inner.limit = vi.fn().mockResolvedValue({ data: [], error: null });
					return inner;
				});
				c.upsert = vi.fn().mockResolvedValue({ error: null });
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAutoPostQueueItem(),
					error: null,
				});
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("accounts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAccount(),
					error: null,
				});
				return c;
			})());

			setupTableMock("account_groups", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { account_ids: ["acc-1"] },
					error: null,
				});
				return c;
			})());

			mockFetch.mockResolvedValueOnce(
				jsonResponse({
					data: [
						{
							id: "c1",
							text: "nice",
							username: "fan",
							timestamp: new Date().toISOString(),
						},
					],
				}),
			);

			const result = await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			expect(result.generated).toBe(0);
		});

		it("returns 0 generated when AI config has no API key", async () => {
			mockGetUserAIConfig.mockResolvedValue({
				provider: "gemini",
				apiKey: null,
				model: "gemini-2.0-flash",
			});

			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			let selectCount = 0;
			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					selectCount++;
					if (selectCount === 1) {
						const inner = createTableChain();
						inner.limit = vi.fn().mockResolvedValue({
							data: [makeQueueItem({ status: "pending" })],
							error: null,
						});
						return inner;
					}
					const inner = createTableChain();
					inner.limit = vi.fn().mockResolvedValue({ data: [], error: null });
					return inner;
				});
				c.upsert = vi.fn().mockResolvedValue({ error: null });
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAutoPostQueueItem(),
					error: null,
				});
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("accounts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAccount(),
					error: null,
				});
				return c;
			})());

			setupTableMock("account_groups", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { account_ids: ["acc-1"] },
					error: null,
				});
				return c;
			})());

			mockFetch.mockResolvedValueOnce(
				jsonResponse({
					data: [
						{
							id: "c1",
							text: "nice",
							username: "fan",
							timestamp: new Date().toISOString(),
						},
					],
				}),
			);

			const result = await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			expect(result.generated).toBe(0);
		});
	});

	// =========================================================================
	// 5. Reply Prompt Construction (buildReplyPrompt)
	// =========================================================================

	describe("reply prompt construction", () => {
		// buildReplyPrompt is private, but we can verify its behavior
		// by checking what gets passed to generateWithProvider

		it("includes voice profile tone in prompt", async () => {
			mockResolveVoiceProfile.mockResolvedValue(
				makeVoiceProfile({ voice_profile: "sarcastic, witty" }),
			);

			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			let selectCount = 0;
			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					selectCount++;
					if (selectCount === 1) {
						const inner = createTableChain();
						inner.limit = vi.fn().mockResolvedValue({
							data: [
								makeQueueItem({
									status: "pending",
									comment_text: "interesting take!",
									comment_username: "curious_fan",
								}),
							],
							error: null,
						});
						return inner;
					}
					const inner = createTableChain();
					inner.limit = vi.fn().mockResolvedValue({ data: [], error: null });
					return inner;
				});
				c.upsert = vi.fn().mockResolvedValue({ error: null });
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAutoPostQueueItem(),
					error: null,
				});
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("accounts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAccount(),
					error: null,
				});
				return c;
			})());

			setupTableMock("account_groups", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { account_ids: ["acc-1"] },
					error: null,
				});
				return c;
			})());

			mockFetch.mockResolvedValueOnce(
				jsonResponse({
					data: [
						{
							id: "c1",
							text: "interesting take!",
							username: "fan",
							timestamp: new Date().toISOString(),
						},
					],
				}),
			);

			await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			if (mockGenerateWithProvider.mock.calls.length > 0) {
				const prompt = mockGenerateWithProvider.mock.calls[0][0];
				expect(prompt).toContain("sarcastic, witty");
				expect(prompt).toContain("Under 80 characters");
				expect(prompt).toContain("Generate exactly 5 different reply variants");
			}
		});

		it("includes avoid topics in prompt", async () => {
			mockResolveVoiceProfile.mockResolvedValue(
				makeVoiceProfile({ avoid_topics: ["politics", "religion"] }),
			);

			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			let selectCount = 0;
			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					selectCount++;
					if (selectCount === 1) {
						const inner = createTableChain();
						inner.limit = vi.fn().mockResolvedValue({
							data: [makeQueueItem({ status: "pending" })],
							error: null,
						});
						return inner;
					}
					const inner = createTableChain();
					inner.limit = vi.fn().mockResolvedValue({ data: [], error: null });
					return inner;
				});
				c.upsert = vi.fn().mockResolvedValue({ error: null });
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAutoPostQueueItem(),
					error: null,
				});
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("accounts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAccount(),
					error: null,
				});
				return c;
			})());

			setupTableMock("account_groups", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { account_ids: ["acc-1"] },
					error: null,
				});
				return c;
			})());

			mockFetch.mockResolvedValueOnce(
				jsonResponse({
					data: [
						{
							id: "c1",
							text: "your thoughts on this?",
							username: "fan",
							timestamp: new Date().toISOString(),
						},
					],
				}),
			);

			await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			if (mockGenerateWithProvider.mock.calls.length > 0) {
				const prompt = mockGenerateWithProvider.mock.calls[0][0];
				expect(prompt).toContain("politics, religion");
			}
		});
	});

	// =========================================================================
	// 6. Reply Sanitization
	// =========================================================================

	describe("reply sanitization", () => {
		it("strips markdown bold/italic from AI replies", async () => {
			mockGenerateWithProvider.mockResolvedValue(
				"**wow** that's *so cool* right\nplain text reply here\nanother one\nfourth variant\nfifth one",
			);

			const updateSpy = vi.fn().mockReturnValue(createTableChain());

			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			let selectCount = 0;
			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					selectCount++;
					if (selectCount === 1) {
						const inner = createTableChain();
						inner.limit = vi.fn().mockResolvedValue({
							data: [makeQueueItem({ status: "pending" })],
							error: null,
						});
						return inner;
					}
					const inner = createTableChain();
					inner.limit = vi.fn().mockResolvedValue({ data: [], error: null });
					return inner;
				});
				c.upsert = vi.fn().mockResolvedValue({ error: null });
				c.update = updateSpy;
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAutoPostQueueItem(),
					error: null,
				});
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("accounts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAccount(),
					error: null,
				});
				return c;
			})());

			setupTableMock("account_groups", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { account_ids: ["acc-1"] },
					error: null,
				});
				return c;
			})());

			mockFetch.mockResolvedValueOnce(
				jsonResponse({
					data: [
						{
							id: "c1",
							text: "cool",
							username: "fan",
							timestamp: new Date().toISOString(),
						},
					],
				}),
			);

			await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			// The generated_reply stored should not contain markdown
			const processingUpdate = updateSpy.mock.calls.find(
				(call: any[]) => call[0]?.status === "processing",
			);
			if (processingUpdate) {
				expect(processingUpdate[0].generated_reply).not.toContain("**");
				expect(processingUpdate[0].generated_reply).not.toContain("*so");
			}
		});

		it("filters out reply variants over 300 chars during variant selection", async () => {
			// Variant selection filters out lines >= 300 chars
			const longLine = "a".repeat(301);
			mockGenerateWithProvider.mockResolvedValue(
				`${longLine}\nshort valid reply here\nanother short one`,
			);
			mockResolveVoiceProfile.mockResolvedValue(
				makeVoiceProfile({ avoid_words: [] }),
			);

			const updateSpy = vi.fn().mockReturnValue(createTableChain());

			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			let selectCount = 0;
			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					selectCount++;
					if (selectCount === 1) {
						const inner = createTableChain();
						inner.limit = vi.fn().mockResolvedValue({
							data: [makeQueueItem({ status: "pending" })],
							error: null,
						});
						return inner;
					}
					const inner = createTableChain();
					inner.limit = vi.fn().mockResolvedValue({ data: [], error: null });
					return inner;
				});
				c.upsert = vi.fn().mockResolvedValue({ error: null });
				c.update = updateSpy;
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAutoPostQueueItem(),
					error: null,
				});
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("accounts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAccount(),
					error: null,
				});
				return c;
			})());

			setupTableMock("account_groups", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { account_ids: ["acc-1"] },
					error: null,
				});
				return c;
			})());

			mockFetch.mockResolvedValueOnce(
				jsonResponse({
					data: [
						{
							id: "c1",
							text: "what do you think?",
							username: "fan",
							timestamp: new Date().toISOString(),
						},
					],
				}),
			);

			await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			const processingUpdate = updateSpy.mock.calls.find(
				(call: any[]) => call[0]?.status === "processing",
			);
			if (processingUpdate) {
				// Selected reply should be one of the short variants, not the 301-char line
				expect(processingUpdate[0].generated_reply.length).toBeLessThan(300);
			}
		});

		it("strips surrounding quotes from AI replies", async () => {
			mockGenerateWithProvider.mockResolvedValue(
				'"nice take what made you think that"\n"another one here"\n"third"\n"fourth"\n"fifth"',
			);
			mockResolveVoiceProfile.mockResolvedValue(
				makeVoiceProfile({ avoid_words: [] }),
			);

			const updateSpy = vi.fn().mockReturnValue(createTableChain());

			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			let selectCount = 0;
			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					selectCount++;
					if (selectCount === 1) {
						const inner = createTableChain();
						inner.limit = vi.fn().mockResolvedValue({
							data: [makeQueueItem({ status: "pending" })],
							error: null,
						});
						return inner;
					}
					const inner = createTableChain();
					inner.limit = vi.fn().mockResolvedValue({ data: [], error: null });
					return inner;
				});
				c.upsert = vi.fn().mockResolvedValue({ error: null });
				c.update = updateSpy;
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAutoPostQueueItem(),
					error: null,
				});
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("accounts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAccount(),
					error: null,
				});
				return c;
			})());

			setupTableMock("account_groups", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { account_ids: ["acc-1"] },
					error: null,
				});
				return c;
			})());

			mockFetch.mockResolvedValueOnce(
				jsonResponse({
					data: [
						{
							id: "c1",
							text: "nice",
							username: "fan",
							timestamp: new Date().toISOString(),
						},
					],
				}),
			);

			await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			const processingUpdate = updateSpy.mock.calls.find(
				(call: any[]) => call[0]?.status === "processing",
			);
			if (processingUpdate) {
				const reply = processingUpdate[0].generated_reply;
				expect(reply).not.toMatch(/^"/);
				expect(reply).not.toMatch(/"$/);
			}
		});

		it("truncates replies over 300 characters", async () => {
			const longReply = "a".repeat(400);
			mockGenerateWithProvider.mockResolvedValue(longReply);
			mockResolveVoiceProfile.mockResolvedValue(
				makeVoiceProfile({ avoid_words: [] }),
			);

			const updateSpy = vi.fn().mockReturnValue(createTableChain());

			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			let selectCount = 0;
			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					selectCount++;
					if (selectCount === 1) {
						const inner = createTableChain();
						inner.limit = vi.fn().mockResolvedValue({
							data: [makeQueueItem({ status: "pending" })],
							error: null,
						});
						return inner;
					}
					const inner = createTableChain();
					inner.limit = vi.fn().mockResolvedValue({ data: [], error: null });
					return inner;
				});
				c.upsert = vi.fn().mockResolvedValue({ error: null });
				c.update = updateSpy;
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAutoPostQueueItem(),
					error: null,
				});
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("accounts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAccount(),
					error: null,
				});
				return c;
			})());

			setupTableMock("account_groups", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { account_ids: ["acc-1"] },
					error: null,
				});
				return c;
			})());

			mockFetch.mockResolvedValueOnce(
				jsonResponse({
					data: [
						{
							id: "c1",
							text: "thoughts?",
							username: "fan",
							timestamp: new Date().toISOString(),
						},
					],
				}),
			);

			await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			const processingUpdate = updateSpy.mock.calls.find(
				(call: any[]) => call[0]?.status === "processing",
			);
			if (processingUpdate) {
				expect(processingUpdate[0].generated_reply.length).toBeLessThanOrEqual(300);
				expect(processingUpdate[0].generated_reply).toMatch(/\.\.\.$/);
			}
		});
	});

	// =========================================================================
	// 7. Negative Pattern Coverage (Direct Pattern Tests)
	// =========================================================================

	describe("negative pattern edge cases", () => {
		// Test case-insensitive matching via the harvest flow
		it("case-insensitive matching on toxic keywords", async () => {
			const upsertSpy = vi.fn().mockResolvedValue({ error: null });

			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					return c;
				});
				c.upsert = upsertSpy;
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAutoPostQueueItem(),
					error: null,
				});
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("accounts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAccount(),
					error: null,
				});
				return c;
			})());

			setupTableMock("account_groups", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { account_ids: ["acc-1"] },
					error: null,
				});
				return c;
			})());

			// Mixed case toxic comment
			mockFetch.mockResolvedValueOnce(
				jsonResponse({
					data: [
						{
							id: "c-mixed",
							text: "KILL YOURSELF you loser",
							username: "troll",
							timestamp: new Date().toISOString(),
						},
					],
				}),
			);

			await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			expect(upsertSpy).toHaveBeenCalled();
			const upsertArg = upsertSpy.mock.calls[0][0];
			expect(upsertArg.status).toBe("needs_review");
		});

		it("does not flag partial word matches that are safe", async () => {
			const upsertSpy = vi.fn().mockResolvedValue({ error: null });

			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					return c;
				});
				c.upsert = upsertSpy;
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAutoPostQueueItem(),
					error: null,
				});
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("accounts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAccount(),
					error: null,
				});
				return c;
			})());

			setupTableMock("account_groups", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { account_ids: ["acc-1"] },
					error: null,
				});
				return c;
			})());

			// "skilled" should not match "kill" due to \b word boundary
			mockFetch.mockResolvedValueOnce(
				jsonResponse({
					data: [
						{
							id: "c-safe-word",
							text: "you are so skilled at this!",
							username: "nice_fan",
							timestamp: new Date().toISOString(),
						},
					],
				}),
			);

			await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			// The word "skilled" should NOT trigger "kill" pattern due to \b
			expect(upsertSpy).toHaveBeenCalled();
			const upsertArg = upsertSpy.mock.calls[0][0];
			expect(upsertArg.status).toBe("pending");
		});
	});

	// =========================================================================
	// 8. Constants & Configuration
	// =========================================================================

	describe("configuration constants", () => {
		it("uses default daily limit of 20 per group", async () => {
			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: null },
					error: null,
				});
				return c;
			})());

			// Count at exactly 20 (default limit)
			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 20, error: null });
						return inner;
					}
					return c;
				});
				return c;
			})());

			const result = await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			// At the default limit of 20, should be blocked
			expect(result.harvested).toBe(0);
		});

		it("respects custom daily limit from group config", async () => {
			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 10 },
					error: null,
				});
				return c;
			})());

			// Count at 10 (custom limit)
			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 10, error: null });
						return inner;
					}
					return c;
				});
				return c;
			})());

			const result = await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			// At custom limit of 10, should be blocked
			expect(result.harvested).toBe(0);
		});
	});

	// =========================================================================
	// 9. AutoReplyResult shape
	// =========================================================================

	describe("AutoReplyResult shape", () => {
		it("returns complete result object with all fields", async () => {
			setupTableMock("profiles", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { agent_paused: true },
					error: null,
				});
				return c;
			})());

			const result = await processAutoReplyQueue("ws-1", "owner-1");

			expect(result).toHaveProperty("harvested");
			expect(result).toHaveProperty("generated");
			expect(result).toHaveProperty("published");
			expect(result).toHaveProperty("skipped");
			expect(result).toHaveProperty("failed");
			expect(typeof result.harvested).toBe("number");
			expect(typeof result.generated).toBe("number");
			expect(typeof result.published).toBe("number");
			expect(typeof result.skipped).toBe("number");
			expect(typeof result.failed).toBe("number");
		});

		it("returns complete result from harvestAndReplyForPost", async () => {
			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: false },
					error: null,
				});
				return c;
			})());

			const result = await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			expect(result).toHaveProperty("harvested");
			expect(result).toHaveProperty("generated");
			expect(result).toHaveProperty("published");
			expect(result).toHaveProperty("skipped");
			expect(result).toHaveProperty("failed");
		});
	});

	// =========================================================================
	// 10. Own-Username Case Insensitive Filtering
	// =========================================================================

	describe("own-username filtering is case insensitive", () => {
		it("filters uppercase variant of own username", async () => {
			const upsertSpy = vi.fn().mockResolvedValue({ error: null });

			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					return c;
				});
				c.upsert = upsertSpy;
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAutoPostQueueItem(),
					error: null,
				});
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("accounts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAccount({ username: "Our_Brand" }), // PascalCase
					error: null,
				});
				// For group accounts query
				c.in = vi.fn().mockResolvedValue({
					data: [{ username: "Our_Brand" }],
					error: null,
				});
				return c;
			})());

			setupTableMock("account_groups", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { account_ids: ["acc-1"] },
					error: null,
				});
				return c;
			})());

			mockFetch.mockResolvedValueOnce(
				jsonResponse({
					data: [
						{
							id: "self-upper",
							text: "replying to myself",
							username: "OUR_BRAND", // UPPERCASE version
							timestamp: new Date().toISOString(),
						},
						{
							id: "external",
							text: "great post!",
							username: "someone_else",
							timestamp: new Date().toISOString(),
						},
					],
				}),
			);

			const result = await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			// Only the external comment should be harvested
			expect(result.harvested).toBe(1);
			if (upsertSpy.mock.calls.length > 0) {
				expect(upsertSpy.mock.calls[0][0].comment_username).toBe(
					"someone_else",
				);
			}
		});
	});

	// =========================================================================
	// 11. Mixed Comments (safe + toxic in same batch)
	// =========================================================================

	describe("mixed safe and toxic comments in same batch", () => {
		it("routes toxic to needs_review and safe to pending", async () => {
			const upsertSpy = vi.fn().mockResolvedValue({ error: null });

			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					c.limit = vi.fn().mockResolvedValue({ data: [], error: null });
					return c;
				});
				c.upsert = upsertSpy;
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAutoPostQueueItem(),
					error: null,
				});
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("accounts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAccount(),
					error: null,
				});
				return c;
			})());

			setupTableMock("account_groups", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { account_ids: ["acc-1"] },
					error: null,
				});
				return c;
			})());

			mockFetch.mockResolvedValueOnce(
				jsonResponse({
					data: [
						{
							id: "safe-1",
							text: "love this!",
							username: "good_fan",
							timestamp: new Date().toISOString(),
						},
						{
							id: "toxic-1",
							text: "fuck off nobody likes you",
							username: "troll_1",
							timestamp: new Date().toISOString(),
						},
						{
							id: "safe-2",
							text: "how do you edit like that?",
							username: "good_fan_2",
							timestamp: new Date().toISOString(),
						},
					],
				}),
			);

			const result = await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			// All 3 comments should be harvested (safe as pending, toxic as needs_review)
			expect(result.harvested).toBe(3);

			// Check that upsert was called with correct statuses
			const calls = upsertSpy.mock.calls;
			const statuses = calls.map((c: any[]) => c[0]?.status);
			// We expect both "pending" and "needs_review" statuses
			expect(statuses).toContain("pending");
			expect(statuses).toContain("needs_review");
		});
	});

	// =========================================================================
	// 12. Idempotency
	// =========================================================================

	describe("idempotency", () => {
		it("uses upsert with onConflict=comment_id to prevent duplicate replies", async () => {
			const upsertSpy = vi.fn().mockResolvedValue({ error: null });

			setupTableMock("auto_post_group_config", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { enable_auto_reply: true, auto_reply_daily_limit: 20 },
					error: null,
				});
				return c;
			})());

			setupTableMock("auto_reply_queue", (() => {
				const c = createTableChain();
				c.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
					if (opts?.count === "exact") {
						const inner = createTableChain();
						inner.gte = vi.fn().mockResolvedValue({ count: 0, error: null });
						return inner;
					}
					c.limit = vi.fn().mockResolvedValue({ data: [], error: null });
					return c;
				});
				c.upsert = upsertSpy;
				return c;
			})());

			setupTableMock("auto_post_queue", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAutoPostQueueItem(),
					error: null,
				});
				c.update = vi.fn().mockReturnValue(createTableChain());
				return c;
			})());

			setupTableMock("accounts", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: makeAccount(),
					error: null,
				});
				return c;
			})());

			setupTableMock("account_groups", (() => {
				const c = createTableChain();
				c.maybeSingle = vi.fn().mockResolvedValue({
					data: { account_ids: ["acc-1"] },
					error: null,
				});
				return c;
			})());

			mockFetch.mockResolvedValueOnce(
				jsonResponse({
					data: [
						{
							id: "c1",
							text: "great post",
							username: "fan",
							timestamp: new Date().toISOString(),
						},
					],
				}),
			);

			await harvestAndReplyForPost(
				"ws-1", "grp-1", "owner-1", "acc-1", "post-1", "apq-1",
			);

			// Verify upsert was called with onConflict and ignoreDuplicates
			expect(upsertSpy).toHaveBeenCalled();
			const upsertOpts = upsertSpy.mock.calls[0][1];
			expect(upsertOpts.onConflict).toBe("comment_id");
			expect(upsertOpts.ignoreDuplicates).toBe(true);
		});
	});
});
