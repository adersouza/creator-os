import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

/**
 * Unit tests for POST /api/posts?action=bulk-schedule-groups
 *
 * Covers: group-level scheduling, round-robin distribution, media auto-attach,
 * cap enforcement, cross-platform paths, error handling, edge cases.
 */

// ---------------------------------------------------------------------------
// Mocks — must be declared BEFORE importing module under test
// ---------------------------------------------------------------------------

const mockCheckDailyCap = vi.fn();
const mockPublishableAccountFilters = vi.fn();
const mockGetRandomMediaWithContext = vi.fn();
const mockDispatchPostPublish = vi.fn();

/** Table-routing Supabase mock — returns chainable objects per table. */
function createBulkScheduleSupabase(opts: {
	ownedGroups?: { id: string }[];
	groupConfigs?: {
		group_id: string;
		crossreshare_to_ig?: boolean | null;
		crossreshare_to_ig_dark_mode?: boolean | null;
		media_attachment_chance?: number | null;
	}[];
	accountsByQuery?: { id: string }[];
	mediaByIds?: { id: string; file_type?: string }[];
	postInsert?: { id: string } | null;
	postInsertError?: { message: string; code?: string; hint?: string; details?: string } | null;
}) {
	return {
		from: vi.fn().mockImplementation((table: string) => {
			if (table === "account_groups") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							in: vi.fn().mockResolvedValue({
								data: opts.ownedGroups ?? [{ id: "group-1" }],
								error: null,
							}),
						}),
					}),
				};
			}

			if (table === "auto_post_group_config") {
				return {
					select: vi.fn().mockReturnValue({
						in: vi.fn().mockResolvedValue({
							data: opts.groupConfigs ?? [],
							error: null,
						}),
					}),
				};
			}

			// accounts / instagram_accounts — used by getGroupAccounts
			if (table === "accounts" || table === "instagram_accounts") {
				const accountData = opts.accountsByQuery ?? [{ id: "acc-1" }];
				// publishableAccountFilters receives the chain and returns chain
				// The mock intercepts via mockPublishableAccountFilters
				const chain: any = {};
				chain.select = vi.fn().mockReturnValue(chain);
				chain.eq = vi.fn().mockReturnValue(chain);
				chain.or = vi.fn().mockReturnValue(chain);
				chain.maybeSingle = vi.fn().mockResolvedValue({
					data:
						table === "instagram_accounts"
							? {
									id: accountData[0]?.id ?? "ig-acc-1",
									instagram_user_id: "17841400000000000",
									instagram_access_token_encrypted: "ig-token",
									login_type: "instagram",
									is_active: true,
									needs_reauth: false,
									status: null,
									token_expires_at: new Date(Date.now() + 7 * 86400000).toISOString(),
								}
							: {
									id: accountData[0]?.id ?? "acc-1",
									threads_user_id: "threads-user-1",
									threads_access_token_encrypted: "threads-token",
									is_active: true,
									needs_reauth: false,
									status: null,
									token_expires_at: new Date(Date.now() + 7 * 86400000).toISOString(),
								},
					error: null,
				});
				// Terminal — publishableAccountFilters calls are applied then .then resolves
				// We resolve via mockPublishableAccountFilters
				mockPublishableAccountFilters.mockResolvedValue({
					data: accountData,
					error: null,
				});
				return chain;
			}

			if (table === "media") {
				return {
					select: vi.fn().mockReturnValue({
						in: vi.fn().mockReturnValue({
							eq: vi.fn().mockResolvedValue({
								data: opts.mediaByIds ?? [],
								error: null,
							}),
						}),
					}),
				};
			}

			if (table === "posts") {
				return {
					insert: vi.fn().mockReturnValue({
						select: vi.fn().mockReturnValue({
							maybeSingle: vi.fn().mockResolvedValue({
								data: opts.postInsert !== undefined ? opts.postInsert : { id: "post-new-1" },
								error: opts.postInsertError !== undefined ? opts.postInsertError : null,
							}),
						}),
					}),
				};
			}

			// fallback
			return {
				select: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				in: vi.fn().mockReturnThis(),
				maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
			};
		}),
	};
}

let currentSupabase: ReturnType<typeof createBulkScheduleSupabase>;

vi.mock("@/api/_lib/supabase.js", () => ({
	getSupabase: () => currentSupabase,
}));

vi.mock("@/api/_lib/logger.js", () => ({
	logger: {
		info: vi.fn(),
		warn: vi.fn(),
		error: vi.fn(),
		debug: vi.fn(),
	},
}));

vi.mock("@/api/_lib/apiResponse.js", () => ({
	apiError: (res: any, status: number, msg: string, extra?: any) =>
		res.status(status).json({ error: msg, ...extra }),
	apiSuccess: (res: any, data: unknown) =>
		res.status(200).json({ success: true, ...(data as Record<string, unknown>) }),
}));

vi.mock("@/api/_lib/sanitize.js", () => ({
	sanitizeHtml: (s: string) => s,
}));

// Zod v4 workaround — zRecord(zUnknown()) crashes. Provide passthrough stubs.
vi.mock("@/api/_lib/zodCompat.js", async () => {
	const { z } = await import("zod");
	return {
		z,
		zEnum: (vals: string[]) => z.enum(vals as [string, ...string[]]),
		zLiteral: (val: unknown) => z.literal(val as any),
		zUnknown: () => z.any(),
		zRecord: (...args: any[]) => {
			if (args.length === 1) return z.record(z.string(), args[0]);
			if (args.length === 0) return z.record(z.string(), z.any());
			return z.record(args[0], args[1]);
		},
		zArray: (schema: any) => z.array(schema),
		zString: () => z.string(),
	};
});

vi.mock("@/api/_lib/validation.js", () => {
	return {
		parseBodyOrError: (res: any, schema: any, body: unknown) => {
			const result = schema.safeParse(body);
			if (!result.success) {
				const messages = result.error.issues
					.map((i: any) => `${i.path.join(".")}: ${i.message}`)
					.join("; ");
				res.status(400).json({ error: messages });
				return null;
			}
			return result.data;
		},
	};
});

vi.mock("@/api/_lib/accountEligibility.js", () => ({
	publishableAccountFilters: (query: any) => mockPublishableAccountFilters(query),
}));

vi.mock("@/api/_lib/dailyCap.js", () => ({
	checkDailyCap: (...args: unknown[]) => mockCheckDailyCap(...args),
	DAILY_CAP: 250,
}));

vi.mock("@/api/_lib/handlers/posts/shared.js", () => ({
	checkSubscriptionPostLimit: vi.fn().mockResolvedValue({
		allowed: true,
		tier: "pro",
		used: 0,
		limit: 50,
	}),
	normalizePostMediaType: (type: string | null | undefined, fallback = "text") => {
		if (!type) return fallback;
		const lower = type.trim().toLowerCase();
		const map: Record<string, string> = {
			text: "text",
			image: "image",
			video: "video",
			carousel: "carousel",
			carousel_album: "carousel",
		};
		return map[lower] || fallback;
	},
	resolveMediaUrls: vi.fn().mockResolvedValue({
		urls: ["https://cdn.example.com/owned.jpg"],
		items: [{ type: "image", url: "https://cdn.example.com/owned.jpg" }],
	}),
}));

vi.mock("@/api/_lib/publishPreflight.js", () => ({
	runPublishPreflight: vi.fn().mockResolvedValue({
		ok: true,
		issues: [],
		summary: { errors: 0, warnings: 0, infos: 0 },
	}),
}));

vi.mock("@/api/_lib/handlers/auto-post/publisher.js", () => ({
	getRandomMediaWithContext: (...args: unknown[]) => mockGetRandomMediaWithContext(...args),
}));

vi.mock("@/api/_lib/qstashSchedule.js", () => ({
	dispatchPostPublish: (...args: unknown[]) => mockDispatchPostPublish(...args),
}));

// ---------------------------------------------------------------------------
// Import module under test AFTER mocks
// ---------------------------------------------------------------------------

import { handleBulkScheduleGroups } from "@/api/_lib/handlers/posts/bulkScheduleGroups";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const USER_ID = "user-123";

function futureISO(minutesFromNow = 60): string {
	return new Date(Date.now() + minutesFromNow * 60_000).toISOString();
}

function makeReq(body: Record<string, unknown>) {
	return {
		method: "POST",
		query: { action: "bulk-schedule-groups" },
		body,
		headers: {},
	} as any;
}

function makePost(overrides: Record<string, unknown> = {}) {
	return {
		groupId: "group-1",
		platform: "threads",
		content: "Test post content",
		scheduledFor: futureISO(),
		...overrides,
	};
}

// ---------------------------------------------------------------------------
// Test suites
// ---------------------------------------------------------------------------

describe("handleBulkScheduleGroups", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockCheckDailyCap.mockResolvedValue({ allowed: true, used: 0, limit: 250 });
		mockDispatchPostPublish.mockResolvedValue("msg-id");
		mockGetRandomMediaWithContext.mockResolvedValue(null);
		currentSupabase = createBulkScheduleSupabase({});
	});

	afterEach(() => {
		vi.restoreAllMocks();
	});

	// =========================================================================
	// 1. Group-level scheduling — posts distributed across accounts
	// =========================================================================
	describe("group-level scheduling", () => {
		it("schedules a single post to a group account", async () => {
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({ posts: [makePost()] }),
				res as any,
				USER_ID,
			);
			expect(res.status).toHaveBeenCalledWith(200);
			const body = res.json.mock.calls[0][0];
			expect(body.scheduledCount).toBe(1);
			expect(body.failedCount).toBe(0);
			expect(body.scheduled[0].accountId).toBe("acc-1");
			expect(body.scheduled[0].platform).toBe("threads");
		});

		it("round-robins across multiple accounts in a group", async () => {
			currentSupabase = createBulkScheduleSupabase({
				accountsByQuery: [{ id: "acc-A" }, { id: "acc-B" }, { id: "acc-C" }],
			});
			const res = mockRes();
			const posts = [
				makePost({ content: "Post 1" }),
				makePost({ content: "Post 2" }),
				makePost({ content: "Post 3" }),
				makePost({ content: "Post 4" }),
			];
			await handleBulkScheduleGroups(
				makeReq({ posts }),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			expect(body.scheduledCount).toBe(4);
			// Round-robin: A, B, C, A
			expect(body.scheduled[0].accountId).toBe("acc-A");
			expect(body.scheduled[1].accountId).toBe("acc-B");
			expect(body.scheduled[2].accountId).toBe("acc-C");
			expect(body.scheduled[3].accountId).toBe("acc-A");
		});

		it("dispatches QStash for each successfully scheduled post", async () => {
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({ posts: [makePost(), makePost()] }),
				res as any,
				USER_ID,
			);
			expect(mockDispatchPostPublish).toHaveBeenCalledTimes(2);
		});

		it("surfaces exact-dispatch failure and saves the inserted post as draft", async () => {
			mockDispatchPostPublish.mockRejectedValue(new Error("QStash unavailable"));
			let updatedDraft = false;
			const originalFrom = currentSupabase.from;
			currentSupabase.from = vi.fn().mockImplementation((table: string) => {
				if (table === "posts") {
					return {
						insert: vi.fn().mockReturnValue({
							select: vi.fn().mockReturnValue({
								maybeSingle: vi.fn().mockResolvedValue({
									data: { id: "post-qstash-failed" },
									error: null,
								}),
							}),
						}),
						update: vi.fn().mockImplementation(() => {
							updatedDraft = true;
							return {
								eq: vi.fn().mockReturnThis(),
							};
						}),
					};
				}
				return originalFrom(table);
			});
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({ posts: [makePost()] }),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			expect(body.scheduledCount).toBe(0);
			expect(body.failedCount).toBe(1);
			expect(body.failed[0].code).toBe("EXACT_SCHEDULE_UNAVAILABLE");
			expect(updatedDraft).toBe(true);
		});
	});

	// =========================================================================
	// 2. Media auto-attachment — IG always gets media, Threads configurable
	// =========================================================================
	describe("media auto-attachment", () => {
		it("always attaches media for Instagram when available", async () => {
			mockGetRandomMediaWithContext.mockResolvedValue({
				id: "media-1",
				url: "https://cdn.example.com/photo.jpg",
				description: "A nice photo",
				tags: null,
				isVideo: false,
			});
			currentSupabase = createBulkScheduleSupabase({
				ownedGroups: [{ id: "group-1" }],
			});
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({ posts: [makePost({ platform: "instagram" })] }),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			expect(body.scheduledCount).toBe(1);
			expect(body.scheduled[0].mediaAttached).toBe(true);
			expect(body.scheduled[0].mediaDescription).toBe("A nice photo");
		});

		it("fails Instagram post when no media available and mediaIds omitted", async () => {
			mockGetRandomMediaWithContext.mockResolvedValue(null);
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({ posts: [makePost({ platform: "instagram" })] }),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			expect(body.failedCount).toBe(1);
			expect(body.failed[0].reason).toContain("Instagram requires media");
		});

		it("fails Instagram post when media fetch throws", async () => {
			mockGetRandomMediaWithContext.mockRejectedValue(new Error("Media DB error"));
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({ posts: [makePost({ platform: "instagram" })] }),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			expect(body.failedCount).toBe(1);
			expect(body.failed[0].reason).toContain("media selection failed");
		});

		it("attaches media for Threads based on media_attachment_chance config", async () => {
			// Set chance to 100% so it always attaches
			currentSupabase = createBulkScheduleSupabase({
				groupConfigs: [
					{ group_id: "group-1", media_attachment_chance: 100 },
				],
			});
			mockGetRandomMediaWithContext.mockResolvedValue({
				id: "media-2",
				url: "https://cdn.example.com/image.png",
				description: "Threads image",
				tags: null,
				isVideo: false,
			});
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({ posts: [makePost()] }),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			expect(body.scheduledCount).toBe(1);
			expect(body.scheduled[0].mediaAttached).toBe(true);
		});

		it("does not attach media for Threads when media_attachment_chance is 0", async () => {
			currentSupabase = createBulkScheduleSupabase({
				groupConfigs: [
					{ group_id: "group-1", media_attachment_chance: 0 },
				],
			});
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({ posts: [makePost()] }),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			expect(body.scheduledCount).toBe(1);
			// Should NOT have media attached
			expect(body.scheduled[0].mediaAttached).toBeUndefined();
			expect(mockGetRandomMediaWithContext).not.toHaveBeenCalled();
		});

		it("defaults Threads media_attachment_chance to text-only when not configured", async () => {
			vi.spyOn(Math, "random").mockReturnValue(0);
			mockGetRandomMediaWithContext.mockResolvedValue({
				id: "media-3",
				url: "https://cdn.example.com/auto.jpg",
				description: null,
				tags: null,
			});
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({ posts: [makePost()] }),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			expect(body.scheduled[0].mediaAttached).toBeUndefined();
			expect(mockGetRandomMediaWithContext).not.toHaveBeenCalled();
		});

		it("proceeds text-only for Threads when media fetch fails", async () => {
			vi.spyOn(Math, "random").mockReturnValue(0);
			mockGetRandomMediaWithContext.mockRejectedValue(new Error("DB fail"));
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({ posts: [makePost()] }),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			// Threads should proceed text-only, no failure
			expect(body.scheduledCount).toBe(1);
			expect(body.failedCount).toBe(0);
			expect(body.scheduled[0].mediaAttached).toBeUndefined();
		});

		it("sets media_type to video when auto-attached media isVideo", async () => {
			currentSupabase = createBulkScheduleSupabase({
				groupConfigs: [
					{ group_id: "group-1", media_attachment_chance: 100 },
				],
			});
			vi.spyOn(Math, "random").mockReturnValue(0);
			mockGetRandomMediaWithContext.mockResolvedValue({
				id: "vid-1",
				url: "https://cdn.example.com/clip.mp4",
				description: "Video clip",
				tags: null,
				isVideo: true,
			});
			const res = mockRes();
			// Intercept the posts insert to capture insert data
			let capturedInsertData: any = null;
			const originalFrom = currentSupabase.from;
			currentSupabase.from = vi.fn().mockImplementation((table: string) => {
				if (table === "posts") {
					return {
						insert: vi.fn().mockImplementation((data: any) => {
							capturedInsertData = data;
							return {
								select: vi.fn().mockReturnValue({
									maybeSingle: vi.fn().mockResolvedValue({
										data: { id: "post-vid" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return originalFrom(table);
			});
			await handleBulkScheduleGroups(
				makeReq({ posts: [makePost()] }),
				res as any,
				USER_ID,
			);
			expect(capturedInsertData).not.toBeNull();
			expect(capturedInsertData.media_type).toBe("video");
		});
	});

	// =========================================================================
	// 3. mediaIds omission handling — auto-attach from group library
	// =========================================================================
	describe("mediaIds omission vs explicit", () => {
		it("skips auto-attach when mediaIds are explicitly provided", async () => {
			currentSupabase = createBulkScheduleSupabase({
				mediaByIds: [{ id: "explicit-media-1", file_type: "image/jpeg" }],
			});
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({
					posts: [makePost({ mediaIds: ["explicit-media-1"] })],
				}),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			expect(body.scheduledCount).toBe(1);
			// Should NOT call auto-attach
			expect(mockGetRandomMediaWithContext).not.toHaveBeenCalled();
		});

		it("uses explicit mediaIds and validates ownership", async () => {
			// Only "owned-1" is owned by user, "foreign-1" is not
			currentSupabase = createBulkScheduleSupabase({
				mediaByIds: [{ id: "owned-1", file_type: "image/png" }],
			});
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({
					posts: [makePost({ mediaIds: ["owned-1", "foreign-1"] })],
				}),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			expect(body.scheduledCount).toBe(1);
		});

		it("forces single media for video when multiple mediaIds with video", async () => {
			currentSupabase = createBulkScheduleSupabase({
				mediaByIds: [
					{ id: "img-1", file_type: "image/jpeg" },
					{ id: "vid-1", file_type: "video/mp4" },
				],
			});
			let capturedInsertData: any = null;
			const originalFrom = currentSupabase.from;
			currentSupabase.from = vi.fn().mockImplementation((table: string) => {
				if (table === "posts") {
					return {
						insert: vi.fn().mockImplementation((data: any) => {
							capturedInsertData = data;
							return {
								select: vi.fn().mockReturnValue({
									maybeSingle: vi.fn().mockResolvedValue({
										data: { id: "post-mixed" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return originalFrom(table);
			});
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({
					posts: [makePost({ mediaIds: ["img-1", "vid-1"] })],
				}),
				res as any,
				USER_ID,
			);
			// Should pick only the first video, not the image
			expect(capturedInsertData.media_urls).toHaveLength(1);
			expect(capturedInsertData.media_urls[0]).toBe("vid-1");
		});
	});

	// =========================================================================
	// 4. Cap enforcement per account
	// =========================================================================
	describe("cap enforcement", () => {
		it("fails post when all accounts in group are at daily cap", async () => {
			mockCheckDailyCap.mockResolvedValue({ allowed: true, used: 250, limit: 250 });
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({ posts: [makePost()] }),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			expect(body.failedCount).toBe(1);
			expect(body.failed[0].reason).toContain("daily cap");
		});

		it("skips capped account and uses next available in round-robin", async () => {
			currentSupabase = createBulkScheduleSupabase({
				accountsByQuery: [{ id: "acc-capped" }, { id: "acc-free" }],
			});
			// First account at cap, second under cap
			mockCheckDailyCap
				.mockResolvedValueOnce({ allowed: true, used: 250, limit: 250 })
				.mockResolvedValueOnce({ allowed: true, used: 5, limit: 250 });
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({ posts: [makePost()] }),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			expect(body.scheduledCount).toBe(1);
			expect(body.scheduled[0].accountId).toBe("acc-free");
		});

		it("tracks batch-local cap usage across posts in same request", async () => {
			// Single account, cap at 249 used (1 remaining)
			mockCheckDailyCap.mockResolvedValue({ allowed: true, used: 249, limit: 250 });
			const res = mockRes();
			const posts = [makePost({ content: "Post 1" }), makePost({ content: "Post 2" })];
			await handleBulkScheduleGroups(
				makeReq({ posts }),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			// First post should succeed (249 DB + 0 batch = 249 < 250)
			// Second post should fail (249 DB + 1 batch = 250 >= 250)
			expect(body.scheduledCount).toBe(1);
			expect(body.failedCount).toBe(1);
			expect(body.failed[0].reason).toContain("daily cap");
		});
	});

	// =========================================================================
	// 5. Cross-platform scheduling — Threads vs Instagram paths
	// =========================================================================
	describe("cross-platform scheduling", () => {
		it("sets account_id for Threads platform", async () => {
			let capturedInsertData: any = null;
			const originalFrom = currentSupabase.from;
			currentSupabase.from = vi.fn().mockImplementation((table: string) => {
				if (table === "posts") {
					return {
						insert: vi.fn().mockImplementation((data: any) => {
							capturedInsertData = data;
							return {
								select: vi.fn().mockReturnValue({
									maybeSingle: vi.fn().mockResolvedValue({
										data: { id: "post-threads" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return originalFrom(table);
			});
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({ posts: [makePost({ platform: "threads" })] }),
				res as any,
				USER_ID,
			);
			expect(capturedInsertData.account_id).toBe("acc-1");
			expect(capturedInsertData.instagram_account_id).toBeUndefined();
			expect(capturedInsertData.platform).toBe("threads");
		});

		it("sets instagram_account_id for Instagram platform with null account_id", async () => {
			mockGetRandomMediaWithContext.mockResolvedValue({
				id: "ig-media",
				url: "https://cdn.example.com/ig.jpg",
				description: null,
				tags: null,
			});
			let capturedInsertData: any = null;
			const originalFrom = currentSupabase.from;
			currentSupabase.from = vi.fn().mockImplementation((table: string) => {
				if (table === "posts") {
					return {
						insert: vi.fn().mockImplementation((data: any) => {
							capturedInsertData = data;
							return {
								select: vi.fn().mockReturnValue({
									maybeSingle: vi.fn().mockResolvedValue({
										data: { id: "post-ig" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return originalFrom(table);
			});
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({ posts: [makePost({ platform: "instagram" })] }),
				res as any,
				USER_ID,
			);
			expect(capturedInsertData.instagram_account_id).toBe("acc-1");
			expect(capturedInsertData.account_id).toBeNull();
			expect(capturedInsertData.platform).toBe("instagram");
			expect(capturedInsertData.ig_media_type).toBe("IMAGE");
		});

		it("includes poll_options for Threads platform", async () => {
			let capturedInsertData: any = null;
			const originalFrom = currentSupabase.from;
			currentSupabase.from = vi.fn().mockImplementation((table: string) => {
				if (table === "posts") {
					return {
						insert: vi.fn().mockImplementation((data: any) => {
							capturedInsertData = data;
							return {
								select: vi.fn().mockReturnValue({
									maybeSingle: vi.fn().mockResolvedValue({
										data: { id: "post-poll" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return originalFrom(table);
			});
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({
					posts: [makePost({ pollOptions: ["Yes", "No"] })],
				}),
				res as any,
				USER_ID,
			);
			expect(capturedInsertData.poll_options).toEqual(["Yes", "No"]);
		});

		it("includes link_url for Threads platform", async () => {
			let capturedInsertData: any = null;
			const originalFrom = currentSupabase.from;
			currentSupabase.from = vi.fn().mockImplementation((table: string) => {
				if (table === "posts") {
					return {
						insert: vi.fn().mockImplementation((data: any) => {
							capturedInsertData = data;
							return {
								select: vi.fn().mockReturnValue({
									maybeSingle: vi.fn().mockResolvedValue({
										data: { id: "post-link" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return originalFrom(table);
			});
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({
					posts: [makePost({ linkUrl: "https://example.com" })],
				}),
				res as any,
				USER_ID,
			);
			expect(capturedInsertData.link_url).toBe("https://example.com");
		});

		it("includes alt_text and location_id for Instagram platform", async () => {
			mockGetRandomMediaWithContext.mockResolvedValue({
				id: "m1",
				url: "https://cdn.example.com/ig.jpg",
				description: null,
				tags: null,
			});
			let capturedInsertData: any = null;
			const originalFrom = currentSupabase.from;
			currentSupabase.from = vi.fn().mockImplementation((table: string) => {
				if (table === "posts") {
					return {
						insert: vi.fn().mockImplementation((data: any) => {
							capturedInsertData = data;
							return {
								select: vi.fn().mockReturnValue({
									maybeSingle: vi.fn().mockResolvedValue({
										data: { id: "post-ig-meta" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return originalFrom(table);
			});
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({
					posts: [
						makePost({
							platform: "instagram",
							altText: "Photo description",
							locationId: "loc-123",
						}),
					],
				}),
				res as any,
				USER_ID,
			);
			expect(capturedInsertData.alt_text).toBe("Photo description");
			expect(capturedInsertData.location_id).toBe("loc-123");
		});
	});

	// =========================================================================
	// 6. Error handling
	// =========================================================================
	describe("error handling", () => {
		it("rejects posts for groups not owned by user", async () => {
			currentSupabase = createBulkScheduleSupabase({
				ownedGroups: [], // no owned groups
			});
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({ posts: [makePost()] }),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			expect(body.failedCount).toBe(1);
			expect(body.failed[0].reason).toContain("not found or not owned");
		});

		it("fails when no active accounts exist in group", async () => {
			currentSupabase = createBulkScheduleSupabase({
				accountsByQuery: [], // no accounts
			});
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({ posts: [makePost()] }),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			expect(body.failedCount).toBe(1);
			expect(body.failed[0].reason).toContain("No active");
			expect(body.failed[0].reason).toContain("threads");
		});

		it("returns 400 for invalid body schema (empty posts array)", async () => {
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({ posts: [] }),
				res as any,
				USER_ID,
			);
			expect(res.status).toHaveBeenCalledWith(400);
		});

		it("returns 400 for missing body", async () => {
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({}),
				res as any,
				USER_ID,
			);
			expect(res.status).toHaveBeenCalledWith(400);
		});

		it("returns 400 when posts exceed MAX_POSTS (100)", async () => {
			const posts = Array.from({ length: 101 }, (_, i) =>
				makePost({ content: `Post ${i}` }),
			);
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({ posts }),
				res as any,
				USER_ID,
			);
			expect(res.status).toHaveBeenCalledWith(400);
		});

		it("fails individual post on invalid scheduledFor date", async () => {
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({
					posts: [makePost({ scheduledFor: "not-a-date" })],
				}),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			expect(body.failedCount).toBe(1);
			expect(body.failed[0].reason).toContain("scheduledFor");
		});

		it("fails individual post when scheduledFor is in the past", async () => {
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({
					posts: [
						makePost({ scheduledFor: "2020-01-01T00:00:00Z" }),
					],
				}),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			expect(body.failedCount).toBe(1);
			expect(body.failed[0].reason).toContain("future");
		});

		it("fails individual post on DB insert error", async () => {
			currentSupabase = createBulkScheduleSupabase({
				postInsertError: { message: "duplicate key violation" },
			});
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({ posts: [makePost()] }),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			expect(body.failedCount).toBe(1);
			expect(body.failed[0].reason).toContain("DB insert failed");
			expect(body.failed[0].reason).toContain("duplicate key violation");
		});

		it("fails individual post when DB insert returns null", async () => {
			currentSupabase = createBulkScheduleSupabase({
				postInsert: null,
				postInsertError: null,
			});
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({ posts: [makePost()] }),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			expect(body.failedCount).toBe(1);
			expect(body.failed[0].reason).toContain("no row returned");
		});

		it("partially succeeds — some posts succeed, others fail", async () => {
			currentSupabase = createBulkScheduleSupabase({
				ownedGroups: [{ id: "group-1" }],
			});
			const res = mockRes();
			const posts = [
				makePost({ content: "Good post" }),
				makePost({ groupId: "group-nonexistent", content: "Bad group" }),
				makePost({ content: "Another good post" }),
			];
			await handleBulkScheduleGroups(
				makeReq({ posts }),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			expect(body.scheduledCount).toBe(2);
			expect(body.failedCount).toBe(1);
			expect(body.totalRequested).toBe(3);
		});
	});

	// =========================================================================
	// 7. autoAttachMedia: false — explicitly disable
	// =========================================================================
	describe("autoAttachMedia: false", () => {
		it("skips media auto-attachment when autoAttachMedia is false", async () => {
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({
					posts: [makePost()],
					autoAttachMedia: false,
				}),
				res as any,
				USER_ID,
			);
			expect(mockGetRandomMediaWithContext).not.toHaveBeenCalled();
			const body = res.json.mock.calls[0][0];
			expect(body.scheduledCount).toBe(1);
			expect(body.scheduled[0].mediaAttached).toBeUndefined();
		});

		it("skips media auto-attachment for Instagram when autoAttachMedia is false AND mediaIds provided", async () => {
			currentSupabase = createBulkScheduleSupabase({
				mediaByIds: [{ id: "my-media", file_type: "image/jpeg" }],
			});
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({
					posts: [
						makePost({
							platform: "instagram",
							mediaIds: ["my-media"],
						}),
					],
					autoAttachMedia: false,
				}),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			// Should succeed because explicit mediaIds were provided
			expect(body.scheduledCount).toBe(1);
			expect(mockGetRandomMediaWithContext).not.toHaveBeenCalled();
		});

		it("Instagram with autoAttachMedia false and no mediaIds schedules text-only (no auto-attach attempt)", async () => {
			let capturedInsertData: any = null;
			const originalFrom = currentSupabase.from;
			currentSupabase.from = vi.fn().mockImplementation((table: string) => {
				if (table === "posts") {
					return {
						insert: vi.fn().mockImplementation((data: any) => {
							capturedInsertData = data;
							return {
								select: vi.fn().mockReturnValue({
									maybeSingle: vi.fn().mockResolvedValue({
										data: { id: "post-ig-noauto" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return originalFrom(table);
			});
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({
					posts: [makePost({ platform: "instagram" })],
					autoAttachMedia: false,
				}),
				res as any,
				USER_ID,
			);
			// No auto-attach attempt
			expect(mockGetRandomMediaWithContext).not.toHaveBeenCalled();
			// Should still be scheduled (no media validation block when auto-attach disabled)
			const body = res.json.mock.calls[0][0];
			expect(body.scheduledCount).toBe(1);
			expect(capturedInsertData).not.toBeNull();
		});
	});

	// =========================================================================
	// 8. Edge cases
	// =========================================================================
	describe("edge cases", () => {
		it("single account group schedules all posts to same account", async () => {
			const res = mockRes();
			const posts = [
				makePost({ content: "Post A" }),
				makePost({ content: "Post B" }),
				makePost({ content: "Post C" }),
			];
			await handleBulkScheduleGroups(
				makeReq({ posts }),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			expect(body.scheduledCount).toBe(3);
			// All should go to the single account
			for (const s of body.scheduled) {
				expect(s.accountId).toBe("acc-1");
			}
		});

		it("handles multiple groups in same batch", async () => {
			currentSupabase = createBulkScheduleSupabase({
				ownedGroups: [{ id: "group-1" }, { id: "group-2" }],
			});
			const res = mockRes();
			const posts = [
				makePost({ groupId: "group-1", content: "G1 post" }),
				makePost({ groupId: "group-2", content: "G2 post" }),
			];
			await handleBulkScheduleGroups(
				makeReq({ posts }),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			expect(body.scheduledCount).toBe(2);
			expect(body.scheduled[0].groupId).toBe("group-1");
			expect(body.scheduled[1].groupId).toBe("group-2");
		});

		it("returns correct totalRequested, scheduledCount, failedCount", async () => {
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({ posts: [makePost()] }),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			expect(body.totalRequested).toBe(1);
			expect(body.scheduledCount).toBe(1);
			expect(body.failedCount).toBe(0);
		});

		it("includes index in scheduled and failed results for client correlation", async () => {
			currentSupabase = createBulkScheduleSupabase({
				ownedGroups: [{ id: "group-1" }],
			});
			const res = mockRes();
			const posts = [
				makePost({ content: "OK" }),
				makePost({ groupId: "nonexistent", content: "Bad" }),
			];
			await handleBulkScheduleGroups(
				makeReq({ posts }),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			expect(body.scheduled[0].index).toBe(0);
			expect(body.failed[0].index).toBe(1);
		});

		it("caches account lookups — same group+platform only queries DB once", async () => {
			const res = mockRes();
			const posts = [
				makePost({ content: "P1" }),
				makePost({ content: "P2" }),
				makePost({ content: "P3" }),
			];
			await handleBulkScheduleGroups(
				makeReq({ posts }),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			expect(body.scheduledCount).toBe(3);
			// publishableAccountFilters should only be called once for same group+platform
			expect(mockPublishableAccountFilters).toHaveBeenCalledTimes(1);
		});

		it("sanitizes HTML in content", async () => {
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({
					posts: [makePost({ content: "<script>alert(1)</script> Hello" })],
				}),
				res as any,
				USER_ID,
			);
			const body = res.json.mock.calls[0][0];
			expect(body.scheduledCount).toBe(1);
		});
	});

	// =========================================================================
	// 9. Metadata — crossreshare, spoilers, collaborators, etc.
	// =========================================================================
	describe("metadata features", () => {
		it("includes crossreshare in metadata from group config", async () => {
			currentSupabase = createBulkScheduleSupabase({
				groupConfigs: [
					{
						group_id: "group-1",
						crossreshare_to_ig: true,
						crossreshare_to_ig_dark_mode: false,
						media_attachment_chance: 0,
					},
				],
			});
			let capturedInsertData: any = null;
			const originalFrom = currentSupabase.from;
			currentSupabase.from = vi.fn().mockImplementation((table: string) => {
				if (table === "posts") {
					return {
						insert: vi.fn().mockImplementation((data: any) => {
							capturedInsertData = data;
							return {
								select: vi.fn().mockReturnValue({
									maybeSingle: vi.fn().mockResolvedValue({
										data: { id: "post-cr" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return originalFrom(table);
			});
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({ posts: [makePost()] }),
				res as any,
				USER_ID,
			);
			expect(capturedInsertData.metadata.crossreshareToIg).toBe(true);
		});

		it("includes text spoilers in metadata and insert data", async () => {
			let capturedInsertData: any = null;
			const originalFrom = currentSupabase.from;
			currentSupabase.from = vi.fn().mockImplementation((table: string) => {
				if (table === "posts") {
					return {
						insert: vi.fn().mockImplementation((data: any) => {
							capturedInsertData = data;
							return {
								select: vi.fn().mockReturnValue({
									maybeSingle: vi.fn().mockResolvedValue({
										data: { id: "post-spoiler" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return originalFrom(table);
			});
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({
					posts: [makePost({ textSpoilers: { "0:5": "spoil" } })],
				}),
				res as any,
				USER_ID,
			);
			expect(capturedInsertData.metadata.textSpoilers).toEqual({ "0:5": "spoil" });
			expect(capturedInsertData.text_spoilers).toEqual({ "0:5": "spoil" });
		});

		it("includes topic_tag in insert data", async () => {
			let capturedInsertData: any = null;
			const originalFrom = currentSupabase.from;
			currentSupabase.from = vi.fn().mockImplementation((table: string) => {
				if (table === "posts") {
					return {
						insert: vi.fn().mockImplementation((data: any) => {
							capturedInsertData = data;
							return {
								select: vi.fn().mockReturnValue({
									maybeSingle: vi.fn().mockResolvedValue({
										data: { id: "post-topic" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return originalFrom(table);
			});
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({
					posts: [makePost({ topicTag: "trending" })],
				}),
				res as any,
				USER_ID,
			);
			expect(capturedInsertData.topic_tag).toBe("trending");
		});

		it("includes collaborators in metadata for IG posts", async () => {
			mockGetRandomMediaWithContext.mockResolvedValue({
				id: "m1",
				url: "https://cdn.example.com/ig.jpg",
				description: null,
				tags: null,
			});
			let capturedInsertData: any = null;
			const originalFrom = currentSupabase.from;
			currentSupabase.from = vi.fn().mockImplementation((table: string) => {
				if (table === "posts") {
					return {
						insert: vi.fn().mockImplementation((data: any) => {
							capturedInsertData = data;
							return {
								select: vi.fn().mockReturnValue({
									maybeSingle: vi.fn().mockResolvedValue({
										data: { id: "post-collab" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return originalFrom(table);
			});
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({
					posts: [
						makePost({
							platform: "instagram",
							collaborators: ["user_a", "user_b"],
						}),
					],
				}),
				res as any,
				USER_ID,
			);
			expect(capturedInsertData.metadata.collaborators).toEqual(["user_a", "user_b"]);
		});

		it("includes isSpoiler media flag in metadata", async () => {
			let capturedInsertData: any = null;
			const originalFrom = currentSupabase.from;
			currentSupabase.from = vi.fn().mockImplementation((table: string) => {
				if (table === "posts") {
					return {
						insert: vi.fn().mockImplementation((data: any) => {
							capturedInsertData = data;
							return {
								select: vi.fn().mockReturnValue({
									maybeSingle: vi.fn().mockResolvedValue({
										data: { id: "post-spoilermedia" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return originalFrom(table);
			});
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({
					posts: [makePost({ isSpoilerMedia: true })],
				}),
				res as any,
				USER_ID,
			);
			expect(capturedInsertData.metadata.isSpoiler).toBe(true);
		});

		it("includes mediaDescription in metadata when auto-media has description", async () => {
			currentSupabase = createBulkScheduleSupabase({
				groupConfigs: [
					{ group_id: "group-1", media_attachment_chance: 100 },
				],
			});
			vi.spyOn(Math, "random").mockReturnValue(0);
			mockGetRandomMediaWithContext.mockResolvedValue({
				id: "m-desc",
				url: "https://cdn.example.com/desc.jpg",
				description: "Beautiful sunset",
				tags: null,
			});
			let capturedInsertData: any = null;
			const originalFrom = currentSupabase.from;
			currentSupabase.from = vi.fn().mockImplementation((table: string) => {
				if (table === "posts") {
					return {
						insert: vi.fn().mockImplementation((data: any) => {
							capturedInsertData = data;
							return {
								select: vi.fn().mockReturnValue({
									maybeSingle: vi.fn().mockResolvedValue({
										data: { id: "post-desc" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return originalFrom(table);
			});
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({ posts: [makePost()] }),
				res as any,
				USER_ID,
			);
			expect(capturedInsertData.metadata.mediaDescription).toBe("Beautiful sunset");
		});
	});

	// =========================================================================
	// 10. Insert data structure validation
	// =========================================================================
	describe("insert data structure", () => {
		it("sets correct base fields for scheduled post", async () => {
			let capturedInsertData: any = null;
			const originalFrom = currentSupabase.from;
			currentSupabase.from = vi.fn().mockImplementation((table: string) => {
				if (table === "posts") {
					return {
						insert: vi.fn().mockImplementation((data: any) => {
							capturedInsertData = data;
							return {
								select: vi.fn().mockReturnValue({
									maybeSingle: vi.fn().mockResolvedValue({
										data: { id: "post-base" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return originalFrom(table);
			});
			const scheduledFor = futureISO();
			const res = mockRes();
			await handleBulkScheduleGroups(
				makeReq({
					posts: [makePost({ scheduledFor })],
				}),
				res as any,
				USER_ID,
			);
			expect(capturedInsertData.user_id).toBe(USER_ID);
			expect(capturedInsertData.status).toBe("scheduled");
			expect(capturedInsertData.platform).toBe("threads");
			expect(capturedInsertData.created_at).toBeDefined();
			expect(capturedInsertData.updated_at).toBeDefined();
		});
	});
});
