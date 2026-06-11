import { describe, expect, it, vi } from "vitest";
import {
	buildIdentityAdvisories,
	conversationKey,
	defaultTabForPlatform,
	inboxAssignmentSource,
	isEmojiOnlyComment,
	needsAttention,
	supportsTabForPlatform,
	tabLabel,
	tabsForPlatform,
} from "./helpers";
import { contradictionWarning } from "./safety";
import type { Conversation } from "./types";

vi.mock("@/services/supabase", () => ({
	supabase: {
		auth: {
			onAuthStateChange: vi.fn(() => ({
				data: { subscription: { unsubscribe: vi.fn() } },
			})),
		},
	},
}));

function conversation(overrides: Partial<Conversation> = {}): Conversation {
	return {
		id: "c1",
		user: {
			name: "Alex Rivera",
			handle: "@alex",
			avatarFrom: "#111",
			avatarTo: "#333",
			followers: 1200,
		},
		toAccount: "@creator",
		network: { id: "creator-a", label: "Creator A", color: "#f00" },
		platform: "threads",
		type: "comment",
		snippet: "Thanks for posting",
		ago: "now",
		sentiment: "positive",
		turns: [
			{ id: "t1", from: "them", text: "Thanks for helping", time: "now" },
		],
		reply: {
			platform: "threads",
			accountId: "acct-1",
			replyToId: "reply-1",
			kind: "reply",
		},
		...overrides,
	};
}

describe("inbox helpers", () => {
	it("builds stable conversation keys for persisted inbox state", () => {
		expect(
			conversationKey(
				conversation({ platform: "instagram", type: "dm", id: "dm-42" }),
			),
		).toBe("instagram:dm:dm-42");
	});

	it("keeps Threads tabs limited to API-backed surfaces", () => {
		expect(tabsForPlatform("threads")).toEqual([
			{ id: "comment", label: "Replies" },
			{ id: "mention", label: "Mentions" },
		]);
		expect(supportsTabForPlatform("threads", "dm")).toBe(false);
		expect(defaultTabForPlatform("threads")).toBe("comment");
		expect(tabLabel("threads", "comment")).toBe("Replies");
	});

	it("keeps Instagram focused on API-backed inbox surfaces", () => {
		expect(tabsForPlatform("instagram")).toEqual([
			{ id: "dm", label: "DMs" },
			{ id: "comment", label: "Comments" },
		]);
		expect(supportsTabForPlatform("instagram", "dm")).toBe(true);
		expect(supportsTabForPlatform("instagram", "mention")).toBe(false);
		expect(supportsTabForPlatform("instagram", "comment")).toBe(true);
		expect(defaultTabForPlatform("instagram")).toBe("dm");
	});

	it("maps rendered conversation types to assignment API sources", () => {
		expect(inboxAssignmentSource(conversation({ platform: "threads", type: "comment" }))).toBe("threads_reply");
		expect(inboxAssignmentSource(conversation({ platform: "threads", type: "mention" }))).toBe("threads_mention");
		expect(inboxAssignmentSource(conversation({ platform: "instagram", type: "comment" }))).toBe("ig_comment");
		expect(inboxAssignmentSource(conversation({ platform: "instagram", type: "mention" }))).toBe("ig_mention");
		expect(inboxAssignmentSource(conversation({ platform: "instagram", type: "dm" }))).toBe("ig_dm");
	});
});

describe("inbox client-only widgets", () => {
	it("detects emoji-only comments for bundled noise rows", () => {
		expect(isEmojiOnlyComment(conversation({ snippet: "🔥 🙌 ✨" }))).toBe(
			true,
		);
		expect(
			isEmojiOnlyComment(conversation({ snippet: "🔥 this is great" })),
		).toBe(false);
		expect(
			isEmojiOnlyComment(conversation({ type: "dm", snippet: "🔥" })),
		).toBe(false);
	});

	it("classifies threads that belong in the daily attention queue", () => {
		expect(needsAttention(conversation({ sentiment: "negative" }))).toBe(true);
		expect(
			needsAttention(
				conversation({
					turns: [{ id: "t1", from: "them", text: "Can you help?", time: "now" }],
				}),
			),
		).toBe(true);
		expect(
			needsAttention(conversation({ sentiment: "neutral" }), {
				id: "s1",
				conversation_key: "threads:comment:c1",
				suggestion_text: "Happy to help.",
				reasoning: null,
				alternatives: [],
				status: "pending",
			}),
		).toBe(true);
		expect(
			needsAttention(
				conversation({
					sentiment: "neutral",
					isTopEngager: false,
					turns: [{ id: "t1", from: "them", text: "Love this", time: "now" }],
				}),
			),
		).toBe(false);
	});

	it("flags likely identity stitching matches across platforms", () => {
		const threads = conversation({
			id: "threads-1",
			platform: "threads",
			user: { ...conversation().user, handle: "@alex_r" },
		});
		const instagram = conversation({
			id: "ig-1",
			platform: "instagram",
			user: { ...conversation().user, handle: "@alex.photo" },
		});

		const advisories = buildIdentityAdvisories([threads, instagram]);

		expect(advisories.get("threads-1")).toBe(
			"Likely same person across Threads + Instagram",
		);
		expect(advisories.get("ig-1")).toBe(
			"Likely same person across Threads + Instagram",
		);
	});

	it("keeps the pre-send heuristic fallback for API failures", () => {
		expect(
			contradictionWarning("No, we cannot refund this", [
				{ id: "t1", from: "them", text: "Please refund this", time: "now" },
			]),
		).toContain("negate");
		expect(
			contradictionWarning("Thanks, happy to help", [
				{ id: "t1", from: "them", text: "This is bad", time: "now" },
			]),
		).toContain("opposite sentiment");
	});
});
