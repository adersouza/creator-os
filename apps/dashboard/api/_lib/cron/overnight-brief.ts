// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Overnight brief orchestrator — generates one brief per active user per night.
 *
 * Invoked by /api/cron/overnight-brief at 1:55 AM UTC. Sits between
 * daily-orchestrator-late (1:30) and analytics-pipeline (2:00) so anomaly data
 * written by the anomaly detector is fresh, and the brief lands before US/EU
 * morning.
 *
 * Flow per user:
 *   1. Skip if daily AI budget exhausted.
 *   2. Gather context — anomaly_alerts from last 24h + post/follower deltas.
 *   3. Meaningful-change gate: skip if zero anomalies AND all deltas <5%.
 *      Dashboard falls back to yesterday's brief or live compute — no regression.
 *   4. Sanitize metrics via sanitizeMetrics() (Meta TOS compliance).
 *   5. Call generateWithProvider(Gemini, structured output) for narrative + moves.
 *   6. Insert into overnight_briefs.
 *
 * Parallelism: batches of 5 to stay under 300s maxDuration across ~hundreds of users.
 * Time-budget check aborts remaining users if we approach deadline.
 */

import { logger } from "../logger.js";
import {
	describeRelativePerformance,
	sanitizeMetrics,
} from "../sanitizeForAI.js";
import type { TypedSupabaseClient } from "../supabase.js";
import { getSupabase } from "../supabase.js";

const JOB_NAME = "overnight-brief";
const WINDOW_HOURS = 24;
const MAX_USERS_PER_RUN = 500;
const BATCH_SIZE = 5;
// Leave 30s headroom inside the 300s cron budget for teardown + Vercel overhead.
const TIME_BUDGET_MS = 270_000;

interface BriefContext {
	userId: string;
	workspaceId: string | null;
	anomalies: Array<{
		account: string;
		metric: "reach" | "engagement" | "follower" | "skip_rate";
		direction: "up" | "down";
		severity: "low" | "medium" | "high" | "critical";
	}>;
	deltas: {
		reachPct: number | null;
		followerNet: number;
		sendsPct: number | null;
	};
	// Raw totals kept in server memory only — passed to describeRelativePerformance()
	// so the LLM sees "above average"/"far below average" language, never numbers.
	totals: {
		nowReach: number;
		priorReach: number;
		nowSends: number;
		priorSends: number;
	};
	topAccount: { username: string; share: number } | null;
	worstAccount: { username: string; changePct: number | null } | null;
	reauthCount: number;
}

interface StructuredBrief {
	narrative: string;
	moves: Array<{
		label: string;
		reason: string;
		route: string;
		severity: "good" | "warn" | "critical";
	}>;
	anomalies: Array<{
		account: string;
		metric: string;
		direction: "up" | "down";
		severity: "low" | "medium" | "high" | "critical";
	}>;
}

const ALLOWED_CRON_ROUTES = new Set<string>([
	"/calendar",
	"/analytics",
	"/accounts",
	"/accounts?status=flagged",
	"/composer",
]);

const BRIEF_SCHEMA = {
	type: "OBJECT",
	properties: {
		narrative: {
			type: "STRING",
			description:
				"Plain-English, ≤280 chars. What moved overnight, in operator voice. No marketing language.",
		},
		moves: {
			type: "ARRAY",
			items: {
				type: "OBJECT",
				properties: {
					label: {
						type: "STRING",
						description:
							"Short action verb + object, ≤28 chars. e.g. 'Reschedule Wed 8pm post'",
					},
					reason: {
						type: "STRING",
						description:
							"One sentence cause, ≤90 chars. e.g. 'reach dropped on @handle last 24h'",
					},
					route: {
						type: "STRING",
						description:
							"One of: /calendar, /analytics, /accounts, /accounts?status=flagged, /composer",
					},
					severity: { type: "STRING", enum: ["good", "warn", "critical"] },
				},
				required: ["label", "reason", "route", "severity"],
			},
		},
		anomalies: {
			type: "ARRAY",
			items: {
				type: "OBJECT",
				properties: {
					account: { type: "STRING" },
					metric: { type: "STRING" },
					direction: { type: "STRING", enum: ["up", "down"] },
					severity: {
						type: "STRING",
						enum: ["low", "medium", "high", "critical"],
					},
				},
				required: ["account", "metric", "direction", "severity"],
			},
		},
	},
	required: ["narrative", "moves", "anomalies"],
};

// ---------------------------------------------------------------------------
// Context gathering
// ---------------------------------------------------------------------------

async function fetchActiveUsers(
	supabase: TypedSupabaseClient,
): Promise<Array<{ id: string }>> {
	// Active user = has at least one is_active account (threads OR instagram)
	// AND at least one post published in the last 7 days (otherwise no movement
	// to narrate). Cap at MAX_USERS_PER_RUN per night; remainder rolls forward.
	const sevenDaysAgo = new Date(
		Date.now() - 7 * 24 * 3600 * 1000,
	).toISOString();
	const supabaseAny = supabase as unknown as {
		rpc: (
			fn: string,
			args: Record<string, unknown>,
		) => Promise<{ data: unknown; error: unknown }>;
		from: (t: string) => {
			select: (c: string) => {
				eq: (
					k: string,
					v: unknown,
				) => {
					gte: (
						k: string,
						v: unknown,
					) => {
						limit: (
							n: number,
						) => Promise<{ data: Array<{ user_id: string }> | null }>;
					};
				};
			};
		};
	};
	const { data } = await supabaseAny
		.from("posts")
		.select("user_id")
		.eq("status", "published")
		.gte("published_at", sevenDaysAgo)
		.limit(MAX_USERS_PER_RUN * 10);
	if (!data) return [];
	// Dedupe client-side (Supabase doesn't expose DISTINCT without RPC)
	const seen = new Set<string>();
	const users: Array<{ id: string }> = [];
	for (const row of data) {
		if (!row.user_id || seen.has(row.user_id)) continue;
		seen.add(row.user_id);
		users.push({ id: row.user_id });
		if (users.length >= MAX_USERS_PER_RUN) break;
	}
	return users;
}

type PostRow = {
	account_id: string | null;
	instagram_account_id: string | null;
	reach_count: number | null;
	ig_reach: number | null;
	shares_count: number | null;
	ig_shares: number | null;
	ig_saved: number | null;
};

const sumField = (
	rows: PostRow[] | null | undefined,
	primary: keyof PostRow,
	fallback: keyof PostRow,
): number =>
	(rows || []).reduce(
		(s, r) => s + (Number(r[primary]) || Number(r[fallback]) || 0),
		0,
	);

function alertTypeToMetric(
	alertType: string,
): BriefContext["anomalies"][number]["metric"] {
	if (alertType === "engagement_drop") return "engagement";
	if (alertType === "follower_drop") return "follower";
	return "reach";
}

function alertTypeToDirection(
	alertType: string,
): BriefContext["anomalies"][number]["direction"] {
	if (/_surge|_spike|_up/.test(alertType)) return "up";
	if (/_drop|_dip|_down|_decline/.test(alertType)) return "down";
	if (/shadowban_suspected|reach_anomaly/.test(alertType)) return "down";
	if (/audience_shift/.test(alertType)) return "up";
	return "up";
}

async function gatherContext(
	supabase: TypedSupabaseClient,
	userId: string,
): Promise<BriefContext> {
	const windowStart = new Date(
		Date.now() - WINDOW_HOURS * 3600 * 1000,
	).toISOString();
	const priorStart = new Date(
		Date.now() - 2 * WINDOW_HOURS * 3600 * 1000,
	).toISOString();
	const cutoffDate = new Date(Date.now() - WINDOW_HOURS * 3600 * 1000)
		.toISOString()
		.split("T")[0]!;

	// biome-ignore lint/suspicious/noExplicitAny: Supabase client surface — sidesteps generated row types for flexible .select() chains
	const db = supabase as unknown as { from: (t: string) => any };

	// Step 1 — fetch user's accounts first. The IDs are needed to scope
	// account_analytics (which otherwise would return all users' rows),
	// plus they carry reauth + workspace + username metadata so we don't
	// need separate queries for those later.
	const { data: accounts } = await db
		.from("accounts")
		.select("id, username, workspace_id, needs_reauth, is_active")
		.eq("user_id", userId);
	type AccountRow = {
		id: string;
		username: string | null;
		workspace_id: string | null;
		needs_reauth: boolean | null;
		is_active: boolean | null;
	};
	const accountRows = (accounts || []) as AccountRow[];
	const accountIds = accountRows.map((a) => a.id);
	const usernameById = new Map<string, string | null>(
		accountRows.map((a) => [a.id, a.username]),
	);
	const reauthCount = accountRows.filter(
		(a) => a.needs_reauth && a.is_active,
	).length;
	const workspaceId =
		accountRows.find((a) => a.is_active)?.workspace_id ?? null;

	// Step 2 — everything else in parallel. Each query is independently
	// scoped by user_id (or by account_id for analytics) so none depend on
	// each other's results.
	const [
		{ data: alerts },
		{ data: posts },
		{ data: priorPosts },
		{ data: analyticsRows },
	] = await Promise.all([
		db
			.from("anomaly_alerts")
			.select("account_id, alert_type, severity")
			.eq("user_id", userId)
			.gte("created_at", windowStart)
			.is("dismissed_at", null),
		db
			.from("posts")
			.select(
				"account_id, instagram_account_id, reach_count, ig_reach, shares_count, ig_shares, ig_saved, platform",
			)
			.eq("user_id", userId)
			.eq("status", "published")
			.gte("published_at", windowStart),
		db
			.from("posts")
			.select("reach_count, ig_reach, shares_count, ig_shares, ig_saved")
			.eq("user_id", userId)
			.eq("status", "published")
			.gte("published_at", priorStart)
			.lt("published_at", windowStart),
		accountIds.length > 0
			? db
					.from("account_analytics")
					.select("follower_growth")
					.in("account_id", accountIds)
					.gte("date", cutoffDate)
			: Promise.resolve({ data: [] }),
	]);

	const anomalies: BriefContext["anomalies"] = (
		(alerts || []) as Array<{
			account_id: string | null;
			alert_type: string;
			severity: string;
		}>
	).map((a) => ({
		account: String(a.account_id || "unknown"),
		metric: alertTypeToMetric(a.alert_type),
		direction: alertTypeToDirection(a.alert_type),
		severity: a.severity as BriefContext["anomalies"][number]["severity"],
	}));

	const postRows = (posts || []) as PostRow[];
	const priorPostRows = (priorPosts || []) as PostRow[];

	const nowReach = sumField(postRows, "reach_count", "ig_reach");
	const priorReach = sumField(priorPostRows, "reach_count", "ig_reach");
	const reachPct =
		priorReach > 0 ? ((nowReach - priorReach) / priorReach) * 100 : null;

	const nowSends =
		sumField(postRows, "shares_count", "ig_shares") +
		sumField(postRows, "ig_saved", "ig_saved");
	const priorSends =
		sumField(priorPostRows, "shares_count", "ig_shares") +
		sumField(priorPostRows, "ig_saved", "ig_saved");
	const sendsPct =
		priorSends > 0 ? ((nowSends - priorSends) / priorSends) * 100 : null;

	const followerNet = (
		(analyticsRows || []) as Array<{ follower_growth: number | null }>
	).reduce((s, r) => s + (r.follower_growth || 0), 0);

	// Rank user's own accounts by reach in the window; username came from
	// the step-1 accounts fetch so no second lookup is needed.
	const reachByAccount = new Map<string, number>();
	for (const p of postRows) {
		const key = p.account_id;
		if (!key) continue;
		reachByAccount.set(
			key,
			(reachByAccount.get(key) || 0) + Number(p.reach_count || p.ig_reach || 0),
		);
	}
	const ranked = Array.from(reachByAccount.entries())
		.map(([id, reach]) => ({
			id,
			reach,
			handle: usernameById.get(id) ?? null,
		}))
		.filter((x) => x.reach > 0 && x.handle)
		.sort((a, b) => b.reach - a.reach);
	const totalReach = ranked.reduce((s, r) => s + r.reach, 0);
	const topAccount =
		ranked.length > 0 && totalReach > 0 && ranked[0]!.handle
			? {
					username: ranked[0]!.handle,
					share: ranked[0]!.reach / totalReach,
				}
			: null;
	const worstAccount =
		ranked.length > 1 && ranked[ranked.length - 1]!.handle
			? {
					username: ranked[ranked.length - 1]!.handle ?? "unknown",
					changePct: reachPct,
				}
			: null;

	return {
		userId,
		workspaceId,
		anomalies,
		deltas: { reachPct, followerNet, sendsPct },
		totals: { nowReach, priorReach, nowSends, priorSends },
		topAccount,
		worstAccount,
		reauthCount,
	};
}

function hasMeaningfulChange(ctx: BriefContext): boolean {
	if (ctx.anomalies.length > 0) return true;
	if (ctx.reauthCount > 0) return true;
	if (Math.abs(ctx.deltas.reachPct ?? 0) >= 5) return true;
	if (Math.abs(ctx.deltas.sendsPct ?? 0) >= 5) return true;
	if (Math.abs(ctx.deltas.followerNet) >= 20) return true;
	return false;
}

// ---------------------------------------------------------------------------
// LLM prompt + call
// ---------------------------------------------------------------------------

function buildPrompt(ctx: BriefContext): string {
	// Meta TOS: never emit exact API metrics to the LLM. All numbers go through
	// sanitizeMetrics() (bucket descriptors) or describeRelativePerformance()
	// (directional language). The Gemini prompt must not carry raw percentages,
	// share fractions, or follower counts.
	const metrics: Record<string, number> = {
		"anomalies detected": ctx.anomalies.length,
		"accounts needing reauth": ctx.reauthCount,
	};

	const reachLine = describeRelativePerformance(
		ctx.totals.nowReach,
		ctx.totals.priorReach,
		"reach",
	);
	const sendsLine = describeRelativePerformance(
		ctx.totals.nowSends,
		ctx.totals.priorSends,
		"sends",
	);
	const followerLine =
		ctx.deltas.followerNet > 0
			? "follower count grew overnight"
			: ctx.deltas.followerNet < 0
				? "follower count shrunk overnight"
				: "follower count held flat overnight";

	const topLine = ctx.topAccount
		? `@${ctx.topAccount.username} carried most of the fleet's reach this window.`
		: "Reach was spread across accounts with no single leader.";
	const worstLine = ctx.worstAccount
		? `@${ctx.worstAccount.username} was the lowest-reach account this window.`
		: "";

	const anomalySummary =
		ctx.anomalies.length > 0
			? `Anomalies: ${ctx.anomalies
					.slice(0, 3)
					.map((a) => `${a.metric} ${a.direction} (${a.severity})`)
					.join("; ")}.`
			: "No anomalies flagged overnight.";

	return [
		"You are the overnight analyst for a social-media operator waking up to coffee.",
		"Task: summarize what moved overnight and surface up to 3 actionable moves.",
		"Voice: direct, operator-to-operator, no marketing language. No exclamation marks.",
		"No preamble. Output MUST conform to the JSON schema.",
		"",
		"Overnight summary:",
		topLine,
		worstLine,
		anomalySummary,
		`${reachLine}; ${sendsLine}; ${followerLine}.`,
		`Signal bucket: ${sanitizeMetrics(metrics)}`,
		ctx.reauthCount > 0
			? `${ctx.reauthCount} account(s) need reconnection before next sync.`
			: "",
		"",
		"Rules:",
		"- narrative ≤280 chars, plain English, past tense where describing overnight movement.",
		"- moves: up to 3, route must be one of /calendar, /analytics, /accounts, /accounts?status=flagged, /composer.",
		"- moves[].severity: 'critical' only for token-expired or sharp reach drop.",
		"- anomalies: copy from the overnight summary, do not invent.",
		"- Never invent or guess numeric values — describe movement in the language above.",
	]
		.filter(Boolean)
		.join("\n");
}

async function generateBrief(
	ctx: BriefContext,
): Promise<StructuredBrief | null> {
	const apiKey = process.env.GEMINI_API_KEY;
	if (!apiKey) {
		logger.warn(`[${JOB_NAME}] GEMINI_API_KEY missing — skipping generation`);
		return null;
	}

	const { generateWithProvider } = await import(
		"../handlers/auto-post/aiProviders.js"
	);

	const prompt = buildPrompt(ctx);
	const raw = await generateWithProvider(prompt, {
		provider: "gemini",
		apiKey,
		model: "gemini-2.5-flash",
		ideaCount: 1,
		useStructuredOutput: true,
		structuredOutputSchema: BRIEF_SCHEMA,
		actionLog: {
			userId: ctx.userId,
			surface: "analytics",
			actionType: "overnight_brief_generate",
			inputText: prompt,
			metadata: { workspaceId: ctx.workspaceId },
		},
	});

	if (!raw) return null;
	try {
		const parsed = JSON.parse(raw) as StructuredBrief;
		if (!parsed.narrative || typeof parsed.narrative !== "string") return null;
		return {
			narrative: parsed.narrative.slice(0, 320),
			moves: Array.isArray(parsed.moves)
				? parsed.moves
						.filter((m) => ALLOWED_CRON_ROUTES.has(m.route))
						.slice(0, 3)
				: [],
			anomalies: Array.isArray(parsed.anomalies)
				? parsed.anomalies.slice(0, 5)
				: [],
		};
	} catch (err) {
		logger.warn(`[${JOB_NAME}] Failed to parse structured brief`, {
			error: err instanceof Error ? err.message : String(err),
			userId: ctx.userId,
		});
		return null;
	}
}

// ---------------------------------------------------------------------------
// Insert
// ---------------------------------------------------------------------------

async function storeBrief(
	supabase: TypedSupabaseClient,
	ctx: BriefContext,
	brief: StructuredBrief,
): Promise<boolean> {
	const windowStart = new Date(Date.now() - WINDOW_HOURS * 3600 * 1000);
	const windowEnd = new Date();

	const supabaseAny = supabase as unknown as {
		from: (t: string) => {
			insert: (row: Record<string, unknown>) => Promise<{ error: unknown }>;
		};
	};

	const { error } = await supabaseAny.from("overnight_briefs").insert({
		user_id: ctx.userId,
		workspace_id: ctx.workspaceId,
		narrative_text: brief.narrative,
		moves_jsonb: brief.moves,
		anomalies_jsonb: brief.anomalies,
		window_start: windowStart.toISOString(),
		window_end: windowEnd.toISOString(),
		ai_provider: "gemini",
		ai_model: "gemini-2.5-flash",
	});

	if (error) {
		logger.error(`[${JOB_NAME}] Insert failed`, {
			userId: ctx.userId,
			error: String(error),
		});
		return false;
	}
	return true;
}

// ---------------------------------------------------------------------------
// Main entrypoint
// ---------------------------------------------------------------------------

export async function processOvernightBriefs(
	startTime: number = Date.now(),
): Promise<{
	usersConsidered: number;
	briefsGenerated: number;
	skippedNoChange: number;
	skippedBudget: number;
	failed: number;
}> {
	const supabase = getSupabase();
	const stats = {
		usersConsidered: 0,
		briefsGenerated: 0,
		skippedNoChange: 0,
		skippedBudget: 0,
		failed: 0,
	};

	// Budget check — if AI spend is exhausted globally, bail early.
	try {
		const { checkDailySpendLimit } = await import("../aiCostTracker.js");
		const { allowed } = await checkDailySpendLimit();
		if (!allowed) {
			logger.warn(`[${JOB_NAME}] Daily spend limit reached — skipping run`);
			return stats;
		}
	} catch {
		/* fail-open */
	}

	const users = await fetchActiveUsers(supabase);
	stats.usersConsidered = users.length;
	logger.info(`[${JOB_NAME}] Processing ${users.length} active users`);

	for (let i = 0; i < users.length; i += BATCH_SIZE) {
		if (Date.now() - startTime > TIME_BUDGET_MS) {
			logger.warn(`[${JOB_NAME}] Time budget exceeded — stopping at ${i}`);
			break;
		}

		const batch = users.slice(i, i + BATCH_SIZE);
		const results = await Promise.allSettled(
			batch.map(async (u) => {
				const ctx = await gatherContext(supabase, u.id);
				if (!hasMeaningfulChange(ctx)) {
					stats.skippedNoChange += 1;
					return "skipped-no-change";
				}
				const brief = await generateBrief(ctx);
				if (!brief) {
					stats.skippedBudget += 1;
					return "skipped-ai";
				}
				const ok = await storeBrief(supabase, ctx, brief);
				if (!ok) {
					stats.failed += 1;
					return "failed-insert";
				}
				stats.briefsGenerated += 1;
				return "ok";
			}),
		);

		for (const r of results) {
			if (r.status === "rejected") {
				stats.failed += 1;
				logger.warn(`[${JOB_NAME}] Batch item rejected`, {
					reason:
						r.reason instanceof Error ? r.reason.message : String(r.reason),
				});
			}
		}
	}

	logger.info(`[${JOB_NAME}] Done`, {
		usersConsidered: stats.usersConsidered,
		briefsGenerated: stats.briefsGenerated,
		skippedNoChange: stats.skippedNoChange,
		skippedBudget: stats.skippedBudget,
		failed: stats.failed,
	});

	return stats;
}
