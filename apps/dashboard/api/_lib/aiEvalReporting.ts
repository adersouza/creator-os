export type AIEvalSnapshotReportRow = {
	id?: unknown;
	suite_name?: unknown;
	case_id?: unknown;
	category?: unknown;
	provider?: unknown;
	model?: unknown;
	regression_score?: unknown;
	passed?: unknown;
	failures?: unknown;
	captured_at?: unknown;
};

export type AIEvalTrendPoint = {
	day: string;
	suiteName: string;
	surface: string;
	total: number;
	passed: number;
	failed: number;
	passRate: number;
	avgRegressionScore: number | null;
};

export type AIEvalSuiteRow = {
	suiteName: string;
	surface: string;
	total: number;
	passed: number;
	failed: number;
	passRate: number;
	avgRegressionScore: number | null;
	lastCapturedAt: string | null;
};

export type AIEvalLatestFailure = {
	id: unknown;
	suiteName: unknown;
	caseId: unknown;
	category: unknown;
	model: unknown;
	failures: unknown[];
	capturedAt: unknown;
};

export type AIEvalThresholdResult = {
	passed: boolean;
	failures: string[];
};

const SUITE_PASS_RATE_THRESHOLDS: Record<string, number> = {
	"operator-ai-golden": 100,
	golden: 100,
};

export function buildAIEvalReport(snapshotRows: AIEvalSnapshotReportRow[]) {
	const total = snapshotRows.length;
	const failed = snapshotRows.filter((row) => row.passed === false).length;
	const passed = total - failed;
	const scored = snapshotRows
		.map((row) => Number(row.regression_score))
		.filter((score) => Number.isFinite(score));
	const avgRegressionScore = scored.length
		? round2(scored.reduce((sum, score) => sum + score, 0) / scored.length)
		: null;
	const latestFailures = snapshotRows
		.filter((row) => row.passed === false)
		.slice(0, 5)
		.map((row) => ({
			id: row.id,
			suiteName: row.suite_name,
			caseId: row.case_id,
			category: row.category,
			model: row.model,
			failures: Array.isArray(row.failures) ? row.failures.slice(0, 3) : [],
			capturedAt: row.captured_at,
		}));

	const trend = aggregateEvalTrend(snapshotRows);
	const suites = aggregateEvalSuites(snapshotRows);
	const thresholds = evaluateAIEvalThresholds(suites);

	return {
		total,
		passed,
		failed,
		passRate: total > 0 ? Math.round((passed / total) * 100) : 100,
		avgRegressionScore,
		latestFailures,
		trend,
		suites,
		thresholds,
	};
}

export function evaluateAIEvalThresholds(
	suites: AIEvalSuiteRow[],
): AIEvalThresholdResult {
	const failures = suites.flatMap((suite) => {
		const threshold = thresholdForSuite(suite.suiteName);
		if (suite.passRate >= threshold) return [];
		return [
			`${suite.suiteName} pass rate ${suite.passRate}% is below ${threshold}% threshold`,
		];
	});
	return { passed: failures.length === 0, failures };
}

function aggregateEvalTrend(rows: AIEvalSnapshotReportRow[]): AIEvalTrendPoint[] {
	const groups = new Map<string, AIEvalSnapshotReportRow[]>();
	for (const row of rows) {
		const day = dayKey(row.captured_at);
		if (!day) continue;
		const suiteName = String(row.suite_name || "unknown");
		const surface = surfaceFromRow(row);
		const key = `${day}\u0000${suiteName}\u0000${surface}`;
		groups.set(key, [...(groups.get(key) ?? []), row]);
	}
	return [...groups.entries()]
		.map(([key, groupRows]) => {
			const [day = "unknown", suiteName = "unknown", surface = "unknown"] = key.split("\u0000");
			return buildAggregate({ day, suiteName, surface }, groupRows);
		})
		.sort((a, b) =>
			a.day === b.day
				? `${a.suiteName}:${a.surface}`.localeCompare(`${b.suiteName}:${b.surface}`)
				: a.day.localeCompare(b.day),
		);
}

function aggregateEvalSuites(rows: AIEvalSnapshotReportRow[]): AIEvalSuiteRow[] {
	const groups = new Map<string, AIEvalSnapshotReportRow[]>();
	for (const row of rows) {
		const suiteName = String(row.suite_name || "unknown");
		const surface = surfaceFromRow(row);
		const key = `${suiteName}\u0000${surface}`;
		groups.set(key, [...(groups.get(key) ?? []), row]);
	}
	return [...groups.entries()]
		.map(([key, groupRows]) => {
			const [suiteName = "unknown", surface = "unknown"] = key.split("\u0000");
			const aggregate = buildAggregate({ suiteName, surface }, groupRows);
			const capturedAtValues = groupRows
				.map((row) => String(row.captured_at || ""))
				.filter(Boolean)
				.sort();
			const lastCapturedAt =
				capturedAtValues.length > 0 ? (capturedAtValues[capturedAtValues.length - 1] ?? null) : null;
			return { ...aggregate, lastCapturedAt: lastCapturedAt ?? null };
		})
		.sort((a, b) => a.suiteName.localeCompare(b.suiteName) || a.surface.localeCompare(b.surface));
}

function buildAggregate(
	base: { day: string; suiteName: string; surface: string },
	rows: AIEvalSnapshotReportRow[],
): AIEvalTrendPoint;
function buildAggregate(
	base: { suiteName: string; surface: string },
	rows: AIEvalSnapshotReportRow[],
): Omit<AIEvalSuiteRow, "lastCapturedAt">;
function buildAggregate(
	base: { day?: string; suiteName: string; surface: string },
	rows: AIEvalSnapshotReportRow[],
) {
	const total = rows.length;
	const failed = rows.filter((row) => row.passed === false).length;
	const passed = total - failed;
	const scored = rows
		.map((row) => Number(row.regression_score))
		.filter((score) => Number.isFinite(score));
	return {
		...base,
		total,
		passed,
		failed,
		passRate: total > 0 ? Math.round((passed / total) * 100) : 100,
		avgRegressionScore: scored.length
			? round2(scored.reduce((sum, score) => sum + score, 0) / scored.length)
			: null,
	};
}

function surfaceFromRow(row: AIEvalSnapshotReportRow): string {
	const suiteName = String(row.suite_name || "");
	if (suiteName.startsWith("live:")) return suiteName.replace(/^live:/, "") || "live";
	return String(row.category || suiteName || "unknown");
}

function thresholdForSuite(suiteName: string): number {
	return SUITE_PASS_RATE_THRESHOLDS[suiteName] ?? (suiteName.includes("golden") ? 100 : 80);
}

function dayKey(value: unknown): string | null {
	const iso = typeof value === "string" ? value : null;
	if (!iso) return null;
	const time = Date.parse(iso);
	if (!Number.isFinite(time)) return null;
	return new Date(time).toISOString().slice(0, 10);
}

function round2(value: number): number {
	return Math.round(value * 100) / 100;
}
