import { describe, expect, it, vi, beforeEach } from "vitest";

/**
 * Tests that requireMinTier() correctly blocks free-tier users
 * and allows pro+ users. Validates the tier gating logic that
 * all premium AI routes depend on.
 */

let mockTier = "free";

vi.mock("../../api/_lib/supabase.js", () => ({
	getSupabase: () => ({
		from: () => ({
			select: () => ({
				eq: () => ({
					maybeSingle: () =>
						Promise.resolve({
							data: { subscription_tier: mockTier },
						}),
				}),
			}),
		}),
	}),
}));

const { requireMinTier, getUserTier, invalidateTierCache } = await import(
	"../../api/_lib/tierGate.js"
);

function mockRes() {
	const res = {} as Record<string, unknown>;
	res.status = vi.fn().mockReturnValue(res);
	res.json = vi.fn().mockReturnValue(res);
	// biome-ignore lint/suspicious/noExplicitAny: test mock
	return res as any;
}

describe("requireMinTier", () => {
	beforeEach(() => {
		invalidateTierCache("test-user");
	});

	it("blocks free-tier user from pro features with 403", async () => {
		mockTier = "free";
		const res = mockRes();
		const allowed = await requireMinTier("test-user", "pro", res);
		expect(allowed).toBe(false);
		expect(res.status).toHaveBeenCalledWith(403);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ code: "TIER_REQUIRED" }),
		);
	});

	it("allows pro-tier user to access pro features", async () => {
		mockTier = "pro";
		const res = mockRes();
		const allowed = await requireMinTier("test-user", "pro", res);
		expect(allowed).toBe(true);
		expect(res.status).not.toHaveBeenCalled();
	});

	it("allows empire-tier user to access pro features", async () => {
		mockTier = "empire";
		const res = mockRes();
		const allowed = await requireMinTier("test-user", "pro", res);
		expect(allowed).toBe(true);
	});

	it("blocks pro-tier user from empire-only features", async () => {
		mockTier = "pro";
		const res = mockRes();
		const allowed = await requireMinTier("test-user", "empire", res);
		expect(allowed).toBe(false);
		expect(res.status).toHaveBeenCalledWith(403);
	});

	it("blocks free-tier user from empire-only features", async () => {
		mockTier = "free";
		const res = mockRes();
		const allowed = await requireMinTier("test-user", "empire", res);
		expect(allowed).toBe(false);
	});
});

describe("getUserTier", () => {
	beforeEach(() => {
		invalidateTierCache("test-user");
	});

	it("returns correct tier from DB", async () => {
		mockTier = "empire";
		const tier = await getUserTier("test-user");
		expect(tier).toBe("empire");
	});

	it("defaults unknown tiers to free", async () => {
		mockTier = "invalid_tier";
		const tier = await getUserTier("test-user");
		expect(tier).toBe("free");
	});
});
