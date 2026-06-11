import { describe, expect, it, vi } from "vitest";
import { checkOperatorKillSwitch } from "../../api/_lib/operatorKillSwitches.js";

vi.mock("../../api/_lib/logger.js", () => ({
	logger: {
		warn: vi.fn(),
		info: vi.fn(),
		error: vi.fn(),
		debug: vi.fn(),
	},
}));

type KillSwitchRow = {
	id: string;
	scope_type: string;
	scope_id: string | null;
	action_name?: string | null;
	min_risk_level?: string | null;
	reason: string;
	is_active?: boolean;
	expires_at?: string | null;
	created_at?: string;
};

function makeDb(options: {
	profilePaused?: boolean;
	rows?: KillSwitchRow[];
	throwOnSwitchRead?: boolean;
}) {
	return {
		from: vi.fn((table: string) => {
			if (table === "profiles") {
				return {
					select: vi.fn(() => ({
						eq: vi.fn(() => ({
							maybeSingle: vi.fn().mockResolvedValue({
								data: { agent_paused: options.profilePaused ?? false },
							}),
						})),
					})),
				};
			}

			if (table === "operator_kill_switches") {
				return {
					select: vi.fn(() => ({
						eq: vi.fn(() => ({
							eq: vi.fn(() => ({
								order: vi.fn(() => ({
									limit: vi.fn().mockImplementation(() => {
										if (options.throwOnSwitchRead) {
											throw new Error("switch read failed");
										}
										return Promise.resolve({ data: options.rows ?? [] });
									}),
								})),
							})),
						})),
					})),
				};
			}

			throw new Error(`Unexpected table: ${table}`);
		}),
	};
}

describe("operator kill switches", () => {
	it("allows actions when no switch matches", async () => {
		const result = await checkOperatorKillSwitch(
			makeDb({ rows: [] }),
			{
				userId: "user-1",
				workspaceId: "workspace-1",
				actionName: "schedule_post",
				riskLevel: "high",
			},
		);

		expect(result).toEqual({ blocked: false });
	});

	it("treats profiles.agent_paused as a legacy global switch", async () => {
		const result = await checkOperatorKillSwitch(
			makeDb({ profilePaused: true }),
			{
				userId: "user-1",
				actionName: "publish_post",
				riskLevel: "critical",
			},
		);

		expect(result).toMatchObject({
			blocked: true,
			scopeType: "global",
			scopeId: null,
			reason: expect.stringContaining("global agent pause"),
		});
	});

	it("checks hierarchy from global to narrower scopes", async () => {
		const result = await checkOperatorKillSwitch(
			makeDb({
				rows: [
					{
						id: "account-switch",
						scope_type: "account",
						scope_id: "acct-1",
						reason: "Account pause",
						is_active: true,
						created_at: "2026-05-22T12:02:00.000Z",
					},
					{
						id: "global-switch",
						scope_type: "global",
						scope_id: null,
						reason: "Global pause",
						is_active: true,
						created_at: "2026-05-22T12:00:00.000Z",
					},
				],
			}),
			{
				userId: "user-1",
				accountId: "acct-1",
				actionName: "publish_post",
				riskLevel: "critical",
			},
		);

		expect(result).toMatchObject({
			blocked: true,
			switchId: "global-switch",
			scopeType: "global",
			reason: expect.stringContaining("Global pause"),
		});
	});

	it("matches action, risk, session, and api-key scoped switches", async () => {
		const rows: KillSwitchRow[] = [
			{
				id: "wrong-action",
				scope_type: "session",
				scope_id: "session-1",
				action_name: "generate_caption",
				reason: "Wrong action",
				is_active: true,
			},
			{
				id: "session-switch",
				scope_type: "session",
				scope_id: "session-1",
				action_name: "publish_post",
				min_risk_level: "high",
				reason: "Session paused",
				is_active: true,
			},
			{
				id: "api-key-switch",
				scope_type: "api_key",
				scope_id: "key-1",
				reason: "API key paused",
				is_active: true,
			},
		];

		const highRisk = await checkOperatorKillSwitch(
			makeDb({ rows }),
			{
				userId: "user-1",
				sessionId: "session-1",
				apiKeyId: "key-1",
				actionName: "publish_post",
				riskLevel: "critical",
			},
		);
		const mediumRisk = await checkOperatorKillSwitch(
			makeDb({ rows: [rows[1]] }),
			{
				userId: "user-1",
				sessionId: "session-1",
				actionName: "publish_post",
				riskLevel: "medium",
			},
		);

		expect(highRisk).toMatchObject({
			blocked: true,
			switchId: "session-switch",
			scopeType: "session",
		});
		expect(mediumRisk).toEqual({ blocked: false });
	});

	it("ignores inactive and expired switches", async () => {
		const result = await checkOperatorKillSwitch(
			makeDb({
				rows: [
					{
						id: "inactive",
						scope_type: "workspace",
						scope_id: "workspace-1",
						reason: "Inactive",
						is_active: false,
					},
					{
						id: "expired",
						scope_type: "workspace",
						scope_id: "workspace-1",
						reason: "Expired",
						is_active: true,
						expires_at: "2026-01-01T00:00:00.000Z",
					},
				],
			}),
			{
				userId: "user-1",
				workspaceId: "workspace-1",
				actionName: "publish_post",
				riskLevel: "critical",
			},
		);

		expect(result).toEqual({ blocked: false });
	});

	it("fails open when the switch query fails", async () => {
		const result = await checkOperatorKillSwitch(
			makeDb({ throwOnSwitchRead: true }),
			{
				userId: "user-1",
				actionName: "publish_post",
				riskLevel: "critical",
			},
		);

		expect(result).toEqual({ blocked: false });
	});
});
