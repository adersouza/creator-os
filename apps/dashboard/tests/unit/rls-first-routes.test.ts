import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
	authUser: { id: "user-1", email: "user@example.com" },
	userDb: null as any,
	adminDb: null as any,
	adminDbAny: null as any,
	enforceRouteRateLimit: vi.fn(async () => true),
	checkRateLimit: vi.fn(async () => ({ allowed: true })),
	qstashPublishJSON: vi.fn(async () => ({ messageId: "msg-1" })),
	redisDel: vi.fn(async () => 1),
	redisSet: vi.fn(async () => "OK"),
	requireMinTier: vi.fn(async () => true),
	getUserTier: vi.fn(async () => "pro"),
	requireStepUp: vi.fn(async () => null),
	getPostSentimentSummary: vi.fn(async () => null),
	getPostSentimentSummaries: vi.fn(async () => new Map()),
}));

vi.mock("../../api/_lib/middleware.js", () => ({
	withAuthDb: (handler: any) => async (req: any, res: any) => {
		if (!req.headers?.authorization?.startsWith("Bearer ")) {
			return res.status(401).json({ error: "Unauthorized" });
		}
		return handler(req, res, {
			user: mocks.authUser,
			userDb: mocks.userDb,
			adminDb: mocks.adminDb,
			adminDbAny: mocks.adminDbAny,
		});
	},
	requireStepUp: mocks.requireStepUp,
}));

vi.mock("../../api/_lib/dbContext.js", () => ({
	createDbContext: () => ({
		user: mocks.authUser,
		userDb: mocks.userDb,
		adminDb: mocks.adminDb,
		adminDbAny: mocks.adminDbAny,
	}),
}));

vi.mock("../../api/_lib/routeRateLimit.js", () => ({
	enforceRouteRateLimit: mocks.enforceRouteRateLimit,
}));

vi.mock("../../api/_lib/rateLimiter.js", () => ({
	checkRateLimit: mocks.checkRateLimit,
}));

vi.mock("../../api/_lib/qstash.js", () => ({
	getQStashClient: () => ({ publishJSON: mocks.qstashPublishJSON }),
}));

vi.mock("../../api/_lib/qstashDefaults.js", () => ({
	getRequiredAppBaseUrl: () => "https://juno33.test",
}));

vi.mock("../../api/_lib/auditLog.js", () => ({
	logAudit: vi.fn(),
	trackUsage: vi.fn(),
}));

vi.mock("../../api/_lib/redis.js", () => ({
	getRedis: () => ({ del: mocks.redisDel, set: mocks.redisSet }),
}));

vi.mock("../../api/_lib/tierGate.js", () => ({
	getUserTier: mocks.getUserTier,
	requireMinTier: mocks.requireMinTier,
}));

vi.mock("../../api/_lib/sentimentTracker.js", () => ({
	getPostSentimentSummary: mocks.getPostSentimentSummary,
	getPostSentimentSummaries: mocks.getPostSentimentSummaries,
}));

vi.mock("../../api/_lib/threadsApi.js", () => ({
	lookupThreadsProfile: vi.fn(async () => ({ username: "target" })),
	getProfilePosts: vi.fn(async () => [{ id: "remote-post-1" }]),
}));

const savedViewsRoute = (await import("../../api/saved-views.js")).default;
const accountsRoute = (await import("../../api/accounts.js")).default;
const competitorsRoute = (await import("../../api/competitors.js")).default;
const tagsRoute = (await import("../../api/tags.js")).default;
const webhooksRoute = (await import("../../api/webhooks.js")).default;
const analyticsFleetHealthAccountsRoute = (
	await import("../../api/_lib/handlers/analytics-sub/fleet-health-accounts.js")
).default;
const analyticsHealthSnapshotsRoute = (
	await import("../../api/_lib/handlers/analytics-sub/health-snapshots.js")
).default;
const agentNotesRoute = (
	await import("../../api/_lib/handlers/agent/notes.js")
).default;
const agentSettingsRoute = (
	await import("../../api/_lib/handlers/agent/settings.js")
).default;
const aiDismissRecommendationRoute = (
	await import("../../api/_lib/handlers/ai/dismiss-recommendation.js")
).default;
const aiFeedbackRoute = (
	await import("../../api/_lib/handlers/ai/feedback.js")
).default;
const betaFeedbackRoute = (
	await import("../../api/_lib/handlers/beta/feedback.js")
).default;
const composerDiffsRoute = (
	await import("../../api/_lib/handlers/composer/diffs.js")
).default;
const composerHealthPillsRoute = (
	await import("../../api/_lib/handlers/composer/health-pills.js")
).default;
const composerVariantsRoute = (
	await import("../../api/_lib/handlers/composer/variants.js")
).default;
const composerVoiceFileRoute = (
	await import("../../api/_lib/handlers/composer/voice-file.js")
).default;
const crisisStatusRoute = (
	await import("../../api/_lib/handlers/crisis/status.js")
).default;
const developerKeysRoute = (await import("../../api/_lib/handlers/developer/keys.js")).default;
const instagramAutoRespondersRoute = (
	await import("../../api/_lib/handlers/instagram/auto-responders.js")
).default;
const instagramDmTemplatesRoute = (
	await import("../../api/_lib/handlers/instagram/dm-templates.js")
).default;
const listeningAlertsRoute = (
	await import("../../api/_lib/handlers/listening/alerts.js")
).default;
const mediaShareRoute = (
	await import("../../api/_lib/handlers/media-sub/share.js")
).default;
const trendingConfigRoute = (
	await import("../../api/_lib/handlers/misc/trending-config.js")
).default;
const repliesRoute = (await import("../../api/replies.js")).default;
const settingsUserWebhooksRoute = (
	await import("../../api/_lib/handlers/settings/user-webhooks.js")
).default;
const inboxMarkReadRoute = (
	await import("../../api/_lib/handlers/inbox/mark-read.js")
).default;
const postCommentsRoute = (
	await import("../../api/_lib/handlers/posts-sub/comments.js")
).default;
const draftFoldersRoute = (
	await import("../../api/_lib/handlers/posts-sub/draft-folders.js")
).default;
const postSentimentSummaryRoute = (
	await import("../../api/_lib/handlers/posts-sub/sentiment-summary.js")
).default;
const postSignalRoute = (
	await import("../../api/_lib/handlers/posts-sub/signal.js")
).default;
const postTemplatesRoute = (
	await import("../../api/_lib/handlers/posts-sub/templates.js")
).default;
const reportsUpdateHandler = (
	await import("../../api/_lib/handlers/reports/update.js")
).default;
const userDataContributionRoute = (
	await import("../../api/_lib/handlers/user/data-contribution.js")
).default;
const userExportRoute = (
	await import("../../api/_lib/handlers/user/export.js")
).default;
const userExportStatusRoute = (
	await import("../../api/_lib/handlers/user/export-status.js")
).default;
const userGrowthJournalRoute = (
	await import("../../api/_lib/handlers/user/growth-journal.js")
).default;

function mockRes() {
	const res: any = {};
	res.status = vi.fn().mockReturnValue(res);
	res.json = vi.fn().mockReturnValue(res);
	res.setHeader = vi.fn().mockReturnValue(res);
	return res;
}

function authedReq(input: Partial<any> = {}) {
	return {
		method: "GET",
		headers: { authorization: "Bearer user-token" },
		query: {},
		body: {},
		url: "/api/test",
		...input,
	};
}

function createSupabaseMock(fixtures: Record<string, any[]> = {}) {
	const calls = {
		filters: [] as Array<{
			table: string;
			column: string;
			value: unknown;
			operator?: "eq" | "gte" | "in" | "is" | "not_is";
		}>,
		inserts: [] as Array<{ table: string; row: Record<string, unknown> }>,
		deletes: [] as Array<{ table: string }>,
	};

	function filteredRows(table: string, filters: typeof calls.filters) {
		const tableFilters = filters.filter((filter) => filter.table === table);
		return (fixtures[table] ?? []).filter((row) =>
			tableFilters.every((filter) => {
				if (filter.operator === "in" && Array.isArray(filter.value)) {
					return filter.value.includes(row[filter.column]);
				}
				if (filter.operator === "is") {
					return row[filter.column] === filter.value;
				}
				if (filter.operator === "not_is") {
					return row[filter.column] !== filter.value;
				}
				if (filter.operator === "gte") {
					return String(row[filter.column]) >= String(filter.value);
				}
				return row[filter.column] === filter.value;
			}),
		);
	}

	const client = {
		from: vi.fn((table: string) => {
			const chain: any = {
				table,
				inserted: null,
				countRequested: false,
				deleteRequested: false,
				filters: [] as typeof calls.filters,
				select: vi.fn((_columns?: string, options?: { count?: string; head?: boolean }) => {
					chain.countRequested = Boolean(options?.count || options?.head);
					return chain;
				}),
				eq: vi.fn((column: string, value: unknown) => {
					const filter = { table, column, value, operator: "eq" as const };
					calls.filters.push(filter);
					chain.filters.push(filter);
					return chain;
				}),
				not: vi.fn((column: string, operator: string, value: unknown) => {
					if (operator === "is") {
						const filter = { table, column, value, operator: "not_is" as const };
						calls.filters.push(filter);
						chain.filters.push(filter);
					}
					return chain;
				}),
				gte: vi.fn((column: string, value: unknown) => {
					const filter = { table, column, value, operator: "gte" as const };
					calls.filters.push(filter);
					chain.filters.push(filter);
					return chain;
				}),
				in: vi.fn((column: string, value: unknown) => {
					const filter = { table, column, value, operator: "in" as const };
					calls.filters.push(filter);
					chain.filters.push(filter);
					return chain;
				}),
				is: vi.fn((column: string, value: unknown) => {
					const filter = { table, column, value, operator: "is" as const };
					calls.filters.push(filter);
					chain.filters.push(filter);
					return chain;
				}),
				order: vi.fn(() => chain),
				limit: vi.fn(() => chain),
				insert: vi.fn((row: Record<string, unknown>) => {
					calls.inserts.push({ table, row });
					chain.inserted = row;
					return chain;
				}),
				upsert: vi.fn((row: Record<string, unknown> | Record<string, unknown>[]) => {
					if (Array.isArray(row)) {
						for (const item of row) calls.inserts.push({ table, row: item });
					} else {
						calls.inserts.push({ table, row });
						chain.inserted = row;
					}
					return chain;
				}),
				single: vi.fn(() =>
					Promise.resolve({
						data: {
							id: "created-view",
							created_at: "2026-06-01T00:00:00.000Z",
							updated_at: "2026-06-01T00:00:00.000Z",
							...chain.inserted,
						},
						error: null,
					}),
				),
				maybeSingle: vi.fn(() =>
					Promise.resolve({
						data: chain.inserted
							? {
									id: "created-view",
									created_at: "2026-06-01T00:00:00.000Z",
									updated_at: "2026-06-01T00:00:00.000Z",
									...chain.inserted,
								}
							: (filteredRows(table, chain.filters)[0] ?? null),
						error: null,
					}),
				),
				delete: vi.fn(() => {
					calls.deletes.push({ table });
					chain.deleteRequested = true;
					return chain;
				}),
				update: vi.fn((row: Record<string, unknown>) => {
					calls.inserts.push({ table, row });
					chain.inserted = row;
					return chain;
				}),
				then: (onFulfilled: any, onRejected: any) =>
					Promise.resolve({
						data: filteredRows(table, chain.filters),
						error: null,
						count: chain.deleteRequested || chain.countRequested
							? filteredRows(table, chain.filters).length
							: undefined,
					}).then(onFulfilled, onRejected),
			};
			return chain;
		}),
		rpc: vi.fn(async () => ({ data: null, error: null })),
	};

	return { client, calls };
}

describe("RLS-first migrated route guardrails", () => {
	it("keeps migrated routes on withAuthDb without direct service-role imports", () => {
		for (const route of [
			"api/saved-views.ts",
			"api/accounts.ts",
			"api/competitors.ts",
			"api/auth/disconnect.ts",
			"api/tags.ts",
			"api/webhooks.ts",
			"api/_lib/handlers/analytics-sub/fleet-health-accounts.ts",
			"api/_lib/handlers/analytics-sub/health-snapshots.ts",
			"api/_lib/handlers/agent/notes.ts",
			"api/_lib/handlers/agent/settings.ts",
			"api/_lib/handlers/ai/dismiss-recommendation.ts",
			"api/_lib/handlers/ai/feedback.ts",
			"api/_lib/handlers/beta/feedback.ts",
			"api/_lib/handlers/composer/diffs.ts",
			"api/_lib/handlers/composer/health-pills.ts",
			"api/_lib/handlers/composer/variants.ts",
			"api/_lib/handlers/composer/voice-file.ts",
			"api/_lib/handlers/crisis/status.ts",
			"api/_lib/handlers/developer/keys.ts",
			"api/_lib/handlers/instagram/auto-responders.ts",
			"api/_lib/handlers/instagram/dm-templates.ts",
			"api/_lib/handlers/listening/alerts.ts",
			"api/_lib/handlers/media/index.ts",
			"api/_lib/handlers/media-sub/share.ts",
			"api/_lib/handlers/misc/trending-config.ts",
			"api/replies.ts",
			"api/_lib/handlers/settings/user-webhooks.ts",
			"api/_lib/handlers/inbox/mark-read.ts",
			"api/_lib/handlers/inbox/rules.ts",
			"api/_lib/handlers/posts-sub/comments.ts",
			"api/_lib/handlers/posts-sub/draft-folders.ts",
			"api/_lib/handlers/posts-sub/sentiment-summary.ts",
			"api/_lib/handlers/posts-sub/signal.ts",
			"api/_lib/handlers/posts-sub/templates.ts",
			"api/_lib/handlers/threads/profile.ts",
			"api/_lib/handlers/user/annual-recap.ts",
			"api/_lib/handlers/user/data-contribution.ts",
			"api/_lib/handlers/user/export.ts",
			"api/_lib/handlers/user/export-status.ts",
			"api/_lib/handlers/user/growth-journal.ts",
		]) {
			const source = readFileSync(resolve(process.cwd(), route), "utf8");
			expect(source).toMatch(/withAuthDb|createDbContext/);
			expect(source).not.toMatch(/getSupabase(?:Any)?\s*\(/);
			expect(source).not.toMatch(
				/from\s+["'](?![^"']*types\/supabase\.js)[^"']*supabase\.js["']/,
			);
		}
	});
});

describe("analytics read-only RLS-first routes", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("reads health snapshots through the user-scoped client", async () => {
		const { client } = createSupabaseMock({
			account_health_snapshots: [
				{
					account_id: "account-1",
					user_id: "user-1",
					account_name: "Main",
					platform: "threads",
					has_anomaly: true,
					anomaly_severity: "high",
					anomaly_detail: "Reach dropped",
					reach_drop_pct: -52,
					growth_pct: -8,
					followers_current: 100,
					posts_this_period: 2,
					days_since_last_post: 1,
					engagement_rate: 0.05,
					computed_at: "2026-06-01T00:00:00.000Z",
					period_days: 7,
				},
				{
					account_id: "account-2",
					user_id: "user-1",
					account_name: "Riser",
					platform: "instagram",
					has_anomaly: false,
					anomaly_severity: null,
					anomaly_detail: null,
					reach_drop_pct: null,
					growth_pct: 12.4,
					followers_current: 250,
					posts_this_period: 3,
					days_since_last_post: 0,
					engagement_rate: 0.2,
					computed_at: "2026-06-01T00:00:00.000Z",
					period_days: 7,
				},
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await analyticsHealthSnapshotsRoute(authedReq() as any, res);

		expect(client.from).toHaveBeenCalledWith("account_health_snapshots");
		expect(admin.from).not.toHaveBeenCalled();
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				success: true,
				totalAccounts: 2,
				computedAt: "2026-06-01T00:00:00.000Z",
				alerts: [
					expect.objectContaining({
						accountId: "account-1",
						type: "reach_drop",
					}),
				],
				topPerformers: [
					expect.objectContaining({
						accountId: "account-2",
						growthPct: 12.4,
					}),
				],
			}),
		);
	});

	it("reads fleet health account rows through the user-scoped client", async () => {
		const { client } = createSupabaseMock({
			accounts: [
				{
					id: "threads-1",
					user_id: "user-1",
					username: "threader",
					needs_reauth: true,
					token_expires_at: null,
					last_synced_at: "2026-06-01T00:00:00.000Z",
					group_id: null,
					is_active: true,
					is_retired: false,
				},
			],
			instagram_accounts: [
				{
					id: "ig-1",
					user_id: "user-1",
					username: "igram",
					needs_reauth: false,
					token_expires_at: "2099-01-01T00:00:00.000Z",
					last_synced_at: "2026-06-09T00:00:00.000Z",
					group_id: null,
					is_active: true,
				},
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await analyticsFleetHealthAccountsRoute(authedReq() as any, res);

		expect(client.from).toHaveBeenCalledWith("accounts");
		expect(client.from).toHaveBeenCalledWith("instagram_accounts");
		expect(admin.from).not.toHaveBeenCalled();
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				success: true,
				accounts: [
					expect.objectContaining({
						accountId: "threads-1",
						bucket: "crit",
					}),
					expect.objectContaining({
						accountId: "ig-1",
						bucket: "healthy",
					}),
				],
				summary: expect.objectContaining({
					total: 2,
					crit: 1,
					healthy: 1,
				}),
			}),
		);
	});
});

describe("competitors list RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mocks.enforceRouteRateLimit.mockResolvedValue(true);
		mocks.requireMinTier.mockResolvedValue(true);
	});

	it("reads list rows through the user-scoped client", async () => {
		const { client, calls } = createSupabaseMock({
			competitors: [
				{
					id: "threads-comp-1",
					user_id: "user-1",
					username: "threads_target",
				},
				{
					id: "threads-comp-2",
					user_id: "other-user",
					username: "other_target",
				},
			],
			instagram_competitors: [
				{
					id: "ig-comp-1",
					user_id: "user-1",
					username: "ig_target",
				},
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await competitorsRoute(
			authedReq({
				method: "GET",
				query: { action: "list" },
			}) as any,
			res,
		);

		expect(client.from).toHaveBeenCalledWith("competitors");
		expect(client.from).toHaveBeenCalledWith("instagram_competitors");
		expect(admin.from).not.toHaveBeenCalled();
		expect(calls.filters).toEqual(
			expect.arrayContaining([
				expect.objectContaining({
					table: "competitors",
					column: "user_id",
					value: "user-1",
				}),
				expect.objectContaining({
					table: "instagram_competitors",
					column: "user_id",
					value: "user-1",
				}),
			]),
		);
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			competitors: [
				expect.objectContaining({
					id: "threads-comp-1",
					username: "threads_target",
				}),
				expect.objectContaining({
					id: "ig-comp-1",
					username: "ig_target",
				}),
			],
		});
	});
});

describe("media folder share RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mocks.checkRateLimit.mockResolvedValue({ allowed: true });
	});

	it("shares an owned folder through the user-scoped client", async () => {
		const { client, calls } = createSupabaseMock({
			media_folders: [{ id: "folder-1", user_id: "user-1", name: "Launch" }],
			workspace_members: [{ user_id: "user-1", workspace_id: "workspace-1" }],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await mediaShareRoute(
			authedReq({
				method: "POST",
				body: { folderId: "folder-1", isShared: true },
			}) as any,
			res,
		);

		expect(client.from).toHaveBeenCalledWith("media_folders");
		expect(client.from).toHaveBeenCalledWith("workspace_members");
		expect(admin.from).not.toHaveBeenCalled();
		expect(calls.inserts).toContainEqual({
			table: "media_folders",
			row: { is_shared: true, workspace_id: "workspace-1" },
		});
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			folderId: "folder-1",
			isShared: true,
			workspaceId: "workspace-1",
		});
	});
});

describe("user data export RLS-first routes", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mocks.checkRateLimit.mockResolvedValue({ allowed: true });
		mocks.qstashPublishJSON.mockResolvedValue({ messageId: "msg-1" });
	});

	it("creates export jobs through the user-scoped client and dispatches the worker", async () => {
		const { client, calls } = createSupabaseMock();
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await userExportRoute(authedReq() as any, res);

		expect(client.from).toHaveBeenCalledWith("data_export_jobs");
		expect(admin.from).not.toHaveBeenCalled();
		expect(calls.inserts).toContainEqual({
			table: "data_export_jobs",
			row: { user_id: "user-1", status: "pending" },
		});
		expect(mocks.qstashPublishJSON).toHaveBeenCalledWith({
			url: "https://juno33.test/api/jobs/export-worker",
			body: { jobId: "created-view", userId: "user-1" },
			retries: 2,
		});
		expect(res.status).toHaveBeenCalledWith(202);
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			jobId: "created-view",
			status: "pending",
			message: "Export started. You will be notified when ready.",
		});
	});

	it("reads pending export status through the user-scoped client", async () => {
		const { client } = createSupabaseMock({
			data_export_jobs: [
				{
					id: "job-1",
					user_id: "user-1",
					status: "pending",
					error_message: null,
					created_at: "2026-06-01T00:00:00.000Z",
				},
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await userExportStatusRoute(
			authedReq({ query: { jobId: "job-1" } }) as any,
			res,
		);

		expect(client.from).toHaveBeenCalledWith("data_export_jobs");
		expect(admin.from).not.toHaveBeenCalled();
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			jobId: "job-1",
			status: "pending",
			errorMessage: null,
			createdAt: "2026-06-01T00:00:00.000Z",
		});
	});

	it("uses admin storage only after complete job ownership is verified", async () => {
		const { client } = createSupabaseMock({
			data_export_jobs: [
				{
					id: "job-1",
					user_id: "user-1",
					status: "complete",
					file_path: "exports/user-1/job-1.json",
					expires_at: "2099-01-01T00:00:00.000Z",
				},
			],
		});
		const admin = createSupabaseMock().client as any;
		admin.storage = {
			from: vi.fn(() => ({
				createSignedUrl: vi.fn(async () => ({
					data: { signedUrl: "https://signed.example/export.json" },
					error: null,
				})),
			})),
		};
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await userExportStatusRoute(
			authedReq({ query: { jobId: "job-1" } }) as any,
			res,
		);

		expect(client.from).toHaveBeenCalledWith("data_export_jobs");
		expect(admin.from).not.toHaveBeenCalled();
		expect(admin.storage.from).toHaveBeenCalledWith("exports");
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			jobId: "job-1",
			status: "complete",
			downloadUrl: "https://signed.example/export.json",
			expiresAt: "2099-01-01T00:00:00.000Z",
		});
	});
});

describe("agent settings RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("reads agent settings through the user-scoped client", async () => {
		const { client } = createSupabaseMock({
			profiles: [{ id: "user-1", agent_paused: true }],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await agentSettingsRoute(authedReq() as any, res);

		expect(client.from).toHaveBeenCalledWith("profiles");
		expect(admin.from).not.toHaveBeenCalled();
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			agent_paused: true,
		});
	});

	it("updates agent settings through the user-scoped client", async () => {
		const { client, calls } = createSupabaseMock();
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await agentSettingsRoute(
			authedReq({
				method: "PATCH",
				body: { agent_paused: true },
			}) as any,
			res,
		);

		expect(client.from).toHaveBeenCalledWith("profiles");
		expect(admin.from).not.toHaveBeenCalled();
		expect(calls.inserts).toEqual([
			{ table: "profiles", row: { agent_paused: true } },
		]);
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			agent_paused: true,
		});
	});
});

describe("agent notes RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("lists agent notes through the user-scoped client after group ownership check", async () => {
		const { client } = createSupabaseMock({
			account_groups: [{ id: "group-1", user_id: "user-1" }],
			agent_notes: [
				{
					id: "note-1",
					user_id: "user-1",
					account_group_id: "group-1",
					key: "tone",
					value: "direct",
				},
				{
					id: "note-2",
					user_id: "user-2",
					account_group_id: "group-1",
					key: "tone",
					value: "other",
				},
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await agentNotesRoute(
			authedReq({ query: { accountGroupId: "group-1" } }) as any,
			res,
		);

		expect(client.from).toHaveBeenCalledWith("account_groups");
		expect(client.from).toHaveBeenCalledWith("agent_notes");
		expect(admin.from).not.toHaveBeenCalled();
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			notes: [
				expect.objectContaining({
					id: "note-1",
					user_id: "user-1",
					account_group_id: "group-1",
				}),
			],
		});
	});

	it("creates global agent notes through the user-scoped client", async () => {
		const { client, calls } = createSupabaseMock();
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await agentNotesRoute(
			authedReq({
				method: "POST",
				body: { action: "upsert", key: "voice", value: "concise" },
			}) as any,
			res,
		);

		expect(client.from).toHaveBeenCalledWith("agent_notes");
		expect(admin.from).not.toHaveBeenCalled();
		expect(calls.inserts).toEqual([
			{
				table: "agent_notes",
				row: {
					user_id: "user-1",
					key: "voice",
					value: "concise",
					account_group_id: null,
				},
			},
		]);
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			action: "created",
			key: "voice",
		});
	});

	it("deletes global agent notes after applying the null group filter", async () => {
		const { client, calls } = createSupabaseMock({
			agent_notes: [
				{
					id: "note-1",
					user_id: "user-1",
					account_group_id: null,
					key: "voice",
					value: "concise",
				},
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await agentNotesRoute(
			authedReq({
				method: "POST",
				body: { action: "delete", key: "voice" },
			}) as any,
			res,
		);

		expect(admin.from).not.toHaveBeenCalled();
		expect(calls.deletes).toEqual([{ table: "agent_notes" }]);
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			action: "deleted",
			key: "voice",
		});
	});
});

describe("beta feedback RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("submits beta feedback through the user-scoped client", async () => {
		const { client, calls } = createSupabaseMock({
			profiles: [
				{
					id: "user-1",
					is_beta_user: true,
					beta_feedback: [
						{
							text: "Existing note",
							category: "general",
							submitted_at: "2026-06-01T00:00:00.000Z",
						},
					],
				},
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await betaFeedbackRoute(
			authedReq({
				method: "POST",
				body: { feedback: "The new Composer flow is clearer", category: "ux" },
			}) as any,
			res,
		);

		expect(client.from).toHaveBeenCalledWith("profiles");
		expect(admin.from).not.toHaveBeenCalled();
		expect(calls.inserts).toEqual([
			{
				table: "profiles",
				row: {
					beta_feedback: [
						{
							text: "Existing note",
							category: "general",
							submitted_at: "2026-06-01T00:00:00.000Z",
						},
						expect.objectContaining({
							text: "The new Composer flow is clearer",
							category: "ux",
							submitted_at: expect.any(String),
						}),
					],
				},
			},
		]);
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			message: "Thank you for your feedback!",
			totalSubmitted: 2,
		});
	});
});

describe("composer health pills RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("reads active health signals through the user-scoped client", async () => {
		const { client } = createSupabaseMock({
			accounts: [
				{ id: "account-1", user_id: "user-1" },
				{ id: "account-2", user_id: "user-1" },
				{ id: "account-3", user_id: "user-2" },
			],
			account_health_signals: [
				{
					account_id: "account-1",
					signal_type: "reach_anomaly",
					severity: "warn",
					resolved_at: null,
					detected_at: "2026-06-01T00:00:00.000Z",
				},
				{
					account_id: "account-1",
					signal_type: "rate_limit",
					severity: "critical",
					resolved_at: "2026-06-02T00:00:00.000Z",
					detected_at: "2026-06-01T00:00:00.000Z",
				},
				{
					account_id: "account-2",
					signal_type: "token_expiring",
					severity: "critical",
					resolved_at: null,
					detected_at: "2026-06-01T00:00:00.000Z",
				},
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await composerHealthPillsRoute(
			authedReq({
				query: { account_ids: "account-1,account-2,account-3" },
			}) as any,
			res,
		);

		expect(client.from).toHaveBeenCalledWith("accounts");
		expect(client.from).toHaveBeenCalledWith("account_health_signals");
		expect(admin.from).not.toHaveBeenCalled();
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			accounts: [
				{
					account_id: "account-1",
					signals: [{ signal_type: "reach_anomaly", severity: "warn" }],
				},
				{
					account_id: "account-2",
					signals: [{ signal_type: "token_expiring", severity: "critical" }],
				},
			],
		});
	});
});

describe("composer voice file RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("returns the generated voice file fallback through the user-scoped client", async () => {
		const { client } = createSupabaseMock({
			account_groups: [
				{
					id: "group-1",
					user_id: "user-1",
					voice_profile: { tone: "direct", top_patterns: ["specific hooks"] },
				},
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await composerVoiceFileRoute(
			authedReq({ query: { account_group_id: "group-1" } }) as any,
			res,
		);

		expect(client.from).toHaveBeenCalledWith("account_groups");
		expect(client.from).toHaveBeenCalledWith("voice_context_files");
		expect(admin.from).not.toHaveBeenCalled();
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			voice_file: {
				account_group_id: "group-1",
				user_id: "user-1",
				content: JSON.stringify(
					{ tone: "direct", top_patterns: ["specific hooks"] },
					null,
					2,
				),
				version: 1,
				top_patterns: [],
			},
		});
	});

	it("saves voice files through the user-scoped client", async () => {
		const { client, calls } = createSupabaseMock({
			account_groups: [
				{ id: "group-1", user_id: "user-1", voice_profile: null },
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await composerVoiceFileRoute(
			authedReq({
				method: "PUT",
				body: {
					account_group_id: "group-1",
					content: "Use concise hooks.",
					banned_patterns: ["generic openers"],
					audience: "founders",
					top_patterns: [{ pattern: "specific hooks" }],
				},
			}) as any,
			res,
		);

		expect(client.from).toHaveBeenCalledWith("account_groups");
		expect(client.from).toHaveBeenCalledWith("voice_context_files");
		expect(admin.from).not.toHaveBeenCalled();
		expect(calls.inserts).toEqual([
			{
				table: "voice_context_files",
				row: expect.objectContaining({
					account_group_id: "group-1",
					user_id: "user-1",
					content: "Use concise hooks.",
					banned_patterns: ["generic openers"],
					audience: "founders",
					top_patterns: [{ pattern: "specific hooks" }],
					last_edited_at: expect.any(String),
				}),
			},
		]);
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			voice_file: expect.objectContaining({
				account_group_id: "group-1",
				user_id: "user-1",
				content: "Use concise hooks.",
			}),
		});
	});
});

describe("crisis status RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("loads crisis events through the user-scoped client", async () => {
		const { client } = createSupabaseMock({
			crisis_events: [
				{
					id: "crisis-1",
					user_id: "user-1",
					severity: "severe",
					resolved_at: null,
					created_at: "2026-06-01T00:00:00.000Z",
				},
				{
					id: "crisis-2",
					user_id: "user-1",
					severity: "warning",
					resolved_at: "2999-06-02T00:00:00.000Z",
					created_at: "2026-06-01T00:00:00.000Z",
				},
				{
					id: "crisis-3",
					user_id: "user-2",
					severity: "severe",
					resolved_at: null,
					created_at: "2026-06-01T00:00:00.000Z",
				},
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await crisisStatusRoute(authedReq() as any, res);

		expect(mocks.checkRateLimit).toHaveBeenCalledWith(
			expect.objectContaining({ key: "crisis-status:user-1" }),
		);
		expect(client.from).toHaveBeenCalledWith("crisis_events");
		expect(admin.from).not.toHaveBeenCalled();
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			active_crises: [
				expect.objectContaining({
					id: "crisis-1",
					user_id: "user-1",
					severity: "severe",
				}),
			],
			resolved_recent: [
				expect.objectContaining({
					id: "crisis-2",
					user_id: "user-1",
					severity: "warning",
				}),
			],
			current_level: "severe",
		});
	});
});

describe("developer API keys RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("uses the user-scoped client for listing developer API keys", async () => {
		const { client } = createSupabaseMock({
			api_keys: [
				{
					id: "key-1",
					user_id: "user-1",
					name: "Production",
					key_prefix: "juno_ak_abc",
					scopes: ["read"],
					allowed_account_ids: null,
					is_active: true,
				},
				{
					id: "key-2",
					user_id: "user-2",
					name: "Other",
					key_prefix: "juno_ak_xyz",
					scopes: ["read"],
					allowed_account_ids: null,
					is_active: true,
				},
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await developerKeysRoute(authedReq() as any, res);

		expect(mocks.requireMinTier).toHaveBeenCalledWith("user-1", "pro", res);
		expect(client.from).toHaveBeenCalledWith("api_keys");
		expect(admin.from).not.toHaveBeenCalled();
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			keys: [
				{
					id: "key-1",
					user_id: "user-1",
					name: "Production",
					key_prefix: "juno_ak_abc",
					scopes: ["read"],
					allowed_account_ids: null,
					is_active: true,
				},
			],
		});
	});

	it("keeps step-up and creates developer API keys through the user client", async () => {
		const { client, calls } = createSupabaseMock();
		mocks.userDb = client;
		mocks.adminDbAny = createSupabaseMock().client;
		const res = mockRes();

		await developerKeysRoute(
			authedReq({
				method: "POST",
				body: {
					name: "Automation",
					scopes: ["read", "write"],
					allowed_account_ids: ["threads-1", "threads-1", " "],
				},
			}) as any,
			res,
		);

		expect(mocks.requireStepUp).toHaveBeenCalledWith(
			expect.objectContaining({ method: "POST" }),
			res,
			"user-1",
		);
		expect(calls.inserts[0]).toEqual({
			table: "api_keys",
			row: expect.objectContaining({
				user_id: "user-1",
				name: "Automation",
				scopes: ["read", "write"],
				allowed_account_ids: ["threads-1"],
			}),
		});
		expect(calls.inserts[0]?.row.key_hash).toEqual(expect.any(String));
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				success: true,
				key: expect.objectContaining({ user_id: "user-1", name: "Automation" }),
				rawKey: expect.stringMatching(/^juno_ak_/),
			}),
		);
	});
});

describe("inbox mark-read RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("marks inbox items and operator tasks through the user-scoped client", async () => {
		const { client, calls } = createSupabaseMock();
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await inboxMarkReadRoute(
			authedReq({
				method: "POST",
				body: { messageId: "ig_mention_mention-1", read: true },
			}) as any,
			res,
		);

		expect(client.from).toHaveBeenCalledWith("ig_mentions");
		expect(client.from).toHaveBeenCalledWith("operator_tasks");
		expect(admin.from).not.toHaveBeenCalled();
		expect(calls.inserts).toEqual([
			{ table: "ig_mentions", row: { is_read: true } },
			{
				table: "operator_tasks",
				row: expect.objectContaining({
					status: "resolved",
					resolution_reason: "Marked done from Inbox",
					snoozed_until: null,
				}),
			},
		]);
		expect(res.json).toHaveBeenCalledWith({ success: true });
	});
});

describe("draft folders RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("lists draft folders and counts through the user-scoped client", async () => {
		const { client } = createSupabaseMock({
			draft_folders: [
				{
					id: "folder-1",
					user_id: "user-1",
					name: "Launches",
					color: "#6366f1",
					icon: "folder",
					sort_order: 0,
				},
				{
					id: "folder-2",
					user_id: "user-2",
					name: "Other",
					color: "#6366f1",
					icon: "folder",
					sort_order: 0,
				},
			],
			posts: [
				{
					id: "post-1",
					user_id: "user-1",
					status: "draft",
					draft_folder_id: "folder-1",
				},
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await draftFoldersRoute(
			authedReq({ method: "POST", query: { action: "list" } }) as any,
			res,
		);

		expect(client.from).toHaveBeenCalledWith("draft_folders");
		expect(client.from).toHaveBeenCalledWith("posts");
		expect(admin.from).not.toHaveBeenCalled();
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			folders: [
				expect.objectContaining({
					id: "folder-1",
					user_id: "user-1",
					name: "Launches",
					post_count: 1,
				}),
			],
		});
	});
});

describe("settings user webhooks RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("uses the user-scoped client for listing settings webhooks", async () => {
		const { client } = createSupabaseMock({
			user_webhooks: [
				{
					id: "settings-hook-1",
					user_id: "user-1",
					url: "https://example.com/a",
					events: ["post_published"],
					is_active: true,
				},
				{
					id: "settings-hook-2",
					user_id: "user-2",
					url: "https://example.com/b",
					events: ["post_failed"],
					is_active: true,
				},
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await settingsUserWebhooksRoute(authedReq() as any, res);

		expect(client.from).toHaveBeenCalledWith("user_webhooks");
		expect(admin.from).not.toHaveBeenCalled();
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			webhooks: [
				{
					id: "settings-hook-1",
					user_id: "user-1",
					url: "https://example.com/a",
					events: ["post_published"],
					is_active: true,
				},
			],
		});
	});
});

describe("replies read-state RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("marks an owned reply read through the user-scoped client", async () => {
		const { client, calls } = createSupabaseMock({
			post_replies: [
				{
					id: "reply-1",
					post_id: "post-1",
					is_read: false,
					"posts.user_id": "user-1",
				},
				{
					id: "reply-2",
					post_id: "post-2",
					is_read: false,
					"posts.user_id": "user-2",
				},
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await repliesRoute(
			authedReq({
				method: "POST",
				query: { action: "mark-read" },
				body: { replyId: "reply-1" },
			}) as any,
			res,
		);

		expect(mocks.checkRateLimit).toHaveBeenCalledWith(
			expect.objectContaining({ key: "replies:mark-read:user-1" }),
		);
		expect(client.from).toHaveBeenCalledWith("post_replies");
		expect(admin.from).not.toHaveBeenCalled();
		expect(calls.inserts).toEqual([
			{ table: "post_replies", row: { is_read: true } },
		]);
		expect(res.json).toHaveBeenCalledWith({ success: true });
	});
});

describe("webhooks RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("uses the user-scoped client for listing webhook subscriptions", async () => {
		const { client } = createSupabaseMock({
			webhook_subscriptions: [
				{ id: "hook-1", user_id: "user-1", url: "https://example.com/a", events: ["post.published"] },
				{ id: "hook-2", user_id: "user-2", url: "https://example.com/b", events: ["post.published"] },
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await webhooksRoute(authedReq() as any, res);

		expect(client.from).toHaveBeenCalledWith("webhook_subscriptions");
		expect(admin.from).not.toHaveBeenCalled();
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			webhooks: [
				{ id: "hook-1", user_id: "user-1", url: "https://example.com/a", events: ["post.published"] },
			],
		});
	});

	it("requires step-up before deleting webhook subscriptions", async () => {
		const { client } = createSupabaseMock({
			webhook_subscriptions: [
				{ id: "hook-1", user_id: "user-1", url: "https://example.com/a", events: ["post.published"] },
			],
		});
		mocks.userDb = client;
		mocks.adminDbAny = createSupabaseMock().client;
		const res = mockRes();

		await webhooksRoute(
			authedReq({ method: "DELETE", body: { webhookId: "hook-1" } }) as any,
			res,
		);

		expect(mocks.requireStepUp).toHaveBeenCalledWith(
			expect.objectContaining({ method: "DELETE" }),
			res,
			"user-1",
		);
		expect(client.from).toHaveBeenCalledWith("webhook_subscriptions");
		expect(res.json).toHaveBeenCalledWith({ success: true, deleted: true });
	});
});

describe("tags RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("uses the user-scoped client for tag palette listing", async () => {
		const { client } = createSupabaseMock({
			user_tag_palette: [
				{ id: "tag-1", user_id: "user-1", tag_name: "Launch", tag_color: "#38bdf8" },
				{ id: "tag-2", user_id: "user-2", tag_name: "Other", tag_color: "#000000" },
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await tagsRoute(authedReq({ query: { action: "list" } }) as any, res);

		expect(client.from).toHaveBeenCalledWith("user_tag_palette");
		expect(admin.from).not.toHaveBeenCalled();
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			tags: [
				{ id: "tag-1", user_id: "user-1", tag_name: "Launch", tag_color: "#38bdf8" },
			],
		});
	});
});

describe("reports update RLS-first branch", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("updates report configuration through the user-scoped client", async () => {
		const { client, calls } = createSupabaseMock();
		const admin = createSupabaseMock().client;
		const res = mockRes();

		await reportsUpdateHandler(
			authedReq({
				method: "PUT",
				body: {
					reportId: "report-1",
					name: "Weekly Ops",
					status: "active",
					recipients: [{ email: "ops@example.com", name: "Ops" }],
					config: { sections: ["overview"] },
				},
			}) as any,
			res,
			{
				user: mocks.authUser,
				userDb: client,
				adminDb: admin,
				adminDbAny: admin,
			},
		);

		expect(client.from).toHaveBeenCalledWith("reports");
		expect(admin.from).not.toHaveBeenCalled();
		expect(calls.inserts).toEqual([
			{
				table: "reports",
				row: expect.objectContaining({
					name: "Weekly Ops",
					status: "active",
					recipients: [{ email: "ops@example.com", name: "Ops" }],
					config: { sections: ["overview"] },
					updated_at: expect.any(String),
				}),
			},
		]);
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			report: expect.objectContaining({
				id: "created-view",
				name: "Weekly Ops",
				status: "active",
			}),
		});
	});
});

describe("saved-views RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mocks.adminDbAny = createSupabaseMock().client;
	});

	it("rejects unauthenticated requests", async () => {
		const res = mockRes();
		await savedViewsRoute({ method: "GET", headers: {}, query: {} } as any, res);
		expect(res.status).toHaveBeenCalledWith(401);
	});

	it("lists only the authenticated user's saved views", async () => {
		const { client } = createSupabaseMock({
			saved_views: [
				{ id: "a", user_id: "user-1", scope: "analytics", name: "Mine" },
				{ id: "b", user_id: "user-2", scope: "analytics", name: "Other" },
			],
		});
		mocks.userDb = client;
		const res = mockRes();

		await savedViewsRoute(authedReq({ query: { scope: "analytics" } }) as any, res);

		expect(client.from).toHaveBeenCalledWith("saved_views");
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			views: [{ id: "a", user_id: "user-1", scope: "analytics", name: "Mine" }],
		});
	});

	it("creates and deletes views with existing response shapes", async () => {
		const { client, calls } = createSupabaseMock();
		mocks.userDb = client;

		const createRes = mockRes();
		await savedViewsRoute(
			authedReq({
				method: "POST",
				body: { name: "Focus", filters: { platform: "threads" } },
			}) as any,
			createRes,
		);

		expect(calls.inserts[0]).toEqual({
			table: "saved_views",
			row: {
				user_id: "user-1",
				name: "Focus",
				filters: { platform: "threads" },
				scope: "analytics",
			},
		});
		expect(createRes.json).toHaveBeenCalledWith(
			expect.objectContaining({
				success: true,
				view: expect.objectContaining({ id: "created-view", user_id: "user-1" }),
			}),
		);

		const deleteRes = mockRes();
		await savedViewsRoute(
			authedReq({ method: "DELETE", query: { id: "created-view" } }) as any,
			deleteRes,
		);

		expect(calls.deletes).toEqual([{ table: "saved_views" }]);
		expect(deleteRes.json).toHaveBeenCalledWith({
			success: true,
			deleted: "created-view",
		});
	});
});

describe("accounts RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("uses the user-scoped client for the default account list", async () => {
		const { client } = createSupabaseMock({
			accounts: [
				{
					id: "threads-1",
					user_id: "user-1",
					username: "threader",
					display_name: "Threader",
					avatar_url: "https://example.com/t.png",
					followers_count: 7,
					following_count: 2,
					is_active: true,
					last_synced_at: "2026-06-01T00:00:00.000Z",
					created_at: "2026-05-01T00:00:00.000Z",
					group_id: "group-1",
				},
			],
			instagram_accounts: [
				{
					id: "ig-1",
					user_id: "user-1",
					username: "igram",
					display_name: "Igram",
					avatar_url: "https://example.com/i.png",
					follower_count: 9,
					following_count: 3,
					is_active: true,
					last_synced_at: "2026-06-02T00:00:00.000Z",
					created_at: "2026-05-02T00:00:00.000Z",
					group_id: "group-2",
				},
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await accountsRoute(authedReq() as any, res);

		expect(client.from).toHaveBeenCalledWith("accounts");
		expect(client.from).toHaveBeenCalledWith("instagram_accounts");
		expect(admin.rpc).not.toHaveBeenCalled();
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			accounts: [
				expect.objectContaining({
					id: "threads-1",
					platform: "threads",
					follower_count: 7,
				}),
				expect.objectContaining({
					id: "ig-1",
					platform: "instagram",
					follower_count: 9,
				}),
			],
		});
	});

	it("keeps assign-group on the explicit admin RPC path", async () => {
		const { client } = createSupabaseMock();
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await accountsRoute(
			authedReq({
				method: "POST",
				query: { action: "assign-group" },
				body: { accountId: "threads-1", groupId: "group-1" },
			}) as any,
			res,
		);

		expect(client.from).not.toHaveBeenCalled();
		expect(admin.rpc).toHaveBeenCalledWith("assign_account_to_group", {
			p_account_id: "threads-1",
			p_target_group_id: "group-1",
			p_user_id: "user-1",
		});
		expect(res.json).toHaveBeenCalledWith({ success: true });
	});
});

describe("post templates RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("uses the user-scoped client for listing templates", async () => {
		const { client } = createSupabaseMock({
			post_templates: [
				{
					id: "template-1",
					user_id: "user-1",
					name: "Daily Hook",
					category: "general",
					platform: "threads",
					text_template: "Hello {{day}}",
					hashtags: ["#build"],
					poll_options: null,
					times_used: 3,
					last_used_at: null,
					is_shared: false,
					created_at: "2026-06-01T00:00:00.000Z",
				},
				{
					id: "template-2",
					user_id: "user-2",
					name: "Other",
					category: "general",
					platform: "threads",
					text_template: "No",
					hashtags: [],
					poll_options: null,
					times_used: 1,
					last_used_at: null,
					is_shared: false,
					created_at: "2026-06-01T00:00:00.000Z",
				},
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await postTemplatesRoute(
			authedReq({
				method: "POST",
				query: { action: "list" },
				body: { platform: "threads" },
			}) as any,
			res,
		);

		expect(client.from).toHaveBeenCalledWith("post_templates");
		expect(admin.from).not.toHaveBeenCalled();
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			templates: [
				expect.objectContaining({
					id: "template-1",
					user_id: "user-1",
					platform: "threads",
				}),
			],
		});
	});
});

describe("post comments RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("uses the user-scoped client for local Threads comments", async () => {
		const { client } = createSupabaseMock({
			posts: [
				{
					id: "post-1",
					user_id: "user-1",
					content: "This is the original post body",
					account_id: "account-1",
				},
			],
			post_replies: [
				{
					id: "reply-1",
					post_id: "post-1",
					username: "reader",
					display_name: "Reader",
					avatar_url: null,
					content: "Nice post",
					likes_count: 2,
					is_read: false,
					created_at: "2026-06-01T00:00:00.000Z",
				},
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await postCommentsRoute(
			authedReq({
				method: "GET",
				query: { postId: "post-1", platform: "threads", limit: "10" },
			}) as any,
			res,
		);

		expect(client.from).toHaveBeenCalledWith("posts");
		expect(client.from).toHaveBeenCalledWith("post_replies");
		expect(admin.from).not.toHaveBeenCalled();
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			postId: "post-1",
			platform: "threads",
			postPreview: "This is the original post body",
			comments: [
				expect.objectContaining({
					id: "reply-1",
					post_id: "post-1",
					content: "Nice post",
				}),
			],
			total: 1,
		});
	});
});

describe("post sentiment summary RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("verifies ownership through the user-scoped client before reading sentiment", async () => {
		const { client } = createSupabaseMock({
			posts: [{ id: "post-1", user_id: "user-1" }],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDbAny = admin;
		mocks.getPostSentimentSummary.mockResolvedValueOnce({
			postId: "post-1",
			total: 2,
			breakdown: { positive: 1, negative: 0, neutral: 1, question: 0 },
			score: 0.5,
			verdict: "Mostly positive",
		});
		const res = mockRes();

		await postSentimentSummaryRoute(
			authedReq({
				method: "GET",
				query: { postId: "post-1" },
			}) as any,
			res,
		);

		expect(client.from).toHaveBeenCalledWith("posts");
		expect(admin.from).not.toHaveBeenCalled();
		expect(mocks.getPostSentimentSummary).toHaveBeenCalledWith("post-1");
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			postId: "post-1",
			total: 2,
			breakdown: { positive: 1, negative: 0, neutral: 1, question: 0 },
			score: 0.5,
			verdict: "Mostly positive",
		});
	});
});

describe("post success signal RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("stores user-owned post signals through the user-scoped client", async () => {
		const { client, calls } = createSupabaseMock({
			posts: [{ id: "post-1", user_id: "user-1" }],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await postSignalRoute(
			authedReq({
				method: "POST",
				body: { postId: "post-1", signal: "strong_hook" },
			}) as any,
			res,
		);

		expect(mocks.requireMinTier).toHaveBeenCalledWith("user-1", "pro", res);
		expect(client.from).toHaveBeenCalledWith("posts");
		expect(client.from).toHaveBeenCalledWith("post_success_signals");
		expect(admin.from).not.toHaveBeenCalled();
		expect(calls.inserts).toContainEqual({
			table: "post_success_signals",
			row: { user_id: "user-1", post_id: "post-1", signal: "strong_hook" },
		});
		expect(res.json).toHaveBeenCalledWith({ success: true, stored: true });
	});
});

describe("AI feedback RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("stores feedback through the user-scoped client", async () => {
		const { client, calls } = createSupabaseMock();
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await aiFeedbackRoute(
			authedReq({
				method: "POST",
				body: {
					feature: "caption",
					suggestionContent: "Try a stronger hook",
					wasUsed: true,
					wasEdited: false,
					context: { source: "composer" },
				},
			}) as any,
			res,
		);

		expect(client.from).toHaveBeenCalledWith("ai_feedback");
		expect(admin.from).not.toHaveBeenCalled();
		expect(calls.inserts).toContainEqual({
			table: "ai_feedback",
			row: {
				user_id: "user-1",
				feature: "caption",
				suggestion_content: "Try a stronger hook",
				was_used: true,
				was_edited: false,
				context: { source: "composer" },
			},
		});
		expect(res.json).toHaveBeenCalledWith({ success: true, saved: true });
	});
});

describe("AI recommendation dismissal RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("upserts recommendation dismissals through the user-scoped client", async () => {
		const { client, calls } = createSupabaseMock();
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await aiDismissRecommendationRoute(
			authedReq({
				method: "POST",
				body: {
					recId: "rec-1",
					accountId: "account-1",
					reason: "will_try_later",
					category: "hooks",
				},
			}) as any,
			res,
		);

		expect(client.from).toHaveBeenCalledWith("recommendation_dismissals");
		expect(admin.from).not.toHaveBeenCalled();
		expect(calls.inserts[0]).toEqual({
			table: "recommendation_dismissals",
			row: expect.objectContaining({
				user_id: "user-1",
				account_id: "account-1",
				rec_id: "rec-1",
				category: "hooks",
				reason: "will_try_later",
				auto_solved: false,
			}),
		});
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			dismissed: true,
			reason: "will_try_later",
		});
	});
});

describe("user data contribution RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("loads contribution preference and account niche through the user-scoped client", async () => {
		const { client } = createSupabaseMock({
			user_preferences: [
				{ user_id: "user-1", data_contribution_opted_in: true },
			],
			accounts: [{ user_id: "user-1", user_niche: "tech" }],
			instagram_accounts: [{ user_id: "user-1", user_niche: null }],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await userDataContributionRoute(authedReq() as any, res);

		expect(client.from).toHaveBeenCalledWith("user_preferences");
		expect(client.from).toHaveBeenCalledWith("accounts");
		expect(client.from).toHaveBeenCalledWith("instagram_accounts");
		expect(admin.from).not.toHaveBeenCalled();
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			opted_in: true,
			niche: "tech",
		});
	});

	it("updates contribution preference and account niches through the user-scoped client", async () => {
		const { client, calls } = createSupabaseMock();
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await userDataContributionRoute(
			authedReq({
				method: "POST",
				body: { opted_in: true, niche: "tech" },
			}) as any,
			res,
		);

		expect(admin.from).not.toHaveBeenCalled();
		expect(calls.inserts).toEqual([
			{
				table: "user_preferences",
				row: expect.objectContaining({
					user_id: "user-1",
					data_contribution_opted_in: true,
				}),
			},
			{ table: "accounts", row: { user_niche: "tech" } },
			{ table: "instagram_accounts", row: { user_niche: "tech" } },
		]);
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			opted_in: true,
			niche: "tech",
		});
	});
});

describe("user growth journal RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mocks.requireMinTier.mockResolvedValue(true);
	});

	it("lists journal entries and baselines through the user-scoped client", async () => {
		const { client } = createSupabaseMock({
			recommendation_dismissals: [
				{
					id: "dismissal-1",
					user_id: "user-1",
					account_id: "account-1",
					rec_id: "rec-1",
					action: "actioned",
					actioned_at: "2026-06-01T00:00:00.000Z",
					recommendation_text: "Post earlier",
					category: "timing",
					baseline_value: 100,
					current_value: 120,
				},
			],
			recommendation_baselines: [
				{
					account_id: "account-1",
					platform: "threads",
					rec_id: "rec-1",
					category: "timing",
					baseline_value: 100,
					threshold: 120,
				},
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await userGrowthJournalRoute(
			authedReq({ query: { accountId: "account-1" } }) as any,
			res,
		);

		expect(mocks.requireMinTier).toHaveBeenCalledWith("user-1", "pro", res);
		expect(client.from).toHaveBeenCalledWith("recommendation_dismissals");
		expect(client.from).toHaveBeenCalledWith("recommendation_baselines");
		expect(admin.from).not.toHaveBeenCalled();
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			entries: [
				expect.objectContaining({
					id: "dismissal-1",
					recId: "rec-1",
					improvementPct: 20,
					outcome: "improved",
				}),
			],
			stats: {
				total: 1,
				successful: 1,
				successRate: 100,
				avgImprovement: 20,
			},
		});
	});

	it("creates journal entries through the user-scoped client", async () => {
		const { client, calls } = createSupabaseMock({
			accounts: [{ id: "account-1", user_id: "user-1" }],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await userGrowthJournalRoute(
			authedReq({
				method: "POST",
				body: {
					accountId: "account-1",
					recommendationText: "Tighten the hook",
					category: "content",
				},
			}) as any,
			res,
		);

		expect(client.from).toHaveBeenCalledWith("accounts");
		expect(client.from).toHaveBeenCalledWith("recommendation_dismissals");
		expect(admin.from).not.toHaveBeenCalled();
		expect(calls.inserts).toContainEqual({
			table: "recommendation_dismissals",
			row: expect.objectContaining({
				user_id: "user-1",
				account_id: "account-1",
				action: "actioned",
				category: "content",
				recommendation_text: "Tighten the hook",
			}),
		});
		expect(res.json).toHaveBeenCalledWith({ success: true, created: true });
	});
});

describe("composer diffs RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("lists channel diffs through the user-scoped client", async () => {
		const { client } = createSupabaseMock({
			post_channel_diffs: [
				{
					id: "diff-1",
					user_id: "user-1",
					draft_id: "draft-1",
					platform: "threads",
					status: "unresolved",
				},
				{
					id: "diff-2",
					user_id: "user-2",
					draft_id: "draft-1",
					platform: "threads",
					status: "unresolved",
				},
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await composerDiffsRoute(
			authedReq({ query: { draft_id: "draft-1" } }) as any,
			res,
		);

		expect(client.from).toHaveBeenCalledWith("post_channel_diffs");
		expect(admin.from).not.toHaveBeenCalled();
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			diffs: [
				expect.objectContaining({
					id: "diff-1",
					user_id: "user-1",
					draft_id: "draft-1",
				}),
			],
		});
	});

	it("creates channel diffs through the user-scoped client", async () => {
		const { client, calls } = createSupabaseMock();
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await composerDiffsRoute(
			authedReq({
				method: "POST",
				body: {
					draft_id: "draft-1",
					platform: "threads",
					master_caption: "Master",
					variant_caption: "Variant",
				},
			}) as any,
			res,
		);

		expect(admin.from).not.toHaveBeenCalled();
		expect(calls.inserts).toContainEqual({
			table: "post_channel_diffs",
			row: {
				user_id: "user-1",
				draft_id: "draft-1",
				platform: "threads",
				divergence_type: "custom",
				master_caption: "Master",
				variant_caption: "Variant",
				status: "unresolved",
			},
		});
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				success: true,
				diff: expect.objectContaining({ user_id: "user-1" }),
			}),
		);
	});
});

describe("composer variants RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("lists variants through the user-scoped client", async () => {
		const { client } = createSupabaseMock({
			post_variants: [
				{ id: "variant-1", user_id: "user-1", draft_id: "draft-1" },
				{ id: "variant-2", user_id: "user-2", draft_id: "draft-1" },
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await composerVariantsRoute(
			authedReq({ query: { draft_id: "draft-1" } }) as any,
			res,
		);

		expect(client.from).toHaveBeenCalledWith("post_variants");
		expect(admin.from).not.toHaveBeenCalled();
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			variants: [
				expect.objectContaining({
					id: "variant-1",
					user_id: "user-1",
					draft_id: "draft-1",
				}),
			],
		});
	});

	it("loads live results and updates variants through the user-scoped client", async () => {
		const { client, calls } = createSupabaseMock({
			post_metric_history: [
				{
					post_id: "post-1",
					views_count: 100,
					likes_count: 10,
					replies_count: 5,
				},
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await composerVariantsRoute(
			authedReq({
				query: { mode: "live-results", post_id: "post-1" },
			}) as any,
			res,
		);

		expect(client.from).toHaveBeenCalledWith("post_metric_history");
		expect(client.from).toHaveBeenCalledWith("post_variants");
		expect(admin.from).not.toHaveBeenCalled();
		expect(calls.inserts).toContainEqual({
			table: "post_variants",
			row: { live_views_count: 100, live_engagement_rate: 0.15 },
		});
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			post_id: "post-1",
			live_views_count: 100,
			live_engagement_rate: 0.15,
		});
	});
});

describe("trending config RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mocks.requireMinTier.mockResolvedValue(true);
	});

	it("loads trending config through the user-scoped client", async () => {
		const { client } = createSupabaseMock({
			trending_topic_config: [
				{
					id: "config-1",
					account_group_id: "group-1",
					user_id: "user-1",
					enabled: true,
				},
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await trendingConfigRoute(
			authedReq({ query: { groupId: "group-1" } }) as any,
			res,
		);

		expect(mocks.requireMinTier).toHaveBeenCalledWith("user-1", "empire", res);
		expect(client.from).toHaveBeenCalledWith("trending_topic_config");
		expect(admin.from).not.toHaveBeenCalled();
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			data: expect.objectContaining({
				id: "config-1",
				user_id: "user-1",
				account_group_id: "group-1",
			}),
		});
	});

	it("upserts trending config through the user-scoped client", async () => {
		const { client, calls } = createSupabaseMock({
			account_groups: [{ id: "group-1", user_id: "user-1" }],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await trendingConfigRoute(
			authedReq({
				method: "POST",
				body: {
					accountGroupId: "group-1",
					keywords: ["ai"],
					enabled: true,
				},
			}) as any,
			res,
		);

		expect(client.from).toHaveBeenCalledWith("account_groups");
		expect(client.from).toHaveBeenCalledWith("trending_topic_config");
		expect(admin.from).not.toHaveBeenCalled();
		expect(calls.inserts).toContainEqual({
			table: "trending_topic_config",
			row: expect.objectContaining({
				account_group_id: "group-1",
				user_id: "user-1",
				keywords: ["ai"],
				enabled: true,
			}),
		});
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				success: true,
				data: expect.objectContaining({ user_id: "user-1" }),
			}),
		);
	});
});

describe("listening alerts RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mocks.requireMinTier.mockResolvedValue(true);
	});

	it("lists listening alerts through the user-scoped client", async () => {
		const { client } = createSupabaseMock({
			listening_alerts: [
				{ id: "alert-1", user_id: "user-1", keyword: "ai" },
				{ id: "alert-2", user_id: "user-2", keyword: "crypto" },
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await listeningAlertsRoute(authedReq() as any, res);

		expect(mocks.requireMinTier).toHaveBeenCalledWith("user-1", "pro", res);
		expect(client.from).toHaveBeenCalledWith("listening_alerts");
		expect(admin.from).not.toHaveBeenCalled();
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			alerts: [
				expect.objectContaining({
					id: "alert-1",
					user_id: "user-1",
					keyword: "ai",
				}),
			],
		});
	});

	it("creates personal listening alerts through the user-scoped client", async () => {
		const { client, calls } = createSupabaseMock();
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await listeningAlertsRoute(
			authedReq({
				method: "POST",
				body: { keyword: "ai", alert_type: "spike", threshold_value: 10 },
			}) as any,
			res,
		);

		expect(mocks.checkRateLimit).toHaveBeenCalledWith(
			expect.objectContaining({ key: "listening-alerts:user-1" }),
		);
		expect(admin.from).not.toHaveBeenCalled();
		expect(calls.inserts).toContainEqual({
			table: "listening_alerts",
			row: {
				user_id: "user-1",
				keyword: "ai",
				alert_type: "spike",
				threshold_value: 10,
				is_active: true,
				workspace_id: null,
			},
		});
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				success: true,
				alert: expect.objectContaining({ user_id: "user-1" }),
			}),
		);
	});
});

describe("Instagram DM templates RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("lists DM templates through the user-scoped client", async () => {
		const { client } = createSupabaseMock({
			ig_dm_templates: [
				{
					id: "template-1",
					user_id: "user-1",
					name: "Welcome",
					content: "Thanks for reaching out",
					category: "general",
					shortcut: "welcome",
					use_count: 2,
				},
			],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await instagramDmTemplatesRoute(
			authedReq({
				method: "POST",
				query: { action: "list" },
				body: { category: "general" },
			}) as any,
			res,
		);

		expect(client.from).toHaveBeenCalledWith("ig_dm_templates");
		expect(admin.from).not.toHaveBeenCalled();
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			templates: [
				expect.objectContaining({
					id: "template-1",
					user_id: "user-1",
					category: "general",
				}),
			],
		});
	});

	it("keeps the service-role-only increment RPC on explicit adminDb", async () => {
		const { client } = createSupabaseMock();
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await instagramDmTemplatesRoute(
			authedReq({
				method: "POST",
				query: { action: "increment-use" },
				body: { templateId: "template-1" },
			}) as any,
			res,
		);

		expect(client.from).not.toHaveBeenCalled();
		expect(admin.rpc).toHaveBeenCalledWith("increment_dm_template_use", {
			p_template_id: "template-1",
			p_user_id: "user-1",
		});
		expect(res.json).toHaveBeenCalledWith({ success: true });
	});
});

describe("Instagram auto-responders RLS-first route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("creates responders through the user-scoped client after ownership check", async () => {
		const { client, calls } = createSupabaseMock({
			instagram_accounts: [{ id: "ig-1", user_id: "user-1" }],
		});
		const admin = createSupabaseMock().client;
		mocks.userDb = client;
		mocks.adminDb = admin;
		mocks.adminDbAny = admin;
		const res = mockRes();

		await instagramAutoRespondersRoute(
			authedReq({
				method: "POST",
				query: { action: "create" },
				body: {
					accountId: "ig-1",
					name: "First reply",
					triggerType: "first_message",
					customResponse: "Thanks for reaching out",
					delaySeconds: 5,
					onlyNewConversations: true,
					maxResponsesPerUser: 1,
				},
			}) as any,
			res,
		);

		expect(client.from).toHaveBeenCalledWith("instagram_accounts");
		expect(client.from).toHaveBeenCalledWith("ig_auto_responders");
		expect(admin.from).not.toHaveBeenCalled();
		expect(calls.inserts).toContainEqual({
			table: "ig_auto_responders",
			row: expect.objectContaining({
				user_id: "user-1",
				ig_account_id: "ig-1",
				name: "First reply",
				trigger_type: "first_message",
				custom_response: "Thanks for reaching out",
				delay_seconds: 5,
				only_new_conversations: true,
				max_responses_per_user: 1,
			}),
		});
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			responder: expect.objectContaining({
				user_id: "user-1",
				ig_account_id: "ig-1",
				name: "First reply",
			}),
		});
	});
});
