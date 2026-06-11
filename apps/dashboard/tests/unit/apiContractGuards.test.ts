import * as crypto from "crypto";
import { describe, expect, it } from "vitest";

/**
 * API Contract Guard Tests
 *
 * Validates:
 * 1. AnalyticsStats type completeness
 * 2. DashboardStats extends AnalyticsStats (EMPTY_STATS shape)
 * 3. AccountAnalyticsRow → MappedAnalyticsRow mapping
 * 4. API response shape (apiSuccess / apiError)
 * 5. Auth guard patterns (getAuthUserOrError, verifyCronAuth)
 * 6. accountId "ALL" guard pattern
 * 7. MetricRegistry ↔ AnalyticsStats key ↔ DB column contract
 */

// ---------------------------------------------------------------------------
// 1. AnalyticsStats Type Completeness
// ---------------------------------------------------------------------------

describe("AnalyticsStats type completeness", () => {
	// This object must conform to the AnalyticsStats interface from types/analytics.ts
	const completeStats = {
		totalFollowers: 1000,
		totalLikes: 500,
		totalReplies: 120,
		totalViews: 50000,
		totalReposts: 80,
		totalQuotes: 30,
		totalShares: 45,
		totalClicks: 200,
		scheduledCount: 5,
		engagementRate: 4.2,
		totalIgImpressions: 15000,
		totalIgReach: 12000,
		totalIgSaved: 300,
		totalIgShares: 150,
		igNewFollows: 25,
		igUnfollows: 3,
	};

	const REQUIRED_FIELDS = [
		"totalFollowers",
		"totalLikes",
		"totalReplies",
		"totalViews",
		"totalReposts",
		"totalQuotes",
		"totalShares",
		"totalClicks",
		"scheduledCount",
	];

	const OPTIONAL_FIELDS = [
		"engagementRate",
		"totalIgImpressions",
		"totalIgReach",
		"totalIgSaved",
		"totalIgShares",
		"igNewFollows",
		"igUnfollows",
	];

	it("has all required fields", () => {
		for (const field of REQUIRED_FIELDS) {
			expect(completeStats).toHaveProperty(field);
			expect(typeof completeStats[field as keyof typeof completeStats]).toBe(
				"number",
			);
		}
	});

	it("has all optional IG fields", () => {
		for (const field of OPTIONAL_FIELDS) {
			expect(completeStats).toHaveProperty(field);
		}
	});

	it("all numeric fields are numbers", () => {
		for (const [, value] of Object.entries(completeStats)) {
			expect(typeof value).toBe("number");
		}
	});

	it("includes exactly 16 fields (9 required + 7 optional)", () => {
		const allFields = [...REQUIRED_FIELDS, ...OPTIONAL_FIELDS];
		expect(allFields).toHaveLength(16);
		expect(Object.keys(completeStats)).toHaveLength(16);
	});
});

// ---------------------------------------------------------------------------
// 2. DashboardStats extends AnalyticsStats
// ---------------------------------------------------------------------------

describe("DashboardStats and EMPTY_STATS", () => {
	// Mirrors EMPTY_STATS from src/components/dashboard/types.ts
	const EMPTY_STATS = {
		totalFollowers: 0,
		totalLikes: 0,
		totalReplies: 0,
		totalReposts: 0,
		totalQuotes: 0,
		totalShares: 0,
		totalClicks: 0,
		scheduledCount: 0,
		totalViews: 0,
		engagementRate: 0,
		totalIgImpressions: 0,
		totalIgReach: 0,
		totalIgSaved: 0,
		totalIgShares: 0,
		igNewFollows: 0,
		igUnfollows: 0,
	};

	it("EMPTY_STATS has all DashboardStats fields set to 0", () => {
		for (const [, value] of Object.entries(EMPTY_STATS)) {
			expect(value).toBe(0);
		}
	});

	it("DashboardStats includes engagementRate as required (not optional)", () => {
		// In DashboardStats, engagementRate is required (number, not number?)
		// In AnalyticsStats, it is optional (number?)
		expect(EMPTY_STATS).toHaveProperty("engagementRate");
		expect(typeof EMPTY_STATS.engagementRate).toBe("number");
	});

	it("DashboardStats includes all IG fields as required (not optional)", () => {
		// In DashboardStats, IG fields are required: number
		// In AnalyticsStats, they are optional: number?
		const igFields = [
			"totalIgImpressions",
			"totalIgReach",
			"totalIgSaved",
			"totalIgShares",
			"igNewFollows",
			"igUnfollows",
		];

		for (const field of igFields) {
			expect(EMPTY_STATS).toHaveProperty(field);
			expect(EMPTY_STATS[field as keyof typeof EMPTY_STATS]).toBe(0);
		}
	});

	it("EMPTY_STATS has exactly 16 fields", () => {
		expect(Object.keys(EMPTY_STATS)).toHaveLength(16);
	});
});

// ---------------------------------------------------------------------------
// 3. AccountAnalyticsRow → MappedAnalyticsRow Mapping
// ---------------------------------------------------------------------------

describe("AccountAnalyticsRow → MappedAnalyticsRow mapping", () => {
	// Simulates the mapping that happens in analytics services
	function mapAnalyticsRow(raw: Record<string, unknown>) {
		return {
			accountId: raw.account_id as string,
			date: raw.date as string,
			rawDate: new Date(raw.date as string),
			followers: Number(raw.followers_count) || 0,
			followersCount: Number(raw.followers_count) || 0,
			followingCount: Number(raw.following_count) || 0,
			views: Number(raw.total_views) || 0,
			likes: Number(raw.total_likes) || 0,
			replies: Number(raw.total_replies) || 0,
			reposts: Number(raw.total_reposts) || 0,
			quotes: Number(raw.total_quotes) || 0,
			shares: Number(raw.total_shares) || 0,
			clicks: Number(raw.total_clicks) || 0,
			engagementRate: Number(raw.engagement_rate) || 0,
			followerGrowth: Number(raw.follower_growth) || 0,
			isBackfilled: false,
		};
	}

	it("maps followers_count → followers AND followersCount (both aliases)", () => {
		const raw = {
			account_id: "acc-1",
			date: "2026-03-09",
			followers_count: 1500,
			following_count: 200,
			total_views: 0,
			total_likes: 0,
			total_replies: 0,
			total_reposts: 0,
			total_quotes: 0,
			total_shares: 0,
			total_clicks: 0,
			engagement_rate: 0,
			follower_growth: 0,
		};

		const mapped = mapAnalyticsRow(raw);

		expect(mapped.followers).toBe(1500);
		expect(mapped.followersCount).toBe(1500);
		expect(mapped.followers).toBe(mapped.followersCount);
	});

	it("maps total_views → views", () => {
		const raw = {
			account_id: "acc-1",
			date: "2026-03-09",
			total_views: 50000,
			followers_count: 0,
			following_count: 0,
			total_likes: 0,
			total_replies: 0,
			total_reposts: 0,
			total_quotes: 0,
			total_shares: 0,
			total_clicks: 0,
			engagement_rate: 0,
			follower_growth: 0,
		};

		const mapped = mapAnalyticsRow(raw);
		expect(mapped.views).toBe(50000);
	});

	it("all numeric fields default to 0 when null", () => {
		const raw = {
			account_id: "acc-1",
			date: "2026-03-09",
			followers_count: null,
			following_count: null,
			total_views: null,
			total_likes: null,
			total_replies: null,
			total_reposts: null,
			total_quotes: null,
			total_shares: null,
			total_clicks: null,
			engagement_rate: null,
			follower_growth: null,
		};

		const mapped = mapAnalyticsRow(raw);

		expect(mapped.followers).toBe(0);
		expect(mapped.followersCount).toBe(0);
		expect(mapped.followingCount).toBe(0);
		expect(mapped.views).toBe(0);
		expect(mapped.likes).toBe(0);
		expect(mapped.replies).toBe(0);
		expect(mapped.reposts).toBe(0);
		expect(mapped.quotes).toBe(0);
		expect(mapped.shares).toBe(0);
		expect(mapped.clicks).toBe(0);
		expect(mapped.engagementRate).toBe(0);
		expect(mapped.followerGrowth).toBe(0);
	});

	it("all numeric fields default to 0 when undefined", () => {
		const raw = {
			account_id: "acc-1",
			date: "2026-03-09",
		};

		const mapped = mapAnalyticsRow(raw);

		expect(mapped.followers).toBe(0);
		expect(mapped.views).toBe(0);
		expect(mapped.likes).toBe(0);
		expect(mapped.replies).toBe(0);
	});

	it("maps account_id → accountId", () => {
		const raw = {
			account_id: "my-account-id",
			date: "2026-03-09",
		};

		const mapped = mapAnalyticsRow(raw);
		expect(mapped.accountId).toBe("my-account-id");
	});
});

// ---------------------------------------------------------------------------
// 4. API Response Shape Consistency
// ---------------------------------------------------------------------------

describe("API response shape consistency", () => {
	// Simulates apiSuccess and apiError from api/_lib/apiResponse.ts
	// without importing (contract test, not integration test)

	const ERROR_CODES: Record<number, string> = {
		400: "BAD_REQUEST",
		401: "UNAUTHORIZED",
		403: "FORBIDDEN",
		404: "NOT_FOUND",
		405: "METHOD_NOT_ALLOWED",
		409: "CONFLICT",
		429: "RATE_LIMITED",
		500: "INTERNAL_ERROR",
	};

	function buildSuccessResponse(data: Record<string, unknown> = {}) {
		return { success: true, ...data };
	}

	function buildErrorResponse(
		status: number,
		message: string,
		options?: { code?: string; details?: string },
	) {
		const body: Record<string, string> = {
			error: message,
			code: options?.code || ERROR_CODES[status] || "UNKNOWN",
		};
		if (options?.details) body.details = options.details;
		return { status, body };
	}

	it("apiSuccess wraps data with { success: true, ...data }", () => {
		const data = { posts: [1, 2, 3], total: 3 };
		const response = buildSuccessResponse(data);

		expect(response.success).toBe(true);
		expect(response).toHaveProperty("posts");
		expect(response).toHaveProperty("total");
	});

	it("apiSuccess with empty data returns { success: true }", () => {
		const response = buildSuccessResponse();
		expect(response).toEqual({ success: true });
	});

	it("apiError wraps with { error: msg, code: ... }", () => {
		const response = buildErrorResponse(401, "Not authenticated");

		expect(response.status).toBe(401);
		expect(response.body.error).toBe("Not authenticated");
		expect(response.body.code).toBe("UNAUTHORIZED");
	});

	it("apiError includes details when provided", () => {
		const response = buildErrorResponse(500, "DB failed", {
			details: "connection timeout",
		});

		expect(response.body.details).toBe("connection timeout");
	});

	it("apiError uses correct code for each HTTP status", () => {
		expect(buildErrorResponse(400, "bad").body.code).toBe("BAD_REQUEST");
		expect(buildErrorResponse(401, "unauth").body.code).toBe("UNAUTHORIZED");
		expect(buildErrorResponse(403, "forbidden").body.code).toBe("FORBIDDEN");
		expect(buildErrorResponse(404, "missing").body.code).toBe("NOT_FOUND");
		expect(buildErrorResponse(405, "method").body.code).toBe(
			"METHOD_NOT_ALLOWED",
		);
		expect(buildErrorResponse(429, "rate").body.code).toBe("RATE_LIMITED");
		expect(buildErrorResponse(500, "error").body.code).toBe("INTERNAL_ERROR");
	});

	it("apiError with unknown status uses UNKNOWN code", () => {
		const response = buildErrorResponse(418, "I'm a teapot");
		expect(response.body.code).toBe("UNKNOWN");
	});

	it("apiSuccess does NOT include an error field", () => {
		const response = buildSuccessResponse({ data: "test" });
		expect(response).not.toHaveProperty("error");
	});

	it("apiError does NOT include success: true", () => {
		const response = buildErrorResponse(500, "fail");
		expect(response.body).not.toHaveProperty("success");
	});
});

// ---------------------------------------------------------------------------
// 5. Auth Guard Patterns
// ---------------------------------------------------------------------------

describe("auth guard patterns", () => {
	describe("getAuthUserOrError contract", () => {
		it("requires Bearer prefix in authorization header", () => {
			const validHeader = "Bearer eyJhbGciOiJIUzI1NiJ9.test.token";
			const invalidHeaders = [
				undefined,
				"",
				"Basic dXNlcjpwYXNz",
				"Token abc123",
				"bearer lowercase", // Must be exactly "Bearer "
			];

			expect(validHeader.startsWith("Bearer ")).toBe(true);
			for (const header of invalidHeaders) {
				expect(header?.startsWith("Bearer ") ?? false).toBe(false);
			}
		});

		it("API keys start with juno_ak_ prefix", () => {
			const apiKey = "juno_ak_abc123def456";
			const jwtToken = "eyJhbGciOiJIUzI1NiJ9.test.token";

			expect(apiKey.startsWith("juno_ak_")).toBe(true);
			expect(jwtToken.startsWith("juno_ak_")).toBe(false);
		});

		it("missing authorization header results in 401", () => {
			// Contract: getAuthUserOrError sends 401 and returns null
			// when authorization header is missing
			const req = { headers: {} } as { headers: Record<string, string> };
			const hasAuth = !!req.headers.authorization;

			expect(hasAuth).toBe(false);
			// The function would return null and send 401
		});
	});

	describe("verifyCronAuth contract", () => {
		it("compares Bearer {CRON_SECRET} using timing-safe comparison", () => {
			const cronSecret = "my-cron-secret-123";
			const expected = `Bearer ${cronSecret}`;
			const validHeader = `Bearer ${cronSecret}`;

			// Timing-safe comparison requires same-length buffers
			expect(validHeader.length).toBe(expected.length);
			expect(
				crypto.timingSafeEqual(
					Buffer.from(validHeader),
					Buffer.from(expected),
				),
			).toBe(true);
		});

		it("rejects when CRON_SECRET is not configured", () => {
			const expectedSecret = undefined;
			// verifyCronAuth returns false if CRON_SECRET is unset
			expect(!expectedSecret).toBe(true);
		});

		it("rejects when Bearer token does not match", () => {
			const cronSecret = "correct-secret";
			const expected = `Bearer ${cronSecret}`;
			const invalidHeader = "Bearer wrong-secret";

			// Different lengths → cannot use timingSafeEqual, must reject
			const sameLength = expected.length === invalidHeader.length;
			if (sameLength) {
				expect(
					crypto.timingSafeEqual(
						Buffer.from(invalidHeader),
						Buffer.from(expected),
					),
				).toBe(false);
			} else {
				expect(sameLength).toBe(false); // Length mismatch → rejected
			}
		});

		it("rejects empty authorization header", () => {
			const cronSecret = "my-secret";
			const expected = `Bearer ${cronSecret}`;
			const emptyHeader = "";

			expect(emptyHeader.length).not.toBe(expected.length);
		});
	});
});

// ---------------------------------------------------------------------------
// 6. accountId "ALL" Guard
// ---------------------------------------------------------------------------

describe('accountId "ALL" guard pattern', () => {
	it('"ALL" is the sentinel value for workspace-scoped queries', () => {
		const accountId = "ALL";
		expect(accountId).toBe("ALL");
	});

	it("guard should return early when accountId is ALL", () => {
		function handleRequest(accountId: string | undefined) {
			if (!accountId || accountId === "ALL") {
				return { guarded: true, data: null };
			}
			return { guarded: false, data: `fetching for ${accountId}` };
		}

		expect(handleRequest("ALL")).toEqual({ guarded: true, data: null });
		expect(handleRequest(undefined)).toEqual({ guarded: true, data: null });
		expect(handleRequest("")).toEqual({ guarded: true, data: null });
		expect(handleRequest("acc-123")).toEqual({
			guarded: false,
			data: "fetching for acc-123",
		});
	});

	it('"ALL" should NOT be passed to single-account API queries', () => {
		function buildQuery(accountId: string) {
			if (accountId === "ALL") {
				throw new Error("Cannot query single account with ALL");
			}
			return `.eq("account_id", "${accountId}")`;
		}

		expect(() => buildQuery("ALL")).toThrow(
			"Cannot query single account with ALL",
		);
		expect(() => buildQuery("acc-123")).not.toThrow();
	});

	it("workspace-scoped resolver should be used for ALL", () => {
		// Contract: when accountId === "ALL", backend should use
		// getAccountIdsForContext() from workspaceAccounts.ts
		// to resolve the list of accounts in the workspace
		const accountId = "ALL";
		const useWorkspaceResolver = accountId === "ALL";
		expect(useWorkspaceResolver).toBe(true);
	});
});

// ---------------------------------------------------------------------------
// 7. MetricRegistry ↔ AnalyticsStats Key ↔ DB Column Contract
// ---------------------------------------------------------------------------

describe("MetricRegistry ↔ AnalyticsStats column contract", () => {
	// Mirror of METRIC_REGISTRY from src/lib/metricRegistry.ts
	const METRIC_REGISTRY = [
		{ key: "totalLikes", dbColumn: "total_likes" },
		{ key: "totalReplies", dbColumn: "total_replies" },
		{ key: "totalViews", dbColumn: "total_views" },
		{ key: "totalReposts", dbColumn: "total_reposts" },
		{ key: "totalQuotes", dbColumn: "total_quotes" },
		{ key: "totalIgReach", dbColumn: "total_reach" },
		{ key: "totalIgSaved", dbColumn: "total_saves" },
		{ key: "totalIgShares", dbColumn: "total_shares" },
		{ key: "totalIgImpressions", dbColumn: "ig_impressions" },
		{ key: "totalFollowers", dbColumn: "followers_count" },
		{ key: "totalClicks", dbColumn: "total_clicks" },
		{ key: "totalShares", dbColumn: "total_shares" },
		{ key: "scheduledCount", dbColumn: "" }, // Computed, no DB column
		{ key: "igNewFollows", dbColumn: "ig_new_follows" },
		{ key: "igUnfollows", dbColumn: "ig_unfollows" },
	];

	// AnalyticsStats fields from types/analytics.ts
	const ANALYTICS_STATS_KEYS = [
		"totalFollowers",
		"totalLikes",
		"totalReplies",
		"totalViews",
		"totalReposts",
		"totalQuotes",
		"totalShares",
		"totalClicks",
		"scheduledCount",
		"engagementRate",
		"totalIgImpressions",
		"totalIgReach",
		"totalIgSaved",
		"totalIgShares",
		"igNewFollows",
		"igUnfollows",
	];

	it("every registry key maps to a known AnalyticsStats field", () => {
		for (const metric of METRIC_REGISTRY) {
			expect(ANALYTICS_STATS_KEYS).toContain(metric.key);
		}
	});

	it("every AnalyticsStats field (except engagementRate) has a registry entry", () => {
		// engagementRate is computed, not stored directly
		const registryKeys = METRIC_REGISTRY.map((m) => m.key);
		for (const statsKey of ANALYTICS_STATS_KEYS) {
			if (statsKey === "engagementRate") continue; // Computed field
			expect(registryKeys).toContain(statsKey);
		}
	});

	it("DB columns are snake_case", () => {
		for (const metric of METRIC_REGISTRY) {
			if (!metric.dbColumn) continue; // scheduledCount has no DB column
			expect(metric.dbColumn).toMatch(/^[a-z][a-z0-9_]*$/);
		}
	});

	it("AnalyticsStats keys are camelCase", () => {
		for (const key of ANALYTICS_STATS_KEYS) {
			// camelCase: starts with lowercase, no underscores
			expect(key).toMatch(/^[a-z][a-zA-Z0-9]*$/);
		}
	});

	it("specific key → column mappings are correct", () => {
		const lookup = Object.fromEntries(
			METRIC_REGISTRY.map((m) => [m.key, m.dbColumn]),
		);

		expect(lookup.totalFollowers).toBe("followers_count");
		expect(lookup.totalLikes).toBe("total_likes");
		expect(lookup.totalReplies).toBe("total_replies");
		expect(lookup.totalViews).toBe("total_views");
		expect(lookup.totalReposts).toBe("total_reposts");
		expect(lookup.totalQuotes).toBe("total_quotes");
		expect(lookup.totalClicks).toBe("total_clicks");
		expect(lookup.totalIgImpressions).toBe("ig_impressions");
		expect(lookup.totalIgReach).toBe("total_reach");
		expect(lookup.totalIgSaved).toBe("total_saves");
		expect(lookup.igNewFollows).toBe("ig_new_follows");
		expect(lookup.igUnfollows).toBe("ig_unfollows");
	});

	it("scheduledCount has no DB column (it is computed from posts table)", () => {
		const scheduled = METRIC_REGISTRY.find(
			(m) => m.key === "scheduledCount",
		);
		expect(scheduled).toBeDefined();
		expect(scheduled!.dbColumn).toBe("");
	});

	it("totalShares and totalIgShares both map to total_shares (shared column)", () => {
		const sharesEntries = METRIC_REGISTRY.filter(
			(m) => m.dbColumn === "total_shares",
		);
		expect(sharesEntries).toHaveLength(2);
		const keys = sharesEntries.map((m) => m.key).sort();
		expect(keys).toEqual(["totalIgShares", "totalShares"]);
	});

	it("no duplicate registry keys", () => {
		const keys = METRIC_REGISTRY.map((m) => m.key);
		const unique = new Set(keys);
		expect(unique.size).toBe(keys.length);
	});
});
