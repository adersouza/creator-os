/**
 * AES-256-GCM Encryption Utility for Vercel API Routes
 *
 * Encrypts/decrypts Threads access tokens before storing in Supabase
 *
 * ## Format versions
 * v1 (legacy): raw base64 string  — layout: salt[32] + iv[12] + tag[16] + ciphertext
 *              PBKDF2-SHA256 at 100,000 iterations (old OWASP recommendation)
 *
 * v2 (current): "v2:" + base64 string — same binary layout
 *               PBKDF2-SHA256 at 600,000 iterations (OWASP 2023 recommendation)
 *               Colons are not valid base64 characters, so the prefix is unambiguous.
 *
 * Migration: encrypt() always produces v2. decrypt() auto-detects the version.
 * The token-refresh cron lazily re-encrypts v1 tokens to v2 over time.
 */

// biome-ignore lint/style/useNodejsImportProtocol: Vercel bundler requires bare "crypto" specifier
import * as crypto from "crypto";

const ALGORITHM = "aes-256-gcm";
const IV_LENGTH = 12; // Must match Firebase encryption (12 bytes for GCM)
const TAG_LENGTH = 16;
const SALT_LENGTH = 32; // Must match Firebase encryption (32 bytes)
const KEY_LENGTH = 32;

// OWASP iteration counts
const ITERATIONS_V1 = 100_000; // Legacy — used for decrypting existing v1 tokens only
const ITERATIONS_V2 = 600_000; // Current OWASP 2023 recommendation for PBKDF2-HMAC-SHA256

// Version prefix — colon is not a valid base64 char, so this is unambiguous
const V2_PREFIX = "v2:";

function getEncryptionKey(): string {
	const key = process.env.ENCRYPTION_KEY;
	if (!key) {
		throw new Error("ENCRYPTION_KEY environment variable is not set");
	}
	return key;
}

// In-memory cache for derived keys with TTL.
// Avoids calling pbkdf2Sync (600k iterations) on every decrypt call.
// Cache key includes iteration count: same salt + different iterations = different key.
interface DerivedKeyCacheEntry {
	key: Buffer;
	createdAt: number;
}
const _derivedKeyCache = new Map<string, DerivedKeyCacheEntry>();
const MAX_DERIVED_KEY_CACHE_SIZE = 500;
// #713: TTL is configurable via ENCRYPTION_KEY_CACHE_TTL_MS env var (default: 60s)
const CACHE_TTL_MS = parseInt(
	process.env.ENCRYPTION_KEY_CACHE_TTL_MS || "60000",
	10,
);

function deriveKey(salt: Buffer, iterations: number): Buffer {
	// Include iterations in cache key — same salt + different iterations = different derived key
	const cacheKey = `${salt.toString("hex")}:${iterations}`;
	const now = Date.now();

	// Check cache with TTL
	const cached = _derivedKeyCache.get(cacheKey);
	if (cached && now - cached.createdAt < CACHE_TTL_MS) {
		return cached.key;
	}

	// Evict expired entries first
	for (const [k, v] of _derivedKeyCache) {
		if (now - v.createdAt >= CACHE_TTL_MS) {
			_derivedKeyCache.delete(k);
		}
	}

	// Size limit fallback
	if (_derivedKeyCache.size >= MAX_DERIVED_KEY_CACHE_SIZE) {
		_derivedKeyCache.clear();
	}

	// Must decode base64 key to bytes first, matching Firebase encryption
	const masterKey = Buffer.from(getEncryptionKey(), "base64");
	const derived = crypto.pbkdf2Sync(
		masterKey,
		salt,
		iterations,
		KEY_LENGTH,
		"sha256",
	);

	_derivedKeyCache.set(cacheKey, { key: derived, createdAt: now });

	return derived;
}

/**
 * Encrypt a string using AES-256-GCM.
 * Always produces v2 format (600k PBKDF2 iterations, "v2:" prefix).
 */
export function encrypt(text: string): string {
	const salt = crypto.randomBytes(SALT_LENGTH);
	const iv = crypto.randomBytes(IV_LENGTH);
	const key = deriveKey(salt, ITERATIONS_V2);

	const cipher = crypto.createCipheriv(ALGORITHM, key, iv);
	const encrypted = Buffer.concat([
		cipher.update(text, "utf8"),
		cipher.final(),
	]);
	const tag = cipher.getAuthTag();

	// Binary layout: salt + iv + tag + encrypted (same as v1)
	const result = Buffer.concat([salt, iv, tag, encrypted]);
	return V2_PREFIX + result.toString("base64");
}

/**
 * Returns true if the token was encrypted with v1 (100k iterations) and
 * should be lazily re-encrypted to v2 (600k iterations).
 *
 * Filters out empty strings and obvious garbage (length below the minimum
 * plausible v1 ciphertext) so the migration cron doesn't retry bad data
 * forever. A valid v1 ciphertext is at least base64(salt[32] + iv[12] +
 * tag[16] + 1 byte) ≈ 81 chars; we use 60 as a conservative floor to avoid
 * false-negatives on any odd historical edge cases.
 */
export function needsUpgrade(encryptedText: string): boolean {
	if (!encryptedText || typeof encryptedText !== "string") return false;
	if (encryptedText.length < 60) return false;
	return !encryptedText.startsWith(V2_PREFIX);
}

/**
 * Clears the derived-key cache. FOR TESTS ONLY.
 * Prefer this over vi.resetModules() — it clears only the cache state,
 * not the entire module, which is cleaner and faster.
 */
export function _resetCacheForTests(): void {
	_derivedKeyCache.clear();
}

/**
 * Internal decryption implementation. Handles both v1 and v2 formats.
 */
function decryptOnce(encryptedText: string): string {
	const isV2 = encryptedText.startsWith(V2_PREFIX);
	const iterations = isV2 ? ITERATIONS_V2 : ITERATIONS_V1;
	const b64 = isV2 ? encryptedText.slice(V2_PREFIX.length) : encryptedText;

	const buffer = Buffer.from(b64, "base64");
	const minLength = SALT_LENGTH + IV_LENGTH + TAG_LENGTH + 1; // at least 1 byte of data
	if (buffer.length < minLength) {
		throw new Error("Invalid encrypted data: too short");
	}

	const salt = buffer.subarray(0, SALT_LENGTH);
	const iv = buffer.subarray(SALT_LENGTH, SALT_LENGTH + IV_LENGTH);
	const tag = buffer.subarray(
		SALT_LENGTH + IV_LENGTH,
		SALT_LENGTH + IV_LENGTH + TAG_LENGTH,
	);
	const encrypted = buffer.subarray(SALT_LENGTH + IV_LENGTH + TAG_LENGTH);

	const key = deriveKey(salt, iterations);

	const decipher = crypto.createDecipheriv(ALGORITHM, key, iv);
	decipher.setAuthTag(tag);

	const decrypted = Buffer.concat([
		decipher.update(encrypted),
		decipher.final(),
	]);

	return decrypted.toString("utf8");
}

/**
 * Decrypt a string using AES-256-GCM. Handles v1 (100k) and v2 (600k) formats.
 *
 * #472: Retries once on transient failures (e.g., derived key cache eviction
 * race, key rotation mid-flight). If both attempts fail, throws the original error.
 */
export function decrypt(encryptedText: string): string {
	if (!encryptedText || typeof encryptedText !== "string") {
		throw new Error("Invalid encrypted text: expected non-empty string");
	}
	try {
		return decryptOnce(encryptedText);
	} catch (firstError) {
		// Evict only this token's derived-key cache entry (not the whole cache).
		// Clearing the entire cache would force full PBKDF2 re-derivation for every
		// concurrently active token — a significant CPU spike under load.
		try {
			const isV2 = encryptedText.startsWith(V2_PREFIX);
			const iterations = isV2 ? ITERATIONS_V2 : ITERATIONS_V1;
			const b64 = isV2 ? encryptedText.slice(V2_PREFIX.length) : encryptedText;
			const buf = Buffer.from(b64, "base64");
			if (buf.length >= SALT_LENGTH) {
				// First 32 bytes are the salt (see encrypt() for layout)
				const cacheKey = `${buf.subarray(0, SALT_LENGTH).toString("hex")}:${iterations}`;
				_derivedKeyCache.delete(cacheKey);
			} else {
				// Malformed ciphertext — clear fully so no stale entry blocks recovery
				_derivedKeyCache.clear();
			}
		} catch {
			// Buffer parse failed — clear fully as a safe fallback
			_derivedKeyCache.clear();
		}
		try {
			return decryptOnce(encryptedText);
		} catch {
			// Both attempts failed — throw the original error for clearer diagnostics
			throw firstError;
		}
	}
}
