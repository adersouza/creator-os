export function hasMinimumEngagerRetentionSignal(data: {
	returningCount: number;
	totalUnique: number;
	periodDays: number;
}): boolean {
	return (
		(data.returningCount >= 3 && data.periodDays >= 7) || data.totalUnique >= 50
	);
}
