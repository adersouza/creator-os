export function dash(
	value: number | null | undefined,
	formatter?: (n: number) => string,
): string {
	if (value == null || !Number.isFinite(value)) return "—";
	return formatter ? formatter(value) : String(value);
}

export function pct(value: number | null | undefined, decimals = 1): string {
	if (value == null || !Number.isFinite(value)) return "—";
	return `${value.toFixed(decimals)}%`;
}
