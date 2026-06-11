// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { getSupabaseAny } from "../../supabase.js";

const DAY_MS = 24 * 60 * 60 * 1000;

interface AccountRow {
	id: string;
	username: string | null;
	display_name: string | null;
	group_id: string | null;
}

interface HealthRow {
	account_id: string;
	health_tier: "good" | "warn" | "critical" | null;
	days_of_content: number | null;
	posts_next_7d: number | null;
	empty_days_next_7d: number | null;
	last_published_at: string | null;
}

function startOfTodayIso(): string {
	const d = new Date();
	d.setHours(0, 0, 0, 0);
	return d.toISOString();
}

export async function handlePortfolio(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

	const supabase = getSupabaseAny();
	const start = new Date(startOfTodayIso());
	const end = new Date(start.getTime() + 7 * DAY_MS);

	const [{ data: accounts, error: accountsError }, { data: health, error: healthError }, { data: posts, error: postsError }] =
		await Promise.all([
			supabase
				.from("accounts")
				.select("id, username, display_name, group_id")
				.eq("user_id", userId)
				.eq("is_active", true)
				.order("username", { ascending: true }),
			supabase.from("portfolio_account_health").select("*").eq("user_id", userId),
			supabase
				.from("posts")
				.select("id, account_id, scheduled_for")
				.eq("user_id", userId)
				.in("status", ["scheduled", "queued", "publishing"])
				.gte("scheduled_for", start.toISOString())
				.lt("scheduled_for", end.toISOString()),
		]);

	if (accountsError || healthError || postsError) {
		return apiError(res, 500, "Failed to load portfolio matrix", {
			details: String(accountsError?.message || healthError?.message || postsError?.message || ""),
		});
	}

	const accountRows = (accounts ?? []) as AccountRow[];
	const healthRows = (health ?? []) as HealthRow[];
	const healthByAccount = new Map(healthRows.map((row) => [row.account_id, row]));
	const postsByAccountDay = new Map<string, number[]>();
	for (const account of accountRows) postsByAccountDay.set(account.id, [0, 0, 0, 0, 0, 0, 0]);
	for (const post of posts ?? []) {
		if (!post.account_id || !post.scheduled_for) continue;
		const day = Math.floor((new Date(post.scheduled_for).getTime() - start.getTime()) / DAY_MS);
		if (day < 0 || day > 6) continue;
		const row = postsByAccountDay.get(post.account_id) ?? [0, 0, 0, 0, 0, 0, 0];
		row[day]! += 1;
		postsByAccountDay.set(post.account_id, row);
	}

	const rows = accountRows.map((account) => {
		const density = postsByAccountDay.get(account.id) ?? [0, 0, 0, 0, 0, 0, 0];
		const fallbackTier = density.some((count) => count === 0)
			? density.every((count) => count === 0)
				? "critical"
				: "warn"
			: "good";
		const h = healthByAccount.get(account.id);
		const fallbackName = "Unnamed account";
		return {
			accountId: account.id,
			handle: account.username ? `@${account.username}` : fallbackName,
			displayName: account.display_name || account.username || fallbackName,
			groupId: account.group_id ?? null,
			healthTier: h?.health_tier ?? fallbackTier,
			daysOfContent: h?.days_of_content ?? Math.round((density.reduce((sum, count) => sum + count, 0) / 3) * 10) / 10,
			postsNext7d: h?.posts_next_7d ?? density.reduce((sum, count) => sum + count, 0),
			emptyDaysNext7d: h?.empty_days_next_7d ?? density.filter((count) => count === 0).length,
			lastPublishedAt: h?.last_published_at ?? null,
			density,
		};
	});

	return apiSuccess(res, {
		days: Array.from({ length: 7 }, (_, i) => new Date(start.getTime() + i * DAY_MS).toISOString()),
		rows,
	});
}
