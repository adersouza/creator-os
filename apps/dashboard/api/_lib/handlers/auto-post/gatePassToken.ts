import crypto from "node:crypto";
import type { DiscoverabilitySafeContentResult } from "../../discoverabilitySafety.js";

export const AUTOPUBLISH_GATE_PASS_VERSION = 1;

export interface AutopublishGatePassInput {
	content: string;
	platform: string;
	sourceType?: string | null | undefined;
	contentFingerprint?: string | null | undefined;
	publishFingerprint?: string | null | undefined;
	qualityGateDecision?: string | null | undefined;
	qualityGateReason?: string | null | undefined;
	provenanceStatus?: string | null | undefined;
	provenanceError?: string | null | undefined;
	dnaDecision?: string | null | undefined;
	discoverability: DiscoverabilitySafeContentResult;
}

export interface AutopublishGatePassToken {
	version: typeof AUTOPUBLISH_GATE_PASS_VERSION;
	contentHash: string;
	verdictHash: string;
	signature: string;
	issuedAt: string;
	discoverabilitySafe: boolean;
	blockedReason: string | null;
}

export type GatePassVerificationResult =
	| { ok: true; contentHash: string; verdictHash: string }
	| { ok: false; reason: string; contentHash: string | null };

function sha256(value: string): string {
	return crypto.createHash("sha256").update(value).digest("hex");
}

function canonicalize(value: unknown): string {
	return JSON.stringify(value, Object.keys(value as Record<string, unknown>).sort());
}

function getGatePassSecret(): string | null {
	const secret =
		process.env.AUTOPOSTER_GATE_TOKEN_SECRET ||
		process.env.CRON_SECRET ||
		process.env.SUPABASE_SERVICE_ROLE_KEY ||
		process.env.SUPABASE_SERVICE_KEY ||
		"";
	return secret.trim() ? secret : null;
}

export function contentHashForGatePass(content: string): string {
	return sha256(content.normalize("NFKC").trim());
}

function verdictPayload(input: AutopublishGatePassInput): Record<string, unknown> {
	return {
		version: AUTOPUBLISH_GATE_PASS_VERSION,
		platform: input.platform || "threads",
		sourceType: input.sourceType ?? null,
		contentFingerprint: input.contentFingerprint ?? null,
		publishFingerprint: input.publishFingerprint ?? null,
		qualityGateDecision: input.qualityGateDecision ?? null,
		qualityGateReason: input.qualityGateReason ?? null,
		provenanceStatus: input.provenanceStatus ?? null,
		provenanceError: input.provenanceError ?? null,
		dnaDecision: input.dnaDecision ?? null,
		discoverabilitySafe: input.discoverability.discoverabilitySafe,
		discoverabilityBlockedReason: input.discoverability.blockedReason || null,
		discoverabilityBlockedTerms: input.discoverability.blockedTerms.map((term) => ({
			reason: term.reason,
			matchedText: term.matchedText,
		})),
	};
}

function sign(contentHash: string, verdictHash: string, secret: string): string {
	return crypto
		.createHmac("sha256", secret)
		.update(`${AUTOPUBLISH_GATE_PASS_VERSION}:${contentHash}:${verdictHash}`)
		.digest("hex");
}

export function createAutopublishGatePassToken(
	input: AutopublishGatePassInput,
	now = new Date(),
): AutopublishGatePassToken | null {
	if (!input.discoverability.discoverabilitySafe) return null;
	const secret = getGatePassSecret();
	if (!secret) return null;
	const contentHash = contentHashForGatePass(input.content);
	const verdictHash = sha256(canonicalize(verdictPayload(input)));
	return {
		version: AUTOPUBLISH_GATE_PASS_VERSION,
		contentHash,
		verdictHash,
		signature: sign(contentHash, verdictHash, secret),
		issuedAt: now.toISOString(),
		discoverabilitySafe: true,
		blockedReason: null,
	};
}

export function verifyAutopublishGatePassToken(input: {
	content: string;
	token: unknown;
}): GatePassVerificationResult {
	const contentHash = contentHashForGatePass(input.content);
	if (!input.token || typeof input.token !== "object" || Array.isArray(input.token)) {
		return { ok: false, reason: "missing_gate_pass_token", contentHash };
	}
	const token = input.token as Partial<AutopublishGatePassToken>;
	if (token.version !== AUTOPUBLISH_GATE_PASS_VERSION) {
		return { ok: false, reason: "invalid_gate_pass_version", contentHash };
	}
	if (token.discoverabilitySafe !== true) {
		return { ok: false, reason: "gate_pass_discoverability_not_safe", contentHash };
	}
	if (
		typeof token.contentHash !== "string" ||
		typeof token.verdictHash !== "string" ||
		typeof token.signature !== "string"
	) {
		return { ok: false, reason: "malformed_gate_pass_token", contentHash };
	}
	if (token.contentHash !== contentHash) {
		return { ok: false, reason: "gate_pass_content_hash_mismatch", contentHash };
	}
	const secret = getGatePassSecret();
	if (!secret) return { ok: false, reason: "gate_pass_secret_unavailable", contentHash };
	const expected = sign(token.contentHash, token.verdictHash, secret);
	const actual = token.signature;
	const expectedBuffer = Buffer.from(expected, "hex");
	const actualBuffer = Buffer.from(actual, "hex");
	if (
		expectedBuffer.length !== actualBuffer.length ||
		!crypto.timingSafeEqual(expectedBuffer, actualBuffer)
	) {
		return { ok: false, reason: "gate_pass_signature_invalid", contentHash };
	}
	return { ok: true, contentHash, verdictHash: token.verdictHash };
}
