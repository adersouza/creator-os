import { describe, expect, it, vi } from "vitest";
import { withRetry } from "../api/_lib/retryUtils";

describe("withRetry", () => {
	it("retries fetch-style HTTP 5xx responses", async () => {
		const call = vi
			.fn<() => Promise<Response>>()
			.mockResolvedValueOnce(new Response("bad gateway", { status: 502 }))
			.mockResolvedValueOnce(new Response("ok", { status: 200 }));

		const response = await withRetry(call, {
			maxRetries: 1,
			baseDelayMs: 0,
			maxDelayMs: 0,
		});

		expect(response.status).toBe(200);
		expect(call).toHaveBeenCalledTimes(2);
	});

	it("does not retry fetch-style HTTP 4xx responses", async () => {
		const call = vi
			.fn<() => Promise<Response>>()
			.mockResolvedValue(new Response("bad request", { status: 400 }));

		const response = await withRetry(call, {
			maxRetries: 1,
			baseDelayMs: 0,
			maxDelayMs: 0,
		});

		expect(response.status).toBe(400);
		expect(call).toHaveBeenCalledTimes(1);
	});
});
