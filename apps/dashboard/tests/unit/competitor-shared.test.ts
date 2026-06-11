import { beforeEach, describe, expect, it, vi } from "vitest";

const mockFrom = vi.fn();
const mockDecrypt = vi.fn();
const mockLoggerWarn = vi.fn();

vi.mock("../../api/_lib/supabase.js", () => ({
	getSupabase: () => ({ from: mockFrom }),
}));

vi.mock("../../api/_lib/encryption.js", () => ({
	decrypt: (...args: unknown[]) => mockDecrypt(...args),
}));

vi.mock("../../api/_lib/logger.js", () => ({
	logger: {
		info: vi.fn(),
		warn: (...args: unknown[]) => mockLoggerWarn(...args),
		error: vi.fn(),
		debug: vi.fn(),
	},
}));

vi.mock("../../api/_lib/redis.js", () => ({
	getRedis: () => ({
		get: vi.fn().mockResolvedValue(null),
		set: vi.fn().mockResolvedValue("OK"),
	}),
}));

const { fetchAndStorePosts, getAllAccessTokens } = await import(
	"../../api/_lib/handlers/competitors/shared"
);

function chain(result: unknown) {
	const q: Record<string, any> = {};
	for (const method of [
		"select",
		"eq",
		"or",
		"not",
		"gt",
		"gte",
		"lte",
		"order",
		"limit",
		"update",
	]) {
		q[method] = vi.fn(() => q);
	}
	q.maybeSingle = vi.fn().mockResolvedValue(result);
	q.then = (resolve: (value: unknown) => unknown) =>
		Promise.resolve(result).then(resolve);
	return q;
}

describe("competitor shared helpers", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockDecrypt.mockImplementation((value: string) => {
			if (value === "bad-encrypted") throw new Error("decrypt failed");
			return `token:${value}`;
		});
	});

	it("loads only healthy account tokens and skips individual decrypt failures", async () => {
		const accountsChain = chain({
			data: [
				{
					id: "acct-1",
					threads_access_token_encrypted: "good-encrypted",
					needs_reauth: false,
					is_active: true,
					status: "active",
					token_expires_at: "2099-01-01T00:00:00Z",
				},
				{
					id: "acct-2",
					threads_access_token_encrypted: "bad-encrypted",
					needs_reauth: false,
					is_active: true,
					status: "active",
					token_expires_at: "2099-01-01T00:00:00Z",
				},
				{
					id: "acct-3",
					threads_access_token_encrypted: "expired",
					needs_reauth: false,
					is_active: true,
					status: "active",
					token_expires_at: "2000-01-01T00:00:00Z",
				},
				{
					id: "acct-4",
					threads_access_token_encrypted: "reauth",
					needs_reauth: true,
					is_active: true,
					status: "active",
					token_expires_at: "2099-01-01T00:00:00Z",
				},
			],
			error: null,
		});
		mockFrom.mockReturnValue(accountsChain);

		const tokens = await getAllAccessTokens("user-1");

		expect(tokens).toEqual(["token:good-encrypted"]);
		expect(accountsChain.eq).toHaveBeenCalledWith("is_active", true);
		expect(accountsChain.eq).toHaveBeenCalledWith("needs_reauth", false);
		expect(accountsChain.eq).toHaveBeenCalledWith("status", "active");
		expect(accountsChain.or).toHaveBeenCalledWith(
			expect.stringContaining("token_expires_at.gt."),
		);
		expect(mockLoggerWarn).toHaveBeenCalledWith(
			"Skipping account with undecryptable Threads token",
			expect.objectContaining({ accountId: "acct-2" }),
		);
	});

	it("upserts competitor posts by user_id and threads_post_id", async () => {
		const upsert = vi.fn(() => ({
			select: vi.fn(() => ({
				maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
			})),
		}));
		const updateEq = vi.fn().mockResolvedValue({ error: null });
		const competitorChain = {
			update: vi.fn(() => ({ eq: updateEq })),
			select: vi.fn(() => ({
				eq: vi.fn(() => ({
					maybeSingle: vi.fn().mockResolvedValue({
						data: { consecutive_failures: 0 },
					}),
				})),
			})),
		};
		const postsChain = {
			upsert,
			select: vi.fn(() => ({
				eq: vi.fn(() => ({
					gte: vi.fn(() => ({
						lte: vi.fn().mockResolvedValue({ data: [], error: null }),
					})),
				})),
			})),
		};
		mockFrom.mockImplementation((table: string) => {
			if (table === "competitors") return competitorChain;
			if (table === "competitor_top_posts") return postsChain;
			return chain({ data: null, error: null });
		});
		vi.stubGlobal(
			"fetch",
			vi.fn().mockResolvedValue({
				ok: true,
				json: vi.fn().mockResolvedValue({
					data: [
						{
							id: "thread-1",
							text: "post text",
							like_count: 10,
							reply_count: 2,
							repost_count: 1,
							views: 100,
							timestamp: "2026-05-05T12:00:00Z",
						},
					],
				}),
			}),
		);

		const result = await fetchAndStorePosts("comp-1", "handle", "token", "user-1");

		expect(result.postsCount).toBe(1);
		expect(upsert).toHaveBeenCalledWith(
			expect.objectContaining({
				user_id: "user-1",
				threads_post_id: "thread-1",
			}),
			{ onConflict: "user_id,threads_post_id" },
		);
	});
});
