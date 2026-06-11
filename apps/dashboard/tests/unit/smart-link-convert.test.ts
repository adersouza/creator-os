import * as crypto from "node:crypto";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

const mockInsertConversion = vi.fn();
let smartLink: { id: string; webhook_secret: string | null } | null = null;
let recentClick: { id: string } | null = null;

const mockFrom = vi.fn((table: string) => {
	if (table === "smart_links") {
		return {
			select: vi.fn().mockReturnValue({
				eq: vi.fn().mockReturnValue({
					eq: vi.fn().mockReturnValue({
						maybeSingle: vi.fn().mockResolvedValue({
							data: smartLink,
							error: null,
						}),
					}),
				}),
			}),
		};
	}
	if (table === "smart_link_clicks") {
		return {
			select: vi.fn().mockReturnValue({
				eq: vi.fn().mockReturnValue({
					gte: vi.fn().mockReturnValue({
						order: vi.fn().mockReturnValue({
							limit: vi.fn().mockReturnValue({
								maybeSingle: vi.fn().mockResolvedValue({
									data: recentClick,
									error: null,
								}),
							}),
						}),
					}),
				}),
			}),
		};
	}
	if (table === "smart_link_conversions") {
		return {
			insert: mockInsertConversion,
		};
	}
	throw new Error(`Unexpected table ${table}`);
});

vi.mock("@/api/_lib/supabase.js", () => ({
	getSupabase: () => ({ from: mockFrom }),
}));
vi.mock("@/api/_lib/rateLimiter.js", () => ({
	checkRateLimit: vi.fn().mockResolvedValue({ allowed: true }),
}));
vi.mock("@/api/_lib/logger.js", () => ({
	logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));
vi.mock("@/api/_lib/apiResponse.js", () => ({
	apiError: (res: any, status: number, message: string) =>
		res.status(status).json({ error: message }),
	apiSuccess: (res: any, data?: unknown) => res.status(200).json(data ?? {}),
}));

import handler from "@/api/go/convert";

function makeReq(query: Record<string, string>) {
	return {
		method: "GET",
		query,
		headers: { "x-forwarded-for": "203.0.113.9" },
	} as any;
}

function sign(secret: string, code: string, orderId: string, value: string) {
	return crypto
		.createHmac("sha256", secret)
		.update(`${code}${orderId}${value}`)
		.digest("hex");
}

describe("smart link conversion postbacks", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		smartLink = { id: "link-1", webhook_secret: "secret-1" };
		recentClick = { id: "click-1" };
		mockInsertConversion.mockResolvedValue({ error: null });
	});

	it("rejects active links that do not have webhook signing configured", async () => {
		smartLink = { id: "link-1", webhook_secret: null };
		const res = mockRes();

		await handler(
			makeReq({ code: "abc123", order_id: "ord-1", value: "49.99" }),
			res as any,
		);

		expect(res.status).toHaveBeenCalledWith(403);
		expect(mockInsertConversion).not.toHaveBeenCalled();
	});

	it("rejects missing or invalid signatures before inserting revenue", async () => {
		const res = mockRes();

		await handler(
			makeReq({ code: "abc123", order_id: "ord-1", value: "49.99" }),
			res as any,
		);

		expect(res.status).toHaveBeenCalledWith(401);
		expect(mockInsertConversion).not.toHaveBeenCalled();
	});

	it("records a signed conversion with the attributed recent click", async () => {
		const res = mockRes();
		const sig = sign("secret-1", "abc123", "ord-1", "49.99");

		await handler(
			makeReq({
				code: "abc123",
				order_id: "ord-1",
				value: "49.99",
				sig,
			}),
			res as any,
		);

		expect(mockInsertConversion).toHaveBeenCalledWith(
			expect.objectContaining({
				smart_link_id: "link-1",
				click_id: "click-1",
				order_id: "ord-1",
				conversion_value: 49.99,
			}),
		);
		expect(res.status).toHaveBeenCalledWith(200);
	});

	it("bounds conversion value and order id before DB work", async () => {
		const res = mockRes();

		await handler(
			makeReq({ code: "abc123", order_id: "bad order", value: "1000001" }),
			res as any,
		);

		expect(res.status).toHaveBeenCalledWith(400);
		expect(mockFrom).not.toHaveBeenCalledWith("smart_links");
	});
});
