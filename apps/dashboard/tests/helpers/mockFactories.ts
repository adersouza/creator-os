/**
 * Shared mock factories for publish-related unit tests.
 *
 * Centralises the Supabase chain mocks, request/response helpers,
 * and test-data factories so individual test files stay focused
 * on assertions rather than setup boilerplate.
 */

import { vi } from "vitest";

// ---------------------------------------------------------------------------
// Request / Response helpers
// ---------------------------------------------------------------------------

/** Creates a chainable mock Express-style response object. */
export function mockRes() {
	const res: Record<string, any> = {};
	res.status = vi.fn().mockReturnValue(res);
	res.json = vi.fn().mockReturnValue(res);
	res.setHeader = vi.fn().mockReturnValue(res);
	return res;
}

/** Creates a mock request for the publish handler (Threads default). */
export function mockPublishReq(body: Record<string, unknown> = {}) {
	return {
		method: "POST",
		query: { action: "publish" },
		body,
		headers: {},
	};
}

/** Creates a mock request for the auto-post-publish handler. */
export function mockAutoPostReq(
	body: Record<string, unknown>,
	headers: Record<string, string> = {},
) {
	return { method: "POST", body, headers } as any;
}

// ---------------------------------------------------------------------------
// Generic chainable Supabase mock (auto-post style)
// ---------------------------------------------------------------------------

/**
 * Returns an object where every common Supabase chain method is
 * stubbed.  Terminal methods (`maybeSingle`, `single`) resolve with
 * `finalValue`; all others return the chain itself.
 */
export function createChainMock(finalValue: unknown) {
	const chain: any = {};
	const methods = [
		"select", "eq", "in", "not", "or", "is", "gte", "lt", "lte",
		"neq", "maybeSingle", "single", "limit", "order", "update", "insert",
	];
	for (const m of methods) {
		if (m === "maybeSingle" || m === "single") {
			chain[m] = vi.fn().mockResolvedValue(finalValue);
		} else {
			chain[m] = vi.fn().mockReturnValue(chain);
		}
	}
	return chain;
}

// ---------------------------------------------------------------------------
// Table-aware Supabase mock (publish handlers)
// ---------------------------------------------------------------------------

export interface PublishSupabaseOverrides {
	profile?: { subscription_tier: string; extra_accounts?: number } | null;
	account?: Record<string, unknown> | null;
	igAccount?: Record<string, unknown> | null;
	igAccountError?: unknown;
	autoPostQueueRows?: Record<string, unknown>[];
	postOriginalitySignals?: Record<string, unknown>[];
	rateLimit?: { allowed: boolean; daily_limit: number; daily_used: number }[];
	rateLimitError?: unknown;
	postInsert?: { id: string } | null;
	postInsertError?: { message: string } | null;
	postCount?: number;
	threadsCount?: number;
	igCount?: number;
}

/**
 * Builds a table-aware Supabase mock whose `.from(table)` returns
 * the appropriate chain for profiles / accounts / instagram_accounts /
 * posts / media.  Used by both the Threads and Instagram publish tests.
 */
export function createPublishSupabaseMock(
	overrides: PublishSupabaseOverrides,
	rpcFn?: ReturnType<typeof vi.fn>,
) {
	const mockRpc = rpcFn ?? vi.fn();

	return {
		from: vi.fn().mockImplementation((table: string) => {
			if (table === "profiles") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							maybeSingle: vi.fn().mockResolvedValue({
								data: overrides.profile ?? { subscription_tier: "pro" },
								error: null,
							}),
						}),
					}),
				};
			}

			if (table === "instagram_accounts") {
				return {
					select: vi.fn().mockImplementation((_cols: string, opts?: any) => {
						if (opts?.count === "exact") {
							return {
								eq: vi.fn().mockReturnValue({
									eq: vi.fn().mockResolvedValue({
										count: overrides.igCount ?? (overrides.igAccount ? 1 : 0),
										error: null,
									}),
								}),
							};
						}
						return {
							eq: vi.fn().mockReturnValue({
								eq: vi.fn().mockReturnValue({
									maybeSingle: vi.fn().mockResolvedValue({
										data: overrides.igAccount !== undefined
											? overrides.igAccount
											: null,
										error: overrides.igAccountError ?? null,
									}),
									order: vi.fn().mockReturnValue({
										limit: vi.fn().mockResolvedValue({
											data: overrides.igAccount
												? [{ id: (overrides.igAccount as any).id || "ig-acc-1" }]
												: [],
											error: null,
										}),
									}),
								}),
							}),
						};
					}),
				};
			}

			if (table === "accounts") {
				return {
					select: vi.fn().mockImplementation((_cols: string, opts?: any) => {
						if (opts?.count === "exact") {
							return {
								eq: vi.fn().mockReturnValue({
									eq: vi.fn().mockResolvedValue({
										count: overrides.threadsCount ?? (overrides.account ? 1 : 0),
										error: null,
									}),
								}),
							};
						}
						return {
							eq: vi.fn().mockReturnValue({
								eq: vi.fn().mockReturnValue({
									maybeSingle: vi.fn().mockResolvedValue({
										data: overrides.account !== undefined
											? overrides.account
											: null,
										error: null,
									}),
									order: vi.fn().mockReturnValue({
										limit: vi.fn().mockResolvedValue({
											data: overrides.account
												? [{ id: (overrides.account as any).id || "acc-1" }]
												: [],
											error: null,
										}),
									}),
								}),
							}),
						};
					}),
					insert: vi.fn().mockReturnValue({
						select: vi.fn().mockReturnValue({
							single: vi.fn().mockResolvedValue({ data: null, error: null }),
						}),
					}),
					update: vi.fn().mockReturnValue({
						eq: vi.fn().mockResolvedValue({ error: null }),
					}),
				};
			}

			if (table === "posts") {
				return {
					select: vi.fn().mockImplementation((_cols: string, opts?: any) => {
						if (opts?.count === "exact") {
							const countResult = {
								count: overrides.postCount ?? 0,
								error: null,
							};
							const chain: any = {};
							chain.eq = vi.fn().mockReturnValue(chain);
							chain.is = vi.fn().mockReturnValue(chain);
							chain.gte = vi.fn().mockReturnValue(chain);
							chain.lt = vi.fn().mockResolvedValue(countResult);
							return chain;
						}
						return {
							eq: vi.fn().mockReturnThis(),
							maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
						};
					}),
					insert: vi.fn().mockReturnValue({
						select: vi.fn().mockReturnValue({
							maybeSingle: vi.fn().mockResolvedValue({
								data: overrides.postInsert ?? { id: "post-123" },
								error: overrides.postInsertError ?? null,
							}),
						}),
					}),
					update: vi.fn().mockReturnValue({
						eq: vi.fn().mockResolvedValue({ error: null }),
					}),
				};
			}

			if (table === "media") {
				return {
					select: vi.fn().mockReturnValue({
						in: vi.fn().mockReturnValue({
							eq: vi.fn().mockResolvedValue({ data: [], error: null }),
						}),
					}),
				};
			}

			if (table === "auto_post_queue") {
				const chain: any = {};
				for (const method of [
					"select",
					"eq",
					"neq",
					"not",
					"in",
					"gte",
					"order",
					"limit",
				]) {
					chain[method] = vi.fn().mockReturnValue(chain);
				}
				chain.then = (resolve: (value: unknown) => unknown) =>
					Promise.resolve({
						data: overrides.autoPostQueueRows ?? [],
						error: null,
					}).then(resolve);
				return chain;
			}

			if (table === "post_originality_signals") {
				const chain: any = {};
				for (const method of [
					"select",
					"eq",
					"neq",
					"not",
					"gte",
					"order",
					"limit",
				]) {
					chain[method] = vi.fn().mockReturnValue(chain);
				}
				chain.then = (resolve: (value: unknown) => unknown) =>
					Promise.resolve({
						data: overrides.postOriginalitySignals ?? [],
						error: null,
					}).then(resolve);
				return chain;
			}

			// Fallback for any other table
			return {
				select: vi.fn().mockReturnThis(),
				insert: vi.fn().mockReturnThis(),
				update: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
			};
		}),
		rpc: mockRpc.mockResolvedValue({
			data: overrides.rateLimit ?? [{ allowed: true, daily_limit: 250, daily_used: 5 }],
			error: overrides.rateLimitError ?? null,
		}),
		storage: {
			from: vi.fn().mockReturnValue({
				createSignedUrl: vi.fn(),
			}),
		},
	};
}

/**
 * Patches a `createPublishSupabaseMock` instance so the `posts.insert`
 * call captures the inserted row into the returned ref object.
 *
 * Usage:
 *   const sb = createPublishSupabaseMock({ ... });
 *   const capture = interceptPostsInsert(sb, "post-carousel-1");
 *   // ... run handler ...
 *   expect(capture.data.ig_media_type).toBe("CAROUSEL");
 */
export function interceptPostsInsert(
	sb: ReturnType<typeof createPublishSupabaseMock>,
	postId: string,
) {
	const capture: { data: any } = { data: null };
	const originalFrom = sb.from;
	sb.from = vi.fn().mockImplementation((table: string) => {
		const result = originalFrom(table);
		if (table === "posts") {
			return {
				...result,
				insert: vi.fn().mockImplementation((data: any) => {
					capture.data = data;
					return {
						select: vi.fn().mockReturnValue({
							maybeSingle: vi.fn().mockResolvedValue({
								data: { id: postId },
								error: null,
							}),
						}),
					};
				}),
			};
		}
		return result;
	});
	return capture;
}

// ---------------------------------------------------------------------------
// Test data factories
// ---------------------------------------------------------------------------

export function createTestProfile(overrides?: Partial<{
	subscription_tier: string;
	extra_accounts: number;
}>) {
	return {
		subscription_tier: "pro",
		...overrides,
	};
}

export function createTestThreadsAccount(overrides?: Partial<{
	id: string;
	user_id: string;
	threads_user_id: string | null;
	username: string;
	threads_access_token_encrypted: string | null;
	is_retired: boolean;
	needs_reauth: boolean;
	is_shadowbanned: boolean;
	status: string | null;
}>) {
	return {
		id: "acc-1",
		user_id: "user-1",
		threads_user_id: "tu-1",
		username: "testuser",
		threads_access_token_encrypted: "enc-token",
		is_retired: false,
		needs_reauth: false,
		is_shadowbanned: false,
		status: null,
		...overrides,
	};
}

export function createTestInstagramAccount(overrides?: Partial<{
	id: string;
	user_id: string;
	instagram_user_id: string;
	username: string;
	instagram_access_token_encrypted: string | null;
	facebook_page_access_token_encrypted: string | null;
}>) {
	return {
		id: "ig-acc-1",
		user_id: "user-1",
		instagram_user_id: "ig-user-1",
		username: "iguser",
		instagram_access_token_encrypted: "enc-ig-token",
		facebook_page_access_token_encrypted: null,
		...overrides,
	};
}

export function createTestQueueItem(overrides?: Partial<{
	id: string;
	status: string;
	content: string;
	media_urls: string[] | null;
	source_content: string | null;
	source_type: string;
	retry_count: number;
	text_spoilers: string | null;
	topic_tag: string | null;
	schedule_nonce: string | null;
	next_retry_at: string | null;
	scheduled_for: string | null;
	claim_token: string | null;
	claim_expires_at: string | null;
	content_fingerprint: string | null;
	generation_id: string | null;
	source_id: string | null;
	publish_fingerprint: string | null;
	provenance_status: string | null;
	provenance_error: string | null;
	metadata: Record<string, unknown> | null;
}>) {
	return {
		id: "q1",
		status: "pending",
		content: "test post content",
		media_urls: null,
		source_content: null,
		source_type: "ai",
		retry_count: 0,
		text_spoilers: null,
		topic_tag: null,
		schedule_nonce: null,
		next_retry_at: null,
		scheduled_for: new Date(Date.now() - 60_000).toISOString(),
		claim_token: null,
		claim_expires_at: null,
		content_fingerprint: "content-fingerprint-1",
		generation_id: "generation-1",
		source_id: "group:group-1",
		publish_fingerprint: "publish-fingerprint-1",
		provenance_status: "verified",
		provenance_error: null,
		metadata: {
			quality_gate: {
				decision: "pass",
				reason: "quality_gate_passed",
				confidences: {},
				flags: [],
				score: { overall: 4 },
			},
			judge: {
				score: 4,
				dimensions: {},
				rationale: null,
			},
		},
		...overrides,
	};
}
