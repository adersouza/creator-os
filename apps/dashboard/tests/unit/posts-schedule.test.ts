import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Unit tests for schedule/reschedule/updateDraft handlers.
 *
 * Tests:
 * - Schedule with future date → creates scheduled post
 * - Schedule without date → creates draft
 * - Schedule in past → 400 error
 * - Reschedule existing post → updates scheduled_for
 * - Reschedule to null → changes status to draft
 * - Update draft content → updates content
 * - Update draft with scheduledFor → changes status to scheduled
 * - Post not owned by user → 404
 * - Post already published → cannot reschedule
 */

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

interface FromOverrides {
	accountLookup?: Record<string, unknown> | null;
	postInsert?: { id: string } | null;
	postInsertError?: { message: string } | null;
	postFetch?: Record<string, unknown> | null;
	postFetchError?: unknown;
	updateError?: unknown;
}

function createSupabaseMock(overrides: FromOverrides = {}) {
	const defaultAccount = {
		id: "acc-1",
		threads_user_id: "threads-user-1",
		threads_access_token_encrypted: "enc-token",
		is_active: true,
		needs_reauth: false,
		status: "active",
		token_expires_at: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString(),
	};
	const defaultPost = {
		id: "post-1",
		status: "draft",
		platform: "threads",
		account_id: "acc-1",
		instagram_account_id: null,
		content: "Existing scheduled content",
		media_ids: null,
		media_urls: null,
		ig_media_type: null,
		media_type: "text",
		poll_options: null,
		quoted_post_id: null,
		link_url: null,
		gif_attachment: null,
		text_attachment: null,
		location_id: null,
		topic_tag: null,
		alt_text: null,
		scheduled_for: futureDate(90),
		metadata: {},
	};
	return {
		from: vi.fn().mockImplementation((table: string) => {
			if (table === "profiles") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							maybeSingle: vi.fn().mockResolvedValue({
								data: { subscription_tier: "pro" },
								error: null,
							}),
						}),
					}),
				};
			}
			if (table === "accounts" || table === "instagram_accounts") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								maybeSingle: vi.fn().mockResolvedValue({
									data: overrides.accountLookup !== undefined
										? overrides.accountLookup &&
											{ ...defaultAccount, ...overrides.accountLookup }
										: defaultAccount,
								}),
							}),
						}),
					}),
				};
			}
			if (table === "posts") {
				const countChain: any = {};
				countChain.eq = vi.fn().mockReturnValue(countChain);
				countChain.in = vi.fn().mockReturnValue(countChain);
				countChain.is = vi.fn().mockReturnValue(countChain);
				countChain.gte = vi.fn().mockReturnValue(countChain);
				countChain.lt = vi.fn().mockResolvedValue({ count: 0, error: null });
				return {
					select: vi.fn().mockImplementation((_cols: string, opts?: any) => {
						if (opts?.count === "exact") {
							return countChain;
						}
						return {
							eq: vi.fn().mockReturnValue({
								eq: vi.fn().mockReturnValue({
									maybeSingle: vi.fn().mockResolvedValue({
										data: overrides.postFetch !== undefined
											? overrides.postFetch && { ...defaultPost, ...overrides.postFetch }
											: defaultPost,
										error: overrides.postFetchError ?? null,
									}),
								}),
							}),
						};
					}),
					insert: vi.fn().mockReturnValue({
						select: vi.fn().mockReturnValue({
							maybeSingle: vi.fn().mockResolvedValue({
								data: overrides.postInsert ?? { id: "post-new-1" },
								error: overrides.postInsertError ?? null,
							}),
						}),
					}),
					update: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockResolvedValue({
								error: overrides.updateError ?? null,
							}),
						}),
					}),
				};
			}
			return {
				select: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
			};
		}),
	};
}

let currentSupabase: ReturnType<typeof createSupabaseMock>;

vi.mock("@/api/_lib/supabase.js", () => ({
	getSupabase: () => currentSupabase,
	getSupabaseAny: () => currentSupabase,
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
		res.status(200).json({ data }),
}));

vi.mock("@/api/_lib/sanitize.js", () => ({
	sanitizeHtml: (s: string) => s,
}));

vi.mock("@/api/_lib/qstashSchedule.js", () => ({
	dispatchPostPublish: vi.fn().mockResolvedValue("msg-123"),
	cancelPostPublish: vi.fn().mockResolvedValue(undefined),
	cancelQStashMessage: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/api/_lib/ssrfProtection.js", () => ({
	validateUrlNotPrivate: vi.fn().mockResolvedValue(null),
}));

vi.mock("@/api/_lib/cron/scheduled-posts/mediaValidation.js", () => ({
	checkMediaUrlAccessible: vi.fn().mockResolvedValue(null),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockRes() {
	const res: Record<string, any> = {};
	res.status = vi.fn().mockReturnValue(res);
	res.json = vi.fn().mockReturnValue(res);
	res.setHeader = vi.fn().mockReturnValue(res);
	return res;
}

function futureDate(minutesAhead = 60): string {
	const d = new Date();
	d.setMinutes(d.getMinutes() + minutesAhead);
	return d.toISOString();
}

function pastDate(minutesAgo = 60): string {
	const d = new Date();
	d.setMinutes(d.getMinutes() - minutesAgo);
	return d.toISOString();
}

// ---------------------------------------------------------------------------
// Schedule Handler Tests
// ---------------------------------------------------------------------------

describe("handleSchedule", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	afterEach(() => {
		vi.restoreAllMocks();
	});

	it("creates a scheduled post with a future date", async () => {
		currentSupabase = createSupabaseMock({
			accountLookup: { id: "acc-1" },
			postInsert: { id: "post-sched-1" },
		});

		const { handleSchedule } = await import("@/api/_lib/handlers/posts/schedule.js");
		const res = mockRes();
		const scheduledFor = futureDate(120);
		const req = {
			method: "POST",
			query: { action: "schedule" },
			body: {
				accountId: "acc-1",
				content: "Scheduled post content",
				platform: "threads",
				scheduledFor,
			},
			headers: {},
		};

		await handleSchedule(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				data: expect.objectContaining({
					postId: "post-sched-1",
					status: "scheduled",
					platform: "threads",
				}),
			}),
		);
		// scheduledFor should be returned
		const jsonCall = res.json.mock.calls[0][0];
		expect(jsonCall.data.scheduledFor).toBeTruthy();
	});

	it("creates a draft when no scheduledFor is provided", async () => {
		currentSupabase = createSupabaseMock({
			accountLookup: { id: "acc-1" },
			postInsert: { id: "post-draft-1" },
		});

		const { handleSchedule } = await import("@/api/_lib/handlers/posts/schedule.js");
		const res = mockRes();
		const req = {
			method: "POST",
			query: { action: "schedule" },
			body: {
				accountId: "acc-1",
				content: "Draft content without schedule",
				platform: "threads",
			},
			headers: {},
		};

		await handleSchedule(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				data: expect.objectContaining({
					postId: "post-draft-1",
					status: "draft",
					scheduledFor: null,
				}),
			}),
		);
	});

	it("blocks scheduled Instagram Campaign Factory posts with unresolved native audio", async () => {
		currentSupabase = createSupabaseMock({
			accountLookup: {
				id: "ig-1",
				instagram_user_id: "1789",
				instagram_access_token_encrypted: "enc-token",
				login_type: "facebook",
			},
		});

		const { handleSchedule } = await import("@/api/_lib/handlers/posts/schedule.js");
		const res = mockRes();
		const req = {
			method: "POST",
			query: { action: "schedule" },
			body: {
				instagramAccountId: "ig-1",
				content: "Campaign Factory reel",
				platform: "instagram",
				publishMode: "auto",
				mediaType: "REELS",
				media: [{ type: "video", url: "https://example.com/reel.mp4" }],
				scheduledFor: futureDate(120),
				metadata: {
					campaign_factory: {
						audio_intent: {
							schema: "pipeline.audio_intent.v1",
							required: true,
							status: "recommended",
						},
					},
				},
			},
			headers: {},
		};

		await handleSchedule(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(422);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				code: "PUBLISH_PREFLIGHT_FAILED",
				extra: expect.objectContaining({
					preflight: expect.objectContaining({
						ok: false,
						issues: expect.arrayContaining([
							expect.objectContaining({ code: "native_audio_unresolved" }),
						]),
					}),
				}),
			}),
		);
	});

	it("returns 400 when scheduledFor is in the past", async () => {
		currentSupabase = createSupabaseMock({});

		const { handleSchedule } = await import("@/api/_lib/handlers/posts/schedule.js");
		const res = mockRes();
		const req = {
			method: "POST",
			query: { action: "schedule" },
			body: {
				accountId: "acc-1",
				content: "Past schedule attempt",
				platform: "threads",
				scheduledFor: pastDate(60),
			},
			headers: {},
		};

		await handleSchedule(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(400);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				error: "scheduledFor must be in the future",
			}),
		);
	});

	it("returns 400 when content is missing", async () => {
		currentSupabase = createSupabaseMock({});

		const { handleSchedule } = await import("@/api/_lib/handlers/posts/schedule.js");
		const res = mockRes();
		const req = {
			method: "POST",
			query: { action: "schedule" },
			body: {
				accountId: "acc-1",
				platform: "threads",
				// No content
			},
			headers: {},
		};

		await handleSchedule(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(400);
		// Schema validation runs before the handler's own check, so when
		// content is undefined we get Zod's auto-generated message
		// ("content: Invalid input: expected string, received undefined")
		// rather than the handler's "content is required" string. Either is
		// fine — the API still 400s and the message names the field.
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: expect.stringContaining("content") }),
		);
	});

	it("returns 404 when account is not found", async () => {
		currentSupabase = createSupabaseMock({
			accountLookup: null,
		});

		const { handleSchedule } = await import("@/api/_lib/handlers/posts/schedule.js");
		const res = mockRes();
		const req = {
			method: "POST",
			query: { action: "schedule" },
			body: {
				accountId: "nonexistent",
				content: "Post for missing account",
				platform: "threads",
			},
			headers: {},
		};

		await handleSchedule(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(404);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "Account not found" }),
		);
	});
});

// ---------------------------------------------------------------------------
// Reschedule Handler Tests
// ---------------------------------------------------------------------------

describe("handleReschedule", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	afterEach(() => {
		vi.restoreAllMocks();
	});

	it("reschedules an existing post to a new future time", async () => {
		currentSupabase = createSupabaseMock({
			postFetch: { id: "post-1", status: "scheduled" },
		});

		const { handleReschedule } = await import("@/api/_lib/handlers/posts/schedule.js");
		const res = mockRes();
		const newTime = futureDate(180);
		const req = {
			method: "POST",
			query: { action: "reschedule" },
			body: {
				postId: "post-1",
				scheduledFor: newTime,
			},
			headers: {},
		};

		await handleReschedule(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				data: expect.objectContaining({
					postId: "post-1",
					status: "scheduled",
				}),
			}),
		);
		const jsonCall = res.json.mock.calls[0][0];
		expect(jsonCall.data.scheduledFor).toBeTruthy();
	});

	it("reschedules to null (moves to draft)", async () => {
		currentSupabase = createSupabaseMock({
			postFetch: { id: "post-1", status: "scheduled" },
		});

		const { handleReschedule } = await import("@/api/_lib/handlers/posts/schedule.js");
		const res = mockRes();
		const req = {
			method: "POST",
			query: { action: "reschedule" },
			body: {
				postId: "post-1",
				// No scheduledFor = move to draft
			},
			headers: {},
		};

		await handleReschedule(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				data: expect.objectContaining({
					postId: "post-1",
					status: "draft",
					scheduledFor: null,
				}),
			}),
		);
	});

	it("returns 404 when post is not owned by user", async () => {
		currentSupabase = createSupabaseMock({
			postFetch: null, // Not found (wrong user)
		});

		const { handleReschedule } = await import("@/api/_lib/handlers/posts/schedule.js");
		const res = mockRes();
		const req = {
			method: "POST",
			query: { action: "reschedule" },
			body: {
				postId: "post-other-user",
				scheduledFor: futureDate(),
			},
			headers: {},
		};

		await handleReschedule(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(404);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "Post not found" }),
		);
	});

	it("returns 400 when post is already published", async () => {
		currentSupabase = createSupabaseMock({
			postFetch: { id: "post-1", status: "published" },
		});

		const { handleReschedule } = await import("@/api/_lib/handlers/posts/schedule.js");
		const res = mockRes();
		const req = {
			method: "POST",
			query: { action: "reschedule" },
			body: {
				postId: "post-1",
				scheduledFor: futureDate(),
			},
			headers: {},
		};

		await handleReschedule(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(400);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				error: "Only scheduled or draft posts can be rescheduled",
			}),
		);
	});

	it("returns 400 when postId is missing", async () => {
		currentSupabase = createSupabaseMock({});

		const { handleReschedule } = await import("@/api/_lib/handlers/posts/schedule.js");
		const res = mockRes();
		const req = {
			method: "POST",
			query: { action: "reschedule" },
			body: {
				// No postId
				scheduledFor: futureDate(),
			},
			headers: {},
		};

		await handleReschedule(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(400);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "postId is required" }),
		);
	});

	it("returns 400 when rescheduling to a past date", async () => {
		currentSupabase = createSupabaseMock({});

		const { handleReschedule } = await import("@/api/_lib/handlers/posts/schedule.js");
		const res = mockRes();
		const req = {
			method: "POST",
			query: { action: "reschedule" },
			body: {
				postId: "post-1",
				scheduledFor: pastDate(30),
			},
			headers: {},
		};

		await handleReschedule(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(400);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				error: "scheduledFor must be in the future",
			}),
		);
	});
});

// ---------------------------------------------------------------------------
// Update Draft Handler Tests
// ---------------------------------------------------------------------------

describe("handleUpdateDraft", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	afterEach(() => {
		vi.restoreAllMocks();
	});

	it("updates draft content successfully", async () => {
		currentSupabase = createSupabaseMock({
			postFetch: { id: "post-draft-1", status: "draft" },
		});

		const { handleUpdateDraft } = await import("@/api/_lib/handlers/posts/schedule.js");
		const res = mockRes();
		const req = {
			method: "POST",
			query: { action: "updateDraft" },
			body: {
				postId: "post-draft-1",
				content: "Updated draft content",
			},
			headers: {},
		};

		await handleUpdateDraft(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				data: expect.objectContaining({
					postId: "post-draft-1",
					updated: expect.arrayContaining(["content"]),
				}),
			}),
		);
	});

	it("updates draft with scheduledFor to change status to scheduled", async () => {
		currentSupabase = createSupabaseMock({
			postFetch: { id: "post-draft-1", status: "draft" },
		});

		const { handleUpdateDraft } = await import("@/api/_lib/handlers/posts/schedule.js");
		const res = mockRes();
		const req = {
			method: "POST",
			query: { action: "updateDraft" },
			body: {
				postId: "post-draft-1",
				scheduledFor: futureDate(60),
			},
			headers: {},
		};

		await handleUpdateDraft(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				data: expect.objectContaining({
					postId: "post-draft-1",
					updated: expect.arrayContaining(["scheduled_for", "status"]),
				}),
			}),
		);
	});

	it("returns 404 when post not owned by user", async () => {
		currentSupabase = createSupabaseMock({
			postFetch: null,
		});

		const { handleUpdateDraft } = await import("@/api/_lib/handlers/posts/schedule.js");
		const res = mockRes();
		const req = {
			method: "POST",
			query: { action: "updateDraft" },
			body: {
				postId: "post-other-user",
				content: "Trying to update",
			},
			headers: {},
		};

		await handleUpdateDraft(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(404);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "Post not found" }),
		);
	});

	it("returns 400 when trying to update a published post", async () => {
		currentSupabase = createSupabaseMock({
			postFetch: { id: "post-1", status: "published" },
		});

		const { handleUpdateDraft } = await import("@/api/_lib/handlers/posts/schedule.js");
		const res = mockRes();
		const req = {
			method: "POST",
			query: { action: "updateDraft" },
			body: {
				postId: "post-1",
				content: "Trying to update published",
			},
			headers: {},
		};

		await handleUpdateDraft(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(400);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				error: "Only draft or scheduled posts can be updated",
			}),
		);
	});

	it("returns 400 when postId is missing", async () => {
		currentSupabase = createSupabaseMock({});

		const { handleUpdateDraft } = await import("@/api/_lib/handlers/posts/schedule.js");
		const res = mockRes();
		const req = {
			method: "POST",
			query: { action: "updateDraft" },
			body: {
				content: "Content without postId",
			},
			headers: {},
		};

		await handleUpdateDraft(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(400);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "postId is required" }),
		);
	});
});
