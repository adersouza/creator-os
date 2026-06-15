import { beforeEach, describe, expect, it, vi } from "vitest";

const mockFrom = vi.fn();

vi.mock("../../api/_lib/supabase", () => ({
	getSupabaseAny: () => ({ from: mockFrom }),
}));

vi.mock("../../api/_lib/logger", () => ({
	logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

vi.mock("../../api/_lib/alerting", () => ({
	AlertLevel: { WARN: "warn" },
	alert: vi.fn().mockResolvedValue(undefined),
	alertCronFailure: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("../../api/_lib/apiResponse", () => ({
	verifyCronAuth: vi.fn(() => true),
}));

vi.mock("../../api/_lib/cronUtils", () => ({
	withCronLock: vi.fn(async (_supabase, _job, fn) => fn()),
	trackCronRun: vi.fn(async (_supabase, _job, fn) => fn()),
}));

vi.mock("../../api/_lib/handlers/auto-post/killSwitch", () => ({
	isAutoposterHardDisabled: vi.fn(() => false),
}));

function chainFor(finalValue: { data: unknown; error: unknown }) {
	const chain: Record<string, ReturnType<typeof vi.fn> | Function> = {};
	const methods = [
		"select",
		"eq",
		"in",
		"is",
		"or",
		"not",
		"gte",
		"lt",
		"limit",
	];
	for (const method of methods) {
		chain[method] = vi.fn().mockReturnValue(chain);
	}
	chain.then = (resolve: (value: unknown) => unknown) =>
		Promise.resolve(finalValue).then(resolve);
	return chain;
}

function tableChain(table: string) {
	let finalValue: { data: unknown; error: unknown } = { data: [], error: null };
	const chain = chainFor(finalValue);
	const select = chain.select as ReturnType<typeof vi.fn>;
	select.mockImplementation((columns: string) => {
		if (table === "auto_post_config") {
			finalValue = {
				data: [{ workspace_id: "workspace-1" }],
				error: null,
			};
		} else if (
			table === "auto_post_queue" &&
			columns.includes("posted_at")
		) {
			finalValue = {
				data: [
					{
						id: "queue-1",
						workspace_id: "workspace-1",
						group_id: "group-1",
						account_id: "account-1",
						threads_post_id: "threads-1",
						posted_at: "2026-06-05T00:00:00.000Z",
					},
				],
				error: null,
			};
		} else {
			finalValue = { data: [], error: null };
		}

		const updatedChain = chainFor(finalValue);
		for (const method of Object.keys(chain)) {
			if (method !== "then") chain[method] = updatedChain[method];
		}
		chain.then = updatedChain.then;
		return chain;
	});
	return chain;
}

describe("autoposter doctor", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockFrom.mockImplementation((table: string) => tableChain(table));
	});

	it("flags published queue rows that have no local posts row", async () => {
		const { runAutoposterDoctor } = await import(
			"../../api/cron/autoposter-doctor.js"
		);

		const findings = await runAutoposterDoctor();

		expect(findings).toEqual(
			expect.arrayContaining([
				expect.objectContaining({
					workspace_id: "workspace-1",
					check_name: "autoposter-doctor:published-without-post",
					severity: "critical",
					details: expect.objectContaining({
						sampleQueueItemIds: ["queue-1"],
						sampleThreadsPostIds: ["threads-1"],
					}),
				}),
			]),
		);
	});

	it("flags accounts with repeated failures but still high health", async () => {
		mockFrom.mockImplementation((table: string) => {
			if (table === "auto_post_config") {
				return chainFor({
					data: [{ workspace_id: "workspace-1" }],
					error: null,
				});
			}
			if (table === "account_autoposter_state") {
				return chainFor({
					data: [
						{
							account_id: "account-1",
							workspace_id: "workspace-1",
							group_id: "group-1",
							status: "active",
							account_health_score: 92,
						},
					],
					error: null,
				});
			}
			if (table === "publish_attempts") {
				return chainFor({
					data: [
						{ account_id: "account-1", result: "dead_letter" },
						{ account_id: "account-1", result: "failed" },
						{ account_id: "account-1", result: "requeued" },
					],
					error: null,
				});
			}
			return chainFor({ data: [], error: null });
		});

		const { runAutoposterDoctor } = await import(
			"../../api/cron/autoposter-doctor.js"
		);

		const findings = await runAutoposterDoctor();

		expect(findings).toEqual(
			expect.arrayContaining([
				expect.objectContaining({
					check_name: "autoposter-doctor:failure-heavy-account-marked-healthy",
					severity: "error",
					details: expect.objectContaining({
						sampleAccountIds: ["account-1"],
					}),
				}),
			]),
		);
	});

	it("does not flag high-health accounts for active-window requeues", async () => {
		mockFrom.mockImplementation((table: string) => {
			if (table === "auto_post_config") {
				return chainFor({
					data: [{ workspace_id: "workspace-1" }],
					error: null,
				});
			}
			if (table === "account_autoposter_state") {
				return chainFor({
					data: [
						{
							account_id: "account-1",
							workspace_id: "workspace-1",
							group_id: "group-1",
							status: "active",
							account_health_score: 92,
						},
					],
					error: null,
				});
			}
			if (table === "publish_attempts") {
				return chainFor({
					data: [
						{
							account_id: "account-1",
							result: "requeued",
							error_code: "outside_active_window",
						},
						{
							account_id: "account-1",
							result: "requeued",
							error_code: "outside_active_window",
						},
						{
							account_id: "account-1",
							result: "requeued",
							error_code: "outside_active_window",
						},
					],
					error: null,
				});
			}
			return chainFor({ data: [], error: null });
		});

		const { runAutoposterDoctor } = await import(
			"../../api/cron/autoposter-doctor.js"
		);

		const findings = await runAutoposterDoctor();

		expect(findings).not.toEqual(
			expect.arrayContaining([
				expect.objectContaining({
					check_name:
						"autoposter-doctor:failure-heavy-account-marked-healthy",
				}),
			]),
		);
	});

	it("does not flag high-health accounts for cap-control requeues", async () => {
		mockFrom.mockImplementation((table: string) => {
			if (table === "auto_post_config") {
				return chainFor({
					data: [{ workspace_id: "workspace-1" }],
					error: null,
				});
			}
			if (table === "account_autoposter_state") {
				return chainFor({
					data: [
						{
							account_id: "account-1",
							workspace_id: "workspace-1",
							group_id: "group-1",
							status: "active",
							account_health_score: 96,
						},
					],
					error: null,
				});
			}
			if (table === "publish_attempts") {
				return chainFor({
					data: [
						{
							account_id: "account-1",
							result: "requeued",
							error_code: "suppressed_cap_zero",
							error_message: "suppressed_cap_zero — requeued",
						},
						{
							account_id: "account-1",
							result: "requeued",
							error_code: "performance_recommended_cap_exceeded",
							error_message:
								"performance_recommended_cap_exceeded — requeued",
						},
						{
							account_id: "account-1",
							result: "requeued",
							error_code: "warmup_cap_exceeded",
							error_message: "warmup_cap_exceeded — requeued",
						},
					],
					error: null,
				});
			}
			return chainFor({ data: [], error: null });
		});

		const { runAutoposterDoctor } = await import(
			"../../api/cron/autoposter-doctor.js"
		);

		const findings = await runAutoposterDoctor();

		expect(findings).not.toEqual(
			expect.arrayContaining([
				expect.objectContaining({
					check_name:
						"autoposter-doctor:failure-heavy-account-marked-healthy",
				}),
			]),
		);
	});
});
