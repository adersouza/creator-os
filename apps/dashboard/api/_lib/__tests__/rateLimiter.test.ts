import { describe, expect, it, vi } from "vitest";
import { apiError, rateLimited } from "../apiResponse.js";

/**
 * Tests for rate limiting response patterns.
 * The actual rate limiting in production uses Supabase RPC calls;
 * here we test the response helpers and patterns.
 */

interface MockResponse {
	status: ReturnType<typeof vi.fn>;
	json: ReturnType<typeof vi.fn>;
}

// biome-ignore lint/suspicious/noExplicitAny: test mock
function mockRes(): any {
	const res = {} as MockResponse;
	res.status = vi.fn().mockReturnValue(res);
	res.json = vi.fn().mockReturnValue(res);
	return res;
}

describe("rateLimited response", () => {
	it("sends 429 status", () => {
		const res = mockRes();
		rateLimited(res);
		expect(res.status).toHaveBeenCalledWith(429);
	});

	it("includes RATE_LIMITED code", () => {
		const res = mockRes();
		rateLimited(res);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ code: "RATE_LIMITED" }),
		);
	});

	it("uses custom message", () => {
		const res = mockRes();
		rateLimited(res, "Too many requests, slow down");
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "Too many requests, slow down" }),
		);
	});

	it("uses default message when none provided", () => {
		const res = mockRes();
		rateLimited(res);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "Rate limit exceeded" }),
		);
	});
});

describe("rate limit error via apiError", () => {
	it("can send 429 with custom code via apiError", () => {
		const res = mockRes();
		apiError(res, 429, "Throttled", { code: "RATE_LIMITED" });
		expect(res.status).toHaveBeenCalledWith(429);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "Throttled", code: "RATE_LIMITED" }),
		);
	});
});
