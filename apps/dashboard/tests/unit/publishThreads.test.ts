import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Unit tests for processThreadsPosts() — the Threads scheduled post publishing
 * cron handler in api/_lib/cron/scheduled-posts/publishThreads.ts.
 *
 * This is the code where the April 9-11 outage (55 hours of silent failure)
 * occurred. Tests cover:
 *
 * 1. Empty queue — no posts due returns immediately
 * 2. Post selection query — error propagation
 * 3. Account validation — missing token, missing threads_user_id
 * 4. Account deactivated (is_active=false) — skipped without failure
 * 5. Token expiry — skipped (awaiting refresh), NOT marked failed
 * 6. Tier limit enforcement — free-tier users blocked
 * 7. Tier limit fail-closed — tier check failure skips publishing
 * 8. Content validation — empty content, >500 chars
 * 9. Thread chain ordering — multi-part posts with reply_to_id chaining
 * 10. Thread chain partial failure — some posts published, later fails
 * 11. Thread chain rate limit — insufficient quota skips whole chain
 * 12. Thread chain post >500 chars — rejected before publish
 * 13. Atomic claim — already-claimed posts skipped
 * 14. Successful single publish — status→published, permalink fetched
 * 15. Rate limiting — hourly/daily limits respected
 * 16. Transient error retry — Meta 429/5xx rescheduled with backoff
 * 17. Permanent failure — non-transient error marks failed
 * 18. Token error (OAuth) — inline refresh attempted
 * 19. Token error — refresh success → retry publish succeeds
 * 20. Token error — refresh fails → account flagged needs_reauth
 * 21. Transient Meta OAuthException code=1 — NOT flagged as needs_reauth
 * 22. Media UUID resolution — non-HTTP URLs resolved before publish
 * 23. Media URL accessibility — inaccessible media fails gracefully
 * 24. Timeout guard — stops processing when approaching MAX_RUNTIME_MS
 * 25. Parallel account processing — batches of 5 accounts
 */

// ---------------------------------------------------------------------------
// Mocks — must be set up BEFORE importing module under test
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();
const mockRpc = vi.fn();
let selectedPostsColumns = "";

vi.mock("../../api/_lib/supabase", () => ({
	getSupabase: () => ({
		from: mockFrom,
		rpc: mockRpc,
	}),
	getSupabaseAny: () => ({
		from: mockFrom,
		rpc: mockRpc,
	}),
}));

vi.mock("../../api/_lib/logger", () => ({
	logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

const mockEnforceOutboundOperatorGuard = vi
	.fn()
	.mockResolvedValue({ allowed: true, auditId: "audit-1" });
const mockRecordOutboundOperatorResult = vi.fn().mockResolvedValue(undefined);
vi.mock("../../api/_lib/outboundOperatorGuard", () => ({
	enforceOutboundOperatorGuard: (...args: unknown[]) =>
		mockEnforceOutboundOperatorGuard(...args),
	recordOutboundOperatorResult: (...args: unknown[]) =>
		mockRecordOutboundOperatorResult(...args),
}));

const mockDeliverNotification = vi.fn().mockResolvedValue(undefined);
vi.mock("../../api/_lib/deliverNotification", () => ({
	deliverNotification: (...args: unknown[]) => mockDeliverNotification(...args),
}));

const mockDecrypt = vi.fn().mockReturnValue("decrypted-token");
const mockEncrypt = vi.fn().mockReturnValue("new-encrypted-token");
vi.mock("../../api/_lib/encryption", () => ({
	decrypt: (...args: unknown[]) => mockDecrypt(...args),
	encrypt: (...args: unknown[]) => mockEncrypt(...args),
}));

const mockPostToThreads = vi.fn();
vi.mock("../../api/_lib/threadsApi", () => ({
	postToThreads: (...args: unknown[]) => mockPostToThreads(...args),
}));

const mockHandleCrossPost = vi.fn().mockResolvedValue(undefined);
vi.mock("../../api/_lib/cron/scheduled-posts/crossPost", () => ({
	handleCrossPost: (...args: unknown[]) => mockHandleCrossPost(...args),
}));

const mockCheckMediaUrlAccessible = vi.fn().mockResolvedValue(null);
vi.mock("../../api/_lib/cron/scheduled-posts/mediaValidation", () => ({
	checkMediaUrlAccessible: (...args: unknown[]) =>
		mockCheckMediaUrlAccessible(...args),
}));

const mockCheckAndIncrementRateLimit = vi
	.fn()
	.mockResolvedValue({ allowed: true });
const mockGetRateLimitStatus = vi.fn().mockResolvedValue({
	postsThisHour: 0,
	postsToday: 0,
	hourlyRemaining: 25,
	dailyRemaining: 250,
});
vi.mock("../../api/_lib/cron/scheduled-posts/rateLimit", () => ({
	checkAndIncrementRateLimit: (...args: unknown[]) =>
		mockCheckAndIncrementRateLimit(...args),
	getRateLimitStatus: (...args: unknown[]) =>
		mockGetRateLimitStatus(...args),
}));

const mockIsTransientError = vi.fn().mockReturnValue(false);
const mockSafeInsertNotification = vi.fn().mockResolvedValue(undefined);
vi.mock("../../api/_lib/cron/scheduled-posts/shared", () => ({
	db: () => ({
		from: mockFrom,
		rpc: mockRpc,
	}),
	isTransientError: (...args: unknown[]) => mockIsTransientError(...args),
	safeInsertNotification: (...args: unknown[]) =>
		mockSafeInsertNotification(...args),
}));

const mockCheckSubscriptionPostLimit = vi.fn().mockResolvedValue({
	allowed: true,
	tier: "pro",
	used: 5,
	limit: 100,
});
vi.mock("../../api/_lib/handlers/posts/shared", () => ({
	checkSubscriptionPostLimit: (...args: unknown[]) =>
		mockCheckSubscriptionPostLimit(...args),
	resolveMediaUrls: vi
		.fn()
		.mockResolvedValue({ urls: ["https://cdn.example.com/img.jpg"], items: [] }),
}));

const mockIsDefinitiveOAuthError = vi.fn().mockReturnValue(false);
vi.mock("../../api/_lib/retryUtils", () => ({
	isDefinitiveOAuthError: (...args: unknown[]) =>
		mockIsDefinitiveOAuthError(...args),
	withRetry: (fn: () => Promise<any>) => fn(),
	isRetryableMetaError: (s: number) => s >= 500,
}));

const mockSchedulePostPublishSyncs = vi.fn().mockResolvedValue(undefined);
const mockDispatchReplyHarvest = vi.fn().mockResolvedValue(undefined);
vi.mock("../../api/_lib/qstashSchedule", () => ({
	schedulePostPublishSyncs: (...args: unknown[]) =>
		mockSchedulePostPublishSyncs(...args),
	dispatchReplyHarvest: (...args: unknown[]) =>
		mockDispatchReplyHarvest(...args),
}));

const mockCreateNotification = vi.fn().mockResolvedValue(undefined);
vi.mock("../../api/_lib/createNotification", () => ({
	createNotification: (...args: unknown[]) =>
		mockCreateNotification(...args),
}));

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

import type { ProcessingStats } from "../../api/_lib/cron/scheduled-posts/shared";

function createStats(): ProcessingStats {
	return {
		found: 0,
		published: 0,
		failed: 0,
		retried: 0,
		rateLimited: 0,
		errors: [],
	};
}

function createTestPost(overrides: Record<string, unknown> = {}) {
	return {
		id: "post-1",
		user_id: "user-1",
		account_id: "acc-1",
		content: "Hello Threads!",
		media_urls: null,
		media_type: null,
		hashtags: null,
		quoted_post_id: null,
		location_id: null,
		metadata: null,
		scheduled_for: new Date(Date.now() - 60000).toISOString(),
		retry_count: 0,
		accounts: {
			id: "acc-1",
			group_id: "group-1",
			threads_user_id: "tu-1",
			threads_access_token_encrypted: "enc-token-123",
			username: "testuser",
			is_active: true,
			token_expires_at: new Date(Date.now() + 86400000).toISOString(),
		},
		...overrides,
	};
}

/**
 * Set up mockFrom to return posts query and handle all table operations.
 * The DB chain must match the exact call patterns in publishThreads.ts:
 *
 * SELECT: .from("posts").select(...).eq().lte().eq().order().limit()
 * CLAIM:  .from("posts").update(...).eq("id").eq("status","scheduled").select().maybeSingle()
 * PUBLISH GUARD: .from("posts").update(...).eq("id").eq("status","publishing").select("id") → returns array
 *
 * For single posts, the update chain is called twice:
 *   1. claim (status → publishing) — maybeSingle returns {id}
 *   2. publish guard (status → published) — select returns [{id}]
 */
function setupDbMock(posts: ReturnType<typeof createTestPost>[]) {
	// Track update calls across ALL db().from("posts") invocations to differentiate
	// claim (odd calls) vs publish guard (even calls).
	// Must be outside mockImplementation since each db().from("posts") is a separate call.
	let postsUpdateCallIndex = 0;

	mockFrom.mockImplementation((table: string) => {
		if (table === "posts") {
			return {
				select: vi.fn().mockImplementation((columns?: string) => {
					selectedPostsColumns = String(columns ?? "");
					return {
						eq: vi.fn().mockReturnValue({
							lte: vi.fn().mockReturnValue({
								or: vi.fn().mockReturnValue({
									eq: vi.fn().mockReturnValue({
										order: vi.fn().mockReturnValue({
											limit: vi
												.fn()
												.mockResolvedValue({ data: posts, error: null }),
										}),
									}),
								}),
							}),
						}),
					};
				}),
				update: vi.fn().mockImplementation((data: any) => {
					postsUpdateCallIndex++;

					// Determine if this is a claim (status→publishing) or publish guard (status→published)
					// by inspecting the update payload.
					const isClaim = data?.status === "publishing";
					const isPublishGuard = data?.status === "published";

					// Build the .eq().eq() chain
					const innerEq = () => {
						const query: any = {
							select: vi.fn().mockImplementation(() => {
							if (isClaim) {
								// Claim: .select().maybeSingle()
								return {
									maybeSingle: vi.fn().mockResolvedValue({
										data: { id: posts[0]?.id || "post-1" },
										error: null,
									}),
								};
							}
							if (isPublishGuard) {
								// Publish guard: .select("id") returns resolved array
								return Promise.resolve({
									data: [{ id: posts[0]?.id || "post-1" }],
									error: null,
								});
							}
							// Other updates (failed, scheduled reschedule, etc)
							return Promise.resolve({ data: null, error: null });
						}),
							maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
						};
						query.or = vi.fn().mockReturnValue(query);
						return query;
					};

					return {
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockImplementation(() => innerEq()),
							// For patterns where there's only one .eq() after update (e.g. status update to failed)
							select: vi.fn().mockReturnValue({
								maybeSingle: vi.fn().mockResolvedValue({
									data: { id: posts[0]?.id || "post-1" },
									error: null,
								}),
							}),
							maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
						}),
					};
				}),
				insert: vi.fn().mockImplementation(() => {
					return {
						select: vi.fn().mockReturnValue({
							maybeSingle: vi.fn().mockResolvedValue({
								data: { id: posts[0]?.id || "post-1" },
								error: null,
							}),
						}),
					};
				}),
			};
		}

		if (table === "accounts") {
			return {
				update: vi.fn().mockReturnValue({
					eq: vi.fn().mockResolvedValue({ error: null }),
				}),
			};
		}

		if (table === "notifications") {
			return {
				insert: vi.fn().mockResolvedValue({ error: null }),
			};
		}

		if (table === "account_groups") {
			return {
				select: vi.fn().mockReturnValue({
					eq: vi.fn().mockReturnValue({
						contains: vi.fn().mockReturnValue({
							maybeSingle: vi
								.fn()
								.mockResolvedValue({ data: null, error: null }),
						}),
					}),
				}),
			};
		}

		if (table === "auto_post_group_config") {
			return {
				select: vi.fn().mockReturnValue({
					eq: vi.fn().mockReturnValue({
						maybeSingle: vi
							.fn()
							.mockResolvedValue({ data: null, error: null }),
					}),
				}),
			};
		}

		// Generic fallback
		return {
			select: vi.fn().mockReturnThis(),
			insert: vi.fn().mockReturnThis(),
			update: vi.fn().mockReturnValue({
				eq: vi.fn().mockResolvedValue({ error: null }),
			}),
			eq: vi.fn().mockReturnThis(),
			maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
		};
	});
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("processThreadsPosts", () => {
	let processThreadsPosts: typeof import("../../api/_lib/cron/scheduled-posts/publishThreads").processThreadsPosts;

	// Override global setTimeout to eliminate anti-detection delays in tests.
	// The source code uses `new Promise(resolve => setTimeout(resolve, 5000+))`
	// for anti-detection timing. We make those resolve instantly.
	const realSetTimeout = globalThis.setTimeout;
	beforeEach(async () => {
		vi.clearAllMocks();
		selectedPostsColumns = "";
		mockPostToThreads.mockReset();
		mockCheckAndIncrementRateLimit.mockReset().mockResolvedValue({ allowed: true });
		mockIsTransientError.mockReturnValue(false);
		mockIsDefinitiveOAuthError.mockReturnValue(false);
		mockCheckMediaUrlAccessible.mockResolvedValue(null);
		mockGetRateLimitStatus.mockResolvedValue({
			postsThisHour: 0,
			postsToday: 0,
			hourlyRemaining: 25,
			dailyRemaining: 250,
		});
		mockCheckSubscriptionPostLimit.mockReset().mockResolvedValue({
			allowed: true,
			tier: "pro",
			used: 5,
			limit: 100,
		});
		mockFetch.mockResolvedValue({
			ok: true,
			status: 200,
			json: () =>
				Promise.resolve({
					permalink: "https://threads.net/@user/post/123",
				}),
		});

		// Stub setTimeout to resolve instantly (avoids 5-25s anti-detection delays)
		vi.stubGlobal(
			"setTimeout",
			(cb: (...args: unknown[]) => void, _ms?: number) => {
				cb();
				return 0;
			},
		);

		// Re-import to get fresh module with mocks applied
		const mod = await import(
			"../../api/_lib/cron/scheduled-posts/publishThreads"
		);
		processThreadsPosts = mod.processThreadsPosts;
	});

	afterEach(() => {
		vi.stubGlobal("setTimeout", realSetTimeout);
		vi.restoreAllMocks();
	});

	// =========================================================================
	// 1. Empty queue
	// =========================================================================

	describe("empty queue", () => {
		it("returns immediately when no posts are due", async () => {
			setupDbMock([]);
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.found).toBe(0);
			expect(stats.published).toBe(0);
			expect(mockPostToThreads).not.toHaveBeenCalled();
		});

		it("reads group ownership from joined accounts instead of posts.group_id", async () => {
			setupDbMock([]);
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			const postColumns = selectedPostsColumns.split("accounts!inner")[0] ?? "";
			expect(postColumns).not.toMatch(/^\s*group_id,/m);
			expect(selectedPostsColumns).toContain("accounts!inner");
			expect(selectedPostsColumns).toMatch(/accounts!inner\s*\([\s\S]*group_id/);
		});
	});

	// =========================================================================
	// 2. Post selection query errors
	// =========================================================================

	describe("post selection query", () => {
		it("throws on Supabase query error", async () => {
			mockFrom.mockImplementation((table: string) => {
				if (table === "posts") {
					return {
						select: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								lte: vi.fn().mockReturnValue({
									or: vi.fn().mockReturnValue({
										eq: vi.fn().mockReturnValue({
											order: vi.fn().mockReturnValue({
												limit: vi.fn().mockResolvedValue({
													data: null,
													error: { message: "connection timeout" },
												}),
											}),
										}),
									}),
								}),
							}),
						}),
					};
				}
				return {};
			});

			const stats = createStats();
			await expect(
				processThreadsPosts(stats, Date.now(), 55000),
			).rejects.toEqual({ message: "connection timeout" });
		});
	});

	// =========================================================================
	// 3. Account validation
	// =========================================================================

	describe("account validation", () => {
		it("skips post with missing token and marks as failed", async () => {
			const post = createTestPost({
				accounts: {
					id: "acc-1",
					threads_user_id: "tu-1",
					threads_access_token_encrypted: null,
					username: "testuser",
					is_active: true,
					token_expires_at: null,
				},
			});
			setupDbMock([post]);
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.failed).toBe(1);
			expect(stats.errors[0]).toContain("Account not properly configured");
			expect(mockPostToThreads).not.toHaveBeenCalled();
		});

		it("skips post with missing threads_user_id and marks as failed", async () => {
			const post = createTestPost({
				accounts: {
					id: "acc-1",
					threads_user_id: null,
					threads_access_token_encrypted: "enc-token",
					username: "testuser",
					is_active: true,
					token_expires_at: null,
				},
			});
			setupDbMock([post]);
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.failed).toBe(1);
			expect(stats.errors[0]).toContain("Account not properly configured");
			expect(mockDeliverNotification).toHaveBeenCalled();
		});
	});

	// =========================================================================
	// 4. Account deactivated (is_active=false)
	// =========================================================================

	describe("account deactivated", () => {
		it("skips post for deactivated account without marking as failed", async () => {
			const post = createTestPost({
				accounts: {
					id: "acc-1",
					threads_user_id: "tu-1",
					threads_access_token_encrypted: "enc-token",
					username: "testuser",
					is_active: false,
					token_expires_at: null,
				},
			});
			setupDbMock([post]);
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.failed).toBe(0);
			expect(stats.published).toBe(0);
			expect(mockPostToThreads).not.toHaveBeenCalled();
		});
	});

	// =========================================================================
	// 5. Token expiry — skipped, NOT marked failed
	// =========================================================================

	describe("token expiry", () => {
		it("skips post with expired token without consuming retry count", async () => {
			const post = createTestPost({
				accounts: {
					id: "acc-1",
					threads_user_id: "tu-1",
					threads_access_token_encrypted: "enc-token",
					username: "testuser",
					is_active: true,
					token_expires_at: new Date(Date.now() - 3600000).toISOString(),
				},
			});
			setupDbMock([post]);
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.failed).toBe(0);
			expect(stats.published).toBe(0);
			expect(mockPostToThreads).not.toHaveBeenCalled();
		});
	});

	// =========================================================================
	// 6. Tier limit enforcement
	// =========================================================================

	describe("tier limit enforcement", () => {
		it("marks post as failed when user exceeds tier daily post limit", async () => {
			mockCheckSubscriptionPostLimit.mockResolvedValue({
				allowed: false,
				tier: "free",
				used: 10,
				limit: 5,
			});
			const post = createTestPost();
			setupDbMock([post]);
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.failed).toBe(1);
			expect(mockPostToThreads).not.toHaveBeenCalled();
		});

		it("skips publishing when tier check throws (fail-closed)", async () => {
			mockCheckSubscriptionPostLimit.mockRejectedValue(
				new Error("DB timeout"),
			);
			const post = createTestPost();
			setupDbMock([post]);
			mockPostToThreads.mockResolvedValue({
				success: true,
				threadId: "tid-1",
				timestamp: new Date(),
			});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(mockPostToThreads).not.toHaveBeenCalled();
		});
	});

	// =========================================================================
	// 7. Content validation
	// =========================================================================

	describe("content validation", () => {
		it("marks post as failed when content is empty", async () => {
			const post = createTestPost({ content: "" });
			setupDbMock([post]);
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.failed).toBe(1);
			expect(stats.errors[0]).toContain("Empty content");
			expect(mockPostToThreads).not.toHaveBeenCalled();
		});

		it("marks post as failed when content is whitespace-only", async () => {
			const post = createTestPost({ content: "   \n\t  " });
			setupDbMock([post]);
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.failed).toBe(1);
			expect(stats.errors[0]).toContain("Empty content");
		});

		it("marks post as failed when content exceeds 500 bytes", async () => {
			const post = createTestPost({ content: "A".repeat(501) });
			setupDbMock([post]);
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.failed).toBe(1);
			expect(stats.errors[0]).toContain("500 byte limit");
		});

		it("accepts post with exactly 500 chars", async () => {
			const post = createTestPost({ content: "A".repeat(500) });
			setupDbMock([post]);
			mockPostToThreads.mockResolvedValue({
				success: true,
				threadId: "tid-500",
				timestamp: new Date(),
			});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(mockPostToThreads).toHaveBeenCalled();
		});
	});

	// =========================================================================
	// 8. Successful single post publish
	// =========================================================================

	describe("successful single publish", () => {
		it("publishes post and updates status to published", async () => {
			const post = createTestPost();
			setupDbMock([post]);
			mockPostToThreads.mockResolvedValue({
				success: true,
				threadId: "tid-abc",
				timestamp: new Date(),
			});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.published).toBe(1);
			expect(stats.failed).toBe(0);
			expect(mockPostToThreads).toHaveBeenCalledWith(
				"enc-token-123",
				"tu-1",
				expect.objectContaining({ content: "Hello Threads!" }),
			);
		});

		it("fetches permalink after successful publish", async () => {
			const post = createTestPost();
			setupDbMock([post]);
			mockPostToThreads.mockResolvedValue({
				success: true,
				threadId: "tid-abc",
				timestamp: new Date(),
			});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(mockFetch).toHaveBeenCalledWith(
				expect.stringContaining("graph.threads.net/v1.0/tid-abc"),
				expect.objectContaining({
					headers: { Authorization: "Bearer decrypted-token" },
				}),
			);
		});

		it("increments rate limit counter after successful publish", async () => {
			const post = createTestPost();
			setupDbMock([post]);
			mockPostToThreads.mockResolvedValue({
				success: true,
				threadId: "tid-abc",
				timestamp: new Date(),
			});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(mockCheckAndIncrementRateLimit).toHaveBeenCalledWith("acc-1");
		});

		it("triggers cross-post after successful publish", async () => {
			const post = createTestPost();
			setupDbMock([post]);
			mockPostToThreads.mockResolvedValue({
				success: true,
				threadId: "tid-abc",
				timestamp: new Date(),
			});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(mockHandleCrossPost).toHaveBeenCalledWith(
				expect.objectContaining({ id: "post-1" }),
				"threads",
			);
		});

		it("sends published notification via safeInsertNotification", async () => {
			const post = createTestPost();
			setupDbMock([post]);
			mockPostToThreads.mockResolvedValue({
				success: true,
				threadId: "tid-notify",
				timestamp: new Date(),
			});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(mockSafeInsertNotification).toHaveBeenCalledWith(
				expect.objectContaining({
					user_id: "user-1",
					type: "post_published",
					title: "Scheduled post published",
				}),
				expect.objectContaining({
					postId: "post-1",
					platform: "threads",
					accountId: "acc-1",
				}),
			);
		});
	});

	// =========================================================================
	// 9. Rate limiting
	// =========================================================================

	describe("rate limiting", () => {
		it("skips post when hourly rate limit exhausted", async () => {
			mockGetRateLimitStatus.mockResolvedValue({
				postsThisHour: 25,
				postsToday: 25,
				hourlyRemaining: 0,
				dailyRemaining: 225,
			});
			const post = createTestPost();
			setupDbMock([post]);
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.rateLimited).toBe(1);
			expect(stats.failed).toBe(0);
			expect(mockPostToThreads).not.toHaveBeenCalled();
		});

		it("skips post when daily rate limit exhausted", async () => {
			mockGetRateLimitStatus.mockResolvedValue({
				postsThisHour: 5,
				postsToday: 250,
				hourlyRemaining: 20,
				dailyRemaining: 0,
			});
			const post = createTestPost();
			setupDbMock([post]);
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.rateLimited).toBe(1);
			expect(mockPostToThreads).not.toHaveBeenCalled();
		});

		it("rate limit increment failure after publish is non-fatal", async () => {
			const post = createTestPost();
			setupDbMock([post]);
			mockPostToThreads.mockResolvedValue({
				success: true,
				threadId: "tid-abc",
				timestamp: new Date(),
			});
			mockCheckAndIncrementRateLimit.mockRejectedValue(
				new Error("Redis down"),
			);
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.published).toBe(1);
		});
	});

	// =========================================================================
	// 10. Atomic claim — prevents duplicate processing
	// =========================================================================

	describe("atomic claim", () => {
		it("skips post when claim returns null (already claimed by another instance)", async () => {
			const post = createTestPost();
			mockFrom.mockImplementation((table: string) => {
				if (table === "posts") {
					return {
						select: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								lte: vi.fn().mockReturnValue({
									or: vi.fn().mockReturnValue({
										eq: vi.fn().mockReturnValue({
											order: vi.fn().mockReturnValue({
												limit: vi.fn().mockResolvedValue({
													data: [post],
													error: null,
												}),
											}),
										}),
									}),
								}),
							}),
						}),
						update: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								eq: vi.fn().mockReturnValue({
									or: vi.fn().mockReturnValue({
										select: vi.fn().mockReturnValue({
											maybeSingle: vi.fn().mockResolvedValue({
												data: null,
												error: null,
											}),
										}),
									}),
								}),
							}),
						}),
					};
				}
				return {
					insert: vi.fn().mockResolvedValue({ error: null }),
					update: vi.fn().mockReturnValue({
						eq: vi.fn().mockResolvedValue({ error: null }),
					}),
				};
			});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(mockPostToThreads).not.toHaveBeenCalled();
			expect(stats.published).toBe(0);
		});
	});

	// =========================================================================
	// 11. Transient error retry
	// =========================================================================

	describe("transient error retry", () => {
		it("reschedules post with exponential backoff on transient error", async () => {
			const post = createTestPost({ retry_count: 0 });
			setupDbMock([post]);
			mockPostToThreads.mockResolvedValue({
				success: false,
				error: "Temporary Meta server error (500)",
				timestamp: new Date(),
			});
			mockIsTransientError.mockReturnValue(true);
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.retried).toBe(1);
			expect(stats.failed).toBe(0);
		});

		it("marks post as permanently failed after 3 retries exhausted", async () => {
			const post = createTestPost({ retry_count: 3 });
			setupDbMock([post]);
			mockPostToThreads.mockResolvedValue({
				success: false,
				error: "Temporary Meta server error (500)",
				timestamp: new Date(),
			});
			mockIsTransientError.mockReturnValue(true);
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.failed).toBe(1);
			expect(stats.retried).toBe(0);
		});
	});

	// =========================================================================
	// 12. Permanent failure
	// =========================================================================

	describe("permanent failure", () => {
		it("marks post as failed on non-transient error", async () => {
			const post = createTestPost();
			setupDbMock([post]);
			mockPostToThreads.mockResolvedValue({
				success: false,
				error: "Content policy violation",
				timestamp: new Date(),
			});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.failed).toBe(1);
			expect(stats.errors[0]).toContain("Content policy violation");
			expect(mockDeliverNotification).toHaveBeenCalled();
		});

		it("delivers Discord notification on failure", async () => {
			const post = createTestPost();
			setupDbMock([post]);
			mockPostToThreads.mockResolvedValue({
				success: false,
				error: "API error",
				timestamp: new Date(),
			});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(mockDeliverNotification).toHaveBeenCalledWith(
				expect.objectContaining({
					userId: "user-1",
					type: "post_failed",
				}),
			);
		});
	});

	// =========================================================================
	// 13. Token/OAuth error handling — inline refresh
	// =========================================================================

	describe("token error handling", () => {
		it("attempts inline token refresh on OAuth error", async () => {
			const post = createTestPost();
			setupDbMock([post]);
			// First call fails with OAuth error, second (after refresh) succeeds
			mockPostToThreads
				.mockResolvedValueOnce({
					success: false,
					error:
						"Error validating access token: Session has been invalidated",
					timestamp: new Date(),
				})
				.mockResolvedValueOnce({
					success: true,
					threadId: "tid-refreshed",
					timestamp: new Date(),
				});
			mockIsDefinitiveOAuthError.mockReturnValue(true);
			// Token refresh endpoint returns success
			mockFetch.mockResolvedValue({
				ok: true,
				status: 200,
				json: () =>
					Promise.resolve({
						access_token: "new-fresh-token",
						expires_in: 5184000,
					}),
			});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(mockFetch).toHaveBeenCalledWith(
				expect.stringContaining("refresh_access_token"),
				expect.any(Object),
			);
			expect(stats.published).toBe(1);
		});

		it("flags account needs_reauth when refresh fails", async () => {
			const post = createTestPost();
			setupDbMock([post]);
			mockPostToThreads.mockResolvedValue({
				success: false,
				error:
					"Error validating access token: Session has been invalidated",
				timestamp: new Date(),
			});
			mockIsDefinitiveOAuthError.mockReturnValue(true);
			// Token refresh endpoint returns failure
			mockFetch.mockResolvedValue({
				ok: false,
				status: 400,
				json: () =>
					Promise.resolve({
						error: { message: "Invalid token", code: 190 },
					}),
			});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.failed).toBe(1);
			expect(stats.errors[0]).toContain("Token expired");
			expect(mockFrom).toHaveBeenCalledWith("accounts");
		});

		it("flags needs_reauth when refresh network request throws", async () => {
			const post = createTestPost();
			setupDbMock([post]);
			mockPostToThreads.mockResolvedValue({
				success: false,
				error:
					"Error validating access token: Session has been invalidated",
				timestamp: new Date(),
			});
			mockIsDefinitiveOAuthError.mockReturnValue(true);
			// fetch throws (network error)
			mockFetch.mockRejectedValue(new Error("ECONNRESET"));
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.failed).toBe(1);
			expect(stats.errors[0]).toContain("Token expired");
		});
	});

	// =========================================================================
	// 14. Transient OAuthException (code=1) should NOT flag needs_reauth
	// =========================================================================

	describe("transient Meta OAuthException", () => {
		it("does NOT flag needs_reauth for transient OAuthException code=1", async () => {
			const transientError =
				"An unknown error has occurred (code=1, type=OAuthException)";
			const post = createTestPost();
			setupDbMock([post]);
			mockPostToThreads.mockResolvedValue({
				success: false,
				error: transientError,
				timestamp: new Date(),
			});
			// isDefinitiveOAuthError returns false for transient OAuthException
			mockIsDefinitiveOAuthError.mockReturnValue(false);
			mockIsTransientError.mockReturnValue(true);
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.retried).toBe(1);
			expect(stats.failed).toBe(0);
		});
	});

	// =========================================================================
	// 15. Thread chain
	// =========================================================================

	describe("thread chain", () => {
		const SEPARATOR = "\n---THREAD_CHAIN_SEPARATOR---\n";

		it("publishes multi-part thread chain in correct sequence with reply_to_id chaining", async () => {
			const chainContent = `First post${SEPARATOR}Second post${SEPARATOR}Third post`;
			const post = createTestPost({ content: chainContent });
			setupDbMock([post]);

			let callCount = 0;
			mockPostToThreads.mockImplementation(async () => {
				callCount++;
				return {
					success: true,
					threadId: `tid-chain-${callCount}`,
					timestamp: new Date(),
				};
			});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.published).toBe(1);
			expect(mockPostToThreads).toHaveBeenCalledTimes(3);

			// First post: no replyToId
			const firstCallData = mockPostToThreads.mock.calls[0][2];
			expect(firstCallData.content).toBe("First post");
			expect(firstCallData.replyToId).toBeUndefined();

			// Second post: replies to first
			const secondCallData = mockPostToThreads.mock.calls[1][2];
			expect(secondCallData.content).toBe("Second post");
			expect(secondCallData.replyToId).toBe("tid-chain-1");

			// Third post: replies to second
			const thirdCallData = mockPostToThreads.mock.calls[2][2];
			expect(thirdCallData.content).toBe("Third post");
			expect(thirdCallData.replyToId).toBe("tid-chain-2");
		});

		it("falls through to single-post when chain has < 2 parts", async () => {
			const chainContent = `Only one part${SEPARATOR}`;
			const post = createTestPost({ content: chainContent });
			setupDbMock([post]);
			mockPostToThreads.mockResolvedValue({
				success: true,
				threadId: "tid-single",
				timestamp: new Date(),
			});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(mockPostToThreads).toHaveBeenCalled();
		});

		it("rejects chain when any post exceeds 500 chars", async () => {
			const longPost = "A".repeat(501);
			const chainContent = `Short post${SEPARATOR}${longPost}${SEPARATOR}Another short`;
			const post = createTestPost({ content: chainContent });
			setupDbMock([post]);
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.failed).toBe(1);
			expect(stats.errors[0]).toContain("500 bytes");
			expect(mockPostToThreads).not.toHaveBeenCalled();
		});

		it("skips chain when insufficient rate limit quota", async () => {
			const chainContent = `Post 1${SEPARATOR}Post 2${SEPARATOR}Post 3`;
			const post = createTestPost({ content: chainContent });
			setupDbMock([post]);
			mockGetRateLimitStatus.mockResolvedValue({
				postsThisHour: 24,
				postsToday: 248,
				hourlyRemaining: 1,
				dailyRemaining: 2,
			});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.rateLimited).toBe(1);
			expect(mockPostToThreads).not.toHaveBeenCalled();
		});

		it("records partial chain failure with orphaned thread IDs in metadata", async () => {
			const chainContent = `Post 1${SEPARATOR}Post 2${SEPARATOR}Post 3`;
			const post = createTestPost({ content: chainContent });
			setupDbMock([post]);

			let callCount = 0;
			mockPostToThreads.mockImplementation(async () => {
				callCount++;
				if (callCount <= 2) {
					return {
						success: true,
						threadId: `tid-chain-${callCount}`,
						timestamp: new Date(),
					};
				}
				return {
					success: false,
					error: "Container creation failed",
					timestamp: new Date(),
				};
			});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.failed).toBe(1);
			// The thrown error includes the chain post index; "Partially published" goes to DB metadata
			expect(stats.errors[0]).toContain("Failed to publish thread post 3");
			expect(stats.errors[0]).toContain("Container creation failed");
		});

		it("increments rate limit N times after successful chain publish", async () => {
			const chainContent = `Post 1${SEPARATOR}Post 2${SEPARATOR}Post 3`;
			const post = createTestPost({ content: chainContent });
			setupDbMock([post]);

			let callCount = 0;
			mockPostToThreads.mockImplementation(async () => {
				callCount++;
				return {
					success: true,
					threadId: `tid-chain-${callCount}`,
					timestamp: new Date(),
				};
			});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.published).toBe(1);
			expect(mockCheckAndIncrementRateLimit).toHaveBeenCalledTimes(3);
		});

		it("notifies user on chain failure", async () => {
			const chainContent = `Post 1${SEPARATOR}Post 2`;
			const post = createTestPost({ content: chainContent });
			setupDbMock([post]);

			mockPostToThreads
				.mockResolvedValueOnce({
					success: true,
					threadId: "tid-1",
					timestamp: new Date(),
				})
				.mockResolvedValueOnce({
					success: false,
					error: "Rate limit exceeded",
					timestamp: new Date(),
				});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.failed).toBe(1);
			expect(mockDeliverNotification).toHaveBeenCalledWith(
				expect.objectContaining({
					type: "post_failed",
					title: "Thread chain failed",
				}),
			);
		});
	});

	// =========================================================================
	// 16. Thread chain propagation retry
	// =========================================================================

	describe("thread chain propagation retry", () => {
		const SEPARATOR = "\n---THREAD_CHAIN_SEPARATOR---\n";

		it("retries chain post when reply target does not exist yet (propagation lag)", async () => {
			const chainContent = `First${SEPARATOR}Second`;
			const post = createTestPost({ content: chainContent });
			setupDbMock([post]);

			let callCount = 0;
			mockPostToThreads.mockImplementation(async () => {
				callCount++;
				if (callCount === 1) {
					return {
						success: true,
						threadId: "tid-1",
						timestamp: new Date(),
					};
				}
				if (callCount === 2) {
					return {
						success: false,
						error: "The post does not exist",
						timestamp: new Date(),
					};
				}
				return {
					success: true,
					threadId: "tid-2",
					timestamp: new Date(),
				};
			});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(mockPostToThreads).toHaveBeenCalledTimes(3);
			expect(stats.published).toBe(1);
		});
	});

	// =========================================================================
	// 17. Media UUID resolution
	// =========================================================================

	describe("media UUID resolution", () => {
		it("resolves non-HTTP media URLs (UUIDs) before publishing", async () => {
			const post = createTestPost({
				media_urls: ["uuid-123-abc", "uuid-456-def"],
			});
			setupDbMock([post]);
			mockPostToThreads.mockResolvedValue({
				success: true,
				threadId: "tid-media",
				timestamp: new Date(),
			});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(mockPostToThreads).toHaveBeenCalledWith(
				expect.any(String),
				expect.any(String),
				expect.objectContaining({
					media: expect.arrayContaining([
						expect.objectContaining({
							url: "https://cdn.example.com/img.jpg",
						}),
					]),
				}),
			);
		});
	});

	// =========================================================================
	// 18. Media URL accessibility
	// =========================================================================

	describe("media URL accessibility", () => {
		it("fails gracefully when media URL is inaccessible", async () => {
			const post = createTestPost({
				media_urls: ["https://cdn.example.com/expired.jpg"],
			});
			setupDbMock([post]);
			mockCheckMediaUrlAccessible.mockResolvedValue(
				"Media URL inaccessible: 404 Not Found. Please re-upload.",
			);
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.failed).toBe(1);
			expect(mockPostToThreads).not.toHaveBeenCalled();
		});
	});

	// =========================================================================
	// 19. Timeout guard
	// =========================================================================

	describe("timeout guard", () => {
		it("stops processing when approaching MAX_RUNTIME_MS", async () => {
			const posts = [
				createTestPost({ id: "post-1", account_id: "acc-1" }),
				createTestPost({ id: "post-2", account_id: "acc-1" }),
				createTestPost({ id: "post-3", account_id: "acc-1" }),
			];
			setupDbMock(posts);
			mockPostToThreads.mockResolvedValue({
				success: true,
				threadId: "tid-1",
				timestamp: new Date(),
			});

			const stats = createStats();
			const startTime = Date.now() - 60000;
			const MAX_RUNTIME_MS = 55000;

			await processThreadsPosts(stats, startTime, MAX_RUNTIME_MS);

			expect(mockPostToThreads).not.toHaveBeenCalled();
		});
	});

	// =========================================================================
	// 20. Parallel account processing
	// =========================================================================

	describe("parallel account processing", () => {
		it("groups posts by account_id for processing", async () => {
			const posts = [
				createTestPost({
					id: "post-1",
					account_id: "acc-A",
					accounts: {
						id: "acc-A",
						threads_user_id: "tu-A",
						threads_access_token_encrypted: "enc-A",
						username: "userA",
						is_active: true,
						status: "active",
						needs_reauth: false,
						token_expires_at: new Date(
							Date.now() + 86400000,
						).toISOString(),
					},
				}),
				createTestPost({
					id: "post-2",
					account_id: "acc-B",
					accounts: {
						id: "acc-B",
						threads_user_id: "tu-B",
						threads_access_token_encrypted: "enc-B",
						username: "userB",
						is_active: true,
						status: "active",
						needs_reauth: false,
						token_expires_at: new Date(
							Date.now() + 86400000,
						).toISOString(),
					},
				}),
			];
			setupDbMock(posts);
			mockPostToThreads.mockResolvedValue({
				success: true,
				threadId: "tid-parallel",
				timestamp: new Date(),
			});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.published).toBe(2);
			expect(mockPostToThreads).toHaveBeenCalledTimes(2);
		});
	});

	// =========================================================================
	// 21. PostData construction
	// =========================================================================

	describe("PostData construction", () => {
		it("includes hashtags as topics", async () => {
			const post = createTestPost({ hashtags: ["test", "threads"] });
			setupDbMock([post]);
			mockPostToThreads.mockResolvedValue({
				success: true,
				threadId: "tid-tags",
				timestamp: new Date(),
			});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(mockPostToThreads).toHaveBeenCalledWith(
				expect.any(String),
				expect.any(String),
				expect.objectContaining({
					topics: ["test", "threads"],
				}),
			);
		});

		it("includes quotePostId from quoted_post_id", async () => {
			const post = createTestPost({ quoted_post_id: "quoted-abc" });
			setupDbMock([post]);
			mockPostToThreads.mockResolvedValue({
				success: true,
				threadId: "tid-quote",
				timestamp: new Date(),
			});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(mockPostToThreads).toHaveBeenCalledWith(
				expect.any(String),
				expect.any(String),
				expect.objectContaining({
					quotePostId: "quoted-abc",
				}),
			);
		});

		it("includes metadata fields (linkUrl, crossreshareToIg, settings)", async () => {
			const post = createTestPost({
				metadata: {
					linkUrl: "https://example.com",
					crossreshareToIg: true,
					settings: {
						allowReplies: false,
						whoCanReply: "mentioned_only",
					},
				},
			});
			setupDbMock([post]);
			mockPostToThreads.mockResolvedValue({
				success: true,
				threadId: "tid-meta",
				timestamp: new Date(),
			});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(mockPostToThreads).toHaveBeenCalledWith(
				expect.any(String),
				expect.any(String),
				expect.objectContaining({
					linkUrl: "https://example.com",
					crossreshareToIg: true,
					settings: {
						allowReplies: false,
						whoCanReply: "mentioned_only",
					},
				}),
			);
		});

		it("detects media type from URL extension", async () => {
			const post = createTestPost({
				media_urls: [
					"https://cdn.example.com/photo.jpg",
					"https://cdn.example.com/clip.mp4",
				],
			});
			setupDbMock([post]);
			mockPostToThreads.mockResolvedValue({
				success: true,
				threadId: "tid-media-type",
				timestamp: new Date(),
			});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(mockPostToThreads).toHaveBeenCalledWith(
				expect.any(String),
				expect.any(String),
				expect.objectContaining({
					media: [
						{
							type: "image",
							url: "https://cdn.example.com/photo.jpg",
						},
						{
							type: "video",
							url: "https://cdn.example.com/clip.mp4",
						},
					],
				}),
			);
		});
	});

	// =========================================================================
	// 22. Publish guard — rejection between claim and publish
	// =========================================================================

	describe("publish guard", () => {
		it("skips post when status changed between claim and publish completion", async () => {
			const post = createTestPost();
			let updateCallNum = 0;
			mockFrom.mockImplementation((table: string) => {
				if (table === "posts") {
					return {
						select: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								lte: vi.fn().mockReturnValue({
									or: vi.fn().mockReturnValue({
										eq: vi.fn().mockReturnValue({
											order: vi.fn().mockReturnValue({
												limit: vi.fn().mockResolvedValue({
													data: [post],
													error: null,
												}),
											}),
										}),
									}),
								}),
							}),
						}),
						update: vi.fn().mockImplementation(() => {
							updateCallNum++;
							const callNum = updateCallNum;
							return {
								eq: vi.fn().mockReturnValue({
									eq: vi.fn().mockReturnValue({
										or: vi.fn().mockReturnValue({
											select: vi.fn().mockImplementation(() => {
												if (callNum === 1) {
													// Claim succeeds
													return {
														maybeSingle: vi.fn().mockResolvedValue({
															data: { id: "post-1" },
															error: null,
														}),
													};
												}
												// Publish guard returns empty array (post was rejected)
												return Promise.resolve({
													data: [],
													error: null,
												});
											}),
										}),
									}),
								}),
							};
						}),
					};
				}
				return {
					insert: vi.fn().mockResolvedValue({ error: null }),
					update: vi.fn().mockReturnValue({
						eq: vi.fn().mockResolvedValue({ error: null }),
					}),
				};
			});

			mockPostToThreads.mockResolvedValue({
				success: true,
				threadId: "tid-guard",
				timestamp: new Date(),
			});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.published).toBe(0);
		});
	});

	// =========================================================================
	// 23. Permalink fetch failure is non-fatal
	// =========================================================================

	describe("permalink fetch", () => {
		it("continues publishing even when permalink fetch fails", async () => {
			const post = createTestPost();
			setupDbMock([post]);
			mockPostToThreads.mockResolvedValue({
				success: true,
				threadId: "tid-nolink",
				timestamp: new Date(),
			});
			// Permalink fetch throws
			mockFetch.mockRejectedValue(new Error("Network error"));
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.published).toBe(1);
		});
	});

	// =========================================================================
	// 24. Multiple posts same account — sequential processing
	// =========================================================================

	describe("sequential processing within account", () => {
		it("processes multiple posts for same account sequentially", async () => {
			const posts = [
				createTestPost({ id: "post-1", account_id: "acc-1" }),
				createTestPost({ id: "post-2", account_id: "acc-1" }),
			];
			setupDbMock(posts);

			const publishOrder: string[] = [];
			mockPostToThreads.mockImplementation(
				async (_t: string, _u: string, data: any) => {
					publishOrder.push(data.content);
					return {
						success: true,
						threadId: `tid-${publishOrder.length}`,
						timestamp: new Date(),
					};
				},
			);
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.published).toBe(2);
			expect(publishOrder).toHaveLength(2);
		});
	});

	// =========================================================================
	// 25. Stats tracking
	// =========================================================================

	describe("stats tracking", () => {
		it("sets stats.found to the number of posts returned by query", async () => {
			const posts = [
				createTestPost({ id: "post-1" }),
				createTestPost({ id: "post-2" }),
				createTestPost({ id: "post-3" }),
			];
			setupDbMock(posts);
			mockPostToThreads.mockResolvedValue({
				success: true,
				threadId: "tid-x",
				timestamp: new Date(),
			});
			const stats = createStats();

			await processThreadsPosts(stats, Date.now(), 55000);

			expect(stats.found).toBe(3);
		});
	});
});
