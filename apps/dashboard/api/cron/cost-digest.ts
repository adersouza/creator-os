import type { VercelRequest, VercelResponse } from "@vercel/node";
import { alertCronFailure } from "../_lib/alerting.js";
import { verifyCronAuth } from "../_lib/apiResponse.js";
import { trackCronRun, withCronLock } from "../_lib/cronUtils.js";
import { logger } from "../_lib/logger.js";
import { getRedis } from "../_lib/redis.js";
import { getSupabase, getSupabaseAny } from "../_lib/supabase.js";

export const config = {
	maxDuration: 120,
};

type EndpointCost = {
	endpoint: string;
	costUsd: number;
	calls: number;
};

type TopUserCost = {
	userId: string;
	label: string;
	costUsd: number;
};

type DailyCostDigest = {
	date: string;
	previousDate: string;
	totalCostUsd: number;
	previousCostUsd: number;
	dodRatio: number | null;
	endpoints: EndpointCost[];
	topUsers: TopUserCost[];
	modelCalls: Record<string, number>;
	alerts: string[];
};

function dateKey(offsetDays: number): string {
	const date = new Date(Date.now() - offsetDays * 24 * 60 * 60 * 1000);
	return date.toISOString().slice(0, 10);
}

async function readMicroCost(key: string): Promise<number> {
	const value = await getRedis().get<number | string | null>(key);
	return typeof value === "number" ? value : Number(value ?? 0);
}

async function scanCostKeys(pattern: string): Promise<Record<string, number>> {
	const redis = getRedis();
	const totals: Record<string, number> = {};
	let cursor = 0;
	do {
		const [nextCursor, keys] = await redis.scan(cursor, {
			match: pattern,
			count: 100,
		});
		cursor =
			typeof nextCursor === "number"
				? nextCursor
				: parseInt(nextCursor as string, 10);
		if (keys.length === 0) continue;
		const values = await redis.mget<(number | string | null)[]>(...keys);
		keys.forEach((key: string, index: number) => {
			const value = values[index];
			totals[key] =
				(totals[key] ?? 0) +
				(typeof value === "number" ? value : Number(value ?? 0));
		});
	} while (cursor !== 0);
	return totals;
}

async function readDailyUserCosts(date: string): Promise<Record<string, number>> {
	const keys = await scanCostKeys(`ai_cost:*:${date}`);
	const costs: Record<string, number> = {};
	for (const [key, value] of Object.entries(keys)) {
		const [, userId] = key.split(":");
		if (!userId || userId === "platform") continue;
		costs[userId] = (costs[userId] ?? 0) + value;
	}
	return costs;
}

async function readEndpointCosts(date: string): Promise<EndpointCost[]> {
	const keys = await scanCostKeys(`ai_cost_endpoint:*:${date}`);
	return Object.entries(keys)
		.map(([key, value]) => {
			const [, endpoint = "unknown"] = key.split(":");
			return {
				endpoint,
				costUsd: value / 1_000_000,
				calls: 1,
			};
		})
		.sort((a, b) => b.costUsd - a.costUsd);
}

async function readModelCalls(date: string): Promise<Record<string, number>> {
	const classes = ["flash", "pro", "sonnet", "haiku", "openai", "grok"];
	const entries = await Promise.all(
		classes.map(async (modelClass) => [
			modelClass,
			Number((await getRedis().get(`ai_model_calls:${modelClass}:${date}`)) ?? 0),
		] as const),
	);
	return Object.fromEntries(entries.filter(([, calls]) => calls > 0));
}

async function enrichTopUsers(
	userCosts: Record<string, number>,
): Promise<TopUserCost[]> {
	const top = Object.entries(userCosts)
		.sort((a, b) => b[1] - a[1])
		.slice(0, 5);
	if (top.length === 0) return [];

	const ids = top.map(([userId]) => userId);
	const { data } = await getSupabaseAny()
		.from("profiles")
		.select("id, email, subscription_tier")
		.in("id", ids);
	const profiles = new Map(
		(data ?? []).map(
			(row: { id: string; email?: string | null; subscription_tier?: string | null }) => [
				row.id,
				row,
			],
		),
	);

	return top.map(([userId, microCost]) => {
		const profile = profiles.get(userId);
		const email = profile?.email ?? `${userId.slice(0, 8)}...`;
		const tier = profile?.subscription_tier ? ` (${profile.subscription_tier})` : "";
		return {
			userId,
			label: `${email}${tier}`,
			costUsd: microCost / 1_000_000,
		};
	});
}

async function buildDigest(): Promise<DailyCostDigest> {
	const date = dateKey(0);
	const previousDate = dateKey(1);
	const [platformMicro, previousPlatformMicro, userCosts, endpoints, modelCalls] =
		await Promise.all([
			readMicroCost(`ai_cost:platform:${date}`),
			readMicroCost(`ai_cost:platform:${previousDate}`),
			readDailyUserCosts(date),
			readEndpointCosts(date),
			readModelCalls(date),
		]);

	const totalCostUsd = platformMicro / 1_000_000;
	const previousCostUsd = previousPlatformMicro / 1_000_000;
	const dodRatio = previousCostUsd > 0 ? totalCostUsd / previousCostUsd : null;
	const topUsers = await enrichTopUsers(userCosts);
	const alerts: string[] = [];
	const dailyLimit = Number(process.env.AI_DAILY_SPEND_LIMIT_USD || "2");
	const topUserPct =
		totalCostUsd > 0 && topUsers[0] ? topUsers[0].costUsd / totalCostUsd : 0;

	if (dodRatio !== null && dodRatio >= 2) {
		alerts.push(
			`DoD spike: $${totalCostUsd.toFixed(4)} vs $${previousCostUsd.toFixed(4)} (${dodRatio.toFixed(1)}x).`,
		);
	}
	if (topUserPct >= 0.8 && topUsers[0]) {
		alerts.push(
			`Single-user concentration: ${topUsers[0].label} is ${(topUserPct * 100).toFixed(0)}% of fleet AI spend.`,
		);
	}
	if (topUsers[0] && topUsers[0].costUsd >= 1) {
		alerts.push(
			`Single-user daily spend: ${topUsers[0].label} reached $${topUsers[0].costUsd.toFixed(4)}.`,
		);
	}
	if (dailyLimit > 0 && totalCostUsd >= dailyLimit * 0.75) {
		alerts.push(
			`Approaching daily AI cap: $${totalCostUsd.toFixed(4)} / $${dailyLimit.toFixed(2)}.`,
		);
	}

	return {
		date,
		previousDate,
		totalCostUsd,
		previousCostUsd,
		dodRatio,
		endpoints,
		topUsers,
		modelCalls,
		alerts,
	};
}

async function sendDiscordDigest(digest: DailyCostDigest): Promise<void> {
	const webhookUrl = process.env.DISCORD_ALERT_WEBHOOK_URL;
	if (!webhookUrl) {
		logger.warn("[cost-digest] DISCORD_ALERT_WEBHOOK_URL not set, skipping");
		return;
	}

	const fields: { name: string; value: string; inline?: boolean }[] = [
		{
			name: "Spend",
			value: `$${digest.totalCostUsd.toFixed(4)} today\n$${digest.previousCostUsd.toFixed(4)} yesterday`,
			inline: true,
		},
		{
			name: "DoD",
			value: digest.dodRatio ? `${digest.dodRatio.toFixed(2)}x` : "n/a",
			inline: true,
		},
	];

	if (Object.keys(digest.modelCalls).length > 0) {
		fields.push({
			name: "Model Calls",
			value: Object.entries(digest.modelCalls)
				.map(([modelClass, calls]) => `\`${modelClass}\`: ${calls}`)
				.join("\n"),
			inline: true,
		});
	}

	if (digest.endpoints.length > 0) {
		fields.push({
			name: "Top Endpoints",
			value: digest.endpoints
				.slice(0, 8)
				.map((item) => `\`${item.endpoint}\`: $${item.costUsd.toFixed(4)}`)
				.join("\n"),
		});
	}

	if (digest.topUsers.length > 0) {
		fields.push({
			name: "Top Users",
			value: digest.topUsers
				.map((user, index) => `${index + 1}. ${user.label}: $${user.costUsd.toFixed(4)}`)
				.join("\n"),
		});
	}

	if (digest.alerts.length > 0) {
		fields.push({
			name: "Alerts",
			value: digest.alerts.map((alert) => `- ${alert}`).join("\n"),
		});
	}

	const response = await fetch(webhookUrl, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({
			embeds: [
				{
					title: `Daily AI Cost Digest — ${digest.date}`,
					color: digest.alerts.length > 0 ? 0xf39c12 : 0x3498db,
					fields,
					footer: { text: "Juno33 AI Cost Tracker" },
					timestamp: new Date().toISOString(),
				},
			],
		}),
		signal: AbortSignal.timeout(15000),
	});

	if (!response.ok) {
		throw new Error(
			`Discord webhook failed: ${response.status} ${await response.text()}`,
		);
	}
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "GET" && req.method !== "POST") {
		return res.status(405).json({ error: "Method not allowed" });
	}
	if (!verifyCronAuth(req, res)) return;

	try {
		const lockResult = await withCronLock(getSupabase(), "cost-digest", () =>
			trackCronRun(getSupabase(), "cost-digest", async () => {
				const digest = await buildDigest();
				await sendDiscordDigest(digest);
				return {
					itemsProcessed: 1,
					metadata: {
						totalCostUsd: digest.totalCostUsd,
						alertCount: digest.alerts.length,
					},
				};
			}),
		);
		if (lockResult.skipped) return res.status(200).json({ skipped: true });
		return res.status(200).json(lockResult.result);
	} catch (error) {
		const message = error instanceof Error ? error.message : String(error);
		logger.error("[cost-digest] failed", { error: message });
		alertCronFailure("cost-digest", message);
		return res.status(500).json({ error: message });
	}
}
