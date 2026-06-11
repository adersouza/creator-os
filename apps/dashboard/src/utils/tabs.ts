/**
 * Returns activeTab if it exists in visibleTabs, otherwise the fallback.
 * Use when tabs are filtered by platform and the current tab may disappear.
 */
export function resolveActiveTab<T extends { id: string }>(
	visibleTabs: T[],
	activeTab: string,
	fallback: string,
): string {
	return visibleTabs.some((t) => t.id === activeTab) ? activeTab : fallback;
}
