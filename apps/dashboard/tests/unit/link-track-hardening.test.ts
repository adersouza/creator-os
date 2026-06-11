import { beforeEach, describe, expect, it, vi } from "vitest";
import { createLinkTrackingToken } from "../../api/_lib/linkTrackingToken";
import { mockRes } from "../helpers/mockFactories";

const mockRpc = vi.fn();
const mockInsertClick = vi.fn().mockResolvedValue({ error: null });

let pageOwned = true;
let linkOwned = true;
let variantOwned = true;

function makeMaybeSingle(data: unknown) {
	return { maybeSingle: vi.fn().mockResolvedValue({ data, error: null }) };
}

const mockFrom = vi.fn().mockImplementation((table: string) => {
	if (table === "link_pages") {
		return {
			select: vi.fn().mockReturnValue({
				eq: vi.fn().mockReturnValue({
					eq: vi.fn().mockReturnValue(
						makeMaybeSingle(pageOwned ? { id: "page-1" } : null),
					),
				}),
			}),
		};
	}

	if (table === "link_items") {
		return {
			select: vi.fn().mockReturnValue({
				eq: vi.fn().mockReturnValue({
					eq: vi.fn().mockReturnValue(
						makeMaybeSingle(linkOwned ? { id: "link-1" } : null),
					),
				}),
			}),
		};
	}

	if (table === "link_page_variants") {
		return {
			select: vi.fn().mockReturnValue({
				eq: vi.fn().mockReturnValue({
					eq: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue(
							makeMaybeSingle(variantOwned ? { id: "variant-1" } : null),
						),
					}),
				}),
			}),
		};
	}

	if (table === "link_clicks") {
		return {
			insert: mockInsertClick,
		};
	}

	throw new Error(`Unexpected table ${table}`);
});

vi.mock("@/api/_lib/supabase.js", () => ({
	getSupabase: () => ({ rpc: mockRpc }),
	getSupabaseAny: () => ({ from: mockFrom }),
}));
vi.mock("../../api/_lib/supabase", () => ({
	getSupabase: () => ({ rpc: mockRpc }),
	getSupabaseAny: () => ({ from: mockFrom }),
}));

vi.mock("@/api/_lib/rateLimiter.js", () => ({
	checkRateLimit: vi.fn().mockResolvedValue({ allowed: true }),
}));
vi.mock("../../api/_lib/rateLimiter", () => ({
	checkRateLimit: vi.fn().mockResolvedValue({ allowed: true }),
}));

vi.mock("@/api/_lib/logger.js", () => ({
	logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));
vi.mock("../../api/_lib/logger", () => ({
	logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

vi.mock("@/api/_lib/apiResponse.js", () => ({
	apiError: (res: any, status: number, message: string) =>
		res.status(status).json({ error: message }),
	apiSuccess: (res: any, data?: unknown) => res.status(200).json(data ?? {}),
}));
vi.mock("../../api/_lib/apiResponse", () => ({
	apiError: (res: any, status: number, message: string) =>
		res.status(status).json({ error: message }),
	apiSuccess: (res: any, data?: unknown) => res.status(200).json(data ?? {}),
}));

import handler from "@/api/_lib/handlers/link-page-sub/track";

function makeReq(userAgent: string, body: Record<string, unknown>) {
	return {
		method: "POST",
		headers: {
			"user-agent": userAgent,
			"x-forwarded-for": "203.0.113.10",
		},
		body,
		query: {},
	} as any;
}

function validToken(overrides: {
	pageId?: string;
	linkId?: string | null;
	variantId?: string | null;
} = {}) {
	return createLinkTrackingToken({
		pageId: overrides.pageId ?? "page-1",
		linkId: overrides.linkId === undefined ? "link-1" : overrides.linkId,
		variantId:
			overrides.variantId === undefined ? "variant-1" : overrides.variantId,
	});
}

describe("link-page track side-effect hardening", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		pageOwned = true;
		linkOwned = true;
		variantOwned = true;
	});

	it("logs crawler clicks but does not increment human counters", async () => {
		const res = mockRes();

		await handler(
			makeReq("Twitterbot/1.0", {
				pageId: "page-1",
				linkId: "link-1",
				variantId: "variant-1",
				token: validToken(),
			}),
			res as any,
		);

		expect(mockInsertClick).toHaveBeenCalledWith(
			expect.objectContaining({
				page_id: "page-1",
				link_id: "link-1",
				variant_id: "variant-1",
				is_crawler: true,
			}),
		);
		expect(mockRpc).not.toHaveBeenCalled();
	});

	it("does not record clicks when the link does not belong to the page", async () => {
		linkOwned = false;
		const res = mockRes();

		await handler(
			makeReq("Mozilla/5.0", {
				pageId: "page-1",
				linkId: "link-elsewhere",
				token: validToken({ linkId: "link-elsewhere", variantId: null }),
			}),
			res as any,
		);

		expect(mockInsertClick).not.toHaveBeenCalled();
		expect(mockRpc).not.toHaveBeenCalled();
		expect(res.status).toHaveBeenCalledWith(200);
	});

	it("rejects GET tracking so public query URLs cannot inflate clicks", async () => {
		const res = mockRes();

		await handler(
			{
				method: "GET",
				headers: { "user-agent": "Mozilla/5.0" },
				query: { pageId: "page-1", linkId: "link-1" },
				body: {},
			} as any,
			res as any,
		);

		expect(res.status).toHaveBeenCalledWith(405);
		expect(mockInsertClick).not.toHaveBeenCalled();
		expect(mockRpc).not.toHaveBeenCalled();
	});

	it("ignores unsigned tracking events", async () => {
		const res = mockRes();

		await handler(
			makeReq("Mozilla/5.0", {
				pageId: "page-1",
				linkId: "link-1",
				variantId: "variant-1",
			}),
			res as any,
		);

		expect(mockInsertClick).not.toHaveBeenCalled();
		expect(mockRpc).not.toHaveBeenCalled();
		expect(res.status).toHaveBeenCalledWith(200);
	});

	it("uses server-detected platform and device instead of client-supplied values", async () => {
		const res = mockRes();

		await handler(
			makeReq("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Instagram 300.0", {
				pageId: "page-1",
				linkId: "link-1",
				variantId: "variant-1",
				sourceApp: "tiktok",
				deviceType: "desktop",
				token: validToken(),
			}),
			res as any,
		);

		expect(mockInsertClick).toHaveBeenCalledWith(
			expect.objectContaining({
				source_app: "instagram",
				device_type: "ios",
			}),
		);
	});
});
