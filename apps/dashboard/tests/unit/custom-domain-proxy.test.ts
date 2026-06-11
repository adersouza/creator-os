import { beforeEach, describe, expect, it, vi } from "vitest";

const mockFrom = vi.fn();
const mockCheckRateLimit = vi.fn();

function chain(data: unknown) {
	const query: any = {
		select: vi.fn(() => query),
		eq: vi.fn(() => query),
		maybeSingle: vi.fn().mockResolvedValue({ data, error: null }),
	};
	return query;
}

vi.mock("@/api/_lib/supabase.js", () => ({
	getSupabaseAny: () => ({ from: mockFrom }),
}));

vi.mock("@/api/_lib/rateLimiter.js", () => ({
	checkRateLimit: (...args: unknown[]) => mockCheckRateLimit(...args),
}));

vi.mock("@/api/_lib/logger.js", () => ({
	logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

vi.mock("@/api/_lib/apiResponse.js", () => ({
	apiError: (res: any, status: number, message: string) =>
		res.status(status).json({ error: message }),
}));

import handler from "@/api/link-page/domain";

function makeRes() {
	const res: any = {
		headers: new Map<string, string>(),
		statusCode: 200,
		body: "",
	};
	res.setHeader = vi.fn((key: string, value: string) => {
		res.headers.set(key.toLowerCase(), value);
		return res;
	});
	res.status = vi.fn((status: number) => {
		res.statusCode = status;
		return res;
	});
	res.send = vi.fn((body: string) => {
		res.body = body;
		return res;
	});
	res.json = vi.fn((body: unknown) => {
		res.body = JSON.stringify(body);
		return res;
	});
	return res;
}

function stubDomainLookup({
	page,
	smartLink,
}: {
	page?: unknown;
	smartLink?: unknown;
}) {
	mockFrom.mockImplementation((table: string) => {
		if (table === "link_pages") return chain(page ?? null);
		if (table === "smart_links") return chain(smartLink ?? null);
		throw new Error(`Unexpected table ${table}`);
	});
}

describe("custom-domain proxy", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockCheckRateLimit.mockResolvedValue({ allowed: true });
		process.env.APP_URL = "https://juno33.com";
		vi.stubGlobal(
			"fetch",
			vi.fn().mockResolvedValue({
				status: 204,
				headers: { get: vi.fn(() => null) },
				text: vi.fn().mockResolvedValue(""),
			}),
		);
	});

	it("proxies smart-link domain POSTs to the /go route without quoting beacon bodies", async () => {
		stubDomainLookup({ smartLink: { code: "abc123" } });
		const res = makeRes();

		await handler(
			{
				method: "POST",
				url: "/?utm_source=ig&utm_campaign=spring",
				body: '{"eventName":"destination_click"}',
				headers: {
					host: "go.example.com",
					"content-type": "application/json",
					"x-forwarded-proto": "https",
				},
			} as any,
			res as any,
		);

		expect(fetch).toHaveBeenCalledWith(
			"https://juno33.com/api/go/abc123?utm_source=ig&utm_campaign=spring",
			expect.objectContaining({
				method: "POST",
				body: '{"eventName":"destination_click"}',
				headers: expect.objectContaining({
					"Content-Type": "application/json",
					"X-Public-Link-Origin": "https://go.example.com",
				}),
			}),
		);
		expect(res.status).toHaveBeenCalledWith(204);
	});

	it("proxies link-page click beacons to the tracking endpoint on custom domains", async () => {
		stubDomainLookup({ page: { slug: "creator" } });
		const res = makeRes();

		await handler(
			{
				method: "POST",
				url: "/api/link-page/domain",
				body: { pageId: "page-1", linkId: "link-1", token: "signed" },
				headers: {
					host: "links.example.com",
					"content-type": "application/json",
					"x-forwarded-uri": "/api/link-page/track",
				},
			} as any,
			res as any,
		);

		expect(fetch).toHaveBeenCalledWith(
			"https://juno33.com/api/link-page/track",
			expect.objectContaining({
				method: "POST",
				body: JSON.stringify({
					pageId: "page-1",
					linkId: "link-1",
					token: "signed",
				}),
			}),
		);
		expect(res.status).toHaveBeenCalledWith(204);
	});
});
