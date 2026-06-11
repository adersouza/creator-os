import { beforeEach, describe, expect, it, vi } from "vitest";

const mockDecrypt = vi.fn();
vi.mock("../../api/_lib/encryption.js", () => ({
	decrypt: (...args: unknown[]) => mockDecrypt(...args),
}));

const mockWarn = vi.fn();
const mockInfo = vi.fn();
vi.mock("../../api/_lib/logger.js", () => ({
	logger: {
		debug: vi.fn(),
		error: vi.fn(),
		info: (...args: unknown[]) => mockInfo(...args),
		warn: (...args: unknown[]) => mockWarn(...args),
	},
}));

const updates: Array<{ patch: unknown; field: string; value: unknown }> = [];
const mockSupabase = {
	from: vi.fn(() => ({
		update: vi.fn((patch: unknown) => ({
			eq: vi.fn(async (field: string, value: unknown) => {
				updates.push({ patch, field, value });
				return { error: null };
			}),
		})),
	})),
};

vi.mock("../../api/_lib/supabase.js", () => ({
	getSupabase: () => mockSupabase,
}));

const mockWithRetry = vi.fn(async (fn: () => Promise<unknown>) => fn());
vi.mock("../../api/_lib/retryUtils.js", () => ({
	withRetry: (...args: unknown[]) => mockWithRetry(...args),
}));

const { syncReplyChainForPost } = await import(
	"../../api/_lib/handlers/threads/replyChainSync.js"
);

describe("syncReplyChainForPost", () => {
	beforeEach(() => {
		updates.length = 0;
		vi.clearAllMocks();
		mockDecrypt.mockReturnValue("plain-token");
	});

	it("records depth=1 when Threads reports the conversation edge is unsupported", async () => {
		const fetchMock = vi.fn().mockResolvedValue(
			new Response(
				JSON.stringify({
					error: {
						message: "Tried accessing nonexisting field (conversation)",
						type: "THApiException",
						code: 100,
						fbtrace_id: "trace-123",
					},
				}),
				{ status: 500 },
			),
		);
		vi.stubGlobal("fetch", fetchMock);

		const result = await syncReplyChainForPost({
			postId: "post-1",
			threadsPostId: "thread-1",
			accountId: "account-1",
			accessTokenEncrypted: "encrypted-token",
		});

		expect(result).toEqual({
			postId: "post-1",
			threadsPostId: "thread-1",
			depth: 1,
			itemCount: 0,
		});
		expect(fetchMock).toHaveBeenCalledTimes(1);
		expect(mockWithRetry).toHaveBeenCalledTimes(1);
		expect(updates).toHaveLength(2);
		expect(updates[0]?.patch).toEqual({ reply_chain: [] });
		expect(updates[1]?.patch).toEqual({
			reply_depth: 1,
			reply_chain_synced_at: expect.any(String),
		});
		expect(mockInfo).toHaveBeenCalledWith(
			"[replyChainSync] Threads conversation edge unavailable; recording depth=1",
			expect.objectContaining({
				postId: "post-1",
				threadsPostId: "thread-1",
				code: 100,
			}),
		);
	});
});
