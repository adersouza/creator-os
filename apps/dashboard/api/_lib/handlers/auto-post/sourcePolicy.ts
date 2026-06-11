/**
 * Source policy for the autoposter content mix.
 *
 * This is the canonical strategy:
 * - competitors are primarily pattern/cadence context
 * - direct competitor text is only allowed through the narrow microcopy lane
 * - AI generation should fill the majority of queue slots from account identity
 *
 * Older "competitor_copy_ratio" config still exists in storage for backward
 * compatibility, but it is no longer the source of truth for queue-fill mix.
 */

export const DIRECT_COMPETITOR_SHARE = 0.1;
export const AI_REMAINDER_SHARE = 0.9;
export const COMPETITOR_SOURCE_TYPES = new Set([
	"competitor_direct_microcopy",
	"competitor_direct",
	"competitor_copy",
]);

export function getDirectCompetitorSlots(remainingSlots: number): number {
	if (remainingSlots <= 0) return 0;
	return Math.max(
		0,
		Math.min(remainingSlots, Math.ceil(remainingSlots * DIRECT_COMPETITOR_SHARE)),
	);
}

export function isCompetitorSourced(
	sourceType: string | null | undefined,
): boolean {
	return !!sourceType && COMPETITOR_SOURCE_TYPES.has(sourceType);
}

export function getRequiredCompetitorSlots(args: {
	currentQueueSize: number;
	currentCompetitorCount: number;
	slotsAvailable: number;
}): number {
	const { currentQueueSize, currentCompetitorCount, slotsAvailable } = args;
	if (slotsAvailable <= 0) return 0;

	const projectedQueueSize = currentQueueSize + slotsAvailable;
	const desiredCompetitorCount = Math.ceil(
		projectedQueueSize * DIRECT_COMPETITOR_SHARE,
	);

	return Math.max(
		0,
		Math.min(slotsAvailable, desiredCompetitorCount - currentCompetitorCount),
	);
}
