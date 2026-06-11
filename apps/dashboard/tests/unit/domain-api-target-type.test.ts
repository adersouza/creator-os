import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

const mockFrom = vi.fn();
const mockGetUserTier = vi.fn();

vi.mock("@/api/_lib/middleware.js", () => ({
	withAuth: (handler: any) => (req: any, res: any) =>
		handler(req, res, { id: "user-1" }),
}));

vi.mock("@/api/_lib/tierGate.js", () => ({
	getUserTier: (...args: unknown[]) => mockGetUserTier(...args),
}));

vi.mock("@/api/_lib/supabase.js", () => ({
	getSupabase: () => ({ from: mockFrom }),
}));

vi.mock("@/api/_lib/logger.js", () => ({
	logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

vi.mock("@/api/_lib/apiResponse.js", () => ({
	apiError: (res: any, status: number, message: string, opts?: any) =>
		res.status(status).json({ error: message, ...opts }),
	apiSuccess: (res: any, data?: unknown) =>
		res.status(200).json({ success: true, ...(data as any) }),
	badRequest: (res: any, message: string) =>
		res.status(400).json({ error: message }),
}));

import handler from "@/api/_lib/handlers/links-sub/domains";

function makeReq(body: Record<string, unknown> = {}) {
	return {
		method: "POST",
		body,
		query: {},
		headers: {},
	} as any;
}

function createQuery(table: string) {
	const eqs: Record<string, unknown> = {};
	let upsertPayload: any = null;
	const query: any = {
		select: vi.fn(() => query),
		eq: vi.fn((field: string, value: unknown) => {
			eqs[field] = value;
			return query;
		}),
		upsert: vi.fn((payload: unknown) => {
			upsertPayload = payload;
			return query;
		}),
		maybeSingle: vi.fn(async () => {
			if (table === "smart_links" && eqs.id === "smart-1") {
				return {
					data: {
						id: "smart-1",
						code: "launch",
						custom_domain: null,
						domain_verified: false,
					},
					error: null,
				};
			}
			if (table === "domain_verifications" && upsertPayload) {
				return {
					data: {
						id: "verification-1",
						expires_at: upsertPayload.expires_at,
					},
					error: null,
				};
			}
			return { data: null, error: null };
		}),
	};
	return query;
}

describe("domain API targetType support", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockGetUserTier.mockResolvedValue("pro");
		mockFrom.mockImplementation((table: string) => createQuery(table));
	});

	it("accepts camelCase smartLink targetType and attaches verification to smart_link_id", async () => {
		const res = mockRes();

		await handler(
			makeReq({
				action: "add",
				targetType: "smartLink",
				smartLinkId: "smart-1",
				domain: "go.example.com",
			}),
			res as any,
		);

		const upsertQuery = mockFrom.mock.results
			.map((result) => result.value)
			.find((query) => query.upsert.mock.calls.length > 0);
		expect(upsertQuery.upsert).toHaveBeenCalledWith(
			expect.objectContaining({
				page_id: null,
				smart_link_id: "smart-1",
				domain: "go.example.com",
			}),
			{ onConflict: "domain" },
		);
		expect(res.status).toHaveBeenCalledWith(200);
	});

	it("rejects unknown targetType values instead of falling back to link_page", async () => {
		const res = mockRes();

		await handler(
			makeReq({
				action: "add",
				targetType: "smartlink",
				smartLinkId: "smart-1",
				domain: "go.example.com",
			}),
			res as any,
		);

		expect(res.status).toHaveBeenCalledWith(400);
		expect(mockFrom).not.toHaveBeenCalled();
	});
});
