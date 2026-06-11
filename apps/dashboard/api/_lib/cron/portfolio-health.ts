// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { getSupabaseAny } from "../supabase.js";
import { logger } from "../logger.js";

const DAY_MS = 24 * 60 * 60 * 1000;

interface AccountRow {
	id: string;
	user_id: string;
	group_id: string | null;
}

interface ScheduledPostRow {
	account_id: string | null;
	scheduled_for: string | null;
}

interface PublishedPostRow {
	account_id: string | null;
	published_at: string | null;
}

export async function computePortfolioAccountHealth(): Promise<number> {
	const supabase = getSupabaseAny();
	const start = new Date();
	start.setHours(0, 0, 0, 0);
	const end = new Date(start.getTime() + 7 * DAY_MS);

	const { data: accounts, error: accountsError } = await supabase
		.from("accounts")
		.select("id, user_id, group_id")
		.eq("is_active", true);

	if (accountsError) throw accountsError;
	if (!accounts || accounts.length === 0) return 0;

	const accountRows = accounts as AccountRow[];
	const userIds = Array.from(new Set(accountRows.map((account) => account.user_id).filter(Boolean)));
	const accountIds = accountRows.map((account) => account.id);

	const [{ data: scheduled, error: scheduledError }, { data: published, error: publishedError }] =
		await Promise.all([
			supabase
				.from("posts")
				.select("account_id, scheduled_for")
				.in("account_id", accountIds)
				.in("status", ["scheduled", "queued", "publishing"])
				.gte("scheduled_for", start.toISOString())
				.lt("scheduled_for", end.toISOString()),
			supabase
				.from("posts")
				.select("account_id, published_at")
				.in("user_id", userIds)
				.eq("status", "published")
				.not("published_at", "is", null)
				.order("published_at", { ascending: false })
				.limit(5000),
		]);

	if (scheduledError) throw scheduledError;
	if (publishedError) throw publishedError;

	const density = new Map<string, number[]>();
	for (const account of accountRows) density.set(account.id, [0, 0, 0, 0, 0, 0, 0]);
	for (const post of (scheduled ?? []) as ScheduledPostRow[]) {
		if (!post.account_id || !post.scheduled_for) continue;
		const day = Math.floor((new Date(post.scheduled_for).getTime() - start.getTime()) / DAY_MS);
		if (day < 0 || day > 6) continue;
		const row = density.get(post.account_id) ?? [0, 0, 0, 0, 0, 0, 0];
		row[day]! += 1;
		density.set(post.account_id, row);
	}

	const lastPublished = new Map<string, string>();
	for (const post of (published ?? []) as PublishedPostRow[]) {
		if (post.account_id && post.published_at && !lastPublished.has(post.account_id)) {
			lastPublished.set(post.account_id, post.published_at);
		}
	}

	const rows = accountRows.map((account) => {
		const row = density.get(account.id) ?? [0, 0, 0, 0, 0, 0, 0];
		const postsNext7d = row.reduce((sum, count) => sum + count, 0);
		const emptyDays = row.filter((count) => count === 0).length;
		const daysOfContent = Math.floor(postsNext7d / 3);
		const healthTier = emptyDays >= 5 || postsNext7d < 3 ? "critical" : emptyDays >= 2 || postsNext7d < 7 ? "warn" : "good";
		return {
			account_id: account.id,
			user_id: account.user_id,
			account_group_id: account.group_id ?? null,
			days_of_content: daysOfContent,
			health_tier: healthTier,
			posts_next_7d: postsNext7d,
			empty_days_next_7d: emptyDays,
			last_published_at: lastPublished.get(account.id) ?? null,
			computed_at: new Date().toISOString(),
		};
	});

	const { error } = await supabase
		.from("portfolio_account_health")
		.upsert(rows, { onConflict: "account_id" });

	if (error) {
		logger.error("[portfolio-health] upsert failed", { error: error.message });
		throw error;
	}

	return rows.length;
}
