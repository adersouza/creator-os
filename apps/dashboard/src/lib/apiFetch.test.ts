import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { z } from "zod";
import {
	apiFetch,
	type ApiHttpError,
	type ApiTimeoutError,
	type ApiValidationError,
} from "@/lib/apiFetch";

vi.mock("@/lib/apiAuth", () => ({
	getApiAuthHeaders: vi.fn().mockResolvedValue({ Authorization: "Bearer token" }),
}));

vi.mock("@/lib/apiUrl", () => ({
	apiUrl: (path: string) => path,
}));

vi.mock("@/lib/uuid", () => ({
	randomUUID: () => "client-request-id",
}));

function jsonResponse(
	body: unknown,
	init: { status?: number; headers?: Record<string, string> } = {},
) {
	return new Response(JSON.stringify(body), {
		status: init.status ?? 200,
		headers: {
			"content-type": "application/json",
			...(init.headers ?? {}),
		},
	});
}

describe("apiFetch", () => {
	beforeEach(() => {
		vi.useRealTimers();
		vi.stubGlobal("fetch", vi.fn());
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it("sends and preserves request ids on successful requests", async () => {
		(globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
			jsonResponse({ ok: true }),
		);

		const result = await apiFetch("/api/test", z.object({ ok: z.boolean() }));

		expect(result).toEqual({ ok: true });
		expect(globalThis.fetch).toHaveBeenCalledWith(
			"/api/test",
			expect.objectContaining({
				headers: expect.objectContaining({
					Authorization: "Bearer token",
					"x-request-id": "client-request-id",
				}),
			}),
		);
	});

	it("attaches backend request id and retry-after to HTTP errors", async () => {
		(globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
			jsonResponse(
				{ error: "slow down" },
				{
					status: 429,
					headers: { "x-request-id": "server-request-id", "retry-after": "12" },
				},
			),
		);

		await expect(apiFetch("/api/test", z.object({ ok: z.boolean() }))).rejects.toMatchObject({
			name: "ApiHttpError",
			status: 429,
			requestId: "server-request-id",
			retryAfter: 12,
		} satisfies Partial<ApiHttpError>);
	});

	it("attaches request id to validation errors", async () => {
		(globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
			jsonResponse({ ok: "yes" }, { headers: { "x-request-id": "server-request-id" } }),
		);

		await expect(apiFetch("/api/test", z.object({ ok: z.boolean() }))).rejects.toMatchObject({
			name: "ApiValidationError",
			requestId: "server-request-id",
		} satisfies Partial<ApiValidationError>);
	});

	it("classifies timed out requests", async () => {
		vi.useFakeTimers();
		(globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
			(_url: string, init: RequestInit) =>
				new Promise((_resolve, reject) => {
					init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
				}),
		);

		const promise = apiFetch("/api/test", z.object({ ok: z.boolean() }), {
			timeoutMs: 50,
		});
		const assertion = expect(promise).rejects.toMatchObject({
			name: "ApiTimeoutError",
			requestId: "client-request-id",
			timeoutMs: 50,
		} satisfies Partial<ApiTimeoutError>);
		await vi.advanceTimersByTimeAsync(50);

		await assertion;
	});
});
