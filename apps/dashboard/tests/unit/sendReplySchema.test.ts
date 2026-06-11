/**
 * Schema guard for /api/replies?action=send.
 *
 * This is the contract frozen with the juno33 frontend
 * (src/services/api/posts.ts::sendReply). Drift here = broken inbox.
 */

import { describe, expect, it } from "vitest";
import { SendReplySchema } from "../../api/_lib/handlers/replies/shared.js";

const validReply = {
	platform: "threads",
	accountId: "acct-1",
	replyToId: "post-123",
	content: "thanks!",
	kind: "reply",
} as const;

describe("SendReplySchema", () => {
	it("accepts the minimal threads reply payload", () => {
		const result = SendReplySchema.safeParse(validReply);
		expect(result.success).toBe(true);
	});

	it("accepts optional conversationId + replyToUsername", () => {
		const result = SendReplySchema.safeParse({
			...validReply,
			platform: "instagram",
			kind: "dm",
			conversationId: "conv-abc",
			replyToUsername: "someone",
		});
		expect(result.success).toBe(true);
	});

	it("accepts optional inbox freshness context", () => {
		const result = SendReplySchema.safeParse({
			...validReply,
			context: {
				conversationId: "tr-row-1",
				lastSeenAt: "2026-05-10T20:00:00.000Z",
				lastTurnId: "tr-row-1-0",
			},
		});
		expect(result.success).toBe(true);
	});

	it.each([
		["platform", "tiktok"],
		["kind", "retweet"],
	])("rejects unknown %s value", (field, value) => {
		const result = SendReplySchema.safeParse({
			...validReply,
			[field]: value,
		});
		expect(result.success).toBe(false);
	});

	it("rejects empty content", () => {
		const result = SendReplySchema.safeParse({ ...validReply, content: "" });
		expect(result.success).toBe(false);
	});

	it("rejects content over 2200 chars (IG cap)", () => {
		const result = SendReplySchema.safeParse({
			...validReply,
			content: "x".repeat(2201),
		});
		expect(result.success).toBe(false);
	});

	it("requires accountId and replyToId", () => {
		expect(
			SendReplySchema.safeParse({ ...validReply, accountId: "" }).success,
		).toBe(false);
		expect(
			SendReplySchema.safeParse({ ...validReply, replyToId: "" }).success,
		).toBe(false);
	});

	it.each(["dm", "comment", "reply"] as const)(
		"accepts kind=%s",
		(kind) => {
			const platform = kind === "reply" ? "threads" : "instagram";
			const result = SendReplySchema.safeParse({
				...validReply,
				platform,
				kind,
			});
			expect(result.success).toBe(true);
		},
	);
});
