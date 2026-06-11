import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess, methodNotAllowed } from "../apiResponse.js";
import { withAuth } from "../middleware.js";
import { getRedis } from "../redis.js";
import { getSupabaseAny } from "../supabase.js";
import { z, zRecord, zUnknown } from "../zodCompat.js";

const GOALS_KEY = "business_goals";
const POLICY_KEY = "business_policy";
const RUNBOOK_KEY = "business_runbook_state";

const ApprovalTypeSchema = z.enum([
	"publish_batch",
	"spend_money",
	"change_automation",
	"delete_content",
	"message_users",
	"alter_branding",
	"invite_team",
	"revoke_keys",
	"data_export",
	"other",
]);

const PolicySchema = z.object({
	highRiskActionsLocked: z.boolean().default(false),
	enforceApprovalBinding: z.boolean().default(false),
	requireApprovalFor: z.array(ApprovalTypeSchema).default([
		"publish_batch",
		"spend_money",
		"change_automation",
		"delete_content",
		"message_users",
		"alter_branding",
		"invite_team",
		"revoke_keys",
		"data_export",
	]),
	budgetLimits: z
		.object({
			dailyAiSpendUsd: z.number().nullable().optional(),
			monthlyAdSpendUsd: z.number().nullable().optional(),
			maxPostsPerAccountPerDay: z.number().nullable().optional(),
		})
		.default({}),
	escalationRules: z.array(z.string()).default([]),
	contentBoundaries: z.array(z.string()).default([]),
	brandRules: z.array(z.string()).default([]),
});

const GoalsSchema = z.object({
	revenueTargets: zRecord(z.string(), zUnknown()).optional(),
	growthTargets: zRecord(z.string(), zUnknown()).optional(),
	priorityAccounts: z.array(z.string()).optional(),
	priorityGroups: z.array(z.string()).optional(),
	products: z.array(zRecord(z.string(), zUnknown())).optional(),
	kpis: z.array(z.string()).optional(),
	constraints: z.array(z.string()).optional(),
}).passthrough();

const db = () => getSupabaseAny();

function defaultPolicy() {
	return PolicySchema.parse({});
}

async function getNote(userId: string, key: string): Promise<{ value?: string; updated_at?: string } | null> {
	const { data, error } = await db()
		.from("agent_notes")
		.select("value, updated_at")
		.eq("user_id", userId)
		.eq("key", key)
		.is("account_group_id", null)
		.maybeSingle();
	if (error) throw error;
	return data ?? null;
}

async function upsertNote(userId: string, key: string, value: unknown) {
	const valStr = typeof value === "string" ? value : JSON.stringify(value, null, 2);
	const { data: existing } = await db()
		.from("agent_notes")
		.select("id")
		.eq("user_id", userId)
		.eq("key", key)
		.is("account_group_id", null)
		.maybeSingle();
	if (existing?.id) {
		const { error } = await db()
			.from("agent_notes")
			.update({ value: valStr, updated_at: new Date().toISOString() })
			.eq("id", existing.id);
		if (error) throw error;
		return { action: "updated", key };
	}
	const { error } = await db().from("agent_notes").insert({
		user_id: userId,
		key,
		value: valStr,
		account_group_id: null,
	});
	if (error) throw error;
	return { action: "created", key };
}

function parseNote<T>(note: { value?: string } | null, fallback: T): T {
	if (!note?.value) return fallback;
	try {
		return JSON.parse(note.value) as T;
	} catch {
		return fallback;
	}
}

function dateKey(offsetDays: number): string {
	const d = new Date();
	d.setUTCDate(d.getUTCDate() - offsetDays);
	return d.toISOString().slice(0, 10);
}

async function aiCosts(userId: string, days: number) {
	const redis = getRedis();
	const daily: Array<{ date: string; userCostUsd: number; platformCostUsd: number }> = [];
	let totalUserMicro = 0;
	let totalPlatformMicro = 0;
	for (let i = 0; i < days; i++) {
		const date = dateKey(i);
		const [userRaw, platformRaw] = await Promise.all([
			redis.get<number | string | null>(`ai_cost:${userId}:${date}`),
			redis.get<number | string | null>(`ai_cost:platform:${date}`),
		]);
		const userMicro = Number(userRaw ?? 0) || 0;
		const platformMicro = Number(platformRaw ?? 0) || 0;
		totalUserMicro += userMicro;
		totalPlatformMicro += platformMicro;
		daily.push({
			date,
			userCostUsd: userMicro / 1_000_000,
			platformCostUsd: platformMicro / 1_000_000,
		});
	}
	return {
		days,
		totalUserCostUsd: totalUserMicro / 1_000_000,
		totalPlatformCostUsd: totalPlatformMicro / 1_000_000,
		daily: daily.reverse(),
	};
}

async function accountCounts(userId: string) {
	const [threads, instagram, groups] = await Promise.all([
		db().from("accounts").select("id", { count: "exact", head: true }).eq("user_id", userId),
		db().from("instagram_accounts").select("id", { count: "exact", head: true }).eq("user_id", userId),
		db().from("account_groups").select("id", { count: "exact", head: true }).eq("user_id", userId),
	]);
	return {
		threads: threads.count ?? 0,
		instagram: instagram.count ?? 0,
		groups: groups.count ?? 0,
	};
}

async function pendingApprovals(userId: string, limit = 20) {
	const { data, error } = await db()
		.from("agent_approvals")
		.select("id, context, urgency, status, expires_at, created_at")
		.eq("user_id", userId)
		.eq("status", "pending")
		.order("created_at", { ascending: false })
		.limit(limit);
	if (error) throw error;
	return data ?? [];
}

async function latestAgentActions(userId: string, limit = 20) {
	const { data, error } = await db()
		.from("agent_actions")
		.select("tool_name, success, result_summary, created_at")
		.eq("user_id", userId)
		.order("created_at", { ascending: false })
		.limit(limit);
	if (error) throw error;
	return data ?? [];
}

async function buildBrief(userId: string, days: number) {
	const [goalsNote, policyNote, counts, approvals, actions, costs] =
		await Promise.all([
			getNote(userId, GOALS_KEY),
			getNote(userId, POLICY_KEY),
			accountCounts(userId),
			pendingApprovals(userId, 10),
			latestAgentActions(userId, 10),
			aiCosts(userId, Math.min(8, days)),
		]);
	const policy = PolicySchema.parse({
		...defaultPolicy(),
		...parseNote(policyNote, {}),
	});
	return {
		generatedAt: new Date().toISOString(),
		windowDays: days,
		goals: parseNote(goalsNote, {}),
		policy,
		accounts: counts,
		pendingApprovals: approvals,
		recentAgentActions: actions,
		aiCosts: costs,
		risk: {
			highRiskActionsLocked: policy.highRiskActionsLocked,
			enforceApprovalBinding: policy.enforceApprovalBinding,
			pendingApprovalCount: approvals.length,
		},
	};
}

export default withAuth(async (req: VercelRequest, res: VercelResponse, user) => {
	const action = String(req.query.action ?? "");
	const days = Math.min(365, Math.max(1, Number(req.query.days ?? req.body?.days ?? 14) || 14));

	try {
		if (action === "brief" && req.method === "GET") {
			return apiSuccess(res, await buildBrief(user.id, Math.min(90, days)));
		}

		if (action === "goals") {
			if (req.method === "GET") {
				const note = await getNote(user.id, GOALS_KEY);
				return apiSuccess(res, {
					goals: parseNote(note, {}),
					updatedAt: note?.updated_at ?? null,
				});
			}
			if (req.method === "POST") {
				const parsed = GoalsSchema.safeParse(req.body?.goals ?? req.body);
				if (!parsed.success) return apiError(res, 400, parsed.error.issues[0]?.message ?? "Invalid goals");
				return apiSuccess(res, await upsertNote(user.id, GOALS_KEY, parsed.data));
			}
			return methodNotAllowed(res);
		}

		if (action === "policy") {
			if (req.method === "GET") {
				const note = await getNote(user.id, POLICY_KEY);
				return apiSuccess(res, {
					policy: PolicySchema.parse({ ...defaultPolicy(), ...parseNote(note, {}) }),
					updatedAt: note?.updated_at ?? null,
				});
			}
			if (req.method === "POST" || req.method === "PATCH") {
				const current = parseNote(await getNote(user.id, POLICY_KEY), {});
				const candidate = req.method === "PATCH"
					? { ...current, ...(req.body?.policy ?? req.body) }
					: (req.body?.policy ?? req.body);
				const parsed = PolicySchema.safeParse(candidate);
				if (!parsed.success) return apiError(res, 400, parsed.error.issues[0]?.message ?? "Invalid policy");
				return apiSuccess(res, await upsertNote(user.id, POLICY_KEY, parsed.data));
			}
			return methodNotAllowed(res);
		}

		if (action === "risk" && req.method === "GET") {
			const [policyNote, approvals, actions] = await Promise.all([
				getNote(user.id, POLICY_KEY),
				pendingApprovals(user.id, 20),
				latestAgentActions(user.id, 20),
			]);
			const policy = PolicySchema.parse({ ...defaultPolicy(), ...parseNote(policyNote, {}) });
			return apiSuccess(res, {
				policy,
				highRiskActionsLocked: policy.highRiskActionsLocked,
				enforceApprovalBinding: policy.enforceApprovalBinding,
				pendingApprovals: approvals,
				recentAgentActions: actions,
			});
		}

		if (action === "costs" && req.method === "GET") {
			const [policyNote, costs] = await Promise.all([
				getNote(user.id, POLICY_KEY),
				aiCosts(user.id, Math.min(8, days)),
			]);
			const policy = PolicySchema.parse({ ...defaultPolicy(), ...parseNote(policyNote, {}) });
			const latestDailyCost = costs.daily.at(-1)?.userCostUsd ?? 0;
			return apiSuccess(res, {
				aiCosts: costs,
				budgetLimits: policy.budgetLimits,
				overBudget:
					typeof policy.budgetLimits.dailyAiSpendUsd === "number" &&
					latestDailyCost >= policy.budgetLimits.dailyAiSpendUsd,
			});
		}

		if (action === "runbook") {
			if (req.method !== "POST") return methodNotAllowed(res);
			const kind = String(req.body?.kind ?? "daily_ops");
			const brief = await buildBrief(user.id, Math.min(90, days));
			const runbook = {
				kind,
				generatedAt: new Date().toISOString(),
				brief,
				steps: [
					"Review risk state, pending approvals, and recent failed agent actions.",
					"Review account counts, AI costs, and current business goals.",
					"Prepare proposed actions as approval requests before any external write.",
				],
			};
			if (req.body?.saveRunbookState === true) {
				await upsertNote(user.id, RUNBOOK_KEY, { lastRun: runbook });
			}
			return apiSuccess(res, { runbook });
		}

		return apiError(res, 400, `Unsupported business-ops action: ${action}`);
	} catch (error) {
		return apiError(res, 500, "Business ops request failed", {
			details: error instanceof Error ? error.message : String(error),
		});
	}
});
