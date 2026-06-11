/**
 * Unit tests for api/_lib/handlers/sync/post-engagement.ts
 *
 * Tests the QStash-dispatched post engagement fetch handler covering:
 *   1. Happy path — engagement metrics fetched and stored
 *   2. Batch processing — multiple posts processed correctly (sequential calls)
 *   3. Partial failure — some posts fail, others succeed, no abort
 *   4. Timestamp coordination — proper ordering of sync timestamps
 *   5. Meta API errors — transient vs permanent error handling
 *   6. Empty batch — no posts to sync → graceful noop
 *   7. Auto-post queue back-population
 *   8. Missing token — graceful skip
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mock factories
// ---------------------------------------------------------------------------

const mockMaybeSingle = vi.fn();
const mockQueueMaybeSingle = vi.fn();
const mockSelect = vi.fn(() => ({
	eq: vi.fn(() => ({ maybeSingle: mockMaybeSingle })),
}));
const mockQueueSelect = vi.fn(() => ({
	eq: vi.fn(() => ({ maybeSingle: mockQueueMaybeSingle })),
}));
const mockUpdateScopeEq = vi.fn();
const mockUpdateEq = vi.fn(() => ({ eq: mockUpdateScopeEq }));
const mockUpdate = vi.fn(() => ({ eq: mockUpdateEq }));
const mockInsert = vi.fn();
const mockUpsert = vi.fn();
const mockRpc = vi.fn();

const mockSupabase = {
	from: vi.fn((table: string) => {
		if (table === "auto_post_queue") {
			return { select: mockQueueSelect, update: mockUpdate };
		}
		if (table === "post_metric_history") {
			return { insert: mockInsert };
		}
		if (table === "autoposter_post_performance_facts") {
			return { upsert: mockUpsert };
		}
		return { select: mockSelect };
	}),
	rpc: mockRpc,
};

vi.mock("@/api/_lib/supabase.js", () => ({
	getSupabase: () => mockSupabase,
}));

vi.mock("@/api/_lib/logger.js", () => ({
	logger: {
		info: vi.fn(),
		warn: vi.fn(),
		error: vi.fn(),
		debug: vi.fn(),
	},
}));

const mockVerifyQStashSignature = vi.fn();
vi.mock("@/api/_lib/qstash.js", () => ({
	verifyQStashSignature: (...args: unknown[]) =>
		mockVerifyQStashSignature(...args),
}));

const mockDecrypt = vi.fn((encrypted: string) => `decrypted-${encrypted}`);
vi.mock("@/api/_lib/encryption.js", () => ({
	decrypt: (s: string) => mockDecrypt(s),
}));

const mockWithRetry = vi.fn();
vi.mock("@/api/_lib/retryUtils.js", () => ({
	withRetry: (fn: () => Promise<unknown>, opts?: unknown) =>
		mockWithRetry(fn, opts),
}));

vi.mock("@/api/_lib/sentryServer.js", () => ({
	captureServerException: vi.fn(),
}));

vi.mock("@/api/_lib/metricCalculators.js", async () => {
	const actual = await vi.importActual<
		typeof import("@/api/_lib/metricCalculators.js")
	>("@/api/_lib/metricCalculators.js");
	return actual;
});

// ---------------------------------------------------------------------------
// Import handler after mocks
// ---------------------------------------------------------------------------

const { default: handler } = await import(
	"@/api/_lib/handlers/sync/post-engagement.js"
);

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

interface MockResponse {
	status: (code: number) => MockResponse;
	json: (body: unknown) => MockResponse;
	_status?: number;
	_body?: unknown;
}

function createMockRes(): any {
	const res: MockResponse = {
		status(code: number) {
			res._status = code;
			return res;
		},
		json(body: unknown) {
			res._body = body;
			return res;
		},
	};
	return res;
}

function createMockReq(overrides: {
	method?: string;
	headers?: Record<string, string | undefined>;
	body?: Record<string, unknown> | null;
}): any {
	return {
		method: overrides.method ?? "POST",
		headers: overrides.headers ?? { "upstash-signature": "valid-sig" },
		body: overrides.body ?? {},
	};
}

function makeThreadsInsightsResponse(
	overrides: {
		views?: number;
		likes?: number;
		replies?: number;
		reposts?: number;
		quotes?: number;
	} = {},
) {
	const {
		views = 1000,
		likes = 50,
		replies = 10,
		reposts = 5,
		quotes = 2,
	} = overrides;
	return {
		data: [
			{ name: "views", values: [{ value: views }] },
			{ name: "likes", values: [{ value: likes }] },
			{ name: "replies", values: [{ value: replies }] },
			{ name: "reposts", values: [{ value: reposts }] },
			{ name: "quotes", values: [{ value: quotes }] },
		],
	};
}

function makePostRow(
	overrides: {
		id?: string;
		user_id?: string;
		account_id?: string;
		metadata?: Record<string, unknown>;
		token?: string | null;
	} = {},
) {
	return {
		id: overrides.id ?? "post-001",
		user_id: overrides.user_id ?? "user-001",
		account_id: overrides.account_id ?? "acc-001",
		metadata: overrides.metadata ?? {},
		accounts:
			overrides.token === null
				? { threads_access_token_encrypted: null }
				: {
						threads_access_token_encrypted:
							overrides.token ?? "enc-token-xyz",
					},
	};
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("post-engagement sync handler", () => {
	beforeEach(() => {
		vi.clearAllMocks();

		// Default: QStash signature valid
		mockVerifyQStashSignature.mockResolvedValue(true);

		// Default: RPC succeeds
		mockRpc.mockResolvedValue({ data: null, error: null });
		mockInsert.mockResolvedValue({ data: null, error: null });
		mockUpsert.mockResolvedValue({ data: null, error: null });

		// Default: auto_post_queue update succeeds
		mockQueueMaybeSingle.mockResolvedValue({
			data: { id: "apq-123", account_id: "acc-001", post_id: null },
			error: null,
		});
		mockUpdateScopeEq.mockResolvedValue({ data: null, error: null });
	});

	afterEach(() => {
		vi.clearAllMocks();
	});

	// ========================================================================
	// 1. Method validation
	// ========================================================================

	it("rejects non-POST requests with 405", async () => {
		const req = createMockReq({ method: "GET" });
		const res = createMockRes();

		await handler(req, res);

		expect(res._status).toBe(405);
		expect(res._body).toEqual({ error: "Method not allowed" });
	});

	// ========================================================================
	// 2. Auth: QStash signature
	// ========================================================================

	describe("QStash signature auth", () => {
		it("returns early when QStash signature verification fails", async () => {
			mockVerifyQStashSignature.mockResolvedValue(false);

			const req = createMockReq({
				body: { postId: "post-001", threadsPostId: "tp-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			// Should not process further
			expect(mockSupabase.from).not.toHaveBeenCalled();
		});
	});

	// ========================================================================
	// 3. Missing parameters — graceful noop
	// ========================================================================

	describe("missing parameters", () => {
		it("returns skipped when postId is missing", async () => {
			const req = createMockReq({
				body: { threadsPostId: "tp-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(res._status).toBe(200);
			expect(res._body).toEqual({
				ok: true,
				skipped: true,
				reason: "missing_params",
			});
		});

		it("returns skipped when threadsPostId is missing", async () => {
			const req = createMockReq({
				body: { postId: "post-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(res._status).toBe(200);
			expect(res._body).toEqual({
				ok: true,
				skipped: true,
				reason: "missing_params",
			});
		});

		it("returns skipped when body is null", async () => {
			const req = createMockReq({ body: null });
			const res = createMockRes();

			await handler(req, res);

			expect(res._status).toBe(200);
			expect(res._body).toEqual({
				ok: true,
				skipped: true,
				reason: "missing_params",
			});
		});

		it("returns skipped when both params are missing", async () => {
			const req = createMockReq({ body: {} });
			const res = createMockRes();

			await handler(req, res);

			expect(res._status).toBe(200);
			expect(res._body).toEqual({
				ok: true,
				skipped: true,
				reason: "missing_params",
			});
		});
	});

	// ========================================================================
	// 4. Missing token — graceful skip
	// ========================================================================

	describe("missing token", () => {
		it("returns skipped when post has no encrypted token", async () => {
			mockMaybeSingle.mockResolvedValue({
				data: makePostRow({ token: null }),
			});

			const req = createMockReq({
				body: { postId: "post-001", threadsPostId: "tp-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(res._status).toBe(200);
			expect(res._body).toEqual({
				ok: true,
				skipped: true,
				reason: "no_token",
			});
		});

		it("returns skipped when post is not found in DB", async () => {
			mockMaybeSingle.mockResolvedValue({ data: null });

			const req = createMockReq({
				body: { postId: "post-nonexistent", threadsPostId: "tp-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(res._status).toBe(200);
			expect(res._body).toEqual({
				ok: true,
				skipped: true,
				reason: "no_token",
			});
		});

		it("returns skipped when accounts object has no token", async () => {
			mockMaybeSingle.mockResolvedValue({
				data: {
					id: "post-001",
					account_id: "acc-001",
					metadata: {},
					accounts: {},
				},
			});

			const req = createMockReq({
				body: { postId: "post-001", threadsPostId: "tp-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(res._status).toBe(200);
			expect(res._body).toEqual({
				ok: true,
				skipped: true,
				reason: "no_token",
			});
		});
	});

	// ========================================================================
	// 5. Happy path — metrics fetched and stored
	// ========================================================================

	describe("happy path", () => {
		it("fetches metrics and updates post via RPC", async () => {
			const post = makePostRow();
			mockMaybeSingle.mockResolvedValue({ data: post });

			const insightsData = makeThreadsInsightsResponse({
				views: 2000,
				likes: 100,
				replies: 20,
				reposts: 10,
				quotes: 5,
			});

			const mockFetchResponse = {
				ok: true,
				json: vi.fn().mockResolvedValue(insightsData),
			};
			mockWithRetry.mockResolvedValue(mockFetchResponse);

			const req = createMockReq({
				body: { postId: "post-001", threadsPostId: "tp-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(res._status).toBe(200);
			const body = res._body as Record<string, unknown>;
			expect(body.ok).toBe(true);
			expect(body.views).toBe(2000);
			expect(body.likes).toBe(100);
			expect(body.replies).toBe(20);
			expect(body.reposts).toBe(10);

			// Verify RPC called with correct params
			expect(mockRpc).toHaveBeenCalledWith(
				"update_post_metrics_if_newer",
				expect.objectContaining({
					p_post_id: "post-001",
					p_threads_post_id: "tp-001",
					p_views_count: 2000,
					p_likes_count: 100,
					p_replies_count: 20,
					p_reposts_count: 10,
					p_quotes_count: 5,
					p_shares_count: 0,
				}),
			);
		});

		it("writes a metric snapshot and performance fact after fetching metrics", async () => {
			const post = makePostRow({
				metadata: { autoPostQueueId: "apq-123" },
			});
			mockMaybeSingle.mockResolvedValue({ data: post });

			const insightsData = makeThreadsInsightsResponse({
				views: 321,
				likes: 12,
				replies: 3,
				reposts: 2,
				quotes: 1,
			});
			mockWithRetry.mockResolvedValue({
				ok: true,
				json: vi.fn().mockResolvedValue(insightsData),
			});

			const req = createMockReq({
				body: { postId: "post-001", threadsPostId: "tp-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockInsert).toHaveBeenCalledWith(
				expect.objectContaining({
					post_id: "post-001",
					account_id: "acc-001",
					platform: "threads",
					views_count: 321,
					likes_count: 12,
					replies_count: 3,
					reposts_count: 2,
					quotes_count: 1,
				}),
			);
			expect(mockUpsert).toHaveBeenCalledWith(
				[
					expect.objectContaining({
						post_id: "post-001",
						account_id: "acc-001",
						views_1h: 321,
						current_views: 321,
					}),
				],
				{ onConflict: "post_id" },
			);
		});

		it("decrypts the token before fetching metrics", async () => {
			const post = makePostRow({ token: "enc-my-special-token" });
			mockMaybeSingle.mockResolvedValue({ data: post });

			const mockFetchResponse = {
				ok: true,
				json: vi.fn().mockResolvedValue(makeThreadsInsightsResponse()),
			};
			mockWithRetry.mockResolvedValue(mockFetchResponse);

			const req = createMockReq({
				body: { postId: "post-001", threadsPostId: "tp-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockDecrypt).toHaveBeenCalledWith("enc-my-special-token");
		});

		it("calculates engagement rate correctly using threads formula", async () => {
			const post = makePostRow();
			mockMaybeSingle.mockResolvedValue({ data: post });

			// views=1000, likes=50, replies=10, reposts=5, quotes=2
			// Threads formula: (likes + replies*2 + reposts*1.5 + quotes + shares) / views * 100
			// = (50 + 20 + 7.5 + 2 + 0) / 1000 * 100 = 7.95
			const insightsData = makeThreadsInsightsResponse({
				views: 1000,
				likes: 50,
				replies: 10,
				reposts: 5,
				quotes: 2,
			});

			const mockFetchResponse = {
				ok: true,
				json: vi.fn().mockResolvedValue(insightsData),
			};
			mockWithRetry.mockResolvedValue(mockFetchResponse);

			const req = createMockReq({
				body: { postId: "post-001", threadsPostId: "tp-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockRpc).toHaveBeenCalledWith(
				"update_post_metrics_if_newer",
				expect.objectContaining({
					p_engagement_rate: expect.closeTo(7.95, 1),
					// totalEngagement = likes(50) + replies(10) + reposts(5) + quotes(2) + shares(0)
					p_total_engagement: 67,
				}),
			);
		});
	});

	// ========================================================================
	// 6. Meta API errors
	// ========================================================================

	describe("Meta API errors", () => {
		it("returns skipped on non-ok API response (500)", async () => {
			const post = makePostRow();
			mockMaybeSingle.mockResolvedValue({ data: post });

			const mockFetchResponse = { ok: false, status: 500 };
			mockWithRetry.mockResolvedValue(mockFetchResponse);

			const req = createMockReq({
				body: { postId: "post-001", threadsPostId: "tp-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(res._status).toBe(200);
			expect(res._body).toEqual({
				ok: true,
				skipped: true,
				reason: "api_error",
			});
			// Should NOT update the DB
			expect(mockRpc).not.toHaveBeenCalled();
		});

		it("returns skipped on 429 rate limited response", async () => {
			const post = makePostRow();
			mockMaybeSingle.mockResolvedValue({ data: post });

			mockWithRetry.mockResolvedValue({ ok: false, status: 429 });

			const req = createMockReq({
				body: { postId: "post-001", threadsPostId: "tp-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(res._status).toBe(200);
			expect(res._body).toEqual({
				ok: true,
				skipped: true,
				reason: "api_error",
			});
		});

		it("returns skipped on 401 unauthorized response", async () => {
			const post = makePostRow();
			mockMaybeSingle.mockResolvedValue({ data: post });

			mockWithRetry.mockResolvedValue({ ok: false, status: 401 });

			const req = createMockReq({
				body: { postId: "post-001", threadsPostId: "tp-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(res._status).toBe(200);
			expect(res._body).toEqual({
				ok: true,
				skipped: true,
				reason: "api_error",
			});
		});
	});

	// ========================================================================
	// 7. Error handling — exceptions caught gracefully
	// ========================================================================

	describe("error handling", () => {
		it("catches fetch exceptions and returns 200 with error", async () => {
			const post = makePostRow();
			mockMaybeSingle.mockResolvedValue({ data: post });

			mockWithRetry.mockRejectedValue(new Error("Network timeout"));

			const req = createMockReq({
				body: { postId: "post-001", threadsPostId: "tp-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(res._status).toBe(200);
			const body = res._body as Record<string, unknown>;
			expect(body.ok).toBe(false);
			expect(body.error).toBe("Engagement sync failed");
		});

		it("catches RPC exceptions and returns 200 with error", async () => {
			const post = makePostRow();
			mockMaybeSingle.mockResolvedValue({ data: post });

			const mockFetchResponse = {
				ok: true,
				json: vi.fn().mockResolvedValue(makeThreadsInsightsResponse()),
			};
			mockWithRetry.mockResolvedValue(mockFetchResponse);
			mockRpc.mockRejectedValue(new Error("Database connection lost"));

			const req = createMockReq({
				body: { postId: "post-001", threadsPostId: "tp-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(res._status).toBe(200);
			const body = res._body as Record<string, unknown>;
			expect(body.ok).toBe(false);
			expect(body.error).toBe("Engagement sync failed");
		});

		it("catches DB query exceptions and returns 200 with error", async () => {
			mockMaybeSingle.mockRejectedValue(
				new Error("relation does not exist"),
			);

			const req = createMockReq({
				body: { postId: "post-001", threadsPostId: "tp-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(res._status).toBe(200);
			const body = res._body as Record<string, unknown>;
			expect(body.ok).toBe(false);
			expect(body.error).toBe("Engagement sync failed");
		});
	});

	// ========================================================================
	// 8. Auto-post queue back-population
	// ========================================================================

	describe("auto-post queue back-population", () => {
		it("updates auto_post_queue when metadata.autoPostQueueId is present", async () => {
			const post = makePostRow({
				metadata: { autoPostQueueId: "apq-123" },
			});
			mockMaybeSingle.mockResolvedValue({ data: post });

			const insightsData = makeThreadsInsightsResponse({
				views: 500,
				likes: 25,
				replies: 5,
				reposts: 3,
				quotes: 1,
			});
			const mockFetchResponse = {
				ok: true,
				json: vi.fn().mockResolvedValue(insightsData),
			};
			mockWithRetry.mockResolvedValue(mockFetchResponse);

			const req = createMockReq({
				body: { postId: "post-001", threadsPostId: "tp-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockSupabase.from).toHaveBeenCalledWith("auto_post_queue");
			expect(mockUpdate).toHaveBeenCalledWith(
				expect.objectContaining({
					views_at_24h: 500,
					likes_count: 25,
					replies_count: 5,
					reposts_count: 3,
					engagement_fetched_at: expect.any(String),
				}),
			);
			expect(mockUpdateEq).toHaveBeenCalledWith("id", "apq-123");
			expect(mockUpdateScopeEq).toHaveBeenCalledWith("account_id", "acc-001");
		});

		it("does NOT update auto_post_queue when metadata queue link belongs to another account", async () => {
			const post = makePostRow({
				account_id: "acc-001",
				metadata: { autoPostQueueId: "apq-123" },
			});
			mockMaybeSingle.mockResolvedValue({ data: post });
			mockQueueMaybeSingle.mockResolvedValue({
				data: { id: "apq-123", account_id: "acc-other", post_id: null },
				error: null,
			});

			const mockFetchResponse = {
				ok: true,
				json: vi.fn().mockResolvedValue(makeThreadsInsightsResponse()),
			};
			mockWithRetry.mockResolvedValue(mockFetchResponse);

			const req = createMockReq({
				body: { postId: "post-001", threadsPostId: "tp-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockUpdate).not.toHaveBeenCalled();
		});

		it("does NOT update auto_post_queue when metadata has no autoPostQueueId", async () => {
			const post = makePostRow({ metadata: {} });
			mockMaybeSingle.mockResolvedValue({ data: post });

			const mockFetchResponse = {
				ok: true,
				json: vi.fn().mockResolvedValue(makeThreadsInsightsResponse()),
			};
			mockWithRetry.mockResolvedValue(mockFetchResponse);

			const req = createMockReq({
				body: { postId: "post-001", threadsPostId: "tp-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			const autoPostCalls = mockSupabase.from.mock.calls.filter(
				(call: unknown[]) => call[0] === "auto_post_queue",
			);
			expect(autoPostCalls).toHaveLength(0);
		});

		it("does NOT update auto_post_queue when metadata is empty/null", async () => {
			const post = makePostRow();
			mockMaybeSingle.mockResolvedValue({ data: post });

			const mockFetchResponse = {
				ok: true,
				json: vi.fn().mockResolvedValue(makeThreadsInsightsResponse()),
			};
			mockWithRetry.mockResolvedValue(mockFetchResponse);

			const req = createMockReq({
				body: { postId: "post-001", threadsPostId: "tp-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			const autoPostCalls = mockSupabase.from.mock.calls.filter(
				(call: unknown[]) => call[0] === "auto_post_queue",
			);
			expect(autoPostCalls).toHaveLength(0);
		});
	});

	// ========================================================================
	// 9. Metric parsing edge cases
	// ========================================================================

	describe("metric parsing", () => {
		it("handles empty metrics data array", async () => {
			const post = makePostRow();
			mockMaybeSingle.mockResolvedValue({ data: post });

			const mockFetchResponse = {
				ok: true,
				json: vi.fn().mockResolvedValue({ data: [] }),
			};
			mockWithRetry.mockResolvedValue(mockFetchResponse);

			const req = createMockReq({
				body: { postId: "post-001", threadsPostId: "tp-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(res._status).toBe(200);
			const body = res._body as Record<string, unknown>;
			expect(body.views).toBe(0);
			expect(body.likes).toBe(0);
			expect(body.replies).toBe(0);
			expect(body.reposts).toBe(0);

			// RPC should still be called with zeroes
			expect(mockRpc).toHaveBeenCalledWith(
				"update_post_metrics_if_newer",
				expect.objectContaining({
					p_views_count: 0,
					p_likes_count: 0,
					p_replies_count: 0,
					p_reposts_count: 0,
					p_quotes_count: 0,
					p_shares_count: 0,
					p_total_engagement: 0,
				}),
			);
		});

		it("handles missing data field in API response", async () => {
			const post = makePostRow();
			mockMaybeSingle.mockResolvedValue({ data: post });

			const mockFetchResponse = {
				ok: true,
				json: vi.fn().mockResolvedValue({}),
			};
			mockWithRetry.mockResolvedValue(mockFetchResponse);

			const req = createMockReq({
				body: { postId: "post-001", threadsPostId: "tp-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(res._status).toBe(200);
			expect(mockRpc).toHaveBeenCalledWith(
				"update_post_metrics_if_newer",
				expect.objectContaining({
					p_views_count: 0,
					p_likes_count: 0,
				}),
			);
		});

		it("handles metric entries with missing values", async () => {
			const post = makePostRow();
			mockMaybeSingle.mockResolvedValue({ data: post });

			const mockFetchResponse = {
				ok: true,
				json: vi.fn().mockResolvedValue({
					data: [
						{ name: "views", values: [{ value: 500 }] },
						{ name: "likes" }, // no values array
						{ name: "replies", values: [] }, // empty values array
						{ name: "reposts", values: [{}] }, // value property missing
					],
				}),
			};
			mockWithRetry.mockResolvedValue(mockFetchResponse);

			const req = createMockReq({
				body: { postId: "post-001", threadsPostId: "tp-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(res._status).toBe(200);
			const body = res._body as Record<string, unknown>;
			expect(body.views).toBe(500);
			expect(body.likes).toBe(0);
			expect(body.replies).toBe(0);
			expect(body.reposts).toBe(0);
		});

		it("handles zero views without division by zero", async () => {
			const post = makePostRow();
			mockMaybeSingle.mockResolvedValue({ data: post });

			const mockFetchResponse = {
				ok: true,
				json: vi.fn().mockResolvedValue(
					makeThreadsInsightsResponse({
						views: 0,
						likes: 5,
						replies: 0,
						reposts: 0,
						quotes: 0,
					}),
				),
			};
			mockWithRetry.mockResolvedValue(mockFetchResponse);

			const req = createMockReq({
				body: { postId: "post-001", threadsPostId: "tp-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			// Should not throw — engagement rate formula uses max(views, 1)
			expect(res._status).toBe(200);
			expect(mockRpc).toHaveBeenCalledWith(
				"update_post_metrics_if_newer",
				expect.objectContaining({
					p_views_count: 0,
					p_engagement_rate: expect.any(Number),
				}),
			);
		});
	});

	// ========================================================================
	// 10. Sequential calls (simulating batch processing)
	// ========================================================================

	describe("sequential calls (batch simulation)", () => {
		it("processes multiple posts independently without cross-contamination", async () => {
			// First call
			const post1 = makePostRow({ id: "post-001" });
			mockMaybeSingle.mockResolvedValue({ data: post1 });
			const insights1 = makeThreadsInsightsResponse({
				views: 100,
				likes: 10,
			});
			mockWithRetry.mockResolvedValue({
				ok: true,
				json: vi.fn().mockResolvedValue(insights1),
			});

			const req1 = createMockReq({
				body: { postId: "post-001", threadsPostId: "tp-001" },
			});
			const res1 = createMockRes();
			await handler(req1, res1);

			expect(res1._status).toBe(200);
			expect((res1._body as Record<string, unknown>).views).toBe(100);

			// Reset for second call
			vi.clearAllMocks();
			mockVerifyQStashSignature.mockResolvedValue(true);
			mockRpc.mockResolvedValue({ data: null, error: null });

			// Second call
			const post2 = makePostRow({ id: "post-002" });
			mockMaybeSingle.mockResolvedValue({ data: post2 });
			const insights2 = makeThreadsInsightsResponse({
				views: 5000,
				likes: 200,
			});
			mockWithRetry.mockResolvedValue({
				ok: true,
				json: vi.fn().mockResolvedValue(insights2),
			});

			const req2 = createMockReq({
				body: { postId: "post-002", threadsPostId: "tp-002" },
			});
			const res2 = createMockRes();
			await handler(req2, res2);

			expect(res2._status).toBe(200);
			expect((res2._body as Record<string, unknown>).views).toBe(5000);
		});

		it("one post failing does not affect subsequent posts", async () => {
			// First call fails
			const post1 = makePostRow({ id: "post-fail" });
			mockMaybeSingle.mockResolvedValue({ data: post1 });
			mockWithRetry.mockRejectedValue(new Error("API unreachable"));

			const req1 = createMockReq({
				body: { postId: "post-fail", threadsPostId: "tp-fail" },
			});
			const res1 = createMockRes();
			await handler(req1, res1);

			expect(res1._status).toBe(200);
			expect(
				(res1._body as Record<string, unknown>).error,
			).toBeDefined();

			// Reset for successful call
			vi.clearAllMocks();
			mockVerifyQStashSignature.mockResolvedValue(true);
			mockRpc.mockResolvedValue({ data: null, error: null });

			// Second call succeeds
			const post2 = makePostRow({ id: "post-ok" });
			mockMaybeSingle.mockResolvedValue({ data: post2 });
			mockWithRetry.mockResolvedValue({
				ok: true,
				json: vi
					.fn()
					.mockResolvedValue(makeThreadsInsightsResponse()),
			});

			const req2 = createMockReq({
				body: { postId: "post-ok", threadsPostId: "tp-ok" },
			});
			const res2 = createMockRes();
			await handler(req2, res2);

			expect(res2._status).toBe(200);
			expect((res2._body as Record<string, unknown>).ok).toBe(true);
			expect(
				(res2._body as Record<string, unknown>).error,
			).toBeUndefined();
		});
	});

	// ========================================================================
	// 11. Uses withRetry for API calls
	// ========================================================================

	describe("retry behavior", () => {
		it("wraps API fetch with withRetry for resilience", async () => {
			const post = makePostRow();
			mockMaybeSingle.mockResolvedValue({ data: post });

			mockWithRetry.mockResolvedValue({
				ok: true,
				json: vi
					.fn()
					.mockResolvedValue(makeThreadsInsightsResponse()),
			});

			const req = createMockReq({
				body: { postId: "post-001", threadsPostId: "tp-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockWithRetry).toHaveBeenCalledWith(
				expect.any(Function),
				{ label: "post-engagement-fetch" },
			);
		});
	});
});
