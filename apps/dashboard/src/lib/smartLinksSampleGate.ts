export const SMART_LINK_TOP_PERFORMER_MIN_CLICKS = 10;

export function qualifiesForSmartLinkTopPerformer(
	clicks: number | null | undefined,
): boolean {
	return (
		typeof clicks === "number" && clicks >= SMART_LINK_TOP_PERFORMER_MIN_CLICKS
	);
}

export function getSmartLinkTopPerformer<T extends { totalClicks: number }>(
	links: T[],
): T | null {
	const ranked = [...links].sort((a, b) => b.totalClicks - a.totalClicks);
	if (ranked.length < 2) return null;
	const top = ranked[0];
	if (!top || !qualifiesForSmartLinkTopPerformer(top.totalClicks)) return null;
	return top;
}

export function getSmartLinkRowTopPerformer<T extends { clickCount: number }>(
	links: T[],
): T | null {
	const ranked = [...links].sort((a, b) => b.clickCount - a.clickCount);
	if (ranked.length < 2) return null;
	const top = ranked[0];
	if (!top || !qualifiesForSmartLinkTopPerformer(top.clickCount)) return null;
	return top;
}

export function smartLinkTopPerformerCaption(): string {
	return `needs ${SMART_LINK_TOP_PERFORMER_MIN_CLICKS}+ clicks`;
}
