/**
 * Instagram Audio API — search/retrieve audio, ad replacement discovery, and
 * media audio metadata.
 *
 * Released by Meta on 2026-06-01 for apps using Facebook Login.
 */

import { decrypt, getGraphBaseUrl, igFetch, logger } from "./shared.js";

export type IGAudioType = "music" | "original_sound";
export type IGAudioReplacementMode = "auto" | "search" | "default";
export type IGMediaAudioType = "MUSIC" | "ORIGINAL_SOUND";

export interface IGAudioAsset {
	id: string;
	title?: string | undefined;
	artistName?: string | undefined;
	audioType?: string | undefined;
	durationMs?: number | undefined;
	thumbnailUrl?: string | undefined;
	previewUrl?: string | undefined;
	isExplicit?: boolean | undefined;
	raw: Record<string, unknown>;
}

export interface IGAudioSearchParams {
	userId: string;
	audioType: IGAudioType;
	query?: string | undefined;
	limit?: number | undefined;
}

export interface IGAudioReplacementParams {
	userId: string;
	igMediaId: string;
	audioReplacementMode: IGAudioReplacementMode;
	query?: string | undefined;
	limit?: number | undefined;
}

const IG_AUDIO_FIELDS = [
	"audio_id",
	"title",
	"display_artist",
	"audio_type",
	"duration_in_ms",
	"cover_artwork_thumbnail_uri",
	"download_url",
	"ig_username",
	"profile_picture_url",
].join(",");

function requireFacebookLogin(loginType?: string): string | null {
	return loginType === "facebook"
		? null
		: "Instagram Audio API requires Facebook Login. Reconnect this Instagram account through Facebook Login to search or attach Meta-native audio.";
}

function asString(value: unknown): string | undefined {
	return typeof value === "string" && value.trim() ? value : undefined;
}

function asNumber(value: unknown): number | undefined {
	return typeof value === "number" && Number.isFinite(value)
		? value
		: undefined;
}

function asBoolean(value: unknown): boolean | undefined {
	return typeof value === "boolean" ? value : undefined;
}

export function normalizeInstagramAudioAsset(
	raw: Record<string, unknown>,
): IGAudioAsset | null {
	const id = asString(raw.audio_id) ?? asString(raw.id);
	if (!id) return null;
	return {
		id,
		title: asString(raw.title) ?? asString(raw.name),
		artistName:
			asString(raw.display_artist) ??
			asString(raw.ig_username) ??
			asString(raw.artist_name) ??
			asString(raw.artist) ??
			asString(raw.author_name),
		audioType: asString(raw.audio_type),
		durationMs:
			asNumber(raw.duration_in_ms) ??
			asNumber(raw.duration_ms) ??
			asNumber(raw.duration),
		thumbnailUrl:
			asString(raw.cover_artwork_thumbnail_uri) ??
			asString(raw.profile_picture_url) ??
			asString(raw.thumbnail_url) ??
			asString(raw.cover_url),
		previewUrl: asString(raw.download_url),
		isExplicit: asBoolean(raw.is_explicit),
		raw,
	};
}

function appendIfPresent(
	params: URLSearchParams,
	key: string,
	value: string | number | undefined,
) {
	if (value !== undefined && String(value).trim())
		params.set(key, String(value));
}

export function buildInstagramAudioSearchParams(params: IGAudioSearchParams) {
	const searchParams = new URLSearchParams({
		audio_type: params.audioType,
		user_id: params.userId,
		fields: IG_AUDIO_FIELDS,
	});
	appendIfPresent(searchParams, "search_query", params.query);
	appendIfPresent(searchParams, "limit", params.limit);
	return searchParams;
}

export function buildInstagramAudioReplacementParams(
	params: IGAudioReplacementParams,
) {
	const searchParams = new URLSearchParams({
		product: "ADS",
		purpose: "AUDIO_COPYRIGHT_REPLACEMENT",
		audio_replacement_mode: params.audioReplacementMode,
		ig_media_id: params.igMediaId,
		user_id: params.userId,
		fields: IG_AUDIO_FIELDS,
	});
	appendIfPresent(searchParams, "search_query", params.query);
	appendIfPresent(searchParams, "limit", params.limit);
	return searchParams;
}

async function fetchAudioList(
	url: URL,
	token: string,
	label: string,
): Promise<{
	success: boolean;
	audio?: IGAudioAsset[] | undefined;
	error?: string | undefined;
	paging?: unknown;
}> {
	const response = await igFetch(url, undefined, label, token);
	const data = await response.json();

	if (!response.ok || data.error) {
		return {
			success: false,
			error: data.error?.message || "Instagram audio request failed",
		};
	}

	const rawItems = Array.isArray(data.audio)
		? data.audio
		: Array.isArray(data.data)
			? data.data
			: [];
	const audio = rawItems
		.map((item: unknown) =>
			item && typeof item === "object"
				? normalizeInstagramAudioAsset(item as Record<string, unknown>)
				: null,
		)
		.filter((item: IGAudioAsset | null): item is IGAudioAsset => item !== null);

	return { success: true, audio, paging: data.paging };
}

export async function searchInstagramAudio(
	encryptedToken: string,
	params: IGAudioSearchParams,
	loginType?: string,
): Promise<{
	success: boolean;
	audio?: IGAudioAsset[] | undefined;
	error?: string | undefined;
	paging?: unknown;
}> {
	const loginError = requireFacebookLogin(loginType);
	if (loginError) return { success: false, error: loginError };

	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);
		const searchParams = buildInstagramAudioSearchParams(params);

		const url = new URL(`${graphBase}/v25.0/ig_audio`);
		url.search = searchParams.toString();
		return await fetchAudioList(url, token, "igApi:audioSearch");
	} catch (error: unknown) {
		logger.error("IG audio search error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

export async function getInstagramAudioMetadata(
	encryptedToken: string,
	igAudioId: string,
	loginType?: string,
): Promise<{
	success: boolean;
	audio?: IGAudioAsset | undefined;
	error?: string | undefined;
}> {
	const loginError = requireFacebookLogin(loginType);
	if (loginError) return { success: false, error: loginError };

	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);
		const url = new URL(`${graphBase}/v25.0/${encodeURIComponent(igAudioId)}`);
		url.searchParams.set("fields", IG_AUDIO_FIELDS);
		const response = await igFetch(
			url,
			undefined,
			"igApi:audioMetadata",
			token,
		);
		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Instagram audio metadata failed",
			};
		}

		const audio = normalizeInstagramAudioAsset(data as Record<string, unknown>);
		return audio
			? { success: true, audio }
			: { success: false, error: "Instagram audio metadata missing id" };
	} catch (error: unknown) {
		logger.error("IG audio metadata error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

export async function discoverInstagramAudioReplacements(
	encryptedToken: string,
	params: IGAudioReplacementParams,
	loginType?: string,
): Promise<{
	success: boolean;
	audio?: IGAudioAsset[] | undefined;
	error?: string | undefined;
	paging?: unknown;
}> {
	const loginError = requireFacebookLogin(loginType);
	if (loginError) return { success: false, error: loginError };

	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);
		const searchParams = buildInstagramAudioReplacementParams(params);

		const url = new URL(`${graphBase}/v25.0/ig_audio`);
		url.search = searchParams.toString();
		return await fetchAudioList(url, token, "igApi:audioReplacement");
	} catch (error: unknown) {
		logger.error("IG audio replacement discovery error", {
			error: String(error),
		});
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

export async function getInstagramMediaAudioType(
	encryptedToken: string,
	igMediaId: string,
	loginType?: string,
): Promise<{
	success: boolean;
	mediaAudioType?: IGMediaAudioType | string | null | undefined;
	error?: string | undefined;
}> {
	const loginError = requireFacebookLogin(loginType);
	if (loginError) {
		return { success: true, mediaAudioType: null };
	}

	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);
		const url = new URL(`${graphBase}/v25.0/${encodeURIComponent(igMediaId)}`);
		url.searchParams.set("fields", "media_audio_type");
		const response = await igFetch(
			url,
			undefined,
			"igApi:mediaAudioType",
			token,
		);
		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Instagram media audio type failed",
			};
		}

		return {
			success: true,
			mediaAudioType:
				typeof data.media_audio_type === "string"
					? data.media_audio_type
					: null,
		};
	} catch (error: unknown) {
		logger.error("IG media audio type error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}
