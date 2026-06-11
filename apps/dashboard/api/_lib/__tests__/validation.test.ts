import { describe, expect, it } from "vitest";
import {
	AutoPostConfigSchema,
	DeletePostSchema,
	PublishPostSchema,
	validateBody,
} from "../validation.js";

describe("validateBody", () => {
	it("returns data for valid input", () => {
		const result = validateBody(PublishPostSchema, { content: "Hello" });
		expect(result).toHaveProperty("data");
		expect((result as { data: { content: string } }).data.content).toBe(
			"Hello",
		);
	});

	it("returns error for invalid input", () => {
		const result = validateBody(PublishPostSchema, { content: "" });
		expect(result).toHaveProperty("error");
	});

	it("returns error for missing required fields", () => {
		const result = validateBody(PublishPostSchema, {});
		expect(result).toHaveProperty("error");
	});
});

describe("PublishPostSchema", () => {
	it("accepts minimal valid post", () => {
		const result = PublishPostSchema.safeParse({ content: "test" });
		expect(result.success).toBe(true);
	});

	it("rejects empty content", () => {
		const result = PublishPostSchema.safeParse({ content: "" });
		expect(result.success).toBe(false);
	});

	it("accepts post with media array", () => {
		const result = PublishPostSchema.safeParse({
			content: "test",
			media: [{ url: "https://example.com/img.jpg" }],
		});
		expect(result.success).toBe(true);
	});

	it("accepts optional nullable fields as null", () => {
		const result = PublishPostSchema.safeParse({
			content: "test",
			linkUrl: null,
			quotePostId: null,
		});
		expect(result.success).toBe(true);
	});
});

describe("DeletePostSchema", () => {
	it("accepts valid postId", () => {
		const result = DeletePostSchema.safeParse({ postId: "123" });
		expect(result.success).toBe(true);
	});

	it("rejects empty postId", () => {
		const result = DeletePostSchema.safeParse({ postId: "" });
		expect(result.success).toBe(false);
	});
});

describe("AutoPostConfigSchema", () => {
	it("accepts valid config", () => {
		const result = AutoPostConfigSchema.safeParse({
			workspaceId: "ws1",
			groupId: "g1",
			config: { posts_per_account_per_day: 5 },
		});
		expect(result.success).toBe(true);
	});

	it("rejects missing workspaceId", () => {
		const result = AutoPostConfigSchema.safeParse({ groupId: "g1" });
		expect(result.success).toBe(false);
	});
});
