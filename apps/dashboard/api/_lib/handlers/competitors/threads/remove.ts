/**
 * Handlers:
 *   POST /api/competitors?action=remove       — Remove a single competitor
 *   POST /api/competitors?action=bulk-remove   — Remove multiple competitors
 *
 * Both validate ownership before deleting.
 * Cascade: competitor_top_posts + competitor_snapshots have FK ON DELETE CASCADE.
 */

import { apiError, apiSuccess } from "../../../apiResponse.js";
import { logger } from "../../../logger.js";
import { z } from "../../../zodCompat.js";
import { withAuthAndBody } from "../../helpers/withAuthAndBody.js";
import { db, verifyCompetitorOwnership } from "../shared.js";

// ============================================================================
// Single remove: POST /api/competitors?action=remove
// ============================================================================

const RemoveSchema = z.object({
	accountId: z.string(),
	competitorId: z.string(),
});

export const handleRemove = withAuthAndBody(
	RemoveSchema,
	async (user, parsed, _req, res) => {
		const { accountId: _accountId, competitorId } = parsed;

		// Verify ownership — competitors are user-scoped, not account-scoped
		const comp = await verifyCompetitorOwnership(
			res,
			competitorId,
			user.id,
			"id, username",
		);
		if (!comp) return;

		// biome-ignore lint/suspicious/noExplicitAny: Supabase deep type TS2589
		const { error } = await (db() as any)
			.from("competitors")
			.delete()
			.eq("id", competitorId)
			.eq("user_id", user.id);

		if (error) {
			logger.error("Failed to remove competitor", {
				competitorId,
				error: error.message,
			});
			return apiError(res, 500, "Failed to remove competitor");
		}

		logger.info("Competitor removed", {
			competitorId,
			username: comp.username,
			userId: user.id,
		});

		return apiSuccess(res, {
			removed: true,
			competitorId,
			username: comp.username,
		});
	},
);

// ============================================================================
// Bulk remove: POST /api/competitors?action=bulk-remove
// ============================================================================

const MAX_BULK_REMOVE = 100;

const BulkRemoveSchema = z.object({
	accountId: z.string(),
	competitorIds: z.array(z.string()).min(1).max(MAX_BULK_REMOVE),
	dryRun: z.boolean().optional(),
});

interface CompetitorRow {
	id: string;
	username: string | null;
}

export const handleBulkRemove = withAuthAndBody(
	BulkRemoveSchema,
	async (user, parsed, _req, res) => {
		const { accountId, competitorIds, dryRun } = parsed;
		const isDryRun = dryRun !== false; // defaults true

		// Verify all competitorIds belong to the user (competitors are user-scoped)
		// biome-ignore lint/suspicious/noExplicitAny: Supabase deep type TS2589
		const { data: owned } = await (db() as any)
			.from("competitors")
			.select("id, username")
			.eq("user_id", user.id)
			.in("id", competitorIds);

		const ownedMap = new Map<string, string | null>();
		for (const c of (owned ?? []) as CompetitorRow[]) {
			ownedMap.set(c.id, c.username);
		}

		// Split into found vs not-found
		const toRemove: Array<{ competitorId: string; username: string | null }> =
			[];
		const failed: Array<{ competitorId: string; reason: string }> = [];

		for (const id of competitorIds) {
			if (ownedMap.has(id)) {
				toRemove.push({ competitorId: id, username: ownedMap.get(id) ?? null });
			} else {
				failed.push({ competitorId: id, reason: "not found" });
			}
		}

		if (isDryRun) {
			return apiSuccess(res, {
				dryRun: true,
				wouldRemove: toRemove,
				wouldFail: failed,
				totalRequested: competitorIds.length,
				removeCount: toRemove.length,
				failedCount: failed.length,
			});
		}

		// Execute removals
		const removed: Array<{ competitorId: string; username: string | null }> =
			[];

		if (toRemove.length > 0) {
			const idsToDelete = toRemove.map((r) => r.competitorId);
			// biome-ignore lint/suspicious/noExplicitAny: Supabase deep type TS2589
			const { error } = await (db() as any)
				.from("competitors")
				.delete()
				.eq("user_id", user.id)
				.in("id", idsToDelete);

			if (error) {
				logger.error("Bulk competitor remove failed", {
					error: error.message,
					count: idsToDelete.length,
				});
				// All removals failed
				for (const r of toRemove) {
					failed.push({
						competitorId: r.competitorId,
						reason: `Delete failed: ${error.message}`,
					});
				}
			} else {
				removed.push(...toRemove);
			}
		}

		logger.info("Bulk competitor remove complete", {
			userId: user.id,
			accountId,
			removedCount: removed.length,
			failedCount: failed.length,
		});

		return apiSuccess(res, {
			dryRun: false,
			removed,
			failed,
			totalRequested: competitorIds.length,
			removedCount: removed.length,
			failedCount: failed.length,
		});
	},
);
