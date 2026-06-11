/**
 * Envelope encryption tests — Phase 0.
 *
 * The real KMS client lands in Phase 1. These tests drive a deterministic
 * mock that mirrors KMS.GenerateDataKey / KMS.Decrypt semantics: plaintext
 * DEK is random, ciphertextBlob is an opaque reference, kms.decrypt(blob)
 * returns the same bytes originally handed out for that blob.
 */

import * as nodeCrypto from "node:crypto";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
	_resetDekCacheForTests,
	decryptEnvelope,
	encryptEnvelope,
	isEnvelope,
	type KmsClient,
} from "@/api/_lib/envelope.js";

// ---------------------------------------------------------------------------
// Mock KMS client. Deterministic-ish: each call to generateDataKey returns a
// fresh random DEK + a random UUID as the ciphertext blob, and remembers the
// mapping so decrypt(blob) can return the same bytes.
// ---------------------------------------------------------------------------

interface MockKms extends KmsClient {
	callCountGenerate: number;
	callCountDecrypt: number;
	lastKekVersion: string;
	failNextDecrypt: boolean;
}

function makeMockKms(kekVersion = "v1"): MockKms {
	// blob hex -> canonical DEK bytes. Every entry/exit from this map is a
	// fresh Buffer copy — encryptEnvelope and decryptEnvelope both zero the
	// DEKs they're handed, which would poison the store if we shared refs.
	const store = new Map<string, Buffer>();
	const blobKey = (blob: Buffer) => blob.toString("hex");
	const mock: MockKms = {
		callCountGenerate: 0,
		callCountDecrypt: 0,
		lastKekVersion: kekVersion,
		failNextDecrypt: false,
		async generateDataKey() {
			mock.callCountGenerate += 1;
			const plaintext = nodeCrypto.randomBytes(32);
			const ciphertextBlob = nodeCrypto.randomBytes(48); // opaque, KMS-like
			store.set(blobKey(ciphertextBlob), Buffer.from(plaintext));
			return { plaintext, ciphertextBlob, kekVersion: mock.lastKekVersion };
		},
		async decrypt(ciphertextBlob, _kekVersion) {
			mock.callCountDecrypt += 1;
			if (mock.failNextDecrypt) {
				mock.failNextDecrypt = false;
				throw new Error("simulated KMS outage");
			}
			const hit = store.get(blobKey(ciphertextBlob));
			if (!hit) throw new Error("mock KMS: unknown ciphertext blob");
			return Buffer.from(hit); // fresh copy, caller may zero
		},
	};
	return mock;
}

beforeEach(() => {
	_resetDekCacheForTests();
});

afterEach(() => {
	_resetDekCacheForTests();
});

// ---------------------------------------------------------------------------
// Round-trip
// ---------------------------------------------------------------------------

describe("encryptEnvelope → decryptEnvelope", () => {
	it("round-trips a short ASCII string", async () => {
		const kms = makeMockKms();
		const wrapped = await encryptEnvelope("hello world", kms);
		expect(isEnvelope(wrapped)).toBe(true);
		const recovered = await decryptEnvelope(wrapped, kms);
		expect(recovered).toBe("hello world");
	});

	it("round-trips a realistic OAuth token (long, base64-ish)", async () => {
		const kms = makeMockKms();
		const token =
			"IGQW_long_fake_token_" + nodeCrypto.randomBytes(96).toString("base64");
		const wrapped = await encryptEnvelope(token, kms);
		const recovered = await decryptEnvelope(wrapped, kms);
		expect(recovered).toBe(token);
	});

	it("round-trips unicode content", async () => {
		const kms = makeMockKms();
		const input = "tokens can include… punctuation? ✓ 汉字 🔒";
		const wrapped = await encryptEnvelope(input, kms);
		const recovered = await decryptEnvelope(wrapped, kms);
		expect(recovered).toBe(input);
	});

	it("produces distinct ciphertexts for identical plaintext (fresh IV + DEK)", async () => {
		const kms = makeMockKms();
		const a = await encryptEnvelope("same input", kms);
		const b = await encryptEnvelope("same input", kms);
		expect(a).not.toBe(b);
		expect(await decryptEnvelope(a, kms)).toBe("same input");
		expect(await decryptEnvelope(b, kms)).toBe("same input");
	});
});

// ---------------------------------------------------------------------------
// Wire format
// ---------------------------------------------------------------------------

describe("wire format", () => {
	it("uses v3 prefix + 6 colon-separated fields", async () => {
		const kms = makeMockKms();
		const wrapped = await encryptEnvelope("x", kms);
		const parts = wrapped.split(":");
		expect(parts[0]).toBe("v3");
		expect(parts.length).toBe(6);
		expect(parts[1]).toBe("v1"); // kek_version from mock
	});

	it("embeds the kek_version returned by KMS", async () => {
		const kms = makeMockKms("v42");
		const wrapped = await encryptEnvelope("x", kms);
		expect(wrapped.split(":")[1]).toBe("v42");
	});

	it("isEnvelope() distinguishes from legacy v1/v2 strings", () => {
		expect(isEnvelope("v3:v1:AAAA:BBBB:CCCC:DDDD")).toBe(true);
		expect(isEnvelope("v2:some_base64_legacy_payload")).toBe(false);
		expect(isEnvelope("raw_base64_v1_token")).toBe(false);
		expect(isEnvelope("")).toBe(false);
	});
});

// ---------------------------------------------------------------------------
// DEK cache
// ---------------------------------------------------------------------------

describe("DEK cache", () => {
	it("avoids a KMS.decrypt call on repeated reads of the same wrapped value", async () => {
		const kms = makeMockKms();
		const wrapped = await encryptEnvelope("cached secret", kms);

		// First read goes through KMS (or the warm cache from encrypt).
		const baseline = kms.callCountDecrypt;
		await decryptEnvelope(wrapped, kms);
		await decryptEnvelope(wrapped, kms);
		await decryptEnvelope(wrapped, kms);

		// encryptEnvelope warms the cache, so all three decrypts should be
		// cache hits. If the cache were off, we'd see ≥1 KMS.decrypt.
		expect(kms.callCountDecrypt).toBe(baseline);
	});

	it("survives KMS being unavailable on subsequent reads (cache hit)", async () => {
		const kms = makeMockKms();
		const wrapped = await encryptEnvelope("cached secret", kms);
		kms.failNextDecrypt = true; // would throw if we tried to call KMS
		const recovered = await decryptEnvelope(wrapped, kms);
		expect(recovered).toBe("cached secret");
		expect(kms.callCountDecrypt).toBe(0); // confirm we didn't try
	});

	it("cache miss after reset forces a fresh KMS call", async () => {
		const kms = makeMockKms();
		const wrapped = await encryptEnvelope("x", kms);
		_resetDekCacheForTests();
		await decryptEnvelope(wrapped, kms);
		expect(kms.callCountDecrypt).toBe(1);
	});
});

// ---------------------------------------------------------------------------
// Tamper resistance
// ---------------------------------------------------------------------------

describe("tamper resistance", () => {
	it("rejects a flipped ciphertext byte (GCM auth tag catches it)", async () => {
		const kms = makeMockKms();
		const wrapped = await encryptEnvelope("untampered", kms);
		// Corrupt the payload (last field). base64 chars A→B is a 1-bit-ish flip.
		const parts = wrapped.split(":");
		const payload = Buffer.from(parts[5], "base64");
		payload[0] ^= 0x01;
		parts[5] = payload.toString("base64");
		const tampered = parts.join(":");

		// Bypass cache so we actually decrypt with the tampered payload.
		_resetDekCacheForTests();
		await expect(decryptEnvelope(tampered, kms)).rejects.toThrow();
	});

	it("rejects a tampered IV (GCM authenticates IV via tag)", async () => {
		const kms = makeMockKms();
		const wrapped = await encryptEnvelope("untampered", kms);
		const parts = wrapped.split(":");
		const iv = Buffer.from(parts[3], "base64");
		iv[0] ^= 0x01;
		parts[3] = iv.toString("base64");
		const tampered = parts.join(":");

		_resetDekCacheForTests();
		await expect(decryptEnvelope(tampered, kms)).rejects.toThrow();
	});
});

// ---------------------------------------------------------------------------
// Input validation
// ---------------------------------------------------------------------------

describe("input validation", () => {
	it("encryptEnvelope rejects empty string", async () => {
		const kms = makeMockKms();
		await expect(encryptEnvelope("", kms)).rejects.toThrow(/non-empty/);
	});

	it("decryptEnvelope rejects empty string", async () => {
		const kms = makeMockKms();
		await expect(decryptEnvelope("", kms)).rejects.toThrow(/non-empty/);
	});

	it("decryptEnvelope rejects wrong version prefix", async () => {
		const kms = makeMockKms();
		await expect(
			decryptEnvelope("v2:AAAA:BBBB:CCCC:DDDD:EEEE", kms),
		).rejects.toThrow(/unsupported version/);
	});

	it("decryptEnvelope rejects malformed field count", async () => {
		const kms = makeMockKms();
		await expect(
			decryptEnvelope("v3:v1:AAAA:BBBB", kms),
		).rejects.toThrow(/6 colon-separated/);
	});

	it("decryptEnvelope rejects bad IV length", async () => {
		const kms = makeMockKms();
		// 6 colon-separated fields; IV (4th) is empty-string → length 0.
		await expect(
			decryptEnvelope("v3:v1:AAAA::CCCC:DDDD", kms),
		).rejects.toThrow(/IV length/);
	});
});
