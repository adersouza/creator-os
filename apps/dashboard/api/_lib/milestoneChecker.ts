import { createNotification } from "./createNotification.js";
import { logger } from "./logger.js";
import type { Platform } from "./platform.js";
import { getSupabase } from "./supabase.js";

const MILESTONES = [
	100, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000, 500000, 1000000,
];

export async function checkMilestones(
	accountId: string,
	platform: Platform,
	currentFollowers: number,
	lastMilestone: number,
	userId: string,
): Promise<void> {
	const nextMilestone = MILESTONES.find(
		(m) => m > lastMilestone && currentFollowers >= m,
	);
	if (!nextMilestone) return;

	// Find the highest milestone reached
	let highestReached = nextMilestone;
	for (const m of MILESTONES) {
		if (m > lastMilestone && currentFollowers >= m) {
			highestReached = m;
		}
	}

	try {
		const table = platform === "instagram" ? "instagram_accounts" : "accounts";

		// #605: Dedup — check if this milestone was already celebrated
		// biome-ignore lint/suspicious/noExplicitAny: dynamic table name prevents static typing
		const { data: existing } = await (getSupabase().from(table) as any)
			.select("last_milestone_celebrated")
			.eq("id", accountId)
			.maybeSingle();

		if (existing?.last_milestone_celebrated >= highestReached) {
			return; // Already celebrated this milestone
		}

		// biome-ignore lint/suspicious/noExplicitAny: dynamic table name prevents static typing
		await (getSupabase().from(table) as any)
			.update({ last_milestone_celebrated: highestReached })
			.eq("id", accountId);

		await createNotification({
			userId,
			type: "milestone",
			title: `🎉 You hit ${highestReached.toLocaleString()} followers!`,
			message: "Here's your growth journey so far.",
			data: { milestone: highestReached, platform, accountId },
		});

		logger.info("Milestone celebrated", {
			accountId,
			platform,
			milestone: highestReached,
		});
	} catch (err) {
		logger.warn("Milestone check failed", { accountId, error: String(err) });
	}
}
