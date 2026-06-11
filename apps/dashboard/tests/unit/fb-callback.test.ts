import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Unit tests for Facebook/Instagram OAuth callback handler.
 *
 * Tests the full OAuth flow:
 * - OAuth state validation (CSRF protection)
 * - Token exchange (short-lived -> long-lived)
 * - Account discovery (Facebook Pages -> Instagram Business)
 * - Account limit enforcement (tier-based)
 * - Token encryption before storage
 * - Error handling (missing params, Meta API errors, DB errors)
 */

// ---------------------------------------------------------------------------
// Mocks — must be declared before any imports that reference them
// ---------------------------------------------------------------------------

const mockEncrypt = vi.fn().mockImplementation((s: string) => `encrypted-${s}`);

vi.mock("@/api/_lib/encryption.js", () => ({
	encrypt: (...args: unknown[]) => mockEncrypt(...args),
}));

vi.mock("@/api/_lib/logger.js", () => ({
	logger: {
		info: vi.fn(),
		warn: vi.fn(),
		error: vi.fn(),
		debug: vi.fn(),
	},
}));

// Top-level mock fns for getAuthUserOrError and validateOAuthState so tests can configure per-case
const mockGetAuthUserOrError = vi.fn();
const mockValidateOAuthState = vi.fn();

vi.mock("@/api/_lib/apiResponse.js", () => ({
	apiError: (res: any, status: number, msg: string, extra?: Record<string, unknown>) =>
		res.status(status).json({ error: msg, ...extra }),
	apiSuccess: (res: any, data: unknown) =>
		res.status(200).json({ success: true, ...(data as Record<string, unknown>) }),
	getAuthUserOrError: (...args: unknown[]) => mockGetAuthUserOrError(...args),
	validateOAuthState: (...args: unknown[]) => mockValidateOAuthState(...args),
}));

// Mock Redis module (lazy imported via dynamic import inside handler)
const mockRedisIncr = vi.fn().mockResolvedValue(1);
const mockRedisExpire = vi.fn().mockResolvedValue(true);
const mockRedisGet = vi.fn().mockResolvedValue("valid");
const mockRedisDel = vi.fn().mockResolvedValue(1);

vi.mock("@/api/_lib/redis.js", () => ({
	getRedis: () => ({
		incr: mockRedisIncr,
		expire: mockRedisExpire,
		get: mockRedisGet,
		del: mockRedisDel,
	}),
}));

// Mock Supabase — build a flexible chain mock
const mockSupabaseFrom = vi.fn();
const mockAuthGetUser = vi.fn();

const mockSupabase = {
	from: mockSupabaseFrom,
	auth: {
		getUser: mockAuthGetUser,
	},
};

vi.mock("@/api/_lib/supabase.js", () => ({
	getSupabase: () => mockSupabase,
}));

// Mock billing module (lazy imported via dynamic import)
const mockGetAccountLimit = vi.fn().mockReturnValue(5);

vi.mock("@/api/_lib/billing.js", () => ({
	getAccountLimit: (...args: unknown[]) => mockGetAccountLimit(...args),
}));

// Mock webhook-subscribe (lazy imported via dynamic import)
const mockSubscribePageToWebhooks = vi.fn().mockResolvedValue({ success: true });

vi.mock("@/api/instagram/webhook-subscribe", () => ({
	subscribePageToWebhooks: (...args: unknown[]) => mockSubscribePageToWebhooks(...args),
}));

// Mock QStash (lazy imported via dynamic import)
const mockQstashPublishJSON = vi.fn().mockResolvedValue({});

vi.mock("@/api/_lib/qstash.js", () => ({
	getQStashClient: () => ({
		publishJSON: mockQstashPublishJSON,
	}),
}));

// Mock global fetch for Meta API calls
const mockFetch = vi.fn();

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface MockResponse {
	status: ReturnType<typeof vi.fn>;
	json: ReturnType<typeof vi.fn>;
	setHeader: ReturnType<typeof vi.fn>;
	end: ReturnType<typeof vi.fn>;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function createMockRes(): MockResponse {
	const res: MockResponse = {
		status: vi.fn(),
		json: vi.fn(),
		setHeader: vi.fn(),
		end: vi.fn(),
	};
	res.status.mockReturnValue(res);
	res.json.mockReturnValue(res);
	res.end.mockReturnValue(res);
	return res;
}

function createMockReq(overrides: {
	method?: string;
	body?: Record<string, unknown>;
	headers?: Record<string, string>;
}) {
	return {
		method: overrides.method || "POST",
		body: overrides.body || { code: "valid-auth-code", state: "valid-state-abc123" },
		headers: {
			authorization: "Bearer valid-jwt-token",
			"x-forwarded-for": "1.2.3.4",
			...overrides.headers,
		},
	};
}

/** Standard Meta token exchange response */
function makeTokenResponse(accessToken: string) {
	return {
		ok: true,
		json: vi.fn().mockResolvedValue({ access_token: accessToken }),
	};
}

/** Standard long-lived token response */
function makeLongLivedTokenResponse(accessToken: string, expiresIn = 5184000) {
	return {
		ok: true,
		json: vi.fn().mockResolvedValue({
			access_token: accessToken,
			expires_in: expiresIn,
		}),
	};
}

/** Standard Pages response with an IG business account */
function makePagesResponse(pages: Array<{
	id: string;
	name: string;
	access_token: string;
	instagram_business_account?: { id: string };
}>) {
	return {
		ok: true,
		json: vi.fn().mockResolvedValue({ data: pages }),
	};
}

/** Standard IG profile response */
function makeIgProfileResponse(profile: {
	id: string;
	username: string;
	name?: string;
	profile_picture_url?: string;
	followers_count?: number;
	follows_count?: number;
	media_count?: number;
}) {
	return {
		ok: true,
		json: vi.fn().mockResolvedValue(profile),
	};
}

/** Standard authenticated user returned by Supabase auth */
function setupAuthUser(userId: string) {
	mockAuthGetUser.mockResolvedValue({
		data: { user: { id: userId } },
		error: null,
	});
}

/**
 * Build complete Supabase mock chain for the happy path.
 * Each `from(table)` call returns the correct mock chain based on what
 * the handler queries.
 */
function setupSupabaseChain(overrides: {
	profile?: { subscription_tier: string; extra_accounts?: number } | null;
	profileError?: { message: string } | null;
	threadsCount?: number;
	igCount?: number;
	existingAccounts?: Array<Record<string, unknown>> | null;
	existingAccountsError?: { message: string } | null;
	updateError?: { message: string } | null;
	insertResult?: Record<string, unknown> | null;
	insertError?: { message: string } | null;
}) {
	// Track call sequence for tables queried multiple times
	const igCallIndex = { value: 0 };

	mockSupabaseFrom.mockImplementation((table: string) => {
		if (table === "profiles") {
			return {
				select: vi.fn().mockReturnValue({
					eq: vi.fn().mockReturnValue({
						maybeSingle: vi.fn().mockResolvedValue({
							data: overrides.profile !== undefined
								? overrides.profile
								: { subscription_tier: "pro", extra_accounts: 0 },
							error: overrides.profileError || null,
						}),
					}),
				}),
			};
		}

		if (table === "accounts") {
			return {
				select: vi.fn().mockImplementation((_cols: string, opts?: { count?: string; head?: boolean }) => {
					if (opts?.count === "exact") {
						return {
							eq: vi.fn().mockReturnValue({
								eq: vi.fn().mockResolvedValue({
									count: overrides.threadsCount ?? 1,
									error: null,
								}),
							}),
						};
					}
					return {
						eq: vi.fn().mockReturnValue({
							maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
						}),
					};
				}),
			};
		}

		if (table === "instagram_accounts") {
			igCallIndex.value++;
			// First call with count: "exact" is the account count query
			// Second call is the existing account lookup
			// Third call could be upsert
			return {
				select: vi.fn().mockImplementation((_cols: string, opts?: { count?: string; head?: boolean }) => {
					if (opts?.count === "exact") {
						return {
							eq: vi.fn().mockReturnValue({
								eq: vi.fn().mockResolvedValue({
									count: overrides.igCount ?? 0,
									error: null,
								}),
							}),
						};
					}
					// Existing account lookup: .select("*").eq("user_id",...).eq("instagram_user_id",...).limit(1)
					return {
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({
									data: overrides.existingAccounts !== undefined
										? overrides.existingAccounts
										: [],
									error: overrides.existingAccountsError || null,
								}),
							}),
						}),
					};
				}),
				update: vi.fn().mockReturnValue({
					eq: vi.fn().mockResolvedValue({
						error: overrides.updateError || null,
					}),
				}),
				upsert: vi.fn().mockReturnValue({
					select: vi.fn().mockReturnValue({
						maybeSingle: vi.fn().mockResolvedValue({
							data: overrides.insertResult !== undefined
								? overrides.insertResult
								: { id: "new-ig-acc-uuid" },
							error: overrides.insertError || null,
						}),
					}),
				}),
			};
		}

		// Fallback
		return {
			select: vi.fn().mockReturnThis(),
			eq: vi.fn().mockReturnThis(),
			maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
		};
	});
}

/**
 * Set up all fetch calls for the full happy path in order:
 * 1. Short-lived token exchange
 * 2. Long-lived token exchange
 * 3. Pages fetch
 * 4. IG profile fetch
 */
function setupHappyPathFetch() {
	mockFetch
		// Step 1: short-lived token exchange
		.mockResolvedValueOnce(makeTokenResponse("short-lived-token"))
		// Step 2: long-lived token exchange
		.mockResolvedValueOnce(makeLongLivedTokenResponse("long-lived-token"))
		// Step 3: Pages with IG business account
		.mockResolvedValueOnce(
			makePagesResponse([
				{
					id: "page-123",
					name: "My Business Page",
					access_token: "page-token-abc",
					instagram_business_account: { id: "ig-biz-456" },
				},
			]),
		)
		// Step 4: IG profile
		.mockResolvedValueOnce(
			makeIgProfileResponse({
				id: "ig-biz-456",
				username: "mybizaccount",
				name: "My Biz Account",
				profile_picture_url: "https://example.com/pic.jpg",
				followers_count: 1000,
				follows_count: 500,
				media_count: 200,
			}),
		);
}

// ---------------------------------------------------------------------------
// Test Suite
// ---------------------------------------------------------------------------

describe("Facebook/Instagram OAuth callback handler", () => {
	let handler: (req: any, res: any) => Promise<any>;

	beforeEach(async () => {
		vi.resetAllMocks();

		// Set required env vars
		process.env.FACEBOOK_APP_ID = "test-app-id";
		process.env.FACEBOOK_APP_SECRET = "test-app-secret";
		process.env.FACEBOOK_REDIRECT_URI = "https://juno33.com/auth/facebook/callback";

		// Mock global fetch
		global.fetch = mockFetch as unknown as typeof fetch;

		// Default mock implementations (resetAllMocks clears these, so re-set each time)
		mockEncrypt.mockImplementation((s: string) => `encrypted-${s}`);
		mockRedisIncr.mockResolvedValue(1);
		mockRedisExpire.mockResolvedValue(true);
		mockRedisGet.mockResolvedValue("valid");
		mockRedisDel.mockResolvedValue(1);
		mockGetAccountLimit.mockReturnValue(5);
		mockSubscribePageToWebhooks.mockResolvedValue({ success: true });
		mockQstashPublishJSON.mockResolvedValue({});

		// Default: validateOAuthState passes (replicates real validation logic)
		mockValidateOAuthState.mockImplementation((state: unknown, _res: any) => {
			if (!state || typeof state !== "string" || state.trim() === "") {
				_res.status(400).json({ error: "Missing or empty OAuth state parameter" });
				return false;
			}
			if (!/^[a-zA-Z0-9_-]{8,128}$/.test(state)) {
				_res.status(400).json({ error: "Invalid OAuth state parameter format" });
				return false;
			}
			return true;
		});

		// Default: getAuthUserOrError returns authenticated user
		mockGetAuthUserOrError.mockResolvedValue({ id: "user-123" });

		// Default auth (kept for any paths that still use Supabase auth directly)
		setupAuthUser("user-123");

		// Re-import handler each test to get fresh module state
		const mod = await import("@/api/auth/instagram/fb-callback.js");
		handler = mod.default;
	});

	afterEach(() => {
		delete process.env.FACEBOOK_APP_ID;
		delete process.env.FACEBOOK_APP_SECRET;
		delete process.env.FACEBOOK_REDIRECT_URI;
		vi.restoreAllMocks();
	});

	// =========================================================================
	// 1. HTTP Method validation
	// =========================================================================

	describe("HTTP method validation", () => {
		it("returns 200 for OPTIONS (CORS preflight)", async () => {
			const req = createMockReq({ method: "OPTIONS" });
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(200);
			expect(res.end).toHaveBeenCalled();
		});

		it("returns 405 for GET requests", async () => {
			const req = createMockReq({ method: "GET" });
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(405);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ error: "Method not allowed" }),
			);
		});
	});

	// =========================================================================
	// 2. OAuth state validation (CSRF protection)
	// =========================================================================

	describe("OAuth state validation", () => {
		it("returns 400 when state parameter is missing", async () => {
			const req = createMockReq({ body: { code: "valid-code" } });
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(400);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ error: "Missing or empty OAuth state parameter" }),
			);
		});

		it("returns 400 when state parameter is empty string", async () => {
			const req = createMockReq({ body: { code: "valid-code", state: "" } });
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(400);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ error: "Missing or empty OAuth state parameter" }),
			);
		});

		it("returns 400 when state parameter is whitespace only", async () => {
			const req = createMockReq({ body: { code: "valid-code", state: "   " } });
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(400);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ error: "Missing or empty OAuth state parameter" }),
			);
		});

		it("returns 400 when state has invalid characters", async () => {
			const req = createMockReq({
				body: { code: "valid-code", state: "invalid<state>with/special" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(400);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ error: "Invalid OAuth state parameter format" }),
			);
		});

		it("returns 400 when state is too short (< 8 chars)", async () => {
			const req = createMockReq({
				body: { code: "valid-code", state: "abc" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(400);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ error: "Invalid OAuth state parameter format" }),
			);
		});

		it("returns 400 when state exceeds 128 characters", async () => {
			const req = createMockReq({
				body: { code: "valid-code", state: "a".repeat(129) },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(400);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ error: "Invalid OAuth state parameter format" }),
			);
		});

		it("accepts valid state with UUID format", async () => {
			// Setup full happy path to confirm it proceeds past state validation
			setupHappyPathFetch();
			setupSupabaseChain({});

			const req = createMockReq({
				body: { code: "valid-code", state: "550e8400-e29b-41d4-a716-446655440000" },
			});
			const res = createMockRes();

			await handler(req, res);

			// Should not fail on state validation (will proceed to token exchange)
			expect(res.status).not.toHaveBeenCalledWith(400);
		});

		it("returns 400 when Redis state not found (fail-closed design)", async () => {
			// Redis returns null (state not stored or expired) — handler rejects (fail-closed)
			mockRedisGet.mockResolvedValue(null);
			setupHappyPathFetch();
			setupSupabaseChain({});

			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			// Should fail (fail-closed on missing state)
			expect(res.status).toHaveBeenCalledWith(400);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ error: "OAuth state expired or invalid. Please try connecting again." }),
			);
		});

		it("returns 503 when Redis state verification is unavailable", async () => {
			// Redis throws on get — handler must fail closed for OAuth CSRF protection
			mockRedisGet.mockRejectedValue(new Error("Redis connection refused"));
			setupHappyPathFetch();
			setupSupabaseChain({});

			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(503);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({
					code: "OAUTH_STATE_UNAVAILABLE",
				}),
			);
		});

		it("deletes Redis state key after successful validation (prevents reuse)", async () => {
			mockRedisGet.mockResolvedValue("valid");
			setupHappyPathFetch();
			setupSupabaseChain({});

			const req = createMockReq({
				body: { code: "valid-code", state: "unique-state-123" },
			});
			const res = createMockRes();

			await handler(req, res);

			// Verify the state was deleted from Redis
			expect(mockRedisDel).toHaveBeenCalledWith("oauth_state:user-123:unique-state-123");
		});
	});

	// =========================================================================
	// 3. Authentication
	// =========================================================================

	describe("Authentication", () => {
		it("returns 401 when getAuthUserOrError returns null (no auth header)", async () => {
			mockGetAuthUserOrError.mockImplementation(async (_req: any, _res: any) => {
				_res.status(401).json({ error: "Unauthorized" });
				return null;
			});

			const req = createMockReq({
				body: { code: "valid-code", state: "valid-state-abc123" },
				headers: {},
			});
			delete (req.headers as Record<string, string>).authorization;
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(401);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ error: "Unauthorized" }),
			);
		});

		it("returns 401 when getAuthUserOrError returns null (wrong header format)", async () => {
			mockGetAuthUserOrError.mockImplementation(async (_req: any, _res: any) => {
				_res.status(401).json({ error: "Unauthorized" });
				return null;
			});

			const req = createMockReq({
				headers: { authorization: "Basic some-token" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(401);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ error: "Unauthorized" }),
			);
		});

		it("returns 401 when getAuthUserOrError returns null (token expired)", async () => {
			mockGetAuthUserOrError.mockImplementation(async (_req: any, _res: any) => {
				_res.status(401).json({ error: "Unauthorized" });
				return null;
			});

			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(401);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ error: "Unauthorized" }),
			);
		});
	});

	// =========================================================================
	// 4. Missing code parameter
	// =========================================================================

	describe("Missing code parameter", () => {
		it("returns 400 when code is missing from body", async () => {
			const req = createMockReq({
				body: { state: "valid-state-abc123" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(400);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ error: "Authorization code is required" }),
			);
		});
	});

	// =========================================================================
	// 5. Server configuration
	// =========================================================================

	describe("Server configuration", () => {
		// vi.resetModules() invalidates vi.mock() registrations, so unit-testing
		// the FACEBOOK_APP_ID/SECRET runtime guard isn't feasible here. Tracked
		// as todo for documentation; runtime path exercised by integration tests.
		it.todo(
			"FACEBOOK_APP_ID/SECRET missing → 500 (integration only — vi.resetModules incompatible with global mocks)",
		);
	});

	// =========================================================================
	// 6. Token exchange
	// =========================================================================

	describe("Token exchange", () => {
		it("returns 400 when short-lived token exchange fails", async () => {
			mockFetch.mockResolvedValueOnce({
				ok: false,
				json: vi.fn().mockResolvedValue({
					error: { message: "Invalid verification code format" },
				}),
			});

			setupSupabaseChain({});
			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(400);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ error: "Failed to exchange authorization code" }),
			);
		});

		it("returns 400 when token response has no access_token", async () => {
			mockFetch.mockResolvedValueOnce({
				ok: true,
				json: vi.fn().mockResolvedValue({ error: "something went wrong" }),
			});

			setupSupabaseChain({});
			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(400);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ error: "Failed to exchange authorization code" }),
			);
		});

		it("returns 400 when long-lived token exchange fails", async () => {
			mockFetch
				.mockResolvedValueOnce(makeTokenResponse("short-token"))
				.mockResolvedValueOnce({
					ok: false,
					status: 400,
					json: vi.fn().mockResolvedValue({
						error: { message: "Invalid OAuth 2.0 Access Token" },
					}),
				});

			setupSupabaseChain({});
			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(400);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ error: "Failed to obtain long-lived token. Please try connecting again." }),
			);
		});

		it("returns 500 when network timeout occurs during token exchange", async () => {
			mockFetch.mockRejectedValueOnce(new DOMException("The operation was aborted", "AbortError"));

			setupSupabaseChain({});
			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			// The outer try/catch catches this and returns 500
			expect(res.status).toHaveBeenCalledWith(500);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ error: "Internal server error" }),
			);
		});

		it("sends correct parameters for short-lived token exchange", async () => {
			setupHappyPathFetch();
			setupSupabaseChain({});

			const req = createMockReq({ body: { code: "my-auth-code", state: "valid-state-abc123" } });
			const res = createMockRes();

			await handler(req, res);

			// Check the first fetch call (short-lived token exchange)
			const firstCall = mockFetch.mock.calls[0];
			expect(firstCall[0]).toBe("https://graph.facebook.com/v25.0/oauth/access_token");
			expect(firstCall[1].method).toBe("POST");
			expect(firstCall[1].headers["Content-Type"]).toBe("application/x-www-form-urlencoded");

			const bodyParams = new URLSearchParams(firstCall[1].body);
			expect(bodyParams.get("client_id")).toBe("test-app-id");
			expect(bodyParams.get("client_secret")).toBe("test-app-secret");
			expect(bodyParams.get("code")).toBe("my-auth-code");
			expect(bodyParams.get("redirect_uri")).toBe("https://juno33.com/auth/facebook/callback");
		});

		it("sends correct parameters for long-lived token exchange", async () => {
			setupHappyPathFetch();
			setupSupabaseChain({});

			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			// Check the second fetch call (long-lived token exchange)
			const secondCall = mockFetch.mock.calls[1];
			expect(secondCall[0]).toBe("https://graph.facebook.com/v25.0/oauth/access_token");

			const bodyParams = new URLSearchParams(secondCall[1].body);
			expect(bodyParams.get("grant_type")).toBe("fb_exchange_token");
			expect(bodyParams.get("fb_exchange_token")).toBe("short-lived-token");
		});
	});

	// =========================================================================
	// 7. Account discovery
	// =========================================================================

	describe("Account discovery", () => {
		it("returns 400 when pages fetch fails", async () => {
			mockFetch
				.mockResolvedValueOnce(makeTokenResponse("short-token"))
				.mockResolvedValueOnce(makeLongLivedTokenResponse("long-token"))
				.mockResolvedValueOnce({
					ok: false,
					json: vi.fn().mockResolvedValue({
						error: { message: "Invalid OAuth access token" },
					}),
				});

			setupSupabaseChain({});
			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(400);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ error: "Failed to fetch Facebook Pages" }),
			);
		});

		it("returns 400 when no Instagram Business account is linked to any page", async () => {
			mockFetch
				.mockResolvedValueOnce(makeTokenResponse("short-token"))
				.mockResolvedValueOnce(makeLongLivedTokenResponse("long-token"))
				.mockResolvedValueOnce(
					makePagesResponse([
						{
							id: "page-1",
							name: "My Page",
							access_token: "page-token-1",
							// No instagram_business_account
						},
						{
							id: "page-2",
							name: "Another Page",
							access_token: "page-token-2",
							// No instagram_business_account
						},
					]),
				);

			setupSupabaseChain({});
			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(400);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({
					error: expect.stringContaining("No Instagram Business or Creator account linked"),
				}),
			);
		});

		it("returns 400 when pages response has empty data array", async () => {
			mockFetch
				.mockResolvedValueOnce(makeTokenResponse("short-token"))
				.mockResolvedValueOnce(makeLongLivedTokenResponse("long-token"))
				.mockResolvedValueOnce(makePagesResponse([]));

			setupSupabaseChain({});
			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(400);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({
					error: expect.stringContaining("No Instagram Business or Creator account linked"),
				}),
			);
		});

		it("picks the first page with an Instagram business account when multiple pages exist", async () => {
			mockFetch
				.mockResolvedValueOnce(makeTokenResponse("short-token"))
				.mockResolvedValueOnce(makeLongLivedTokenResponse("long-token"))
				.mockResolvedValueOnce(
					makePagesResponse([
						{
							id: "page-no-ig",
							name: "No IG Page",
							access_token: "token-no-ig",
						},
						{
							id: "page-with-ig",
							name: "Has IG Page",
							access_token: "token-with-ig",
							instagram_business_account: { id: "ig-from-second-page" },
						},
						{
							id: "page-with-ig-2",
							name: "Also Has IG",
							access_token: "token-with-ig-2",
							instagram_business_account: { id: "ig-from-third-page" },
						},
					]),
				)
				.mockResolvedValueOnce(
					makeIgProfileResponse({
						id: "ig-from-second-page",
						username: "secondpage_ig",
						followers_count: 100,
					}),
				);

			setupSupabaseChain({});
			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(200);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({
					success: true,
					username: "secondpage_ig",
				}),
			);

			// Verify the IG profile fetch used the correct page access token
			const igProfileCall = mockFetch.mock.calls[3];
			expect(igProfileCall[0]).toContain("ig-from-second-page");
			expect(igProfileCall[1].headers.Authorization).toBe("Bearer token-with-ig");
		});

		it("returns 400 when IG profile fetch fails", async () => {
			mockFetch
				.mockResolvedValueOnce(makeTokenResponse("short-token"))
				.mockResolvedValueOnce(makeLongLivedTokenResponse("long-token"))
				.mockResolvedValueOnce(
					makePagesResponse([
						{
							id: "page-1",
							name: "My Page",
							access_token: "page-token",
							instagram_business_account: { id: "ig-123" },
						},
					]),
				)
				.mockResolvedValueOnce({
					ok: false,
					json: vi.fn().mockResolvedValue({
						error: { message: "Unsupported get request" },
					}),
				});

			setupSupabaseChain({});
			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(400);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ error: "Failed to fetch Instagram profile" }),
			);
		});

		it("returns 400 when IG profile has no username", async () => {
			mockFetch
				.mockResolvedValueOnce(makeTokenResponse("short-token"))
				.mockResolvedValueOnce(makeLongLivedTokenResponse("long-token"))
				.mockResolvedValueOnce(
					makePagesResponse([
						{
							id: "page-1",
							name: "My Page",
							access_token: "page-token",
							instagram_business_account: { id: "ig-123" },
						},
					]),
				)
				.mockResolvedValueOnce({
					ok: true,
					json: vi.fn().mockResolvedValue({
						id: "ig-123",
						// Missing username
						name: "Some IG",
					}),
				});

			setupSupabaseChain({});
			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(400);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ error: "Failed to fetch Instagram profile" }),
			);
		});
	});

	// =========================================================================
	// 8. Token encryption
	// =========================================================================

	describe("Token encryption", () => {
		it("encrypts both user token and page token before storage", async () => {
			setupHappyPathFetch();
			setupSupabaseChain({});

			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			// encrypt() should be called exactly twice: once for user token, once for page token
			expect(mockEncrypt).toHaveBeenCalledTimes(2);
			expect(mockEncrypt).toHaveBeenCalledWith("long-lived-token");
			expect(mockEncrypt).toHaveBeenCalledWith("page-token-abc");
		});
	});

	// =========================================================================
	// 9. Account limit enforcement
	// =========================================================================

	describe("Account limit enforcement", () => {
		it("allows new account when under limit", async () => {
			setupHappyPathFetch();
			setupSupabaseChain({
				profile: { subscription_tier: "free", extra_accounts: 0 },
				threadsCount: 0,
				igCount: 0,
			});
			mockGetAccountLimit.mockReturnValue(1);

			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(200);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({
					success: true,
					username: "mybizaccount",
				}),
			);
		});

		it("returns 403 when new account would exceed free tier limit", async () => {
			setupHappyPathFetch();
			setupSupabaseChain({
				profile: { subscription_tier: "free", extra_accounts: 0 },
				threadsCount: 1,
				igCount: 0,
				existingAccounts: [], // No existing IG account (this is a new one)
			});
			mockGetAccountLimit.mockReturnValue(1);

			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(403);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({
					code: "ACCOUNT_LIMIT_REACHED",
					tier: "free",
					maxAllowed: 1,
				}),
			);
		});

		it("returns 403 when reconnecting inactive account would exceed limit", async () => {
			setupHappyPathFetch();
			setupSupabaseChain({
				profile: { subscription_tier: "free", extra_accounts: 0 },
				threadsCount: 1,
				igCount: 0,
				existingAccounts: [
					{ id: "existing-ig-acc", is_active: false, instagram_user_id: "ig-biz-456" },
				],
			});
			mockGetAccountLimit.mockReturnValue(1);

			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(403);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({
					code: "ACCOUNT_LIMIT_REACHED",
				}),
			);
		});

		it("allows reconnecting existing active account regardless of limit", async () => {
			setupHappyPathFetch();
			setupSupabaseChain({
				profile: { subscription_tier: "free", extra_accounts: 0 },
				threadsCount: 1,
				igCount: 0,
				existingAccounts: [
					{ id: "existing-ig-acc", is_active: true, instagram_user_id: "ig-biz-456" },
				],
			});
			mockGetAccountLimit.mockReturnValue(1);

			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			// Active account reconnection skips the limit check
			expect(res.status).toHaveBeenCalledWith(200);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({
					success: true,
					isReconnected: true,
				}),
			);
		});

		it("calls getAccountLimit with correct tier and extra_accounts", async () => {
			setupHappyPathFetch();
			setupSupabaseChain({
				profile: { subscription_tier: "pro", extra_accounts: 3 },
				threadsCount: 2,
				igCount: 1,
			});
			mockGetAccountLimit.mockReturnValue(8); // pro base 5 + 3 extras

			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(mockGetAccountLimit).toHaveBeenCalledWith("pro", 3);
		});

		// Count query + insert is not atomic. Race mitigated by (1) browser-
		// serialized OAuth redirect flow, (2) upsert on (user_id, instagram_user_id),
		// (3) daily-maintenance cron cleaning excess. See fb-callback.ts:260.
		it.todo("account-limit insert race — accepted; see comment + fb-callback.ts:260");
	});

	// =========================================================================
	// 10. Database operations — existing account update
	// =========================================================================

	describe("Existing account update", () => {
		it("updates existing account and returns isReconnected=true", async () => {
			setupHappyPathFetch();
			setupSupabaseChain({
				existingAccounts: [
					{
						id: "existing-ig-uuid",
						is_active: true,
						instagram_user_id: "ig-biz-456",
						avatar_url: "https://old-pic.jpg",
						follower_count: 500,
						following_count: 250,
						media_count: 100,
					},
				],
			});

			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(200);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({
					success: true,
					accountId: "existing-ig-uuid",
					username: "mybizaccount",
					isReconnected: true,
					loginType: "facebook",
				}),
			);
		});

		it("returns 500 when database update fails", async () => {
			setupHappyPathFetch();
			setupSupabaseChain({
				existingAccounts: [
					{ id: "existing-ig-uuid", is_active: true, instagram_user_id: "ig-biz-456" },
				],
				updateError: { message: "connection refused" },
			});

			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(500);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ error: "Failed to update account" }),
			);
		});
	});

	// =========================================================================
	// 11. Database operations — new account creation
	// =========================================================================

	describe("New account creation", () => {
		it("creates new account with upsert and returns correct data", async () => {
			setupHappyPathFetch();
			setupSupabaseChain({
				existingAccounts: [],
				insertResult: { id: "new-ig-uuid-456" },
			});

			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(200);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({
					success: true,
					accountId: "new-ig-uuid-456",
					username: "mybizaccount",
					isReconnected: false,
					loginType: "facebook",
				}),
			);
		});

		it("returns 500 when database insert fails", async () => {
			setupHappyPathFetch();
			setupSupabaseChain({
				existingAccounts: [],
				insertResult: null,
				insertError: { message: "unique violation" },
			});

			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(500);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ error: "Failed to create account" }),
			);
		});

		it("returns 500 when insert returns no data (null result)", async () => {
			setupHappyPathFetch();
			setupSupabaseChain({
				existingAccounts: [],
				insertResult: null,
				insertError: null,
			});

			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(500);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ error: "Failed to create account" }),
			);
		});
	});

	// =========================================================================
	// 12. Database query error
	// =========================================================================

	describe("Database query error", () => {
		it("returns 500 when existing account query fails", async () => {
			setupHappyPathFetch();
			setupSupabaseChain({
				existingAccountsError: { message: "timeout" },
			});

			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(500);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ error: "Database error" }),
			);
		});
	});

	// =========================================================================
	// 13. Post-success operations (best-effort, should not fail login)
	// =========================================================================

	describe("Post-success operations", () => {
		it("attempts webhook subscription after successful account creation", async () => {
			setupHappyPathFetch();
			setupSupabaseChain({});

			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(mockSubscribePageToWebhooks).toHaveBeenCalledWith(
				"page-123",
				"page-token-abc",
			);
		});

		it("succeeds even when webhook subscription fails", async () => {
			mockSubscribePageToWebhooks.mockResolvedValue({ success: false, error: "Webhook error" });
			setupHappyPathFetch();
			setupSupabaseChain({});

			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			// Login should still succeed
			expect(res.status).toHaveBeenCalledWith(200);
		});

		it("succeeds even when webhook subscription throws", async () => {
			mockSubscribePageToWebhooks.mockRejectedValue(new Error("Network error"));
			setupHappyPathFetch();
			setupSupabaseChain({});

			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			// Login should still succeed
			expect(res.status).toHaveBeenCalledWith(200);
		});

		it("dispatches DM backfill via QStash after account creation", async () => {
			setupHappyPathFetch();
			setupSupabaseChain({ insertResult: { id: "new-acc-id" } });

			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(mockQstashPublishJSON).toHaveBeenCalledWith(
				expect.objectContaining({
					url: "https://juno33.com/api/instagram/messages?action=sync-inbox",
					body: expect.objectContaining({
						accountId: "new-acc-id",
						userId: "user-123",
						isBackfill: true,
					}),
				}),
			);
		});

		it("succeeds even when QStash dispatch fails", async () => {
			mockQstashPublishJSON.mockRejectedValue(new Error("QStash unavailable"));
			setupHappyPathFetch();
			setupSupabaseChain({});

			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(200);
		});
	});

	// =========================================================================
	// 14. Rate limiting
	// =========================================================================

	describe("Rate limiting", () => {
		it("returns 429 when auth rate limit is exceeded", async () => {
			mockRedisIncr.mockResolvedValue(151);

			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(429);
			expect(res.setHeader).toHaveBeenCalledWith("Retry-After", "60");
		});

		it("fails closed when the per-IP rate limiter Redis call fails", async () => {
			mockRedisIncr.mockRejectedValue(new Error("Redis down"));
			setupHappyPathFetch();
			setupSupabaseChain({});

			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(429);
		});

		it("sets TTL on rate limit key only on first increment", async () => {
			mockRedisIncr.mockResolvedValue(1);
			setupHappyPathFetch();
			setupSupabaseChain({});

			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(mockRedisExpire).toHaveBeenCalledWith(
				expect.stringContaining("rl:auth:fb:"),
				3600,
			);
		});
	});

	// =========================================================================
	// 15. CORS headers
	// =========================================================================

	describe("CORS headers", () => {
		it("sets correct CORS headers on all responses", async () => {
			const req = createMockReq({ method: "POST" });
			const res = createMockRes();

			// Even if auth fails, CORS headers should be set
			mockGetAuthUserOrError.mockImplementation(async (_req: any, _res: any) => {
				_res.status(401).json({ error: "Unauthorized" });
				return null;
			});

			await handler(req, res);

			expect(res.setHeader).toHaveBeenCalledWith(
				"Access-Control-Allow-Origin",
				"https://juno33.com",
			);
			expect(res.setHeader).toHaveBeenCalledWith(
				"Access-Control-Allow-Methods",
				"GET,OPTIONS,POST",
			);
			expect(res.setHeader).toHaveBeenCalledWith(
				"Access-Control-Allow-Headers",
				"Content-Type, Authorization",
			);
		});
	});

	// =========================================================================
	// 16. Full happy path integration
	// =========================================================================

	describe("Full happy path", () => {
		it("completes full OAuth flow for new account creation", async () => {
			setupHappyPathFetch();
			setupSupabaseChain({
				profile: { subscription_tier: "pro", extra_accounts: 0 },
				threadsCount: 1,
				igCount: 0,
				existingAccounts: [],
				insertResult: { id: "brand-new-ig-account" },
			});
			mockGetAccountLimit.mockReturnValue(5);

			const req = createMockReq({
				body: { code: "fresh-auth-code", state: "valid-state-abc123" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(200);
			expect(res.json).toHaveBeenCalledWith({
				success: true,
				accountId: "brand-new-ig-account",
				username: "mybizaccount",
				isReconnected: false,
				loginType: "facebook",
			});

			// Verify all 4 Meta API calls were made
			expect(mockFetch).toHaveBeenCalledTimes(4);

			// Verify encryption was called
			expect(mockEncrypt).toHaveBeenCalledTimes(2);

			// Verify webhook auto-subscribe was called
			expect(mockSubscribePageToWebhooks).toHaveBeenCalled();

			// Verify DM backfill was dispatched
			expect(mockQstashPublishJSON).toHaveBeenCalled();
		});

		it("completes full OAuth flow for existing account reconnection", async () => {
			setupHappyPathFetch();
			setupSupabaseChain({
				profile: { subscription_tier: "pro", extra_accounts: 0 },
				threadsCount: 2,
				igCount: 1,
				existingAccounts: [
					{
						id: "reconnected-ig-acc",
						is_active: true,
						instagram_user_id: "ig-biz-456",
						avatar_url: "https://old.jpg",
						follower_count: 800,
						following_count: 400,
						media_count: 150,
					},
				],
			});
			mockGetAccountLimit.mockReturnValue(5);

			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(200);
			expect(res.json).toHaveBeenCalledWith({
				success: true,
				accountId: "reconnected-ig-acc",
				username: "mybizaccount",
				isReconnected: true,
				loginType: "facebook",
			});
		});
	});

	// =========================================================================
	// 17. Edge cases
	// =========================================================================

	describe("Edge cases", () => {
		it("handles Meta API returning error response body with ok=true but no access_token", async () => {
			mockFetch.mockResolvedValueOnce({
				ok: true,
				json: vi.fn().mockResolvedValue({
					// Meta sometimes returns 200 with an error object
					error: { message: "Something went wrong", type: "OAuthException" },
				}),
			});

			setupSupabaseChain({});
			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(400);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ error: "Failed to exchange authorization code" }),
			);
		});

		it("uses default 60-day expiration when expires_in is not in response", async () => {
			mockFetch
				.mockResolvedValueOnce(makeTokenResponse("short-token"))
				.mockResolvedValueOnce({
					ok: true,
					json: vi.fn().mockResolvedValue({
						access_token: "long-token-no-expiry",
						// No expires_in field
					}),
				})
				.mockResolvedValueOnce(
					makePagesResponse([
						{
							id: "page-1",
							name: "Page",
							access_token: "page-token",
							instagram_business_account: { id: "ig-1" },
						},
					]),
				)
				.mockResolvedValueOnce(
					makeIgProfileResponse({
						id: "ig-1",
						username: "iguser",
					}),
				);

			setupSupabaseChain({});
			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			// Should succeed — default expiration is used
			expect(res.status).toHaveBeenCalledWith(200);
		});

		it("catches unhandled exceptions in the outer try/catch", async () => {
			// Force an unexpected error by making auth succeed but then throw in an unexpected place
			mockAuthGetUser.mockResolvedValue({
				data: { user: { id: "user-123" } },
				error: null,
			});
			// Make fetch throw an unexpected non-network error
			mockFetch.mockImplementation(() => {
				throw new TypeError("Cannot read properties of undefined");
			});

			const req = createMockReq({});
			const res = createMockRes();

			await handler(req, res);

			expect(res.status).toHaveBeenCalledWith(500);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ error: "Internal server error" }),
			);
		});
	});
});
