import { getSupabaseAny } from "../../supabase.js";

const db = () => getSupabaseAny();

export type ProvenanceDecision =
	| "pass"
	| "manual_allowed"
	| "missing";

export interface ProvenanceCheckResult {
	decision: ProvenanceDecision;
	status: "pass" | "manual_allowed" | "missing";
	reasons: string[];
	fields: {
		sourceType: string | null;
		contentFingerprint: string | null;
		generationId: string | null;
		sourceId: string | null;
		hasQualityGate: boolean;
		hasJudge: boolean;
	};
}

interface QueueProvenanceInput {
	source_type?: string | null | undefined;
	source_competitor_id?: string | null | undefined;
	content_fingerprint?: string | null | undefined;
	publish_fingerprint?: string | null | undefined;
	generation_id?: string | null | undefined;
	source_id?: string | null | undefined;
	metadata?: unknown;
}

function metadataRecord(metadata: unknown): Record<string, unknown> {
	if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
		return {};
	}
	return metadata as Record<string, unknown>;
}

function stringFrom(value: unknown): string | null {
	return typeof value === "string" && value.trim().length > 0
		? value.trim()
		: null;
}

function nestedRecord(
	record: Record<string, unknown>,
	key: string,
): Record<string, unknown> | null {
	const value = record[key];
	return value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: null;
}

function isManualSource(sourceType: string | null): boolean {
	return sourceType === "manual";
}

function isAiGeneratedSource(sourceType: string | null): boolean {
	return sourceType === "ai" || sourceType === "ai_variant";
}

function isCompetitorSource(sourceType: string | null): boolean {
	return Boolean(sourceType?.includes("competitor"));
}

function isSystemSource(sourceType: string | null): boolean {
	return ["template", "recycled", "recycled_direct", "system"].includes(
		sourceType ?? "",
	);
}

export function evaluateQueueProvenance(
	row: QueueProvenanceInput,
): ProvenanceCheckResult {
	const metadata = metadataRecord(row.metadata);
	const provenance = nestedRecord(metadata, "provenance");
	const qualityGate = nestedRecord(metadata, "quality_gate");
	const judge = nestedRecord(metadata, "judge");
	const sourceType = stringFrom(row.source_type);
	const contentFingerprint =
		stringFrom(row.content_fingerprint) ||
		stringFrom(metadata.content_fingerprint) ||
		stringFrom(provenance?.content_fingerprint) ||
		stringFrom(row.publish_fingerprint);
	const generationId =
		stringFrom(row.generation_id) ||
		stringFrom(metadata.generation_id) ||
		stringFrom(provenance?.generation_id);
	const sourceId =
		stringFrom(row.source_id) ||
		stringFrom(metadata.source_id) ||
		stringFrom(provenance?.source_id) ||
		stringFrom(row.source_competitor_id);
	const hasQualityGate = Boolean(
		qualityGate ||
			nestedRecord(provenance ?? {}, "quality_gate") ||
			stringFrom(provenance?.quality_gate_result),
	);
	const hasJudge = Boolean(
		judge ||
			nestedRecord(provenance ?? {}, "judge") ||
			stringFrom(provenance?.judge_result),
	);

	if (isManualSource(sourceType)) {
		return {
			decision: "manual_allowed",
			status: "manual_allowed",
			reasons: [],
			fields: {
				sourceType,
				contentFingerprint,
				generationId,
				sourceId,
				hasQualityGate,
				hasJudge,
			},
		};
	}

	const reasons: string[] = [];
	if (!sourceType) reasons.push("missing_source_type");
	if (!contentFingerprint) reasons.push("missing_content_fingerprint");
	if (!hasQualityGate) reasons.push("missing_quality_gate_result");
	if (isAiGeneratedSource(sourceType) && !generationId) {
		reasons.push("missing_generation_id");
	}
	if (isAiGeneratedSource(sourceType) && !hasJudge) {
		reasons.push("missing_judge_result");
	}
	if (
		(isCompetitorSource(sourceType) || isSystemSource(sourceType)) &&
		!sourceId
	) {
		reasons.push("missing_source_id");
	}

	return {
		decision: reasons.length > 0 ? "missing" : "pass",
		status: reasons.length > 0 ? "missing" : "pass",
		reasons,
		fields: {
			sourceType,
			contentFingerprint,
			generationId,
			sourceId,
			hasQualityGate,
			hasJudge,
		},
	};
}

export async function stampQueueProvenance(
	queueItemId: string,
	result: ProvenanceCheckResult,
): Promise<void> {
	await db()
		.from("auto_post_queue")
		.update({
			provenance_status: result.status,
			provenance_error:
				result.reasons.length > 0 ? result.reasons.join(",") : null,
			content_fingerprint: result.fields.contentFingerprint,
			generation_id: result.fields.generationId,
			source_id: result.fields.sourceId,
		} as Record<string, unknown>)
		.eq("id", queueItemId);
}
