import { beforeEach, describe, expect, it, vi } from "vitest";
import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import { withIdempotency } from "../../api/_lib/idempotency.js";

const mockFrom = vi.fn();

vi.mock("../../api/_lib/supabase.js", () => ({
	getSupabaseAny: () => ({ from: (...args: unknown[]) => mockFrom(...args) }),
}));

vi.mock("../../api/_lib/logger.js", () => ({
	logger: { warn: vi.fn(), error: vi.fn(), info: vi.fn(), debug: vi.fn() },
}));

const ROOT = path.resolve(__dirname, "../..");

function read(relativePath: string) {
	return fs.readFileSync(path.join(ROOT, relativePath), "utf8");
}

// biome-ignore lint/suspicious/noExplicitAny: lightweight Vercel response test double
function mockRes(): any {
	const res: Record<string, unknown> = {};
	res.status = vi.fn().mockReturnValue(res);
	res.json = vi.fn().mockReturnValue(res);
	res.setHeader = vi.fn().mockReturnValue(res);
	return res;
}

function tableBackedIdempotencyStore(
	seedRows: Array<Record<string, unknown>> = [],
) {
	const rows = new Map<string, Record<string, unknown>>();
	const rowKey = (row: Record<string, unknown>) =>
		[row.user_id, row.route, row.action, row.idempotency_key].join("|");
	for (const row of seedRows) rows.set(rowKey(row), { ...row });

	const makeFilterChain = (
		resolve: (filters: Record<string, unknown>) => unknown,
	) => {
		const filters: Record<string, unknown> = {};
		const chain: Record<string, unknown> = {};
		chain.eq = vi.fn((column: string, value: unknown) => {
			filters[column] = value;
			return chain;
		});
		chain.maybeSingle = vi.fn(async () => resolve(filters));
		return chain;
	};
	const makeUpdateChain = (patch: Record<string, unknown>) => {
		const filters: Record<string, unknown> = {};
		const chain: Record<string, unknown> = {};
		chain.eq = vi.fn((column: string, value: unknown) => {
			filters[column] = value;
			const key = rowKey(filters);
			const row = rows.get(key);
			if (
				row &&
				(!filters.payload_hash || row.payload_hash === filters.payload_hash)
			) {
				rows.set(key, { ...row, ...patch });
			}
			return chain;
		});
		return chain;
	};

	return {
		from: vi.fn((table: string) => {
			expect(table).toBe("api_idempotency_keys");
			return {
				insert: vi.fn(async (row: Record<string, unknown>) => {
					const key = rowKey(row);
					if (rows.has(key)) return { error: { code: "23505" } };
					rows.set(key, {
						...row,
						response_status: null,
						response_body: null,
					});
					return { error: null };
				}),
				select: vi.fn(() =>
					makeFilterChain((filters) => {
						const row = rows.get(rowKey(filters));
						return { data: row ?? null, error: null };
					}),
				),
				update: vi.fn((patch: Record<string, unknown>) =>
					makeUpdateChain(patch),
				),
			};
		}),
		rows,
	};
}

const highRiskReplayCases = [
	{
		name: "queue-fill worker replay",
		options: { userId: "owner-1", route: "queue-fill", action: "fill" },
		key: "queue-fill:workspace-1:group-1:trace-1",
		body: {
			workspaceId: "workspace-1",
			ownerId: "owner-1",
			groupId: "group-1",
			traceId: "trace-1",
		},
		conflictBody: {
			workspaceId: "workspace-1",
			ownerId: "owner-1",
			groupId: "group-1",
			traceId: "trace-2",
		},
		response: { ok: true, filled: true, count: 2 },
	},
	{
		name: "autopilot replay",
		options: {
			userId: "user-1",
			route: "autopilot-replay",
			action: "replay-step",
		},
		key: "autopilot-replay:00000000-0000-4000-8000-000000000001:00000000-0000-4000-8000-000000000002",
		body: {
			runId: "00000000-0000-4000-8000-000000000001",
			stepId: "00000000-0000-4000-8000-000000000002",
		},
		conflictBody: {
			runId: "00000000-0000-4000-8000-000000000001",
			stepId: "00000000-0000-4000-8000-000000000003",
		},
		response: { success: true, runId: "replay-run-1", status: "partial" },
	},
	{
		name: "DLQ retry",
		options: {
			userId: "admin-1",
			route: "admin/dead-letters",
			action: "retry:auto_post_queue",
		},
		key: "admin-dlq-retry:auto_post_queue:q-1",
		body: { action: "retry", source: "auto_post_queue", itemId: "q-1" },
		conflictBody: {
			action: "retry",
			source: "auto_post_queue",
			itemId: "q-2",
		},
		response: { success: true, retried: "q-1" },
	},
	{
		name: "publish retry",
		options: { userId: "user-1", route: "posts", action: "publish" },
		key: "publish-post:threads:acct-1:retry-1",
		body: { platform: "threads", accountId: "acct-1", content: "retry me" },
		conflictBody: {
			platform: "threads",
			accountId: "acct-1",
			content: "retry me differently",
		},
		response: { success: true, postId: "post-1" },
	},
	{
		name: "reply send",
		options: { userId: "user-1", route: "/api/replies", action: "send" },
		key: "inbox-reply:reply-1:send-1",
		body: { accountId: "acct-1", replyToId: "reply-1", content: "Thanks!" },
		conflictBody: {
			accountId: "acct-1",
			replyToId: "reply-1",
			content: "Thanks again!",
		},
		response: { success: true, replyId: "reply-sent-1" },
	},
] as const;

function hashPayloadForTest(payload: unknown): string {
	return crypto
		.createHash("sha256")
		.update(stableStringifyForTest(payload))
		.digest("hex");
}

function stableStringifyForTest(value: unknown): string {
	if (value === null || typeof value !== "object") return JSON.stringify(value);
	if (Array.isArray(value)) {
		return `[${value.map(stableStringifyForTest).join(",")}]`;
	}
	const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) =>
		a.localeCompare(b),
	);
	return `{${entries
		.map(([key, child]) => `${JSON.stringify(key)}:${stableStringifyForTest(child)}`)
		.join(",")}}`;
}

describe("high-risk write idempotency", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("requires fail-closed idempotency for high-risk post writes", () => {
		const postsApi = read("api/posts.ts");
		const postsClient = read("src/services/api/posts.ts");

		expect(postsApi).toContain("REQUIRE_IDEMPOTENCY_KEY_ACTIONS");
		expect(postsApi).toContain("\"publish\"");
		expect(postsApi).toContain("\"schedule\"");
		expect(postsApi).toContain("\"reschedule\"");
		expect(postsApi).toContain("\"bulk-schedule-groups\"");
		expect(postsApi).toContain("requireKey: REQUIRE_IDEMPOTENCY_KEY_ACTIONS.has(action)");
		expect(postsApi).toContain("failClosed: REQUIRE_IDEMPOTENCY_KEY_ACTIONS.has(action)");
		expect(postsClient).toContain("publish-post:");
		expect(postsClient).toContain("schedule-post:");
	});

	it("requires fail-closed idempotency for auto-post queue recovery writes", () => {
		const autoPostApi = read("api/auto-post.ts");

		expect(autoPostApi).toContain("IDEMPOTENT_HIGH_RISK_ACTIONS");
		expect(autoPostApi).toContain("\"retry-dead-letter\"");
		expect(autoPostApi).toContain("\"trigger-queue-fill\"");
		expect(autoPostApi).toContain("\"bulk-clear-queue\"");
		expect(autoPostApi).toContain("\"bulk-clear-all-queues\"");
		expect(autoPostApi).toContain("\"delete-queue-item\"");
		expect(autoPostApi).toContain("\"add-queue-items\"");
		expect(autoPostApi).toContain("\"reorder-queue\"");
		expect(autoPostApi).toContain("\"upsert-workspace-config\"");
		expect(autoPostApi).toContain("\"upsert-group-config\"");
		expect(autoPostApi).toContain("\"delete-group-config\"");
		expect(autoPostApi).toContain("\"toggle-group-mode\"");
		expect(autoPostApi).toContain("\"override-account-state\"");
		expect(autoPostApi).toContain("requireKey: IDEMPOTENT_HIGH_RISK_ACTIONS.has(action)");
		expect(autoPostApi).toContain("failClosed: IDEMPOTENT_HIGH_RISK_ACTIONS.has(action)");
	});

	it("routes legacy auto-post queue/config mutations through the API", () => {
		const queueService = read("src/services/autoPost/queue.ts");
		const groupService = read("src/services/autoPost/groups.ts");
		const configService = read("src/services/autoPost/config.ts");
		const apiClient = read("src/services/autoPost/apiClient.ts");
		const queueHandlers = read("api/_lib/handlers/auto-post/route/queueHandlers.ts");

		expect(apiClient).toContain("postAutoPostAction");
		expect(apiClient).toContain("Idempotency-Key");
		expect(queueService).toContain('postAutoPostAction<{ inserted?: number | undefined }>');
		expect(queueService).toContain('"add-queue-items"');
		expect(queueService).toContain('"delete-queue-item"');
		expect(queueService).toContain('"reorder-queue"');
		expect(queueService).toContain('"bulk-clear-all-queues"');
		expect(groupService).toContain('"add-queue-items"');
		expect(configService).toContain('"upsert-workspace-config"');
		expect(queueHandlers).toContain("handleAddQueueItems");
		expect(queueHandlers).toContain("handleReorderQueue");
		expect(queueService).not.toContain(".insert(row as any)");
		expect(queueService).not.toContain(".delete()");
		expect(groupService).not.toContain(".from(\"auto_post_queue\").insert");
	});

	it("keeps legacy autoPostService queue mutations delegated to idempotent API helpers", () => {
		const legacyService = read("services/autoPostService.ts");

		expect(legacyService).toContain("addToAutoQueueViaApi");
		expect(legacyService).toContain("removeFromAutoQueueViaApi");
		expect(legacyService).toContain("reorderAutoQueueViaApi");
		expect(legacyService).toContain("clearAutoQueueViaApi");
		expect(legacyService).not.toContain(".insert(row as any)");
		expect(legacyService).not.toContain(".upsert(upsertRows as any");
		expect(legacyService).not.toContain(".delete()\n\t\t\t.eq(\"workspace_id\", wsId)");
	});

	it("sends deterministic idempotency keys from MCP write calls", () => {
		const helpers = read("mcp-server/src/helpers.ts");

		expect(helpers).toContain("Idempotency-Key");
		expect(helpers).toContain("hashStableValue");
		expect(helpers).toContain("stableStringify");
		expect(helpers).toContain("mcp:${SESSION_ID}:${method}:${path}");
	});

	it.each(highRiskReplayCases)(
		"replays completed duplicate $name without duplicate side effects",
		async ({ options, key, body, conflictBody, response }) => {
			const store = tableBackedIdempotencyStore();
			mockFrom.mockImplementation(store.from);
			const sideEffect = vi.fn();
			const firstRes = mockRes();

			await withIdempotency(
				{ headers: { "idempotency-key": key }, body } as never,
				firstRes as never,
				{
					...options,
					enabled: true,
					requireKey: true,
					failClosed: true,
				},
				async () => {
					sideEffect();
					firstRes.status(200);
					firstRes.json(response);
					return firstRes as never;
				},
			);

			const replayRes = mockRes();
			const replayHandler = vi.fn();
			await withIdempotency(
				{ headers: { "idempotency-key": key }, body } as never,
				replayRes as never,
				{
					...options,
					enabled: true,
					requireKey: true,
					failClosed: true,
				},
				replayHandler,
			);

			expect(replayHandler).not.toHaveBeenCalled();
			expect(sideEffect).toHaveBeenCalledOnce();
			expect(replayRes.setHeader).toHaveBeenCalledWith(
				"x-idempotent-replay",
				"true",
			);
			expect(replayRes.status).toHaveBeenCalledWith(200);
			expect(replayRes.json).toHaveBeenCalledWith(response);

			const conflictRes = mockRes();
			const conflictHandler = vi.fn();
			await withIdempotency(
				{ headers: { "idempotency-key": key }, body: conflictBody } as never,
				conflictRes as never,
				{
					...options,
					enabled: true,
					requireKey: true,
					failClosed: true,
				},
				conflictHandler,
			);

			expect(conflictHandler).not.toHaveBeenCalled();
			expect(sideEffect).toHaveBeenCalledOnce();
			expect(conflictRes.status).toHaveBeenCalledWith(409);
			expect(conflictRes.json).toHaveBeenCalledWith(
				expect.objectContaining({ code: "IDEMPOTENCY_PAYLOAD_MISMATCH" }),
			);
		},
	);

	it.each(highRiskReplayCases)(
		"returns in-progress for duplicate $name claims without side effects",
		async ({ options, key, body }) => {
			const store = tableBackedIdempotencyStore([
				{
					user_id: options.userId,
					route: options.route,
					action: options.action,
					idempotency_key: key,
					status: "processing",
					payload_hash: hashPayloadForTest(body),
					response_status: null,
					response_body: null,
				},
			]);
			mockFrom.mockImplementation(store.from);
			const res = mockRes();
			const handler = vi.fn();

			await withIdempotency(
				{ headers: { "idempotency-key": key }, body } as never,
				res as never,
				{
					...options,
					enabled: true,
					requireKey: true,
					failClosed: true,
				},
				handler,
			);

			expect(handler).not.toHaveBeenCalled();
			expect(res.status).toHaveBeenCalledWith(409);
			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ code: "IDEMPOTENCY_IN_PROGRESS" }),
			);
		},
	);
});
