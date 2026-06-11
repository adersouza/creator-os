import * as crypto from "node:crypto";

const TOKEN_VERSION = "v1";
const TOKEN_TTL_SECONDS = 60 * 60 * 6;

type TokenPayload = {
	pageId: string;
	linkId?: string | null | undefined;
	variantId?: string | null | undefined;
	expiresAt?: number | undefined;
};

function getSecret(): string {
	const secret =
		process.env.LINK_TRACKING_SECRET ||
		process.env.SUPABASE_SERVICE_ROLE_KEY ||
		process.env.SUPABASE_SERVICE_KEY ||
		process.env.JWT_SECRET;
	if (secret) return secret;
	if (process.env.NODE_ENV === "production") {
		throw new Error(
			"LINK_TRACKING_SECRET or a service-role secret is required in production",
		);
	}
	return "development-link-tracking-secret";
}

function canonicalPayload(payload: TokenPayload): string {
	return [
		TOKEN_VERSION,
		payload.pageId,
		payload.linkId || "",
		payload.variantId || "",
		String(payload.expiresAt || ""),
	].join("\n");
}

function sign(payload: TokenPayload): string {
	return crypto
		.createHmac("sha256", getSecret())
		.update(canonicalPayload(payload))
		.digest("base64url");
}

function timingSafeEqualString(a: string, b: string): boolean {
	const aBuf = Buffer.from(a);
	const bBuf = Buffer.from(b);
	if (aBuf.length !== bBuf.length) return false;
	return crypto.timingSafeEqual(aBuf, bBuf);
}

export function createLinkTrackingToken(payload: TokenPayload): string {
	const expiresAt =
		payload.expiresAt || Math.floor(Date.now() / 1000) + TOKEN_TTL_SECONDS;
	const signedPayload = { ...payload, expiresAt };
	return `${TOKEN_VERSION}.${expiresAt}.${sign(signedPayload)}`;
}

export function verifyLinkTrackingToken(
	token: string | null | undefined,
	payload: Omit<TokenPayload, "expiresAt">,
	nowSeconds = Math.floor(Date.now() / 1000),
): boolean {
	if (!token) return false;
	const [version, expiresAtRaw, signature] = token.split(".");
	if (version !== TOKEN_VERSION || !expiresAtRaw || !signature) return false;
	const expiresAt = Number(expiresAtRaw);
	if (!Number.isFinite(expiresAt) || expiresAt < nowSeconds) return false;
	const expected = sign({ ...payload, expiresAt });
	return timingSafeEqualString(signature, expected);
}
