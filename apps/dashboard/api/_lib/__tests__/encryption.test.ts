// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import * as crypto from "node:crypto";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { decrypt, encrypt } from "../encryption.js";

const TEST_KEY = crypto.randomBytes(32).toString("base64");
let savedKey: string | undefined;

beforeEach(() => {
	savedKey = process.env.ENCRYPTION_KEY;
	process.env.ENCRYPTION_KEY = TEST_KEY;
});

afterEach(() => {
	if (savedKey !== undefined) {
		process.env.ENCRYPTION_KEY = savedKey;
	} else {
		delete process.env.ENCRYPTION_KEY;
	}
});

describe("encrypt/decrypt round-trip", () => {
	it("roundtrips a simple string", () => {
		const input = "hello world";
		expect(decrypt(encrypt(input))).toBe(input);
	});

	it("roundtrips an empty string", () => {
		expect(decrypt(encrypt(""))).toBe("");
	});

	it("roundtrips unicode/emoji content", () => {
		const input = "café ☕ 日本語 🎉";
		expect(decrypt(encrypt(input))).toBe(input);
	});

	it("roundtrips a long string (10KB)", () => {
		const input = "x".repeat(10000);
		expect(decrypt(encrypt(input))).toBe(input);
	});

	it("roundtrips JSON content", () => {
		const input = JSON.stringify({ token: "abc123", userId: 42 });
		expect(decrypt(encrypt(input))).toBe(input);
	});

	it("roundtrips special characters", () => {
		const input = "line1\nline2\ttab\r\nwindows\0null";
		expect(decrypt(encrypt(input))).toBe(input);
	});

	it("roundtrips a realistic access token", () => {
		const input = "EAAGm0PX4ZCps...long-base64-token-from-meta";
		expect(decrypt(encrypt(input))).toBe(input);
	});
});

describe("encrypt output properties", () => {
	it("produces different ciphertexts for same input (random IV/salt)", () => {
		const input = "determinism check";
		const a = encrypt(input);
		const b = encrypt(input);
		expect(a).not.toBe(b);
		// But both decrypt to the same value
		expect(decrypt(a)).toBe(input);
		expect(decrypt(b)).toBe(input);
	});

	it("produces different ciphertexts for different inputs", () => {
		const a = encrypt("input-one");
		const b = encrypt("input-two");
		expect(a).not.toBe(b);
	});

	it("output is valid base64", () => {
		const encrypted = encrypt("test data");
		expect(() => Buffer.from(encrypted, "base64")).not.toThrow();
		// Re-encoding should match (valid base64 roundtrips)
		const buf = Buffer.from(encrypted, "base64");
		expect(buf.toString("base64")).toBe(encrypted);
	});

	it("output has minimum length (salt + iv + tag = 60 bytes)", () => {
		const encrypted = encrypt("");
		const buf = Buffer.from(encrypted, "base64");
		// Even empty string: 32 (salt) + 12 (iv) + 16 (tag) = 60 bytes minimum
		expect(buf.length).toBeGreaterThanOrEqual(60);
	});
});

describe("decrypt error handling", () => {
	it("detects tampered ciphertext (flipped byte in encrypted portion)", () => {
		const encrypted = encrypt("secret");
		const buf = Buffer.from(encrypted, "base64");
		// Flip a byte in the encrypted portion (after salt+iv+tag = 32+12+16 = 60)
		if (buf.length > 61) buf[61]! ^= 0xff;
		const tampered = buf.toString("base64");
		expect(() => decrypt(tampered)).toThrow();
	});

	it("detects tampered auth tag", () => {
		const encrypted = encrypt("secret data");
		const buf = Buffer.from(encrypted, "base64");
		// Flip byte in auth tag region (bytes 44-59)
		buf[45]! ^= 0xff;
		const tampered = buf.toString("base64");
		expect(() => decrypt(tampered)).toThrow();
	});

	it("throws on completely invalid base64", () => {
		expect(() => decrypt("not-valid-base64!!!")).toThrow();
	});

	it("throws on data too short (less than salt + iv + tag)", () => {
		// 59 bytes is less than 60 (32+12+16) minimum
		const shortData = crypto.randomBytes(59).toString("base64");
		expect(() => decrypt(shortData)).toThrow("Invalid encrypted data");
	});

	it("throws on empty string input to decrypt", () => {
		// Empty base64 → 0 bytes → less than minimum
		expect(() => decrypt("")).toThrow();
	});

	it("fails to decrypt when salt is replaced (simulating wrong key derivation)", () => {
		const encrypted = encrypt("secret-value");
		const buf = Buffer.from(encrypted, "base64");
		// Replace the salt (first 32 bytes) with random bytes so the cache misses
		// and deriveKey re-derives with the same ENCRYPTION_KEY but different salt,
		// producing a different AES key that won't match the original ciphertext
		const newSalt = crypto.randomBytes(32);
		newSalt.copy(buf, 0);
		const modified = buf.toString("base64");
		expect(() => decrypt(modified)).toThrow();
	});

	it("ciphertext encrypted with key A cannot be decrypted by fresh derivation with key B", () => {
		// Encrypt with key A
		const keyA = crypto.randomBytes(32).toString("base64");
		process.env.ENCRYPTION_KEY = keyA;
		const encrypted = encrypt("secret-value");

		// Manually construct what decryption with key B would produce:
		// Extract salt from ciphertext, derive key using a different master key
		const buf = Buffer.from(encrypted, "base64");
		const salt = buf.subarray(0, 32);
		const iv = buf.subarray(32, 44);
		const tag = buf.subarray(44, 60);
		const ciphertext = buf.subarray(60);

		const keyB = crypto.randomBytes(32).toString("base64");
		const masterKeyB = Buffer.from(keyB, "base64");
		const derivedB = crypto.pbkdf2Sync(masterKeyB, salt, 100000, 32, "sha256");

		const decipher = crypto.createDecipheriv("aes-256-gcm", derivedB, iv);
		decipher.setAuthTag(tag);

		expect(() => {
			Buffer.concat([decipher.update(ciphertext), decipher.final()]);
		}).toThrow();
	});
});

describe("ENCRYPTION_KEY validation", () => {
	it("throws when ENCRYPTION_KEY is missing for encrypt", () => {
		delete process.env.ENCRYPTION_KEY;
		expect(() => encrypt("test")).toThrow("ENCRYPTION_KEY");
	});

	it("throws when ENCRYPTION_KEY is missing and salt is not cached", () => {
		// Use a fresh salt that was never cached by creating raw ciphertext
		const fakeSalt = crypto.randomBytes(32);
		const fakeIv = crypto.randomBytes(12);
		const fakeTag = crypto.randomBytes(16);
		const fakeEncrypted = crypto.randomBytes(10);
		const buf = Buffer.concat([fakeSalt, fakeIv, fakeTag, fakeEncrypted]);
		const encoded = buf.toString("base64");

		delete process.env.ENCRYPTION_KEY;
		expect(() => decrypt(encoded)).toThrow("ENCRYPTION_KEY");
	});
});
