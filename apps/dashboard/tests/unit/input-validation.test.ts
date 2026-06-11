import { describe, it, expect } from "vitest";

/**
 * Input validation tests for API routes that previously accepted
 * raw req.body without Zod schemas.
 *
 * Tests import the schemas directly to verify they reject bad input
 * and accept valid input — no HTTP mocking needed.
 */

// ── growth-journal schemas ──────────────────────────────────────────────────
const GrowthJournalCreateSchema = (await import("../../api/_lib/handlers/user/growth-journal.js"))
	.GrowthJournalCreateSchema;

describe("GrowthJournalCreateSchema", () => {
	it("accepts valid input", () => {
		const result = GrowthJournalCreateSchema.safeParse({
			accountId: "acc_123",
			recommendationText: "Post more reels",
		});
		expect(result.success).toBe(true);
	});

	it("accepts all optional fields", () => {
		const result = GrowthJournalCreateSchema.safeParse({
			accountId: "acc_123",
			recommendationText: "Post more reels",
			platform: "instagram",
			category: "content",
			icon: "rocket",
			postId: "post_456",
		});
		expect(result.success).toBe(true);
	});

	it("rejects missing accountId", () => {
		const result = GrowthJournalCreateSchema.safeParse({
			recommendationText: "Post more reels",
		});
		expect(result.success).toBe(false);
	});

	it("rejects missing recommendationText", () => {
		const result = GrowthJournalCreateSchema.safeParse({
			accountId: "acc_123",
		});
		expect(result.success).toBe(false);
	});

	it("rejects recommendationText exceeding max length", () => {
		const result = GrowthJournalCreateSchema.safeParse({
			accountId: "acc_123",
			recommendationText: "x".repeat(2001),
		});
		expect(result.success).toBe(false);
	});

	it("rejects non-string accountId", () => {
		const result = GrowthJournalCreateSchema.safeParse({
			accountId: 12345,
			recommendationText: "Post more reels",
		});
		expect(result.success).toBe(false);
	});

	it("rejects icon exceeding max length", () => {
		const result = GrowthJournalCreateSchema.safeParse({
			accountId: "acc_123",
			recommendationText: "Valid text",
			icon: "x".repeat(51),
		});
		expect(result.success).toBe(false);
	});
});

// ── agency-branding schemas ─────────────────────────────────────────────────
const AgencyBrandingSchema = (await import("../../api/_lib/handlers/user/branding.js"))
	.AgencyBrandingSchema;

describe("AgencyBrandingSchema", () => {
	it("accepts valid input", () => {
		const result = AgencyBrandingSchema.safeParse({
			agency_name: "Acme Agency",
			brand_color: "#ff5500",
		});
		expect(result.success).toBe(true);
	});

	it("accepts empty body (all optional)", () => {
		const result = AgencyBrandingSchema.safeParse({});
		expect(result.success).toBe(true);
	});

	it("rejects agency_name exceeding max length", () => {
		const result = AgencyBrandingSchema.safeParse({
			agency_name: "x".repeat(201),
		});
		expect(result.success).toBe(false);
	});

	it("rejects brand_color exceeding max length", () => {
		const result = AgencyBrandingSchema.safeParse({
			brand_color: "x".repeat(31),
		});
		expect(result.success).toBe(false);
	});

	it("rejects non-string agency_name", () => {
		const result = AgencyBrandingSchema.safeParse({
			agency_name: { injection: true },
		});
		expect(result.success).toBe(false);
	});
});

// ── content-strategy schemas ────────────────────────────────────────────────
const ContentStrategySchema = (
	await import("../../api/_lib/handlers/agent/content-strategy.js")
).ContentStrategySchema;

describe("ContentStrategySchema", () => {
	it("accepts valid strategy", () => {
		const result = ContentStrategySchema.safeParse({
			accountGroupId: "grp_123",
			strategy: {
				pillars: ["education", "entertainment"],
				weekly_target: 5,
				tone_notes: "Keep it casual",
			},
		});
		expect(result.success).toBe(true);
	});

	it("rejects missing accountGroupId", () => {
		const result = ContentStrategySchema.safeParse({
			strategy: { pillars: ["a"] },
		});
		expect(result.success).toBe(false);
	});

	it("rejects missing strategy", () => {
		const result = ContentStrategySchema.safeParse({
			accountGroupId: "grp_123",
		});
		expect(result.success).toBe(false);
	});

	it("rejects pillars exceeding max count", () => {
		const result = ContentStrategySchema.safeParse({
			accountGroupId: "grp_123",
			strategy: {
				pillars: Array(11).fill("topic"),
			},
		});
		expect(result.success).toBe(false);
	});

	it("rejects weekly_target out of range", () => {
		const result = ContentStrategySchema.safeParse({
			accountGroupId: "grp_123",
			strategy: {
				pillars: ["a"],
				weekly_target: 200,
			},
		});
		expect(result.success).toBe(false);
	});

	it("rejects tone_notes exceeding max length", () => {
		const result = ContentStrategySchema.safeParse({
			accountGroupId: "grp_123",
			strategy: {
				pillars: ["a"],
				tone_notes: "x".repeat(2001),
			},
		});
		expect(result.success).toBe(false);
	});

	it("rejects non-string accountGroupId", () => {
		const result = ContentStrategySchema.safeParse({
			accountGroupId: 999,
			strategy: { pillars: ["a"] },
		});
		expect(result.success).toBe(false);
	});
});
