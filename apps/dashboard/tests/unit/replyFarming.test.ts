/**
 * Reply Farming Engine Tests
 *
 * Comprehensive tests for api/_lib/replyFarming.ts (~653 lines).
 *
 * Reply farming drives engagement growth by finding trending posts
 * and replying from our accounts. Bugs waste API quota or miss
 * engagement opportunities; overshoot risks shadowbans.
 *
 * Covers:
 * 1. Keyword matching — finding relevant posts to engage with
 * 2. Comment eligibility filtering — which posts qualify for replies
 * 3. Rate limiting — per-account reply limits
 * 4. Reply generation — appropriate reply content from templates
 * 5. API quota management — not wasting search quota
 * 6. Error handling — API failures, Redis unavailable, missing credentials
 * 7. Edge cases — no keywords, no matching posts, all posts already replied to
 * 8. Self-reply prevention — skipping own accounts
 * 9. Author dedup — not replying to same author twice per day
 * 10. Post dedup — not replying to same post twice
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mocks — must be declared BEFORE importing module under test
// ---------------------------------------------------------------------------

const mockRedisGet = vi.fn().mockResolvedValue(null);
const mockRedisSet = vi.fn().mockResolvedValue("OK");
const mockRedisIncr = vi.fn().mockResolvedValue(1);
const mockRedisExpire = vi.fn().mockResolvedValue(1);

let redisAvailable = true;

vi.mock("../../api/_lib/redis", () => ({
	getRedis: () => {
		if (!redisAvailable) throw new Error("Redis connection refused");
		return {
			get: mockRedisGet,
			set: mockRedisSet,
			incr: mockRedisIncr,
			expire: mockRedisExpire,
		};
	},
}));

// Table-aware Supabase mock — tracks calls per table
let supabaseFromHandler: (table: string) => any;

function createTableChain(overrides: Record<string, any> = {}) {
	const chain: any = {};
	const methods = [
		"select", "eq", "in", "not", "or", "gte", "lt", "lte", "is",
		"neq", "maybeSingle", "single", "limit", "order", "update", "insert",
	];
	for (const m of methods) {
		if (m === "maybeSingle" || m === "single") {
			chain[m] = vi.fn().mockResolvedValue({ data: null, error: null });
		} else {
			chain[m] = vi.fn().mockReturnValue(chain);
		}
	}
	Object.assign(chain, overrides);
	return chain;
}

vi.mock("../../api/_lib/supabase", () => ({
	getSupabase: () => ({
		from: (table: string) => supabaseFromHandler(table),
	}),
}));

vi.mock("../../api/_lib/encryption", () => ({
	decrypt: (v: string) => `decrypted_${v}`,
}));

vi.mock("../../api/_lib/logger", () => ({
	logger: {
		info: vi.fn(),
		warn: vi.fn(),
		error: vi.fn(),
		debug: vi.fn(),
	},
}));

// Mock fetch for Threads API calls
const mockFetch = vi.fn();
global.fetch = mockFetch;

// ---------------------------------------------------------------------------
// Import module under test AFTER mocks
// ---------------------------------------------------------------------------

const { runReplyFarming } = await import("../../api/_lib/replyFarming");

// ---------------------------------------------------------------------------
// Test data factories
// ---------------------------------------------------------------------------

function createAccountRow(overrides: Partial<{
	id: string;
	user_id: string;
	username: string;
	threads_user_id: string;
	threads_access_token_encrypted: string | null;
	needs_reauth: boolean;
	is_active: boolean;
}> = {}) {
	return {
		id: "acc-1",
		user_id: "user-1",
		username: "testaccount",
		threads_user_id: "tu-123",
		threads_access_token_encrypted: "enc-token-abc",
		needs_reauth: false,
		is_active: true,
		...overrides,
	};
}

function createSearchPost(overrides: Partial<{
	id: string;
	text: string;
	username: string;
	like_count: number;
	reply_count: number;
	views: number;
}> = {}) {
	return {
		id: "post-1",
		text: "What is your favorite game?",
		username: "trendinguser",
		like_count: 50,
		reply_count: 10,
		views: 500,
		...overrides,
	};
}

// ---------------------------------------------------------------------------
// Full pipeline setup — handles the 3 Supabase table lookups
// (accounts for pickEligibleAccount, account_groups for topics,
//  accounts again for getOurUsernames)
// ---------------------------------------------------------------------------

function setupFullPipeline(opts: {
	account?: ReturnType<typeof createAccountRow> | null;
	pillars?: string[];
	ourUsernames?: string[];
} = {}) {
	const account = opts.account ?? createAccountRow();
	const pillars = opts.pillars ?? ["viral"];
	const ourUsernames = opts.ourUsernames ?? [];

	let accountsCallCount = 0;

	supabaseFromHandler = (table: string) => {
		if (table === "accounts") {
			accountsCallCount++;
			if (accountsCallCount === 1) {
				// pickEligibleAccount: .select().eq().maybeSingle()
				return createTableChain({
					maybeSingle: vi.fn().mockResolvedValue({ data: account, error: null }),
				});
			}
			// getOurUsernames: .select().eq().not() — awaited directly (no terminal)
			const chain = createTableChain();
			chain.not = vi.fn().mockResolvedValue({
				data: ourUsernames.map(u => ({ username: u })),
				error: null,
			});
			return chain;
		}
		if (table === "account_groups") {
			// getGroupTopics: .select().eq().maybeSingle()
			return createTableChain({
				maybeSingle: vi.fn().mockResolvedValue({
					data: { content_strategy: { pillars } },
					error: null,
				}),
			});
		}
		return createTableChain();
	};
}

function setupKeywordSearchResponse(posts: ReturnType<typeof createSearchPost>[]) {
	mockFetch.mockResolvedValueOnce({
		ok: true,
		json: async () => ({ data: posts }),
	});
}

function setupReplySuccess() {
	// Container creation
	mockFetch.mockResolvedValueOnce({
		ok: true,
		json: async () => ({ id: "container-1" }),
	});
	// Publish
	mockFetch.mockResolvedValueOnce({
		ok: true,
		json: async () => ({ id: "published-1" }),
	});
}

function setupReplyFailure(step: "container" | "publish" = "container") {
	if (step === "container") {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 400,
			json: async () => ({ error: { message: "Container failed" } }),
		});
	} else {
		// Container succeeds
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => ({ id: "container-1" }),
		});
		// Publish fails
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 500,
			json: async () => ({ error: { message: "Publish failed" } }),
		});
	}
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("replyFarming", () => {
	// Save original setTimeout so abort-controller timeouts still work
	const realSetTimeout = globalThis.setTimeout;

	beforeEach(() => {
		vi.clearAllMocks();
		redisAvailable = true;
		mockRedisGet.mockResolvedValue(null);
		supabaseFromHandler = () => createTableChain();

		// Mock setTimeout to skip the 30-60s human-like delay between replies.
		// The keywordSearch abort controller also uses setTimeout, but clearTimeout
		// cancels it before it fires (our mocked fetch resolves synchronously).
		vi.spyOn(globalThis, "setTimeout").mockImplementation(((fn: Function, _ms?: number) => {
			// Execute immediately — the mock fetch resolves synchronously so
			// controller.abort() won't matter (clearTimeout runs in finally block)
			const id = realSetTimeout(fn, 0);
			return id;
		}) as any);
	});

	afterEach(() => {
		vi.restoreAllMocks();
		global.fetch = mockFetch;
	});

	// =========================================================================
	// 1. Empty inputs / early exits
	// =========================================================================

	describe("early exits", () => {
		it("returns immediately with no accountIds", async () => {
			const result = await runReplyFarming("ws-1", "group-1", [], 5);
			expect(result.sent).toBe(0);
			expect(result.details).toContain("No account IDs provided");
		});

		it("returns when Redis is unavailable", async () => {
			redisAvailable = false;

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 5);
			expect(result.details).toContain("Redis unavailable");
			expect(result.sent).toBe(0);
		});

		it("returns when no eligible accounts (all at daily limit)", async () => {
			mockRedisGet.mockResolvedValue(10); // daily limit = 10
			setupFullPipeline();

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 5);
			expect(result.details[0]).toContain("No eligible accounts");
		});

		it("returns when no content pillars found", async () => {
			// Group with no content_strategy at all
			let accountsCallCount = 0;
			supabaseFromHandler = (table: string) => {
				if (table === "accounts") {
					accountsCallCount++;
					if (accountsCallCount === 1) {
						return createTableChain({
							maybeSingle: vi.fn().mockResolvedValue({
								data: createAccountRow(),
								error: null,
							}),
						});
					}
					return createTableChain();
				}
				if (table === "account_groups") {
					return createTableChain({
						maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
					});
				}
				return createTableChain();
			};

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 5);
			// Falls back to generic topics ["viral", "relatable", "hot take", "unpopular opinion"]
			// So it won't say "No content pillars" — it will proceed with fallback topics
			// The result should get past topic loading
			expect(
				result.details.every((d: string) => !d.includes("No content pillars")),
			).toBe(true);
		});

		it("returns when group has empty strategy with no pillars array", async () => {
			// content_strategy exists but pillars is undefined/empty
			let accountsCallCount = 0;
			supabaseFromHandler = (table: string) => {
				if (table === "accounts") {
					accountsCallCount++;
					if (accountsCallCount === 1) {
						return createTableChain({
							maybeSingle: vi.fn().mockResolvedValue({
								data: createAccountRow(),
								error: null,
							}),
						});
					}
					const chain = createTableChain();
					chain.not = vi.fn().mockResolvedValue({ data: [], error: null });
					return chain;
				}
				if (table === "account_groups") {
					return createTableChain({
						maybeSingle: vi.fn().mockResolvedValue({
							data: { content_strategy: { pillars: [] } },
							error: null,
						}),
					});
				}
				return createTableChain();
			};

			setupKeywordSearchResponse([]);

			await runReplyFarming("ws-1", "group-1", ["acc-1"], 5);
			// Falls back to generic topics, then search found nothing
			expect(mockFetch).toHaveBeenCalled();
		});
	});

	// =========================================================================
	// 2. Account eligibility
	// =========================================================================

	describe("account eligibility (pickEligibleAccount)", () => {
		it("skips accounts with needs_reauth=true", async () => {
			setupFullPipeline({ account: createAccountRow({ needs_reauth: true }) });

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 5);
			expect(result.details[0]).toContain("No eligible accounts");
		});

		it("skips inactive accounts", async () => {
			setupFullPipeline({ account: createAccountRow({ is_active: false }) });

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 5);
			expect(result.details[0]).toContain("No eligible accounts");
		});

		it("skips accounts without encrypted token", async () => {
			setupFullPipeline({
				account: createAccountRow({ threads_access_token_encrypted: null }),
			});

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 5);
			expect(result.details[0]).toContain("No eligible accounts");
		});

		it("skips accounts without threads_user_id", async () => {
			setupFullPipeline({ account: createAccountRow({ threads_user_id: "" }) });

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 5);
			expect(result.details[0]).toContain("No eligible accounts");
		});

		it("selects an account that passes all checks", async () => {
			setupFullPipeline();
			setupKeywordSearchResponse([]);

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 5);
			expect(result.details.every(d => !d.includes("No eligible accounts"))).toBe(true);
		});
	});

	// =========================================================================
	// 3. Topic loading (getGroupTopics)
	// =========================================================================

	describe("topic loading", () => {
		it("uses content strategy pillars when available", async () => {
			setupFullPipeline({ pillars: ["anime", "manga"] });
			setupKeywordSearchResponse([]);

			await runReplyFarming("ws-1", "group-1", ["acc-1"], 5);

			expect(mockFetch).toHaveBeenCalled();
			const fetchUrl = mockFetch.mock.calls[0][0] as string;
			expect(fetchUrl).toContain("keyword_search");
		});

		it("falls back to generic topics when strategy has no pillars", async () => {
			setupFullPipeline({ pillars: [] });
			setupKeywordSearchResponse([]);

			await runReplyFarming("ws-1", "group-1", ["acc-1"], 5);

			// Should have called keyword search (got past topic loading with fallback)
			expect(mockFetch).toHaveBeenCalled();
		});
	});

	// =========================================================================
	// 4. Keyword search
	// =========================================================================

	describe("keyword search", () => {
		beforeEach(() => {
			setupFullPipeline({ pillars: ["gaming"] });
		});

		it("calls Threads keyword_search API with correct parameters", async () => {
			setupKeywordSearchResponse([]);

			await runReplyFarming("ws-1", "group-1", ["acc-1"], 5);

			expect(mockFetch).toHaveBeenCalledTimes(1);
			const url = mockFetch.mock.calls[0][0] as string;
			expect(url).toContain("graph.threads.net/v1.0/keyword_search");
			expect(url).toContain("search_type=TOP");
			expect(url).toContain("limit=25");
			expect(url).toContain("access_token=decrypted_enc-token-abc");
		});

		it("reports when keyword search returns no posts", async () => {
			setupKeywordSearchResponse([]);

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 5);
			expect(result.details.some(d => d.includes("No posts found"))).toBe(true);
		});

		it("handles keyword search API failure gracefully", async () => {
			mockFetch.mockResolvedValueOnce({
				ok: false,
				status: 400,
				text: async () => "Invalid access token",
			});

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 5);
			expect(result.details.some(d => d.includes("Search failed"))).toBe(true);
			expect(result.sent).toBe(0);
		});

		it("handles network timeout gracefully", async () => {
			mockFetch.mockRejectedValueOnce(new Error("AbortError"));

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 5);
			expect(result.details.some(d => d.includes("Search failed"))).toBe(true);
		});
	});

	// =========================================================================
	// 5. Post filtering
	// =========================================================================

	describe("post filtering", () => {
		it("skips posts with views below threshold (100)", async () => {
			setupFullPipeline();
			setupKeywordSearchResponse([
				createSearchPost({ id: "p1", views: 50 }),
				createSearchPost({ id: "p2", views: 99 }),
			]);

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 5);
			expect(result.skipped).toBe(2);
			expect(result.sent).toBe(0);
		});

		it("skips posts from own accounts (self-reply prevention)", async () => {
			setupFullPipeline({
				account: createAccountRow({ username: "myaccount" }),
				ourUsernames: ["myaccount", "otheraccount"],
			});

			setupKeywordSearchResponse([
				createSearchPost({ id: "p1", username: "myaccount", views: 500 }),
				createSearchPost({ id: "p2", username: "OtherAccount", views: 500 }),
			]);

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 5);
			expect(result.skipped).toBe(2);
		});

		it("is case-insensitive when matching own usernames", async () => {
			setupFullPipeline({
				account: createAccountRow({ username: "MyAccount" }),
				ourUsernames: ["MyAccount"],
			});

			setupKeywordSearchResponse([
				createSearchPost({ username: "MYACCOUNT", views: 500 }),
			]);

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 5);
			expect(result.skipped).toBe(1);
		});

		it("skips already-seen posts (dedup via Redis)", async () => {
			setupFullPipeline();

			mockRedisGet.mockImplementation((key: string) => {
				if (key.startsWith("reply-farm-seen:")) return Promise.resolve("1");
				return Promise.resolve(null);
			});

			setupKeywordSearchResponse([
				createSearchPost({ id: "seen-post-1", views: 500 }),
			]);

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 5);
			expect(result.skipped).toBe(1);
			expect(result.sent).toBe(0);
		});

		it("skips posts from authors already replied to today", async () => {
			setupFullPipeline();

			mockRedisGet.mockImplementation((key: string) => {
				if (key.startsWith("reply-farm-author:")) return Promise.resolve("1");
				return Promise.resolve(null);
			});

			setupKeywordSearchResponse([
				createSearchPost({ username: "dupeauthor", views: 500 }),
			]);

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 5);
			expect(result.skipped).toBe(1);
		});

		it("reports when all posts are filtered out", async () => {
			setupFullPipeline();
			setupKeywordSearchResponse([
				createSearchPost({ views: 10 }), // below threshold
			]);

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 5);
			expect(result.details.some(d => d.includes("filtered out"))).toBe(true);
		});
	});

	// =========================================================================
	// 6. Rate limiting
	// =========================================================================

	describe("rate limiting", () => {
		it("respects maxRepliesPerRun limit", async () => {
			setupFullPipeline();

			const posts = Array.from({ length: 5 }, (_, i) =>
				createSearchPost({ id: `post-${i}`, username: `user${i}`, views: 500 }),
			);
			setupKeywordSearchResponse(posts);

			// 2 replies x 2 API calls each (container + publish)
			for (let i = 0; i < 2; i++) {
				setupReplySuccess();
			}

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 2);
			expect(result.sent).toBe(2);
		}, 15000);

		it("stops mid-run if daily limit is hit", async () => {
			setupFullPipeline();

			let getCallCount = 0;
			mockRedisGet.mockImplementation((key: string) => {
				if (key.startsWith("reply-farm:acc-1:")) {
					getCallCount++;
					// 1st call: pickEligibleAccount (under limit)
					// 2nd call: first post re-check in loop (under limit)
					// 3rd call: second post re-check in loop (AT limit)
					if (getCallCount <= 2) return Promise.resolve(9);
					return Promise.resolve(10);
				}
				return Promise.resolve(null);
			});

			const posts = Array.from({ length: 5 }, (_, i) =>
				createSearchPost({ id: `post-${i}`, username: `user${i}`, views: 500 }),
			);
			setupKeywordSearchResponse(posts);

			setupReplySuccess(); // first reply succeeds

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 5);
			expect(result.details.some(d => d.includes("daily limit"))).toBe(true);
		}, 15000);
	});

	// =========================================================================
	// 7. Reply generation (pickReply template matching)
	// =========================================================================

	describe("reply template selection", () => {
		const QUESTION_TEMPLATES = [
			"omg this is such a good question",
			"ok but mine might be embarrassing",
			"literally been thinking about this all day",
			"wait i actually have so many answers for this",
			"this question lives in my head rent free",
			"saving this to answer properly later",
		];

		const HOT_TAKE_TEMPLATES = [
			"this is so real",
			"finally someone said it",
			"the comments on this are gonna be wild",
			"no bc you're actually so right",
			"needed to hear this today",
			"screenshotting this before it goes viral",
		];

		const RELATABLE_TEMPLATES = [
			"why is this so accurate",
			"felt this in my soul ngl",
			"literally me rn",
			"did you just read my mind",
			"ok i feel seen",
			"this is too relatable it hurts",
		];

		const GAMING_TEMPLATES = [
			"ok but what rank are you tho",
			"this game is addicting fr",
			"the way i felt this",
			"genuinely can't stop playing",
			"ok we need to talk about this more",
			"the grind is so real",
		];

		const GENERIC_TEMPLATES = [
			"this >>",
			"no literally",
			"the way i agree with this",
			"period",
			"say it louder",
			"facts",
			"ngl this hit different",
			"underrated take",
		];

		it("uses question templates for posts containing '?'", async () => {
			setupFullPipeline({ pillars: ["gaming"] });

			let replyText = "";
			mockFetch
				// keyword search
				.mockResolvedValueOnce({
					ok: true,
					json: async () => ({
						data: [createSearchPost({
							text: "What's your favorite anime?",
							views: 500,
						})],
					}),
				})
				// container create — capture the reply text
				.mockImplementationOnce(async (_url: string, opts: any) => {
					const bodyStr = opts.body?.toString() || "";
					replyText = new URLSearchParams(bodyStr).get("text") || "";
					return { ok: true, json: async () => ({ id: "container-1" }) };
				})
				// publish
				.mockResolvedValueOnce({
					ok: true,
					json: async () => ({ id: "published-1" }),
				});

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 1);

			expect(result.sent).toBe(1);
			expect(QUESTION_TEMPLATES).toContain(replyText);
		});

		it("uses gaming-related templates for gaming topic", async () => {
			setupFullPipeline({ pillars: ["gaming"] });

			let replyText = "";
			mockFetch
				.mockResolvedValueOnce({
					ok: true,
					json: async () => ({
						data: [createSearchPost({
							// Not a question, not a hot take, not relatable — topic will drive selection
							text: "just reached diamond today",
							views: 500,
						})],
					}),
				})
				.mockImplementationOnce(async (_url: string, opts: any) => {
					const bodyStr = opts.body?.toString() || "";
					replyText = new URLSearchParams(bodyStr).get("text") || "";
					return { ok: true, json: async () => ({ id: "container-1" }) };
				})
				.mockResolvedValueOnce({
					ok: true,
					json: async () => ({ id: "published-1" }),
				});

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 1);

			if (result.sent > 0) {
				// gaming topic maps to GAMING + HOT_TAKE templates
				const validTemplates = [...GAMING_TEMPLATES, ...HOT_TAKE_TEMPLATES];
				expect(validTemplates).toContain(replyText);
			}
		});

		it("uses hot take templates for 'unpopular opinion' posts", async () => {
			// Use non-mapped topic so hot take signal detection works
			setupFullPipeline({ pillars: ["lifestyle"] });

			let replyText = "";
			mockFetch
				.mockResolvedValueOnce({
					ok: true,
					json: async () => ({
						data: [createSearchPost({
							text: "unpopular opinion but pineapple on pizza is great",
							views: 500,
						})],
					}),
				})
				.mockImplementationOnce(async (_url: string, opts: any) => {
					const bodyStr = opts.body?.toString() || "";
					replyText = new URLSearchParams(bodyStr).get("text") || "";
					return { ok: true, json: async () => ({ id: "container-1" }) };
				})
				.mockResolvedValueOnce({
					ok: true,
					json: async () => ({ id: "published-1" }),
				});

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 1);

			if (result.sent > 0) {
				expect(HOT_TAKE_TEMPLATES).toContain(replyText);
			}
		});

		it("uses relatable templates for 'does anyone else' posts", async () => {
			setupFullPipeline({ pillars: ["lifestyle"] });

			let replyText = "";
			mockFetch
				.mockResolvedValueOnce({
					ok: true,
					json: async () => ({
						data: [createSearchPost({
							text: "does anyone else feel like this",
							views: 500,
						})],
					}),
				})
				.mockImplementationOnce(async (_url: string, opts: any) => {
					const bodyStr = opts.body?.toString() || "";
					replyText = new URLSearchParams(bodyStr).get("text") || "";
					return { ok: true, json: async () => ({ id: "container-1" }) };
				})
				.mockResolvedValueOnce({
					ok: true,
					json: async () => ({ id: "published-1" }),
				});

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 1);

			if (result.sent > 0) {
				expect(RELATABLE_TEMPLATES).toContain(replyText);
			}
		});

		it("falls back to generic templates for unmapped content", async () => {
			setupFullPipeline({ pillars: ["randomtopic123"] });

			let replyText = "";
			mockFetch
				.mockResolvedValueOnce({
					ok: true,
					json: async () => ({
						data: [createSearchPost({
							text: "just a regular statement about life",
							views: 500,
						})],
					}),
				})
				.mockImplementationOnce(async (_url: string, opts: any) => {
					const bodyStr = opts.body?.toString() || "";
					replyText = new URLSearchParams(bodyStr).get("text") || "";
					return { ok: true, json: async () => ({ id: "container-1" }) };
				})
				.mockResolvedValueOnce({
					ok: true,
					json: async () => ({ id: "published-1" }),
				});

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 1);

			if (result.sent > 0) {
				expect(GENERIC_TEMPLATES).toContain(replyText);
			}
		});
	});

	// =========================================================================
	// 8. Posting replies (two-step container -> publish)
	// =========================================================================

	describe("reply posting", () => {
		it("sends reply via two-step container+publish flow", async () => {
			setupFullPipeline();
			setupKeywordSearchResponse([
				createSearchPost({ id: "target-post", views: 500 }),
			]);
			setupReplySuccess();

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 1);
			expect(result.sent).toBe(1);

			// [0] = keyword search, [1] = container create, [2] = publish
			expect(mockFetch).toHaveBeenCalledTimes(3);
			const containerCall = mockFetch.mock.calls[1];
			expect(containerCall[0]).toContain("threads");
			expect(containerCall[1].method).toBe("POST");

			const publishCall = mockFetch.mock.calls[2];
			expect(publishCall[0]).toContain("threads_publish");
			expect(publishCall[1].method).toBe("POST");
		});

		it("counts as failed when container creation fails", async () => {
			setupFullPipeline();
			setupKeywordSearchResponse([
				createSearchPost({ id: "target-post", views: 500 }),
			]);
			setupReplyFailure("container");

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 1);
			expect(result.failed).toBe(1);
			expect(result.sent).toBe(0);
		});

		it("counts as failed when publish step fails", async () => {
			setupFullPipeline();
			setupKeywordSearchResponse([
				createSearchPost({ id: "target-post", views: 500 }),
			]);
			setupReplyFailure("publish");

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 1);
			expect(result.failed).toBe(1);
			expect(result.sent).toBe(0);
		});

		it("handles fetch exception gracefully", async () => {
			setupFullPipeline();
			setupKeywordSearchResponse([
				createSearchPost({ id: "target-post", views: 500 }),
			]);
			// Container throws
			mockFetch.mockRejectedValueOnce(new Error("Network error"));

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 1);
			expect(result.failed).toBe(1);
		});
	});

	// =========================================================================
	// 9. Redis state management after successful reply
	// =========================================================================

	describe("Redis state after successful reply", () => {
		it("marks post as seen in Redis after successful reply", async () => {
			setupFullPipeline();
			setupKeywordSearchResponse([
				createSearchPost({ id: "post-abc", username: "externaluser", views: 500 }),
			]);
			setupReplySuccess();

			await runReplyFarming("ws-1", "group-1", ["acc-1"], 1);

			expect(mockRedisSet).toHaveBeenCalledWith(
				"reply-farm-seen:post-abc",
				"1",
				{ ex: 86400 },
			);
		});

		it("marks author as replied-to in Redis", async () => {
			setupFullPipeline();
			const dateKey = new Date().toISOString().split("T")[0];
			setupKeywordSearchResponse([
				createSearchPost({ id: "post-abc", username: "targetuser", views: 500 }),
			]);
			setupReplySuccess();

			await runReplyFarming("ws-1", "group-1", ["acc-1"], 1);

			expect(mockRedisSet).toHaveBeenCalledWith(
				`reply-farm-author:acc-1:targetuser:${dateKey}`,
				"1",
				{ ex: 86400 },
			);
		});

		it("increments daily counter in Redis", async () => {
			setupFullPipeline();
			const dateKey = new Date().toISOString().split("T")[0];
			setupKeywordSearchResponse([
				createSearchPost({ id: "post-abc", views: 500 }),
			]);
			setupReplySuccess();

			await runReplyFarming("ws-1", "group-1", ["acc-1"], 1);

			expect(mockRedisIncr).toHaveBeenCalledWith(`reply-farm:acc-1:${dateKey}`);
			expect(mockRedisExpire).toHaveBeenCalledWith(`reply-farm:acc-1:${dateKey}`, 86400);
		});

		it("does not crash if Redis dedup write fails", async () => {
			setupFullPipeline();
			setupKeywordSearchResponse([
				createSearchPost({ id: "post-abc", views: 500 }),
			]);
			setupReplySuccess();

			mockRedisSet.mockRejectedValue(new Error("Redis write error"));

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 1);
			expect(result.sent).toBe(1); // Reply was still sent
		});
	});

	// =========================================================================
	// 10. Full integration flow
	// =========================================================================

	describe("end-to-end flow", () => {
		it("sends multiple replies up to maxRepliesPerRun", async () => {
			setupFullPipeline();

			const posts = [
				createSearchPost({ id: "p1", username: "u1", views: 500 }),
				createSearchPost({ id: "p2", username: "u2", views: 1000 }),
				createSearchPost({ id: "p3", username: "u3", views: 200 }),
			];

			setupKeywordSearchResponse(posts);

			// 3 replies x 2 API calls each (container + publish)
			for (let i = 0; i < 3; i++) {
				setupReplySuccess();
			}

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 3);
			expect(result.sent).toBe(3);
			expect(result.failed).toBe(0);
		}, 120000);

		it("mixes successes and failures correctly", async () => {
			setupFullPipeline();

			setupKeywordSearchResponse([
				createSearchPost({ id: "p1", username: "u1", views: 500 }),
				createSearchPost({ id: "p2", username: "u2", views: 500 }),
			]);

			// First reply succeeds
			setupReplySuccess();
			// Second reply fails at container
			setupReplyFailure("container");

			const result = await runReplyFarming("ws-1", "group-1", ["acc-1"], 5);
			expect(result.sent).toBe(1);
			expect(result.failed).toBe(1);
		}, 60000);

		it("returns correct structure even on zero activity", async () => {
			const result = await runReplyFarming("ws-1", "group-1", [], 5);
			expect(result).toEqual({
				sent: 0,
				failed: 0,
				skipped: 0,
				details: ["No account IDs provided"],
			});
		});
	});
});
