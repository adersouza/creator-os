// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Envelope encryption helper — Phase 0.
 *
 * Status: not wired to any call sites yet. This ships the cryptographic
 * primitive + in-memory DEK cache only. Migration plan and rollout phases
 * live in docs/ENVELOPE_ENCRYPTION_PLAN.md.
 *
 * ## Wire format
 *
 * `v3:<kek_version>:<base64(ciphertext_blob)>:<base64(iv)>:<base64(tag)>:<base64(payload)>`
 *
 *   - `v3` prefix is unambiguous (colon is not valid base64 or in legacy v1/v2)
 *   - `kek_version` lets us rotate the KMS master key without re-wrapping every
 *     row at rotation time. Old rows stay readable; new rows use the new KEK.
 *   - `ciphertext_blob` is the DEK wrapped by KMS. We hand it back to KMS on
 *     read to recover the plaintext DEK.
 *   - `iv` / `tag` / `payload` are standard AES-256-GCM output.
 *
 * ## DEK cache
 *
 * Unwrapping a DEK via KMS costs ~10–30 ms and a billed API call. Caching the
 * plaintext DEK keyed by the `ciphertext_blob` hash gives us O(1) decrypt for
 * recently-seen rows. TTL is short (matches the existing `encryption.ts`
 * pattern, default 60 s) so a leaked process memory window stays small.
 *
 * The cache key is the SHA-256 of the ciphertext_blob — **never** the plaintext
 * DEK. This prevents accidentally logging the cache keyspace.
 *
 * ## Testing
 *
 * The KMS client is abstracted behind a narrow `KmsClient` interface so tests
 * can inject a deterministic mock without pulling `@aws-sdk/client-kms` into
 * the test graph. Phase 1 lands the real SDK implementation as
 * `createAwsKmsClient()`.
 */

// biome-ignore lint/style/useNodejsImportProtocol: Vercel bundler requires bare "crypto" specifier
import * as crypto from "crypto";

const ALGORITHM = "aes-256-gcm";
const IV_LENGTH = 12;
const TAG_LENGTH = 16;
const DEK_LENGTH = 32; // AES-256 key length — matches KMS AES_256 spec
const VERSION_PREFIX = "v3";

export interface GenerateDataKeyResult {
	/** 32-byte AES key. Caller uses for a single encrypt, then zeroes out. */
	plaintext: Buffer;
	/** Opaque wrapped DEK. Persisted alongside the ciphertext. */
	ciphertextBlob: Buffer;
	/** Version of the KEK used. Persisted so rotation is possible later. */
	kekVersion: string;
}

export interface KmsClient {
	/** Generate a fresh DEK. Plaintext returned once; wrapped form is storage. */
	generateDataKey(): Promise<GenerateDataKeyResult>;
	/** Unwrap a ciphertext blob. Returns plaintext DEK bytes. */
	decrypt(ciphertextBlob: Buffer, kekVersion: string): Promise<Buffer>;
}

// ---------------------------------------------------------------------------
// DEK cache — keyed by SHA-256 of ciphertext blob, never by plaintext.
// ---------------------------------------------------------------------------

interface DekCacheEntry {
	key: Buffer;
	createdAt: number;
}

const _dekCache = new Map<string, DekCacheEntry>();
const MAX_DEK_CACHE_SIZE = 500;
const CACHE_TTL_MS = parseInt(
	process.env.ENVELOPE_DEK_CACHE_TTL_MS || "60000",
	10,
);

function cacheKeyFor(ciphertextBlob: Buffer): string {
	return crypto.createHash("sha256").update(ciphertextBlob).digest("hex");
}

function readCache(ciphertextBlob: Buffer): Buffer | null {
	const key = cacheKeyFor(ciphertextBlob);
	const entry = _dekCache.get(key);
	if (!entry) return null;
	if (Date.now() - entry.createdAt >= CACHE_TTL_MS) {
		_dekCache.delete(key);
		return null;
	}
	return entry.key;
}

function writeCache(ciphertextBlob: Buffer, plaintext: Buffer): void {
	// Opportunistic cleanup of expired entries before we hit the size cap.
	const now = Date.now();
	for (const [k, v] of _dekCache) {
		if (now - v.createdAt >= CACHE_TTL_MS) _dekCache.delete(k);
	}
	if (_dekCache.size >= MAX_DEK_CACHE_SIZE) {
		_dekCache.clear();
	}
	// Copy so the caller can zero its buffer without nulling our cached key.
	_dekCache.set(cacheKeyFor(ciphertextBlob), {
		key: Buffer.from(plaintext),
		createdAt: now,
	});
}

/**
 * Validate KMS-returned DEK length. Zeroes the buffer before throwing so we
 * never leak a partial key from a misbehaving KMS implementation.
 */
function assertDekLength(dek: Buffer): void {
	if (dek.length !== DEK_LENGTH) {
		const actual = dek.length;
		dek.fill(0);
		throw new Error(
			`KMS returned DEK of length ${actual}, expected ${DEK_LENGTH}`,
		);
	}
}

/** FOR TESTS ONLY — clears the DEK cache. */
export function _resetDekCacheForTests(): void {
	_dekCache.clear();
}

// ---------------------------------------------------------------------------
// Wire format helpers
// ---------------------------------------------------------------------------

function encodeEnvelope(
	kekVersion: string,
	ciphertextBlob: Buffer,
	iv: Buffer,
	tag: Buffer,
	payload: Buffer,
): string {
	return [
		VERSION_PREFIX,
		kekVersion,
		ciphertextBlob.toString("base64"),
		iv.toString("base64"),
		tag.toString("base64"),
		payload.toString("base64"),
	].join(":");
}

interface ParsedEnvelope {
	kekVersion: string;
	ciphertextBlob: Buffer;
	iv: Buffer;
	tag: Buffer;
	payload: Buffer;
}

function decodeEnvelope(wrapped: string): ParsedEnvelope {
	const parts = wrapped.split(":");
	if (parts.length !== 6) {
		throw new Error("Invalid envelope: expected 6 colon-separated fields");
	}
	if (parts[0] !== VERSION_PREFIX) {
		throw new Error(
			`Invalid envelope: unsupported version "${parts[0]}" (expected "${VERSION_PREFIX}")`,
		);
	}
	const [, kekVersion, blobB64, ivB64, tagB64, payloadB64] = parts;
	const iv = Buffer.from(ivB64!, "base64");
	const tag = Buffer.from(tagB64!, "base64");
	if (iv.length !== IV_LENGTH) {
		throw new Error(`Invalid envelope: IV length ${iv.length}, expected ${IV_LENGTH}`);
	}
	if (tag.length !== TAG_LENGTH) {
		throw new Error(`Invalid envelope: tag length ${tag.length}, expected ${TAG_LENGTH}`);
	}
	return {
		kekVersion: kekVersion!,
		ciphertextBlob: Buffer.from(blobB64!, "base64"),
		iv,
		tag,
		payload: Buffer.from(payloadB64!, "base64"),
	};
}

/** True if the string looks like an envelope-encrypted value (vs. legacy v1/v2). */
export function isEnvelope(s: string): boolean {
	return typeof s === "string" && s.startsWith(`${VERSION_PREFIX}:`);
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Encrypt a plaintext string using envelope encryption.
 *
 * Generates a fresh DEK via the KMS client, encrypts the payload with it, and
 * returns the combined envelope string. The plaintext DEK is zeroed in-memory
 * after use; only the wrapped form leaves this function.
 */
export async function encryptEnvelope(
	plaintext: string,
	kms: KmsClient,
): Promise<string> {
	if (typeof plaintext !== "string" || plaintext.length === 0) {
		throw new Error("encryptEnvelope: plaintext must be a non-empty string");
	}

	const { plaintext: dek, ciphertextBlob, kekVersion } =
		await kms.generateDataKey();
	assertDekLength(dek);

	try {
		const iv = crypto.randomBytes(IV_LENGTH);
		const cipher = crypto.createCipheriv(ALGORITHM, dek, iv);
		const payload = Buffer.concat([
			cipher.update(plaintext, "utf8"),
			cipher.final(),
		]);
		const tag = cipher.getAuthTag();

		// Warm the cache with this DEK so an immediate read hits cache.
		writeCache(ciphertextBlob, dek);

		return encodeEnvelope(kekVersion, ciphertextBlob, iv, tag, payload);
	} finally {
		dek.fill(0);
	}
}

/**
 * Decrypt an envelope-encrypted string.
 *
 * Cache hit → no KMS call. Miss → KMS.Decrypt is invoked to unwrap the DEK,
 * result is cached with TTL, then AES-GCM decrypts the payload.
 */
export async function decryptEnvelope(
	wrapped: string,
	kms: KmsClient,
): Promise<string> {
	if (typeof wrapped !== "string" || wrapped.length === 0) {
		throw new Error("decryptEnvelope: wrapped must be a non-empty string");
	}
	const { kekVersion, ciphertextBlob, iv, tag, payload } =
		decodeEnvelope(wrapped);

	const cached = readCache(ciphertextBlob);
	const fromCache = cached !== null;
	let dek: Buffer;
	if (cached) {
		dek = cached;
	} else {
		dek = await kms.decrypt(ciphertextBlob, kekVersion);
		assertDekLength(dek);
		writeCache(ciphertextBlob, dek);
	}

	try {
		const decipher = crypto.createDecipheriv(ALGORITHM, dek, iv);
		decipher.setAuthTag(tag);
		return Buffer.concat([
			decipher.update(payload),
			decipher.final(),
		]).toString("utf8");
	} finally {
		// Only zero the DEK if we just unwrapped it — cache owns its copy.
		if (!fromCache) dek.fill(0);
	}
}
