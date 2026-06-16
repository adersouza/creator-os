function stringValue(value: unknown): string | null {
	return typeof value === "string" && value.trim() ? value.trim() : null;
}

function recordValue(value: unknown): Record<string, unknown> | null {
	return value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: null;
}

export function getAutoposterRejectionReason(row: {
	rejection_reason?: string | null | undefined;
	last_error?: string | null | undefined;
	metadata?: Record<string, unknown> | null | undefined;
}): string {
	const metadata = recordValue(row.metadata);
	const qualityGate = recordValue(metadata?.quality_gate);
	const approval = recordValue(metadata?.approval);
	const dna = recordValue(metadata?.dna);
	const dnaReasons = Array.isArray(dna?.reasons) ? dna.reasons : [];
	const firstDnaReason = dnaReasons.find(
		(reason): reason is string => typeof reason === "string" && reason.trim().length > 0,
	);

	return (
		stringValue(row.rejection_reason) ||
		stringValue(row.last_error) ||
		stringValue(metadata?.quality_gate_reason) ||
		stringValue(qualityGate?.laneReason) ||
		stringValue(qualityGate?.reason) ||
		stringValue(approval?.reason) ||
		(firstDnaReason ? `dna:${firstDnaReason}` : null) ||
		"unknown"
	);
}
