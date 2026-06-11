import { describe, expect, it } from "vitest";
import {
	sanitizeHtml,
	sanitizeMessage,
	validateMessageLength,
} from "../sanitize.js";

describe("sanitizeHtml", () => {
	it("strips HTML tags", () => {
		expect(sanitizeHtml("<b>bold</b>")).not.toContain("<b>");
	});

	it("removes script tags", () => {
		const input = '<script>alert("xss")</script>hello';
		const result = sanitizeHtml(input);
		expect(result).not.toContain("script");
		expect(result).toContain("hello");
	});

	it("strips content that looks like tags", () => {
		// The sanitizer strips HTML tags first, then escapes remaining chars
		const result = sanitizeHtml("a < b > c");
		expect(result).not.toContain("<");
		expect(result).not.toContain(">");
	});

	it("handles empty string", () => {
		expect(sanitizeHtml("")).toBe("");
	});

	it("removes null bytes", () => {
		expect(sanitizeHtml("hello\0world")).not.toContain("\0");
	});

	it("escapes quotes", () => {
		const result = sanitizeHtml("say \"hello\" & 'bye'");
		expect(result).toContain("&quot;");
		expect(result).toContain("&#x27;");
	});

	it("handles SQL injection strings safely", () => {
		const input = "'; DROP TABLE users; --";
		const result = sanitizeHtml(input);
		expect(result).toContain("&#x27;");
		// The dangerous characters are escaped
		expect(result).not.toContain("'");
	});

	it("handles event handler attributes", () => {
		const input = '<img onerror="alert(1)" src="x">';
		const result = sanitizeHtml(input);
		expect(result).not.toContain("onerror");
	});
});

describe("sanitizeMessage", () => {
	it("sanitizes message content", () => {
		expect(sanitizeMessage("<script>alert(1)</script>")).not.toContain(
			"script",
		);
	});
});

describe("validateMessageLength", () => {
	it("accepts valid message", () => {
		expect(validateMessageLength("hello").valid).toBe(true);
	});

	it("rejects empty message", () => {
		expect(validateMessageLength("").valid).toBe(false);
	});

	it("rejects whitespace-only message", () => {
		expect(validateMessageLength("   ").valid).toBe(false);
	});

	it("rejects message exceeding max length", () => {
		expect(validateMessageLength("x".repeat(1001)).valid).toBe(false);
	});

	it("accepts message at exact max length", () => {
		expect(validateMessageLength("x".repeat(1000)).valid).toBe(true);
	});

	it("respects custom max length", () => {
		expect(validateMessageLength("hello", 3).valid).toBe(false);
	});
});
