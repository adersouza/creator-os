import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { getSupabaseAny } from "../../supabase.js";
import { z } from "../../zodCompat.js";

const AudioActionSchema = z.object({
	postIds: z.array(z.string().min(1)).min(1).max(200),
	action: z.enum([
		"apply_primary_audio",
		"apply_first_recommendation",
		"selected",
		"attached",
		"verified",
		"skipped",
		"blocked",
	]),
	note: z.string().max(1000).optional(),
	proofUrl: z.string().max(1000).optional(),
	proofType: z.string().max(100).optional(),
	proofNote: z.string().max(1000).optional(),
	selectedAudioId: z.string().max(300).optional(),
	nowIso: z.string().datetime().optional(),
});

type AudioAction =
	| "apply_primary_audio"
	| "apply_first_recommendation"
	| "selected"
	| "attached"
	| "verified"
	| "skipped"
	| "blocked";

type PostRow = {
	id: string;
	user_id: string;
	platform: string | null;
	status: string | null;
	metadata: Record<string, unknown> | null;
};

function asRecord(value: unknown): Record<string, unknown> | null {
	return value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: null;
}

function firstRecommendation(
	audioIntent: Record<string, unknown>,
): Record<string, unknown> | null {
	const decision = asRecord(audioIntent.decision);
	const primary = asRecord(decision?.primaryAudio);
	if (primary) return primary;
	const recommendations = audioIntent.recommendations;
	if (!Array.isArray(recommendations)) return null;
	return recommendations.find((item) => asRecord(item)) as Record<string, unknown> | null;
}

function recommendationMatchesAudioId(item: Record<string, unknown>, selectedAudioId: string): boolean {
	const candidates = [
		item.catalog_audio_id,
		item.catalogAudioId,
		item.audioMemoryGraphId,
		item.platform_audio_id,
		item.platformAudioId,
		item.audioId,
		item.native_audio_id,
		item.nativeAudioId,
		item.platform_url,
		item.platformUrl,
	].map((value) => (typeof value === "string" ? value.trim() : ""));
	return candidates.includes(selectedAudioId.trim());
}

function findRecommendation(
	audioIntent: Record<string, unknown>,
	selectedAudioId?: string | undefined,
): Record<string, unknown> | null {
	if (!selectedAudioId) return firstRecommendation(audioIntent);
	const decision = asRecord(audioIntent.decision);
	const primary = asRecord(decision?.primaryAudio);
	if (primary && recommendationMatchesAudioId(primary, selectedAudioId)) return primary;
	const recommendations = audioIntent.recommendations;
	if (!Array.isArray(recommendations)) return null;
	return (
		(recommendations.find((item) => {
			const record = asRecord(item);
			return record ? recommendationMatchesAudioId(record, selectedAudioId) : false;
		}) as Record<string, unknown> | undefined) ?? null
	);
}

function nativeLocator(selection: Record<string, unknown>): string | null {
	for (const key of [
		"platform_audio_id",
		"platform_url",
		"native_audio_id",
		"native_audio_url",
		"audio_id",
	]) {
		const value = selection[key];
		if (typeof value === "string" && value.trim()) return value.trim();
	}
	return null;
}

function audioTaskForIntent(
	audioIntent: Record<string, unknown>,
	proofComplete: boolean,
	nowIso: string,
): Record<string, unknown> {
	const existing = asRecord(audioIntent.task) ?? {};
	const status = String(audioIntent.status || "needs_operator_selection").trim().toLowerCase();
	const selection = asRecord(audioIntent.operator_selection) ?? {};
	let taskStatus = "open";
	if (audioIntent.required !== true || status === "not_required") taskStatus = "not_required";
	else if (status === "selected") taskStatus = "selected";
	else if (status === "blocked" || status === "burned") taskStatus = "blocked";
	else if (status === "needs_review") taskStatus = "needs_review";
	else if (status === "skipped") taskStatus = "completed";
	else if (status === "attached" || status === "verified") {
		taskStatus = proofComplete ? "completed" : "proof_missing";
	}
	const completedAt =
		existing.completed_at ||
		(taskStatus === "completed"
			? selection.verified_at || selection.attached_at || selection.skipped_at || nowIso
			: null);
	return {
		...existing,
		schema:
			typeof existing.schema === "string"
				? existing.schema
				: "pipeline.audio_task.v1",
		status: taskStatus,
		proof_required:
			audioIntent.required === true && (status === "attached" || status === "verified"),
		assignee: existing.assignee ?? null,
		due_at: existing.due_at ?? null,
		created_at: existing.created_at ?? null,
		updated_at: nowIso,
		completed_at: completedAt,
	};
}

export function applyCampaignFactoryAudioServerAction(
	row: PostRow,
	action: AudioAction,
	nowIso = new Date().toISOString(),
	note?: string | undefined,
	proof?: { url?: string | undefined; type?: string | undefined; note?: string | undefined } | undefined,
	selectedAudioId?: string | undefined,
): {
	metadata: Record<string, unknown> | null;
	previousStatus: string | null;
	nextStatus: string | null;
	proofComplete: boolean;
	eventMetadata: Record<string, unknown>;
} {
	const metadata = { ...(asRecord(row.metadata) ?? {}) };
	const campaignFactory = { ...(asRecord(metadata.campaign_factory) ?? {}) };
	const audioIntent = { ...(asRecord(campaignFactory.audio_intent) ?? {}) };
	if (!Object.keys(campaignFactory).length || !Object.keys(audioIntent).length) {
		return {
			metadata: null,
			previousStatus: null,
			nextStatus: null,
			proofComplete: false,
			eventMetadata: { skipped_reason: "missing_audio_intent" },
		};
	}

	const previousStatus =
		typeof audioIntent.status === "string" ? audioIntent.status : null;
	const existingSelection = {
		...(asRecord(audioIntent.operator_selection) ?? {}),
	};
	let nextStatus: string = action;
	let operatorSelection: Record<string, unknown> = existingSelection;
	const eventMetadata: Record<string, unknown> = {};

	if (action === "apply_primary_audio" || action === "apply_first_recommendation" || (action === "selected" && selectedAudioId)) {
		const recommendation = findRecommendation(audioIntent, selectedAudioId);
		if (!recommendation) {
			return {
				metadata: null,
				previousStatus,
				nextStatus: null,
				proofComplete: false,
				eventMetadata: { skipped_reason: "missing_recommendation" },
			};
		}
		nextStatus = "selected";
		operatorSelection = {
			audio_title:
				recommendation.audio_title ??
				recommendation.audioTitle ??
				recommendation.title ??
				null,
			artist_name:
				recommendation.artist_name ?? recommendation.artistName ?? null,
			platform_audio_id:
				recommendation.platform_audio_id ??
				recommendation.platformAudioId ??
				recommendation.audioId ??
				null,
			platform_url:
				recommendation.platform_url ?? recommendation.platformUrl ?? null,
			catalog_audio_id:
				recommendation.catalog_audio_id ??
				recommendation.catalogAudioId ??
				null,
			audio_memory_graph_id: recommendation.audioMemoryGraphId ?? null,
			selection_rank: recommendation.selectionRank ?? null,
			source: recommendation.source ?? null,
			selected_at: nowIso,
			selection_source: selectedAudioId
				? "operator_selected_recommendation"
				: action === "apply_primary_audio"
					? "server_batch_primary_audio_decision"
					: "server_batch_first_recommendation",
		};
		eventMetadata.recommendation = operatorSelection;
	} else if (action === "attached" || action === "verified") {
		const timestampKey = action === "verified" ? "verified_at" : "attached_at";
		operatorSelection = {
			...existingSelection,
			...(existingSelection.selected_at ? {} : { selected_at: nowIso }),
			[timestampKey]: nowIso,
			proof_source: "operator_server_action",
			...(proof?.url ? { proof_url: proof.url } : {}),
			...(proof?.type ? { proof_type: proof.type } : {}),
			...(proof?.note ? { proof_note: proof.note } : {}),
			...(proof?.url || proof?.type || proof?.note ? { proof_captured_at: nowIso } : {}),
			updated_at: nowIso,
		};
	} else {
		operatorSelection = {
			...existingSelection,
			...(action === "skipped" ? { skipped_at: nowIso } : {}),
			...(note ? { note, notes: note } : {}),
			updated_at: nowIso,
		};
	}

	if (note) {
		operatorSelection.note = note;
		operatorSelection.notes = note;
	}
	if (proof?.url || proof?.type || proof?.note) {
		eventMetadata.proof = {
			url: proof.url ?? null,
			type: proof.type ?? null,
			note: proof.note ?? null,
			captured_at: nowIso,
		};
	}

	audioIntent.schema =
		typeof audioIntent.schema === "string"
			? audioIntent.schema
			: "pipeline.audio_intent.v1";
	audioIntent.status = nextStatus;
	audioIntent.operator_selection = operatorSelection;
	campaignFactory.audio_intent = audioIntent;
	metadata.campaign_factory = campaignFactory;

	const selection = asRecord(audioIntent.operator_selection) ?? {};
	const proofComplete =
		(nextStatus === "attached" || nextStatus === "verified") &&
		!!nativeLocator(selection) &&
		typeof selection.selected_at === "string" &&
		!!selection.selected_at &&
		typeof selection[nextStatus === "verified" ? "verified_at" : "attached_at"] ===
			"string" &&
		!!selection[nextStatus === "verified" ? "verified_at" : "attached_at"];

	audioIntent.task = audioTaskForIntent(audioIntent, proofComplete, nowIso);
	campaignFactory.audio_intent = audioIntent;
	metadata.campaign_factory = campaignFactory;

	return {
		metadata,
		previousStatus,
		nextStatus,
		proofComplete,
		eventMetadata,
	};
}

export async function handleCampaignFactoryAudioAction(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (req.method !== "POST") return apiError(res, 405, "Method not allowed");
	const parsed = AudioActionSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			parsed.error.issues.map((issue) => issue.message).join("; "),
		);
	}
	const { postIds, action, note, proofUrl, proofType, proofNote, selectedAudioId, nowIso } = parsed.data;
	const db = getSupabaseAny();
	const uniquePostIds = Array.from(new Set(postIds));

	const { data: rows, error: fetchError } = await db
		.from("posts")
		.select("id, user_id, platform, status, metadata")
		.eq("user_id", userId)
		.in("id", uniquePostIds);
	if (fetchError) {
		return apiError(res, 500, "Failed to load posts", {
			details: String(fetchError.message || fetchError),
		});
	}

	const updatedPosts: Array<Record<string, unknown>> = [];
	const skipped: Array<{ postId: string; reason: string }> = [];
	const events: Array<Record<string, unknown>> = [];
	const now = nowIso ?? new Date().toISOString();

	for (const row of (rows ?? []) as PostRow[]) {
		const result = applyCampaignFactoryAudioServerAction(row, action, now, note, {
			url: proofUrl,
			type: proofType,
			note: proofNote,
		}, selectedAudioId);
		if (!result.metadata || !result.nextStatus) {
			skipped.push({
				postId: row.id,
				reason: String(result.eventMetadata.skipped_reason || "not_campaign_factory"),
			});
			continue;
		}

		const { data: updated, error: updateError } = await db
			.from("posts")
			.update({ metadata: result.metadata, updated_at: now })
			.eq("id", row.id)
			.eq("user_id", userId)
			.select("id, platform, status, metadata, updated_at")
			.maybeSingle();
		if (updateError || !updated) {
			return apiError(res, 500, "Failed to update audio state", {
				details: String(updateError?.message || "No updated row returned"),
			});
		}
		updatedPosts.push(updated as Record<string, unknown>);

		const cf = asRecord(result.metadata.campaign_factory) ?? {};
		const intent = asRecord(cf.audio_intent) ?? {};
		const selection = asRecord(intent.operator_selection) ?? {};
		events.push({
			user_id: userId,
			post_id: row.id,
			campaign_id: cf.campaign_id ?? null,
			rendered_asset_id: cf.rendered_asset_id ?? null,
			action,
			previous_status: result.previousStatus,
			next_status: result.nextStatus,
			platform_audio_id:
				selection.platform_audio_id ?? selection.native_audio_id ?? null,
			platform_url: selection.platform_url ?? selection.native_audio_url ?? null,
			proof_complete: result.proofComplete,
			note: note ?? null,
			metadata: {
				...result.eventMetadata,
				proof_source: selection.proof_source ?? null,
				audio_task: intent.task ?? null,
			},
			created_at: now,
		});
	}

	const foundIds = new Set(((rows ?? []) as PostRow[]).map((row) => row.id));
	for (const postId of uniquePostIds) {
		if (!foundIds.has(postId)) skipped.push({ postId, reason: "not_found" });
	}

	if (events.length > 0) {
		const { error: eventError } = await db
			.from("campaign_factory_audio_events")
			.insert(events);
		if (eventError) {
			return apiError(res, 500, "Failed to record audio event history", {
				details: String(eventError.message || eventError),
			});
		}
	}

	return apiSuccess(res, {
		posts: updatedPosts,
		eventsWritten: events.length,
		skipped,
	});
}
