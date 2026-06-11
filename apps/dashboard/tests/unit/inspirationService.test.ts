/**
 * Inspiration Service Tests
 *
 * Comprehensive tests for services/inspirationService.ts (~843 lines).
 *
 * Frontend service for AI-generated content ideas from competitor top posts.
 * Manages idea lifecycle: fetching, saving, dismissing, queuing, config CRUD,
 * external post saving, bulk operations, and real-time subscriptions.
 *
 * Covers:
 * 1. getIdeas — filtering, sorting, pagination, error handling
 * 2. getIdea — single idea fetch, auth guard
 * 3. saveIdea / unsaveIdea — status transitions
 * 4. dismissIdea — hiding ideas
 * 5. queueIdea — adding to auto-poster queue
 * 6. bulkQueueTop — batch queuing top viral ideas
 * 7. getConfig / updateConfig — config CRUD with auto-creation
 * 8. getIdeaCounts — status aggregation
 * 9. getCompetitorsWithIdeas — grouping by competitor
 * 10. getTopicTags — tag extraction and counting
 * 11. deleteExpiredIdeas — cleanup of pending expired ideas
 * 12. saveExternalPost — API call to save external posts
 * 13. subscribeToIdeas — real-time subscription lifecycle
 * 14. Auth guard — all methods return empty/false when not authenticated
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mocks — must be declared BEFORE importing module under test
// ---------------------------------------------------------------------------

const mockSession = {
	user: { id: "user-123" },
	access_token: "test-jwt-token",
};
const mockGetStoredSession = vi.fn(() => mockSession);

const mockSupabase = {
	auth: {
		getSession: vi.fn().mockResolvedValue({
			data: { session: mockSession },
		}),
	},
	from: vi.fn(),
	channel: vi.fn().mockReturnValue({
		on: vi.fn().mockReturnValue({
			subscribe: vi.fn(),
		}),
	}),
};

vi.mock("@/services/api/shared", () => ({
	supabase: mockSupabase,
	getUserIdAsync: vi.fn().mockResolvedValue("user-123"),
	getSession: vi.fn().mockResolvedValue(mockSession),
	createServiceLogger: () => ({
		log: vi.fn(),
		warn: vi.fn(),
		error: vi.fn(),
		info: vi.fn(),
		debug: vi.fn(),
	}),
	dbQuery: vi.fn().mockImplementation(async (query: any) => {
		const { data, error } = await query;
		if (error) throw error;
		return data;
	}),
}));

vi.mock("@/services/supabase", () => ({
	supabase: mockSupabase,
	getStoredSession: mockGetStoredSession,
}));

vi.mock("@/services/realtimeManager", () => ({
	subscribe: vi.fn().mockReturnValue(vi.fn()),
}));

const mockAddToAutoQueue = vi.fn().mockResolvedValue({ success: true });
vi.mock("@/services/autoPost", () => ({
	addToAutoQueue: mockAddToAutoQueue,
}));

// Mock fetch
const mockFetch = vi.fn();
global.fetch = mockFetch;

function mockApiResponse({
	ok,
	status,
	body,
}: {
	ok: boolean;
	status: number;
	body: Record<string, unknown>;
}) {
	return {
		ok,
		status,
		headers: new Headers(),
		text: () => Promise.resolve(JSON.stringify(body)),
		json: () => Promise.resolve(body),
	};
}

// ---------------------------------------------------------------------------
// Import module under test AFTER mocks
// ---------------------------------------------------------------------------

const {
	getIdeas,
	getIdea,
	saveIdea,
	unsaveIdea,
	dismissIdea,
	queueIdea,
	bulkQueueTop,
	getConfig,
	updateConfig,
	getIdeaCounts,
	getCompetitorsWithIdeas,
	getTopicTags,
	deleteExpiredIdeas,
	saveExternalPost,
	subscribeToIdeas,
	TIER_LIMITS,
	DEFAULT_INSPIRATION_CONFIG,
	ADAPTATION_ANGLE_LABELS,
} = await import("@/services/inspirationService");

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function createChainMock(resolvedValue: any = { data: null, error: null }) {
	const terminal = vi.fn().mockResolvedValue(resolvedValue);
	const chainable: any = {};
	const methods = [
		"select", "eq", "in", "gte", "lte", "lt", "order", "limit",
		"range", "insert", "update", "delete", "upsert", "not", "or",
		"contains",
	];
	for (const method of methods) {
		chainable[method] = vi.fn().mockReturnValue(chainable);
	}
	chainable.single = terminal;
	chainable.maybeSingle = terminal;
	chainable.then = (resolve: any) => resolve(resolvedValue);
	return { chainable, terminal };
}

function createIdeaRow(overrides: Partial<Record<string, unknown>> = {}) {
	return {
		id: "idea-1",
		user_id: "user-123",
		workspace_id: "ws-1",
		original_post: {
			id: "orig-1",
			content: "Original viral post",
			engagementScore: 95,
			likes: 500,
			replies: 50,
		},
		competitor_id: "comp-1",
		competitor_username: "competitor_user",
		competitor_avatar_url: "https://example.com/avatar.jpg",
		adapted_content: "Adapted version of the viral post",
		viral_score: 85,
		ai_insight: "This post uses curiosity hooks",
		topic_tags: ["growth", "marketing"],
		adaptation_style: "casual",
		adaptation_angle: "direct",
		viral_formula: "Contrarian + curiosity + one-liner",
		status: "pending",
		saved: false,
		queued: false,
		queued_at: null,
		posted_at: null,
		generated_at: "2026-04-10T12:00:00Z",
		expires_at: "2026-04-17T12:00:00Z",
		created_at: "2026-04-10T12:00:00Z",
		competitors: null,
		...overrides,
	};
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
	vi.clearAllMocks();
	mockSupabase.auth.getSession.mockResolvedValue({
		data: { session: mockSession },
	});
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("inspirationService", () => {
	// =========================================================================
	// Constants & Exports
	// =========================================================================

	describe("constants", () => {
		it("exports TIER_LIMITS with correct structure", () => {
			expect(TIER_LIMITS.free.dailyIdeas).toBe(10);
			expect(TIER_LIMITS.pro.dailyIdeas).toBe(50);
			expect(TIER_LIMITS.agency.dailyIdeas).toBe(Infinity);
			expect(TIER_LIMITS.empire.dailyIdeas).toBe(Infinity);
			expect(TIER_LIMITS.free.manualRefreshCooldown).toBe(24 * 60);
			expect(TIER_LIMITS.empire.manualRefreshCooldown).toBe(0);
		});

		it("exports DEFAULT_INSPIRATION_CONFIG with sane defaults", () => {
			expect(DEFAULT_INSPIRATION_CONFIG.enabled).toBe(true);
			expect(DEFAULT_INSPIRATION_CONFIG.ideasPerCompetitor).toBe(10);
			expect(DEFAULT_INSPIRATION_CONFIG.adaptationStyle).toBe("casual");
			expect(DEFAULT_INSPIRATION_CONFIG.topicFilters).toEqual([]);
			expect(DEFAULT_INSPIRATION_CONFIG.notifyNewIdeas).toBe(true);
			expect(DEFAULT_INSPIRATION_CONFIG.dailyDigestEnabled).toBe(false);
		});

		it("exports ADAPTATION_ANGLE_LABELS for all angles", () => {
			expect(ADAPTATION_ANGLE_LABELS.direct).toBe("Direct");
			expect(ADAPTATION_ANGLE_LABELS.counter).toBe("Counter");
			expect(ADAPTATION_ANGLE_LABELS.story).toBe("Story");
			expect(ADAPTATION_ANGLE_LABELS.list).toBe("List");
			expect(ADAPTATION_ANGLE_LABELS.meme).toBe("Meme");
			expect(ADAPTATION_ANGLE_LABELS.question).toBe("Question");
		});
	});

	// =========================================================================
	// getIdeas
	// =========================================================================

	describe("getIdeas", () => {
		it("fetches ideas for the current user", async () => {
			const rows = [createIdeaRow(), createIdeaRow({ id: "idea-2", viral_score: 70 })];
			const { chainable } = createChainMock({ data: rows, error: null });
			mockSupabase.from.mockReturnValue(chainable);

			const ideas = await getIdeas();

			expect(mockSupabase.from).toHaveBeenCalledWith("inspiration_ideas");
			expect(chainable.select).toHaveBeenCalledWith(
				"*, competitors(username, avatar_url)",
			);
			expect(chainable.eq).toHaveBeenCalledWith("user_id", "user-123");
			expect(ideas).toHaveLength(2);
			expect(ideas[0].id).toBe("idea-1");
			expect(ideas[0].adaptedContent).toBe("Adapted version of the viral post");
			expect(ideas[0].viralScore).toBe(85);
		});

		it("applies competitor filter", async () => {
			const { chainable } = createChainMock({ data: [], error: null });
			mockSupabase.from.mockReturnValue(chainable);

			await getIdeas({ competitor: "competitor_user" });

			expect(chainable.eq).toHaveBeenCalledWith(
				"competitor_username",
				"competitor_user",
			);
		});

		it("applies minScore and maxScore filters", async () => {
			const { chainable } = createChainMock({ data: [], error: null });
			mockSupabase.from.mockReturnValue(chainable);

			await getIdeas({ minScore: 50, maxScore: 90 });

			expect(chainable.gte).toHaveBeenCalledWith("viral_score", 50);
			expect(chainable.lte).toHaveBeenCalledWith("viral_score", 90);
		});

		it("applies single status filter", async () => {
			const { chainable } = createChainMock({ data: [], error: null });
			mockSupabase.from.mockReturnValue(chainable);

			await getIdeas({ status: "saved" });

			expect(chainable.eq).toHaveBeenCalledWith("status", "saved");
		});

		it("applies array status filter", async () => {
			const { chainable } = createChainMock({ data: [], error: null });
			mockSupabase.from.mockReturnValue(chainable);

			await getIdeas({ status: ["pending", "saved"] });

			expect(chainable.in).toHaveBeenCalledWith("status", ["pending", "saved"]);
		});

		it("applies saved and queued filters", async () => {
			const { chainable } = createChainMock({ data: [], error: null });
			mockSupabase.from.mockReturnValue(chainable);

			await getIdeas({ saved: true, queued: false });

			expect(chainable.eq).toHaveBeenCalledWith("saved", true);
			expect(chainable.eq).toHaveBeenCalledWith("queued", false);
		});

		it("applies topicTag filter", async () => {
			const { chainable } = createChainMock({ data: [], error: null });
			mockSupabase.from.mockReturnValue(chainable);

			await getIdeas({ topicTag: "growth" });

			expect(chainable.contains).toHaveBeenCalledWith("topic_tags", ["growth"]);
		});

		it("applies sorting defaults to viral_score desc", async () => {
			const { chainable } = createChainMock({ data: [], error: null });
			mockSupabase.from.mockReturnValue(chainable);

			await getIdeas();

			expect(chainable.order).toHaveBeenCalledWith("viral_score", {
				ascending: false,
			});
		});

		it("applies custom sorting", async () => {
			const { chainable } = createChainMock({ data: [], error: null });
			mockSupabase.from.mockReturnValue(chainable);

			await getIdeas({ sortBy: "generated_at", sortOrder: "asc" });

			expect(chainable.order).toHaveBeenCalledWith("generated_at", {
				ascending: true,
			});
		});

		it("applies pagination with limit and offset", async () => {
			const { chainable } = createChainMock({ data: [], error: null });
			mockSupabase.from.mockReturnValue(chainable);

			await getIdeas({ limit: 10, offset: 20 });

			expect(chainable.limit).toHaveBeenCalledWith(10);
			expect(chainable.range).toHaveBeenCalledWith(20, 29);
		});

		it("returns empty array when not authenticated", async () => {
			const { getUserIdAsync } = await import("@/services/api/shared");
			(getUserIdAsync as any).mockRejectedValueOnce(new Error("Not auth"));

			const ideas = await getIdeas();

			expect(ideas).toEqual([]);
		});

		it("returns empty array on database error", async () => {
			const { chainable } = createChainMock({ data: null, error: { message: "DB error" } });
			mockSupabase.from.mockReturnValue(chainable);
			// dbQuery will throw on error, getIdeas catches it
			const { dbQuery } = await import("@/services/api/shared");
			(dbQuery as any).mockRejectedValueOnce(new Error("DB error"));

			const ideas = await getIdeas();

			expect(ideas).toEqual([]);
		});

		it("maps competitor join data as fallback for missing username", async () => {
			const row = createIdeaRow({
				competitor_username: null,
				competitor_avatar_url: null,
				competitors: { username: "joined_user", avatar_url: "https://joined.com/av.jpg" },
			});
			const { chainable } = createChainMock({ data: [row], error: null });
			mockSupabase.from.mockReturnValue(chainable);

			const ideas = await getIdeas();

			expect(ideas[0].competitorUsername).toBe("joined_user");
			expect(ideas[0].competitorAvatarUrl).toBe("https://joined.com/av.jpg");
		});

		it("falls back to 'unknown' when no username source exists", async () => {
			const row = createIdeaRow({
				competitor_username: null,
				competitor_avatar_url: null,
				competitors: null,
			});
			const { chainable } = createChainMock({ data: [row], error: null });
			mockSupabase.from.mockReturnValue(chainable);

			const ideas = await getIdeas();

			expect(ideas[0].competitorUsername).toBe("unknown");
		});

		it("correctly maps date fields", async () => {
			const row = createIdeaRow({
				queued_at: "2026-04-12T08:00:00Z",
				posted_at: "2026-04-13T10:00:00Z",
			});
			const { chainable } = createChainMock({ data: [row], error: null });
			mockSupabase.from.mockReturnValue(chainable);

			const ideas = await getIdeas();

			expect(ideas[0].queuedAt).toBeInstanceOf(Date);
			expect(ideas[0].postedAt).toBeInstanceOf(Date);
			expect(ideas[0].generatedAt).toBeInstanceOf(Date);
			expect(ideas[0].expiresAt).toBeInstanceOf(Date);
			expect(ideas[0].createdAt).toBeInstanceOf(Date);
		});

		it("returns empty topic_tags when null in DB", async () => {
			const row = createIdeaRow({ topic_tags: null });
			const { chainable } = createChainMock({ data: [row], error: null });
			mockSupabase.from.mockReturnValue(chainable);

			const ideas = await getIdeas();

			expect(ideas[0].topicTags).toEqual([]);
		});
	});

	// =========================================================================
	// getIdea
	// =========================================================================

	describe("getIdea", () => {
		it("fetches a single idea by ID", async () => {
			const row = createIdeaRow();
			const { chainable } = createChainMock({ data: row, error: null });
			mockSupabase.from.mockReturnValue(chainable);

			const idea = await getIdea("idea-1");

			expect(mockSupabase.from).toHaveBeenCalledWith("inspiration_ideas");
			expect(chainable.eq).toHaveBeenCalledWith("id", "idea-1");
			expect(chainable.eq).toHaveBeenCalledWith("user_id", "user-123");
			expect(idea).not.toBeNull();
			expect(idea!.id).toBe("idea-1");
		});

		it("returns null when idea not found", async () => {
			const { chainable } = createChainMock({ data: null, error: null });
			mockSupabase.from.mockReturnValue(chainable);

			const idea = await getIdea("nonexistent");

			expect(idea).toBeNull();
		});

		it("returns null when not authenticated", async () => {
			const { getUserIdAsync } = await import("@/services/api/shared");
			(getUserIdAsync as any).mockRejectedValueOnce(new Error("Not auth"));

			const idea = await getIdea("idea-1");

			expect(idea).toBeNull();
		});

		it("returns null on database error", async () => {
			const { chainable } = createChainMock({ data: null, error: { message: "err" } });
			mockSupabase.from.mockReturnValue(chainable);

			const idea = await getIdea("idea-1");

			expect(idea).toBeNull();
		});
	});

	// =========================================================================
	// saveIdea / unsaveIdea
	// =========================================================================

	describe("saveIdea", () => {
		it("marks an idea as saved", async () => {
			const { chainable } = createChainMock({ data: null, error: null });
			mockSupabase.from.mockReturnValue(chainable);

			const result = await saveIdea("idea-1");

			expect(result).toBe(true);
			expect(chainable.update).toHaveBeenCalledWith({
				saved: true,
				status: "saved",
			});
			expect(chainable.eq).toHaveBeenCalledWith("id", "idea-1");
			expect(chainable.eq).toHaveBeenCalledWith("user_id", "user-123");
		});

		it("returns false when not authenticated", async () => {
			const { getUserIdAsync } = await import("@/services/api/shared");
			(getUserIdAsync as any).mockRejectedValueOnce(new Error("Not auth"));

			const result = await saveIdea("idea-1");

			expect(result).toBe(false);
		});

		it("returns false on database error", async () => {
			const { chainable } = createChainMock({ data: null, error: null });
			// Make the update throw
			chainable.update = vi.fn().mockReturnValue({
				eq: vi.fn().mockReturnValue({
					eq: vi.fn().mockRejectedValue(new Error("DB fail")),
				}),
			});
			mockSupabase.from.mockReturnValue(chainable);

			const result = await saveIdea("idea-1");

			expect(result).toBe(false);
		});
	});

	describe("unsaveIdea", () => {
		it("marks an idea as unsaved and resets to pending", async () => {
			const { chainable } = createChainMock({ data: null, error: null });
			mockSupabase.from.mockReturnValue(chainable);

			const result = await unsaveIdea("idea-1");

			expect(result).toBe(true);
			expect(chainable.update).toHaveBeenCalledWith({
				saved: false,
				status: "pending",
			});
		});

		it("returns false when not authenticated", async () => {
			const { getUserIdAsync } = await import("@/services/api/shared");
			(getUserIdAsync as any).mockRejectedValueOnce(new Error("Not auth"));

			const result = await unsaveIdea("idea-1");

			expect(result).toBe(false);
		});
	});

	// =========================================================================
	// dismissIdea
	// =========================================================================

	describe("dismissIdea", () => {
		it("sets status to dismissed", async () => {
			const { chainable } = createChainMock({ data: null, error: null });
			mockSupabase.from.mockReturnValue(chainable);

			const result = await dismissIdea("idea-1");

			expect(result).toBe(true);
			expect(chainable.update).toHaveBeenCalledWith({ status: "dismissed" });
			expect(chainable.eq).toHaveBeenCalledWith("id", "idea-1");
		});

		it("returns false when not authenticated", async () => {
			const { getUserIdAsync } = await import("@/services/api/shared");
			(getUserIdAsync as any).mockRejectedValueOnce(new Error("Not auth"));

			const result = await dismissIdea("idea-1");

			expect(result).toBe(false);
		});

		it("returns false on database error", async () => {
			const { chainable } = createChainMock({ data: null, error: null });
			chainable.update = vi.fn().mockReturnValue({
				eq: vi.fn().mockReturnValue({
					eq: vi.fn().mockRejectedValue(new Error("DB fail")),
				}),
			});
			mockSupabase.from.mockReturnValue(chainable);

			const result = await dismissIdea("idea-1");

			expect(result).toBe(false);
		});
	});

	// =========================================================================
	// queueIdea
	// =========================================================================

	describe("queueIdea", () => {
		it("adds idea to auto-poster queue and updates status", async () => {
			// First call: getIdea internal supabase call
			const ideaRow = createIdeaRow();
			const { chainable: ideaChain } = createChainMock({ data: ideaRow, error: null });
			// Second call: status update
			const { chainable: updateChain } = createChainMock({ data: null, error: null });

			let callCount = 0;
			mockSupabase.from.mockImplementation(() => {
				callCount++;
				if (callCount <= 1) return ideaChain; // getIdea
				return updateChain; // status update
			});

			mockAddToAutoQueue.mockResolvedValueOnce({ success: true });

			const result = await queueIdea("idea-1");

			expect(result).toBe(true);
			expect(mockAddToAutoQueue).toHaveBeenCalledWith(
				"Adapted version of the viral post",
			);
		});

		it("returns false when idea not found", async () => {
			const { chainable } = createChainMock({ data: null, error: null });
			mockSupabase.from.mockReturnValue(chainable);

			const result = await queueIdea("nonexistent");

			expect(result).toBe(false);
		});

		it("returns false when addToAutoQueue fails", async () => {
			const ideaRow = createIdeaRow();
			const { chainable } = createChainMock({ data: ideaRow, error: null });
			mockSupabase.from.mockReturnValue(chainable);
			mockAddToAutoQueue.mockResolvedValueOnce({ success: false });

			const result = await queueIdea("idea-1");

			expect(result).toBe(false);
		});

		it("returns false when not authenticated", async () => {
			const { getUserIdAsync } = await import("@/services/api/shared");
			(getUserIdAsync as any).mockRejectedValueOnce(new Error("Not auth"));

			const result = await queueIdea("idea-1");

			expect(result).toBe(false);
		});
	});

	// =========================================================================
	// bulkQueueTop
	// =========================================================================

	describe("bulkQueueTop", () => {
		it("queues top N ideas by viral score", async () => {
			const rows = [
				createIdeaRow({ id: "idea-1", viral_score: 95 }),
				createIdeaRow({ id: "idea-2", viral_score: 85 }),
			];
			const { chainable } = createChainMock({ data: rows, error: null });
			mockSupabase.from.mockReturnValue(chainable);
			mockAddToAutoQueue.mockResolvedValue({ success: true });

			const result = await bulkQueueTop(5);

			expect(result.queued).toBe(2);
			expect(result.failed).toBe(0);
		});

		it("returns zero counts when not authenticated", async () => {
			const { getUserIdAsync } = await import("@/services/api/shared");
			(getUserIdAsync as any).mockRejectedValueOnce(new Error("Not auth"));

			const result = await bulkQueueTop();

			expect(result).toEqual({ queued: 0, failed: 0 });
		});

		it("defaults to count of 20 if not specified", async () => {
			const { chainable } = createChainMock({ data: [], error: null });
			mockSupabase.from.mockReturnValue(chainable);

			await bulkQueueTop();

			// The limit filter is applied through getIdeas with limit: 20
			expect(chainable.limit).toHaveBeenCalled();
		});
	});

	// =========================================================================
	// getConfig / updateConfig
	// =========================================================================

	describe("getConfig", () => {
		it("returns existing config mapped correctly", async () => {
			const configRow = {
				id: "cfg-1",
				user_id: "user-123",
				workspace_id: "ws-1",
				enabled: true,
				ideas_per_competitor: 10,
				adaptation_style: "casual",
				topic_filters: ["marketing"],
				notify_new_ideas: true,
				daily_digest_enabled: false,
				last_scan_at: "2026-04-10T12:00:00Z",
				ideas_generated_today: 5,
				last_generation_reset: "2026-04-10",
			};
			const { chainable } = createChainMock({ data: configRow, error: null });
			mockSupabase.from.mockReturnValue(chainable);

			const config = await getConfig();

			expect(config).not.toBeNull();
			expect(config!.id).toBe("cfg-1");
			expect(config!.enabled).toBe(true);
			expect(config!.ideasPerCompetitor).toBe(10);
			expect(config!.adaptationStyle).toBe("casual");
			expect(config!.topicFilters).toEqual(["marketing"]);
			expect(config!.lastScanAt).toBeInstanceOf(Date);
			expect(config!.ideasGeneratedToday).toBe(5);
		});

		it("creates default config when none exists", async () => {
			// First call returns no config, second call for workspace, third for insert
			const { chainable: noConfigChain } = createChainMock({ data: null, error: null });
			const wsRow = { id: "ws-1" };
			const { chainable: wsChain } = createChainMock({ data: wsRow, error: null });
			const createdConfig = {
				id: "cfg-new",
				user_id: "user-123",
				workspace_id: "ws-1",
				enabled: true,
				ideas_per_competitor: 10,
				adaptation_style: "casual",
				topic_filters: [],
				notify_new_ideas: true,
				daily_digest_enabled: false,
				ideas_generated_today: 0,
			};
			const { chainable: insertChain } = createChainMock({ data: createdConfig, error: null });

			let callCount = 0;
			mockSupabase.from.mockImplementation((table: string) => {
				callCount++;
				if (table === "inspiration_config" && callCount === 1) return noConfigChain;
				if (table === "workspaces") return wsChain;
				return insertChain;
			});

			const config = await getConfig();

			expect(config).not.toBeNull();
			expect(config!.id).toBe("cfg-new");
		});

		it("returns null when not authenticated", async () => {
			const { getUserIdAsync } = await import("@/services/api/shared");
			(getUserIdAsync as any).mockRejectedValueOnce(new Error("Not auth"));

			const config = await getConfig();

			expect(config).toBeNull();
		});

		it("returns null on database error", async () => {
			const { chainable } = createChainMock({ data: null, error: { message: "DB fail" } });
			mockSupabase.from.mockReturnValue(chainable);

			const config = await getConfig();

			expect(config).toBeNull();
		});

		it("handles null topic_filters gracefully", async () => {
			const configRow = {
				id: "cfg-1",
				user_id: "user-123",
				enabled: true,
				ideas_per_competitor: 10,
				adaptation_style: "casual",
				topic_filters: null,
				notify_new_ideas: true,
				daily_digest_enabled: false,
				ideas_generated_today: 0,
			};
			const { chainable } = createChainMock({ data: configRow, error: null });
			mockSupabase.from.mockReturnValue(chainable);

			const config = await getConfig();

			expect(config!.topicFilters).toEqual([]);
		});
	});

	describe("updateConfig", () => {
		it("maps camelCase fields to snake_case DB columns", async () => {
			const { chainable } = createChainMock({ data: null, error: null });
			mockSupabase.from.mockReturnValue(chainable);

			const result = await updateConfig({
				enabled: false,
				ideasPerCompetitor: 20,
				adaptationStyle: "professional",
				topicFilters: ["tech"],
				notifyNewIdeas: false,
				dailyDigestEnabled: true,
			});

			expect(result).toBe(true);
			expect(chainable.update).toHaveBeenCalledWith({
				enabled: false,
				ideas_per_competitor: 20,
				adaptation_style: "professional",
				topic_filters: ["tech"],
				notify_new_ideas: false,
				daily_digest_enabled: true,
			});
		});

		it("only includes provided fields in update", async () => {
			const { chainable } = createChainMock({ data: null, error: null });
			mockSupabase.from.mockReturnValue(chainable);

			await updateConfig({ enabled: true });

			expect(chainable.update).toHaveBeenCalledWith({ enabled: true });
		});

		it("returns false when not authenticated", async () => {
			const { getUserIdAsync } = await import("@/services/api/shared");
			(getUserIdAsync as any).mockRejectedValueOnce(new Error("Not auth"));

			const result = await updateConfig({ enabled: false });

			expect(result).toBe(false);
		});

		it("returns false on database error", async () => {
			const { chainable } = createChainMock({ data: null, error: null });
			chainable.update = vi.fn().mockReturnValue({
				eq: vi.fn().mockRejectedValue(new Error("DB fail")),
			});
			mockSupabase.from.mockReturnValue(chainable);

			const result = await updateConfig({ enabled: false });

			expect(result).toBe(false);
		});
	});

	// =========================================================================
	// getIdeaCounts
	// =========================================================================

	describe("getIdeaCounts", () => {
		it("returns counts by status", async () => {
			const data = [
				{ status: "pending" },
				{ status: "pending" },
				{ status: "saved" },
				{ status: "queued" },
			];
			const { chainable } = createChainMock({ data, error: null });
			mockSupabase.from.mockReturnValue(chainable);

			const counts = await getIdeaCounts();

			expect(counts.total).toBe(4);
			expect(counts.pending).toBe(2);
			expect(counts.saved).toBe(1);
			expect(counts.queued).toBe(1);
		});

		it("returns zero counts when not authenticated", async () => {
			const { getUserIdAsync } = await import("@/services/api/shared");
			(getUserIdAsync as any).mockRejectedValueOnce(new Error("Not auth"));

			const counts = await getIdeaCounts();

			expect(counts).toEqual({ total: 0, pending: 0, saved: 0, queued: 0 });
		});

		it("returns zero counts on database error", async () => {
			const { chainable } = createChainMock({ data: null, error: { message: "fail" } });
			mockSupabase.from.mockReturnValue(chainable);

			const counts = await getIdeaCounts();

			expect(counts).toEqual({ total: 0, pending: 0, saved: 0, queued: 0 });
		});

		it("handles empty result set", async () => {
			const { chainable } = createChainMock({ data: [], error: null });
			mockSupabase.from.mockReturnValue(chainable);

			const counts = await getIdeaCounts();

			expect(counts.total).toBe(0);
		});
	});

	// =========================================================================
	// getCompetitorsWithIdeas
	// =========================================================================

	describe("getCompetitorsWithIdeas", () => {
		it("groups ideas by competitor and sorts by count desc", async () => {
			const data = [
				{ competitor_username: "user_a", competitor_avatar_url: "https://a.com/av.jpg" },
				{ competitor_username: "user_a", competitor_avatar_url: "https://a.com/av.jpg" },
				{ competitor_username: "user_b", competitor_avatar_url: null },
				{ competitor_username: "user_a", competitor_avatar_url: "https://a.com/av.jpg" },
			];
			const { chainable } = createChainMock({ data, error: null });
			mockSupabase.from.mockReturnValue(chainable);

			const competitors = await getCompetitorsWithIdeas();

			expect(competitors).toHaveLength(2);
			expect(competitors[0].username).toBe("user_a");
			expect(competitors[0].count).toBe(3);
			expect(competitors[0].avatarUrl).toBe("https://a.com/av.jpg");
			expect(competitors[1].username).toBe("user_b");
			expect(competitors[1].count).toBe(1);
			expect(competitors[1].avatarUrl).toBeUndefined();
		});

		it("returns empty array when not authenticated", async () => {
			const { getUserIdAsync } = await import("@/services/api/shared");
			(getUserIdAsync as any).mockRejectedValueOnce(new Error("Not auth"));

			const competitors = await getCompetitorsWithIdeas();

			expect(competitors).toEqual([]);
		});
	});

	// =========================================================================
	// getTopicTags
	// =========================================================================

	describe("getTopicTags", () => {
		it("flattens and counts tags across all ideas", async () => {
			const data = [
				{ topic_tags: ["growth", "marketing"] },
				{ topic_tags: ["growth", "ai"] },
				{ topic_tags: ["marketing"] },
			];
			const { chainable } = createChainMock({ data, error: null });
			mockSupabase.from.mockReturnValue(chainable);

			const tags = await getTopicTags();

			expect(tags).toHaveLength(3);
			// Sorted by count desc
			const growthTag = tags.find((t) => t.tag === "growth");
			const marketingTag = tags.find((t) => t.tag === "marketing");
			const aiTag = tags.find((t) => t.tag === "ai");
			expect(growthTag!.count).toBe(2);
			expect(marketingTag!.count).toBe(2);
			expect(aiTag!.count).toBe(1);
		});

		it("handles null topic_tags in rows", async () => {
			const data = [
				{ topic_tags: null },
				{ topic_tags: ["ai"] },
			];
			const { chainable } = createChainMock({ data, error: null });
			mockSupabase.from.mockReturnValue(chainable);

			const tags = await getTopicTags();

			expect(tags).toHaveLength(1);
			expect(tags[0].tag).toBe("ai");
			expect(tags[0].count).toBe(1);
		});

		it("returns empty array when not authenticated", async () => {
			const { getUserIdAsync } = await import("@/services/api/shared");
			(getUserIdAsync as any).mockRejectedValueOnce(new Error("Not auth"));

			const tags = await getTopicTags();

			expect(tags).toEqual([]);
		});
	});

	// =========================================================================
	// deleteExpiredIdeas
	// =========================================================================

	describe("deleteExpiredIdeas", () => {
		it("deletes expired pending ideas and returns count", async () => {
			const deletedRows = [{ id: "idea-old-1" }, { id: "idea-old-2" }];
			const { chainable } = createChainMock({ data: deletedRows, error: null });
			mockSupabase.from.mockReturnValue(chainable);

			const count = await deleteExpiredIdeas();

			expect(count).toBe(2);
			expect(mockSupabase.from).toHaveBeenCalledWith("inspiration_ideas");
			expect(chainable.delete).toHaveBeenCalled();
			expect(chainable.eq).toHaveBeenCalledWith("status", "pending");
		});

		it("returns 0 on error", async () => {
			const { chainable } = createChainMock({ data: null, error: { message: "fail" } });
			mockSupabase.from.mockReturnValue(chainable);

			const count = await deleteExpiredIdeas();

			expect(count).toBe(0);
		});

		it("returns 0 when no expired ideas exist", async () => {
			const { chainable } = createChainMock({ data: [], error: null });
			mockSupabase.from.mockReturnValue(chainable);

			const count = await deleteExpiredIdeas();

			expect(count).toBe(0);
		});
	});

	// =========================================================================
	// saveExternalPost
	// =========================================================================

	describe("saveExternalPost", () => {
		it("sends POST request with correct body and auth header", async () => {
			mockFetch.mockResolvedValueOnce(mockApiResponse({
				ok: true,
				status: 200,
				body: { success: true },
			}));

			const post = {
				id: "ext-1",
				content: "External post content",
				username: "external_user",
				likeCount: 100,
				replyCount: 10,
			};

			const result = await saveExternalPost(post);

			expect(result).toBe(true);
			expect(mockFetch).toHaveBeenCalledWith(
				"/api/inspiration?action=save-external",
				expect.objectContaining({
					method: "POST",
					headers: expect.objectContaining({
						"Content-Type": "application/json",
						Authorization: `Bearer ${mockSession.access_token}`,
					}),
					body: JSON.stringify({ post }),
				}),
			);
		});

		it("returns true on 409 conflict (already saved)", async () => {
			mockFetch.mockResolvedValueOnce(mockApiResponse({
				ok: false,
				status: 409,
				body: { error: "Already exists" },
			}));

			const post = {
				id: "ext-1",
				content: "Post",
				username: "user",
			};

			const result = await saveExternalPost(post);

			expect(result).toBe(true);
		});

		it("throws on non-409 error responses", async () => {
			mockFetch.mockResolvedValueOnce(mockApiResponse({
				ok: false,
				status: 500,
				body: { error: "Server error" },
			}));

			const post = {
				id: "ext-1",
				content: "Post",
				username: "user",
			};

			await expect(saveExternalPost(post)).rejects.toMatchObject({
				status: 500,
				body: expect.stringContaining("Server error"),
			});
		});

		it("returns false when no session exists", async () => {
			mockSupabase.auth.getSession.mockResolvedValueOnce({
				data: { session: null },
			});
			mockGetStoredSession.mockReturnValueOnce(null);

			const post = {
				id: "ext-1",
				content: "Post",
				username: "user",
			};

			const result = await saveExternalPost(post);

			expect(result).toBe(false);
		});
	});

	// =========================================================================
	// subscribeToIdeas
	// =========================================================================

	describe("subscribeToIdeas", () => {
		it("returns an unsubscribe function", () => {
			const onUpdate = vi.fn();
			const onError = vi.fn();

			const unsub = subscribeToIdeas(onUpdate, onError);

			expect(typeof unsub).toBe("function");
			// Clean up
			unsub();
		});

		it("calls realtimeManager subscribe", async () => {
			const { subscribe } = await import("@/services/realtimeManager");
			const onUpdate = vi.fn();
			const onError = vi.fn();

			const unsub = subscribeToIdeas(onUpdate, onError);

			expect(subscribe).toHaveBeenCalledWith(
				"inspiration-ideas",
				expect.any(Function),
				expect.any(Function),
			);
			unsub();
		});
	});

	// =========================================================================
	// getIdeasByCompetitor (convenience wrapper)
	// =========================================================================

	describe("getIdeasByCompetitor", () => {
		it("delegates to getIdeas with competitor filter", async () => {
			const { chainable } = createChainMock({ data: [], error: null });
			mockSupabase.from.mockReturnValue(chainable);

			await (await import("@/services/inspirationService")).getIdeasByCompetitor("competitor_user");

			expect(chainable.eq).toHaveBeenCalledWith(
				"competitor_username",
				"competitor_user",
			);
		});
	});
});
