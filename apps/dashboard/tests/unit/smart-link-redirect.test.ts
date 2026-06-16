import { beforeEach, describe, expect, it, vi } from "vitest";

const mockRpc = vi.fn();
const mockInsertClick = vi.fn();
const mockMaybeSingleClick = vi.fn();

const smartLink = {
	id: "link-1",
	code: "abc123",
	target_url: "https://example.com/checkout",
	title: "Test Offer",
	ig_deep_link: "instagram://user?username=test",
	threads_deep_link: "barcelona://user/123",
	ig_redirect_url: null,
	threads_redirect_url: null,
	mobile_redirect_url: null,
	is_active: true,
	enable_deep_links: true,
	blocks: null,
	metadata: {
		appearance: {
			displayTitle: "Creator VIP",
			subtitle: "Tap once to open the page.",
			ctaLabel: "View Profile",
			avatarUrl: "https://cdn.example.com/avatar.jpg",
			imageUrls: [
				"https://cdn.example.com/one.jpg",
				"https://cdn.example.com/two.jpg",
			],
		},
	},
};

let currentSmartLink = smartLink;

function chain(finalValue: unknown) {
	const query: any = {
		select: vi.fn(() => query),
		eq: vi.fn(() => query),
		gte: vi.fn(() => query),
		maybeSingle: vi.fn().mockResolvedValue(finalValue),
	};
	return query;
}

const mockFrom = vi.fn((table: string) => {
	if (table === "smart_links") {
		return chain({ data: currentSmartLink, error: null });
	}
	if (table === "smart_link_clicks") {
		const query = chain({ data: null, error: null });
		query.maybeSingle = mockMaybeSingleClick;
		query.insert = mockInsertClick;
		return query;
	}
	throw new Error(`Unexpected table ${table}`);
});

vi.mock("@/api/_lib/supabase.js", () => ({
	getSupabase: () => ({ rpc: mockRpc }),
	getSupabaseAny: () => ({ from: mockFrom, rpc: mockRpc }),
}));

vi.mock("@/api/_lib/privilegedDb.js", () => ({
	PRIVILEGED_DB_REASONS: { publicLinkRedirect: "public_link_redirect" },
	getPrivilegedSupabase: () => ({ from: mockFrom, rpc: mockRpc }),
	getPrivilegedSupabaseAny: () => ({ from: mockFrom, rpc: mockRpc }),
}));

vi.mock("@/api/_lib/rateLimiter.js", () => ({
	checkRateLimit: vi.fn().mockResolvedValue({ allowed: true }),
}));

vi.mock("@/api/_lib/outboundUrlSecurity.js", () => ({
	validatePublicRedirectUrl: vi.fn().mockResolvedValue(null),
}));

vi.mock("@/api/_lib/redisCache.js", () => ({
	cached: vi.fn(async (_key: string, _ttl: number, fn: () => Promise<unknown>) =>
		fn(),
	),
}));

vi.mock("@/api/_lib/logger.js", () => ({
	logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

vi.mock("@/api/_lib/apiResponse.js", () => ({
	apiError: (res: any, status: number, message: string) =>
		res.status(status).json({ error: message }),
}));

import handler from "@/api/go/[code]";

function makeReq(userAgent: string) {
	return {
		method: "GET",
		query: { code: "abc123" },
		headers: {
			"user-agent": userAgent,
			"x-forwarded-for": "203.0.113.10",
		},
	} as any;
}

function makePostReq(userAgent: string) {
	return {
		...makeReq(userAgent),
		method: "POST",
		body: { eventName: "destination_click" },
	} as any;
}

function makeHeadReq(userAgent: string) {
	return {
		...makeReq(userAgent),
		method: "HEAD",
	} as any;
}

function makeRes() {
	const res: any = {
		headers: new Map<string, string>(),
		body: "",
		statusCode: 200,
		redirectStatus: 0,
		redirectLocation: "",
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
	res.end = vi.fn(() => res);
	res.json = vi.fn((body: unknown) => {
		res.body = JSON.stringify(body);
		return res;
	});
	res.redirect = vi.fn((status: number, url: string) => {
		res.redirectStatus = status;
		res.redirectLocation = url;
		return res;
	});
	return res;
}

describe("smart link redirect route", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		currentSmartLink = smartLink;
		mockRpc.mockResolvedValue({ error: null });
		mockInsertClick.mockResolvedValue({ error: null });
		mockMaybeSingleClick.mockResolvedValue({ data: null, error: null });
	});

	it("redirects desktop visitors to the canonical target", async () => {
		const res = makeRes();

		await handler(
			makeReq(
				"Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/537.36 Chrome/130 Safari/537.36",
			),
			res,
		);

		expect(res.redirect).toHaveBeenCalledWith(
			302,
			expect.stringContaining("https://example.com/checkout"),
		);
	});

	it("supports HEAD checks for desktop links without counting clicks", async () => {
		const res = makeRes();

		await handler(
			makeHeadReq(
				"Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/537.36 Chrome/130 Safari/537.36",
			),
			res,
		);

		expect(res.redirect).toHaveBeenCalledWith(
			302,
			expect.stringContaining("https://example.com/checkout"),
		);
		expect(mockInsertClick).not.toHaveBeenCalled();
		expect(mockRpc).not.toHaveBeenCalled();
	});

	it("serves an explicit in-app interstitial without auto-launch script", async () => {
		const res = makeRes();

		await handler(
			makeReq(
				"Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Instagram 356.0.0.0.0",
			),
			res,
		);

		expect(res.statusCode).toBe(200);
		expect(res.body).toContain("Creator VIP");
		expect(res.body).toContain("Tap once to open the page.");
		expect(res.body).toContain("View Profile");
		expect(res.body).toContain("https://cdn.example.com/avatar.jpg");
		expect(res.body).toContain("https://cdn.example.com/one.jpg");
		expect(res.body).toContain(
			'<meta property="og:image" content="https://juno33.com/og-image.png">',
		);
		expect(res.body).toContain("Destination: example.com");
		expect(res.body).toContain("No hidden redirects or auto-launches.");
		expect(res.body).toContain("Copy Link");
		expect(res.body).toContain("data-track-destination");
		expect(res.body).not.toContain("Online now");
		expect(res.body).not.toContain("6.9 miles away");
		expect(res.body).not.toContain("@abc123");
		expect(res.body).toContain('<link rel="canonical"');
		expect(res.body).toContain('property="og:title"');
		expect(res.body).toContain('property="og:image"');
		expect(res.headers.get("content-security-policy")).toContain(
			"https://cdn.example.com",
		);
		expect(res.headers.get("content-security-policy")).not.toContain(
			"apsrvwxfoomhtswlhczo.supabase.co",
		);
		expect(res.headers.get("content-security-policy")).not.toContain(
			"fonts.googleapis.com",
		);
		expect(res.body).not.toMatch(/window\.location\.(href|replace)\s*=\s*deep/i);
		expect(res.body).not.toContain("intent://");
	});

	it("renders explicit appearance handles without falling back to the short code", async () => {
		currentSmartLink = {
			...smartLink,
			metadata: {
				appearance: {
					...(smartLink.metadata.appearance as Record<string, unknown>),
					handle: "@creator.real",
				},
			},
		};
		const res = makeRes();

		await handler(
			makeReq(
				"Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Instagram 356.0.0.0.0",
			),
			res,
		);

		expect(res.statusCode).toBe(200);
		expect(res.body).toContain("@creator.real");
		expect(res.body).not.toContain("@abc123");
	});

	it("supports HEAD checks for in-app interstitials without rendering a body", async () => {
		const res = makeRes();

		await handler(
			makeHeadReq(
				"Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Instagram 356.0.0.0.0",
			),
			res,
		);

		expect(res.statusCode).toBe(200);
		expect(res.end).toHaveBeenCalled();
		expect(res.send).not.toHaveBeenCalled();
		expect(mockInsertClick).not.toHaveBeenCalled();
		expect(mockRpc).not.toHaveBeenCalled();
	});

	it("serves creator destinations through a transparent desktop interstitial", async () => {
		currentSmartLink = {
			...smartLink,
			target_url: "https://onlyfans.com/testcreator",
			enable_deep_links: false,
			ig_deep_link: null,
			threads_deep_link: null,
		};
		const res = makeRes();

		await handler(
			makeReq(
				"Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/537.36 Chrome/130 Safari/537.36",
			),
			res,
		);

		expect(res.redirect).not.toHaveBeenCalled();
		expect(res.statusCode).toBe(200);
		expect(res.body).toContain("Creator VIP");
		expect(res.body).toContain("Destination: onlyfans.com");
		expect(res.body).toContain("This page shows the destination before opening it.");
		expect(res.body).toContain("Copy Link");
		expect(res.body).not.toContain("Online now");
		expect(res.body).not.toContain("6.9 miles away");
		expect(res.body).not.toContain("@abc123");
		expect(mockInsertClick).toHaveBeenCalledWith(
			expect.objectContaining({
				smart_link_id: "link-1",
				event_name: "interstitial_view",
			}),
		);
		expect(mockRpc).not.toHaveBeenCalled();
	});

	it("expands short preview metadata and supplies a default 1200x630 image", async () => {
		currentSmartLink = {
			...smartLink,
			title: "Larissa",
			target_url: "https://onlyfans.com/testcreator",
			enable_deep_links: false,
			ig_deep_link: null,
			threads_deep_link: null,
			metadata: {
				appearance: {
					displayTitle: "Larissa",
					subtitle: "View profile.",
					ctaLabel: "View Profile",
				},
			},
		};
		const res = makeRes();

		await handler(
			makeReq(
				"facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
			),
			res,
		);

		expect(res.statusCode).toBe(200);
		expect(res.body).toContain(
			'<meta property="og:title" content="Larissa - Creator Profile Link">',
		);
		expect(res.body).toContain(
			'<meta property="og:description" content="Open Larissa with a transparent destination preview before continuing. Destination: onlyfans.com.">',
		);
		expect(res.body).toContain(
			'<meta property="og:image" content="https://juno33.com/og-image.png">',
		);
		expect(res.body).toContain('<meta property="og:image:width" content="1200">');
		expect(res.body).toContain('<meta property="og:image:height" content="630">');
		expect(res.body).toContain(
			'<meta name="twitter:card" content="summary_large_image">',
		);
	});

	it("serves creator destinations to crawlers without counting analytics", async () => {
		currentSmartLink = {
			...smartLink,
			target_url: "https://onlyfans.com/testcreator",
			enable_deep_links: false,
			ig_deep_link: null,
			threads_deep_link: null,
		};
		const res = makeRes();

		await handler(
			makeReq(
				"facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
			),
			res,
		);

		expect(res.redirect).not.toHaveBeenCalled();
		expect(res.statusCode).toBe(200);
		expect(res.body).toContain("Destination: onlyfans.com");
		expect(mockInsertClick).not.toHaveBeenCalled();
		expect(mockRpc).not.toHaveBeenCalled();
	});

	it("supports HEAD checks for creator destinations without counting analytics", async () => {
		currentSmartLink = {
			...smartLink,
			target_url: "https://onlyfans.com/testcreator",
			enable_deep_links: false,
			ig_deep_link: null,
			threads_deep_link: null,
		};
		const res = makeRes();

		await handler(
			makeHeadReq(
				"Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/537.36 Chrome/130 Safari/537.36",
			),
			res,
		);

		expect(res.statusCode).toBe(200);
		expect(res.end).toHaveBeenCalled();
		expect(res.redirect).not.toHaveBeenCalled();
		expect(mockInsertClick).not.toHaveBeenCalled();
		expect(mockRpc).not.toHaveBeenCalled();
	});

	it("serves mobile app deep links only behind a user tap", async () => {
		const res = makeRes();

		await handler(
			makeReq(
				"Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1",
			),
			res,
		);

		expect(res.statusCode).toBe(200);
		expect(res.body).toContain("This page waits for your tap before opening.");
		expect(res.body).toContain("data-track-destination");
		expect(res.body).toContain("Open in Instagram");
		expect(res.body).toContain("View Profile");
		expect(res.body).toContain("Copy Link");
		expect(res.body).toContain("Creator VIP");
		expect(res.body).not.toContain("Online now");
		expect(res.body).not.toContain("6.9 miles away");
		expect(res.body).not.toContain("@abc123");
		expect(res.body).toContain('<link rel="canonical"');
		expect(res.body).toContain('property="og:title"');
		expect(res.body).not.toMatch(/window\.location\.(href|replace)\s*=\s*deep/i);
		expect(res.body).not.toContain("intent://");
	});

	it("records destination clicks from interstitial button taps", async () => {
		const res = makeRes();

		await handler(
			makePostReq(
				"Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Instagram 356.0.0.0.0",
			),
			res,
		);

		expect(res.statusCode).toBe(204);
		expect(mockInsertClick).toHaveBeenCalledWith(
			expect.objectContaining({
				smart_link_id: "link-1",
				event_name: "destination_click",
			}),
		);
		expect(mockRpc).toHaveBeenCalledWith("increment_smart_link_click", {
			p_link_id: "link-1",
		});
	});
});
