import { beforeEach, describe, expect, it, vi } from "vitest";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

vi.mock("../../api/_lib/encryption", () => ({
	decrypt: (value: string) => `decrypted-${value}`,
}));

vi.mock("../../api/_lib/logger", () => ({
	logger: {
		info: vi.fn(),
		warn: vi.fn(),
		error: vi.fn(),
		debug: vi.fn(),
	},
}));

vi.mock("../../api/_lib/retryUtils", () => ({
	withRetry: (fn: () => Promise<unknown>) => fn(),
}));

import { processAutoReplyRules } from "../../api/_lib/autoReplyEngine";

function makeSupabaseWithDuplicateLogClaim() {
	return {
		from: vi.fn().mockImplementation((table: string) => {
			if (table === "accounts") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							maybeSingle: vi.fn().mockResolvedValue({
								data: { id: "acc-1", user_id: "user-1" },
								error: null,
							}),
						}),
					}),
				};
			}

			if (table === "workspace_members") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockResolvedValue({
							data: [{ workspace_id: "ws-1" }],
							error: null,
						}),
					}),
				};
			}

			if (table === "auto_reply_rules") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							in: vi.fn().mockReturnValue({
								or: vi.fn().mockResolvedValue({
									data: [
										{
											id: "rule-1",
											workspace_id: "ws-1",
											account_id: "acc-1",
											trigger_type: "keyword",
											trigger_pattern: "hello",
											reply_text: "hi {{username}}",
											is_active: true,
										},
									],
									error: null,
								}),
							}),
						}),
					}),
					update: vi.fn().mockReturnValue({
						eq: vi.fn().mockResolvedValue({ data: null, error: null }),
					}),
				};
			}

			if (table === "auto_reply_logs") {
				return {
					select: vi.fn().mockImplementation((_cols: string, opts?: unknown) => {
						if (opts) {
							return {
								eq: vi.fn().mockReturnValue({
									gte: vi.fn().mockResolvedValue({ count: 0, error: null }),
								}),
							};
						}
						return {
							eq: vi.fn().mockReturnValue({
								eq: vi.fn().mockReturnValue({
									gte: vi.fn().mockReturnValue({
										limit: vi.fn().mockResolvedValue({
											data: [],
											error: null,
										}),
									}),
								}),
							}),
						};
					}),
					insert: vi.fn().mockReturnValue({
						select: vi.fn().mockResolvedValue({
							data: null,
							error: { code: "23505", message: "duplicate key" },
						}),
					}),
					update: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockResolvedValue({ data: null, error: null }),
						}),
					}),
				};
			}

			throw new Error(`Unexpected table ${table}`);
		}),
	};
}

describe("processAutoReplyRules side-effect hardening", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("does not call Threads when the durable idempotency claim already exists", async () => {
		const supabase = makeSupabaseWithDuplicateLogClaim();

		await processAutoReplyRules(supabase as never, {
			accountId: "acc-1",
			threadsUserId: "threads-user-1",
			encryptedAccessToken: "token",
			eventType: "replies",
			text: "hello there",
			replyToId: "reply-1",
			authorId: "author-1",
			authorUsername: "fan",
		});

		expect(mockFetch).not.toHaveBeenCalled();
	});
});
