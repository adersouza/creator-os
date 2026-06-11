import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { getSupabaseAny } from "../../supabase.js";

type AudioEventRow = {
	id?: string | null;
	post_id?: string | null;
	campaign_id?: string | null;
	rendered_asset_id?: string | null;
	action?: string | null;
	previous_status?: string | null;
	next_status?: string | null;
	platform_audio_id?: string | null;
	platform_url?: string | null;
	proof_complete?: boolean | null;
	note?: string | null;
	metadata?: Record<string, unknown> | null;
	created_at?: string | null;
};

function firstQueryValue(value: string | string[] | undefined): string | null {
	if (Array.isArray(value)) return value[0]?.trim() || null;
	return value?.trim() || null;
}

function parseLimit(value: string | string[] | undefined): number {
	const raw = firstQueryValue(value);
	if (!raw) return 20;
	const parsed = Number.parseInt(raw, 10);
	if (!Number.isFinite(parsed) || parsed < 1) return 20;
	return Math.min(parsed, 100);
}

function metadataReason(metadata: Record<string, unknown> | null | undefined): string | null {
	if (!metadata) return null;
	for (const key of ["reason", "skipped_reason", "blocked_reason"]) {
		const value = metadata[key];
		if (typeof value === "string" && value.trim()) return value.trim();
	}
	return null;
}

export function formatCampaignFactoryAudioEvent(row: AudioEventRow) {
	const metadata = row.metadata && typeof row.metadata === "object" ? row.metadata : null;
	const platformUrl = row.platform_url?.trim() || null;
	const platformAudioId = row.platform_audio_id?.trim() || null;

	return {
		id: row.id ?? null,
		postId: row.post_id ?? null,
		campaignId: row.campaign_id ?? null,
		renderedAssetId: row.rendered_asset_id ?? null,
		action: row.action ?? null,
		previousStatus: row.previous_status ?? null,
		nextStatus: row.next_status ?? null,
		proofComplete: row.proof_complete ?? null,
		nativeAudioLocator: platformUrl || platformAudioId,
		platformAudioId,
		platformUrl,
		note: row.note?.trim() || null,
		reason: metadataReason(metadata),
		timestamp: row.created_at ?? null,
	};
}

export async function handleCampaignFactoryAudioEvents(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

	const postId = firstQueryValue(req.query.postId);
	const campaignId = firstQueryValue(req.query.campaignId);
	const renderedAssetId = firstQueryValue(req.query.renderedAssetId);
	const limit = parseLimit(req.query.limit);

	const db = getSupabaseAny();
	let query = db
		.from("campaign_factory_audio_events")
		.select(
			"id, post_id, campaign_id, rendered_asset_id, action, previous_status, next_status, platform_audio_id, platform_url, proof_complete, note, metadata, created_at",
		)
		.eq("user_id", userId)
		.order("created_at", { ascending: false })
		.limit(limit);

	if (postId) query = query.eq("post_id", postId);
	if (campaignId) query = query.eq("campaign_id", campaignId);
	if (renderedAssetId) query = query.eq("rendered_asset_id", renderedAssetId);

	const { data, error } = await query;
	if (error) {
		return apiError(res, 500, "Failed to load Campaign Factory audio events", {
			details: String(error.message || error),
		});
	}

	return apiSuccess(res, {
		events: ((data ?? []) as AudioEventRow[]).map(formatCampaignFactoryAudioEvent),
		limit,
	});
}
