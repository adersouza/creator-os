/**
 * Phase 10: DLQ Sweep
 * Auto-revives dead-lettered webhook events that have not exhausted their
 * lifetime revival budget (max 3 times). Only events in the DLQ for at least
 * 1 hour are eligible.
 */

import type { Logger, PhaseMetadata, TypedSupabaseClient } from "./shared.js";

export async function phaseDlqSweep(
	supabase: TypedSupabaseClient,
	logger: Logger,
): Promise<PhaseMetadata["dlqSweep"]> {
	const oneHourAgo = new Date(Date.now() - 3_600_000).toISOString();
	const MAX_LIFETIME_RETRIES = 3;

	let threadsRevived = 0;
	let igRevived = 0;

	for (const table of [
		"threads_webhook_events",
		"ig_webhook_events",
	] as const) {
		const { data: eligible, error: fetchError } = await supabase
			.from(table)
			.select("id, lifetime_retry_count")
			.eq("dead_letter", true)
			.lt("lifetime_retry_count", MAX_LIFETIME_RETRIES)
			.lt("dead_letter_at", oneHourAgo)
			.limit(50);

		if (fetchError) {
			logger.error("[daily-maintenance] DLQ sweep fetch failed", {
				table,
				error: fetchError.message,
			});
			continue;
		}

		if (!eligible || eligible.length === 0) continue;

		// Group by current lifetime_retry_count to minimise update round-trips.
		const groups = new Map<number, string[]>();
		// Vercel TS 5.9: Supabase select type needs double-cast
		for (const row of eligible as unknown as Array<{
			id: string;
			lifetime_retry_count: number;
		}>) {
			const count = row.lifetime_retry_count ?? 0;
			if (!groups.has(count)) groups.set(count, []);
			groups.get(count)?.push(row.id);
		}

		for (const [count, ids] of groups) {
			const { error: updateError } = await supabase
				.from(table)
				.update({
					dead_letter: false,
					dead_letter_at: null,
					dead_letter_reason: null,
					processed: false,
					processed_at: null,
					retry_count: 0,
					next_retry_at: null,
					error: null,
					lifetime_retry_count: count + 1,
				})
				.in("id", ids);

			if (updateError) {
				logger.error("[daily-maintenance] DLQ sweep update failed", {
					table,
					error: updateError.message,
				});
				continue;
			}

			if (table === "threads_webhook_events") {
				threadsRevived += ids.length;
			} else {
				igRevived += ids.length;
			}
		}

		logger.info("[daily-maintenance] DLQ sweep complete", {
			table,
			revived: table === "threads_webhook_events" ? threadsRevived : igRevived,
		});
	}

	return { threadsRevived, igRevived };
}
