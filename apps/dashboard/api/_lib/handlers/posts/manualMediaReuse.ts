import crypto from "node:crypto";
import type {
	PreflightIssue,
	PreflightMediaItem,
	PreflightPlatform,
	PreflightResult,
} from "../../publishPreflight.js";
import {
	buildMediaReuseSignals,
	buildPublishFingerprint,
	type DuplicateFingerprintMatch,
	findRecentMediaFingerprintAcrossAccounts,
} from "../auto-post/publishFingerprint.js";

export const CROSS_ACCOUNT_MEDIA_REUSE_WARNING_CODE =
	"cross_account_media_reuse_warning";
export const MANUAL_MEDIA_REUSE_CONFIRMATION_REQUIRED_CODE =
	"MANUAL_MEDIA_REUSE_CONFIRMATION_REQUIRED";

const TOKEN_PURPOSE = "manual_media_reuse_override";
const TOKEN_VERSION = 1;
const OVERRIDE_TOKEN_TTL_MS = 10 * 60 * 1000;
const DEV_FALLBACK_SECRET = "manual-media-reuse-override-development-secret";

export interface ManualMediaReuseTokenContext {
	userId: string;
	platform: PreflightPlatform;
	accountId: string;
	normalizedTextHash: string;
	mediaFingerprint: string;
	matchId: string;
	matchType: string;
	matchedAccountId: string;
}

interface ManualMediaReuseTokenClaims extends ManualMediaReuseTokenContext {
	v: typeof TOKEN_VERSION;
	purpose: typeof TOKEN_PURPOSE;
	expiresAt: string;
}

export interface ManualMediaReuseAudit {
	acknowledged_at: string;
	match_type: string;
	matched_post_id: string | null;
	matched_queue_id: string | null;
	matched_account_id: string;
	matched_platform: PreflightPlatform;
	override_token_expires_at: string;
}

export interface ManualMediaReuseEvaluation {
	match: DuplicateFingerprintMatch | null;
	issue: PreflightIssue | null;
	preflight: PreflightResult | null;
	overrideValid: boolean;
	audit: ManualMediaReuseAudit | null;
}

function getSigningSecret(): string {
	const secret =
		process.env.MANUAL_MEDIA_REUSE_OVERRIDE_SECRET ||
		process.env.SUPABASE_SERVICE_ROLE_KEY ||
		process.env.SUPABASE_SERVICE_KEY ||
		process.env.JWT_SECRET ||
		(process.env.NODE_ENV === "production" ? "" : DEV_FALLBACK_SECRET);
	if (!secret) {
		throw new Error("Manual media reuse override signing secret is unavailable");
	}
	return secret;
}

function encodeJson(value: unknown): string {
	return Buffer.from(JSON.stringify(value), "utf8").toString("base64url");
}

function decodeJson<T>(value: string): T | null {
	try {
		return JSON.parse(Buffer.from(value, "base64url").toString("utf8")) as T;
	} catch {
		return null;
	}
}

function signPayload(encodedPayload: string): string {
	return crypto
		.createHmac("sha256", getSigningSecret())
		.update(encodedPayload)
		.digest("base64url");
}

function signaturesMatch(a: string, b: string): boolean {
	const left = Buffer.from(a);
	const right = Buffer.from(b);
	return left.length === right.length && crypto.timingSafeEqual(left, right);
}

export function createManualMediaReuseOverrideToken(
	context: ManualMediaReuseTokenContext,
	options: { nowMs?: number | undefined; expiresAtMs?: number | undefined } = {},
): { token: string; expiresAt: string } {
	const nowMs = options.nowMs ?? Date.now();
	const expiresAt = new Date(
		options.expiresAtMs ?? nowMs + OVERRIDE_TOKEN_TTL_MS,
	).toISOString();
	const payload: ManualMediaReuseTokenClaims = {
		v: TOKEN_VERSION,
		purpose: TOKEN_PURPOSE,
		...context,
		expiresAt,
	};
	const encodedPayload = encodeJson(payload);
	return {
		token: `${encodedPayload}.${signPayload(encodedPayload)}`,
		expiresAt,
	};
}

export function verifyManualMediaReuseOverrideToken(
	token: string | null | undefined,
	context: ManualMediaReuseTokenContext,
	options: { nowMs?: number | undefined } = {},
): { valid: boolean; reason?: string | undefined; expiresAt?: string | undefined } {
	if (!token) return { valid: false, reason: "missing" };
	const [encodedPayload, signature] = token.split(".");
	if (!encodedPayload || !signature) return { valid: false, reason: "malformed" };
	const expectedSignature = signPayload(encodedPayload);
	if (!signaturesMatch(signature, expectedSignature)) {
		return { valid: false, reason: "bad_signature" };
	}
	const claims = decodeJson<ManualMediaReuseTokenClaims>(encodedPayload);
	if (!claims || claims.v !== TOKEN_VERSION || claims.purpose !== TOKEN_PURPOSE) {
		return { valid: false, reason: "bad_claims" };
	}
	const expiresAtMs = Date.parse(claims.expiresAt);
	if (!Number.isFinite(expiresAtMs)) {
		return { valid: false, reason: "bad_expiry" };
	}
	if (expiresAtMs <= (options.nowMs ?? Date.now())) {
		return { valid: false, reason: "expired", expiresAt: claims.expiresAt };
	}
	for (const key of [
		"userId",
		"platform",
		"accountId",
		"normalizedTextHash",
		"mediaFingerprint",
		"matchId",
		"matchType",
		"matchedAccountId",
	] as const) {
		if (claims[key] !== context[key]) {
			return { valid: false, reason: `mismatched_${key}` };
		}
	}
	return { valid: true, expiresAt: claims.expiresAt };
}

function mediaUrlsFrom(media: PreflightMediaItem[] | null | undefined): string[] {
	return (media ?? [])
		.map((item) => item.url?.trim())
		.filter((url): url is string => Boolean(url));
}

function matchedAccountIdFor(
	match: DuplicateFingerprintMatch,
	platform: PreflightPlatform,
): string | null {
	return (
		match.matched_account_id ||
		(platform === "instagram" ? match.instagram_account_id : match.account_id) ||
		match.account_id ||
		null
	);
}

function matchIdFor(match: DuplicateFingerprintMatch): string {
	return match.post_id || match.id;
}

function issueFor(
	match: DuplicateFingerprintMatch,
	platform: PreflightPlatform,
	matchedAccountId: string,
	override: { token: string; expiresAt: string },
): PreflightIssue {
	const matchedPostId = match.post_id || null;
	const matchedQueueId = matchedPostId ? null : match.id;
	return {
		severity: "warning",
		category: "media",
		code: CROSS_ACCOUNT_MEDIA_REUSE_WARNING_CODE,
		message:
			"This media appears to have been used recently on another account. Confirm before publishing it manually.",
		details: {
			matchType: match.match_type || "media_reuse",
			matchedPostId,
			matchedQueueId,
			matchedAccountId,
			matchedPlatform: platform,
			overrideToken: override.token,
			overrideExpiresAt: override.expiresAt,
		},
	};
}

export function summarizePreflightIssues(
	issues: PreflightIssue[],
): PreflightResult["summary"] {
	return {
		errors: issues.filter((issue) => issue.severity === "error").length,
		warnings: issues.filter((issue) => issue.severity === "warning").length,
		infos: issues.filter((issue) => issue.severity === "info").length,
	};
}

export function withManualMediaReuseIssue(
	result: PreflightResult,
	issue: PreflightIssue | null,
): PreflightResult {
	if (!issue) return result;
	const issues = [...result.issues, issue];
	const summary = summarizePreflightIssues(issues);
	return {
		ok: summary.errors === 0,
		issues,
		summary,
	};
}

export async function evaluateManualMediaReuse(values: {
	userId: string;
	platform: PreflightPlatform;
	accountId: string | null | undefined;
	content: string | null | undefined;
	media: PreflightMediaItem[] | null | undefined;
	overrideToken?: string | null | undefined;
	nowMs?: number | undefined;
}): Promise<ManualMediaReuseEvaluation> {
	const accountId = values.accountId?.trim();
	const mediaUrls = mediaUrlsFrom(values.media);
	if (!accountId || mediaUrls.length === 0) {
		return {
			match: null,
			issue: null,
			preflight: null,
			overrideValid: false,
			audit: null,
		};
	}

	const fingerprint = buildPublishFingerprint({
		workspaceId: values.userId,
		accountId,
		platform: values.platform,
		content: values.content ?? "",
		mediaUrls,
	});
	const signals = await buildMediaReuseSignals({
		userId: values.userId,
		content: values.content,
		mediaUrls,
	});
	const match = await findRecentMediaFingerprintAcrossAccounts({
		workspaceId: values.userId,
		userId: values.userId,
		accountId,
		platform: values.platform,
		mediaFingerprint: fingerprint.mediaFingerprint,
		mediaUrlHashes: signals.mediaUrlHashes,
		perceptualHashes: signals.perceptualHashes,
	});
	if (!match) {
		return {
			match: null,
			issue: null,
			preflight: null,
			overrideValid: false,
			audit: null,
		};
	}

	const matchedAccountId = matchedAccountIdFor(match, values.platform);
	if (!matchedAccountId || matchedAccountId === accountId) {
		return {
			match: null,
			issue: null,
			preflight: null,
			overrideValid: false,
			audit: null,
		};
	}

	const context: ManualMediaReuseTokenContext = {
		userId: values.userId,
		platform: values.platform,
		accountId,
		normalizedTextHash: fingerprint.normalizedTextHash,
		mediaFingerprint: fingerprint.mediaFingerprint,
		matchId: matchIdFor(match),
		matchType: match.match_type || "media_reuse",
		matchedAccountId,
	};
	const override = createManualMediaReuseOverrideToken(context, {
		nowMs: values.nowMs,
	});
	const verification = verifyManualMediaReuseOverrideToken(
		values.overrideToken,
		context,
		{ nowMs: values.nowMs },
	);
	const issue = issueFor(match, values.platform, matchedAccountId, override);
	const preflight: PreflightResult = {
		ok: true,
		issues: [issue],
		summary: summarizePreflightIssues([issue]),
	};

	if (!verification.valid) {
		return {
			match,
			issue,
			preflight,
			overrideValid: false,
			audit: null,
		};
	}

	const matchedPostId = match.post_id || null;
	return {
		match,
		issue,
		preflight,
		overrideValid: true,
		audit: {
			acknowledged_at: new Date(values.nowMs ?? Date.now()).toISOString(),
			match_type: context.matchType,
			matched_post_id: matchedPostId,
			matched_queue_id: matchedPostId ? null : match.id,
			matched_account_id: matchedAccountId,
			matched_platform: values.platform,
			override_token_expires_at: verification.expiresAt || override.expiresAt,
		},
	};
}
