import { describe, expect, it } from "vitest";
import {
	type ConversationItem,
	computeReplyDepth,
} from "../../api/_lib/handlers/threads/replyChainSync.js";

/**
 * Reply Chain Depth — pure-logic tests.
 *
 * Validates the BFS depth reconstruction from Threads /replies
 * flat-list format. No network; no DB.
 */

const ROOT = "root_post_id";

describe("computeReplyDepth", () => {
	it("returns 1 for a post with no replies", () => {
		expect(computeReplyDepth(ROOT, [])).toBe(1);
	});

	it("returns 2 for a single direct reply to root", () => {
		const items: ConversationItem[] = [
			{ id: "r1", replied_to: { id: ROOT } },
		];
		expect(computeReplyDepth(ROOT, items)).toBe(2);
	});

	it("returns 3 for a reply-to-a-reply (A → B → C chain)", () => {
		const items: ConversationItem[] = [
			{ id: "r1", replied_to: { id: ROOT } },
			{ id: "r2", replied_to: { id: "r1" } },
		];
		expect(computeReplyDepth(ROOT, items)).toBe(3);
	});

	it("returns the LONGEST chain, not total count", () => {
		// Root has 3 direct replies; one of them has a deep chain.
		// Depth should be 4 (root → r1 → r1a → r1aa), not 4 from counting.
		const items: ConversationItem[] = [
			{ id: "r1", replied_to: { id: ROOT } },
			{ id: "r2", replied_to: { id: ROOT } },
			{ id: "r3", replied_to: { id: ROOT } },
			{ id: "r1a", replied_to: { id: "r1" } },
			{ id: "r1aa", replied_to: { id: "r1a" } },
		];
		expect(computeReplyDepth(ROOT, items)).toBe(4);
	});

	it("handles unordered input (child arrives before parent in array)", () => {
		const items: ConversationItem[] = [
			// Deliberately out of order:
			{ id: "r1a", replied_to: { id: "r1" } },
			{ id: "r1", replied_to: { id: ROOT } },
		];
		expect(computeReplyDepth(ROOT, items)).toBe(3);
	});

	it("treats orphan replies (parent not in list) as children of root", () => {
		// r1's parent 'unknown_id' isn't returned by /replies.
		// Defensive: attach to root so it still contributes to depth.
		const items: ConversationItem[] = [
			{ id: "r1", replied_to: { id: "unknown_parent" } },
		];
		expect(computeReplyDepth(ROOT, items)).toBe(2);
	});

	it("treats missing replied_to as child of root", () => {
		const items: ConversationItem[] = [
			{ id: "r1" }, // no replied_to at all
			{ id: "r2", replied_to: null },
		];
		expect(computeReplyDepth(ROOT, items)).toBe(2);
	});

	it("does not infinite-loop on cyclic replied_to edges (defensive)", () => {
		// Hostile input: r1 says it replies to r2 and r2 says it replies to r1.
		// Neither chains from root, so both become root-children (depth 2).
		const items: ConversationItem[] = [
			{ id: "r1", replied_to: { id: "r2" } },
			{ id: "r2", replied_to: { id: "r1" } },
		];
		const depth = computeReplyDepth(ROOT, items);
		// Whatever the resolved value is, it must terminate and be finite.
		expect(depth).toBeGreaterThanOrEqual(2);
		expect(depth).toBeLessThan(10);
	});

	it("picks the deepest branch among multiple long chains", () => {
		// Chain A: root → a1 → a2 (depth 3)
		// Chain B: root → b1 → b2 → b3 → b4 (depth 5)
		const items: ConversationItem[] = [
			{ id: "a1", replied_to: { id: ROOT } },
			{ id: "a2", replied_to: { id: "a1" } },
			{ id: "b1", replied_to: { id: ROOT } },
			{ id: "b2", replied_to: { id: "b1" } },
			{ id: "b3", replied_to: { id: "b2" } },
			{ id: "b4", replied_to: { id: "b3" } },
		];
		expect(computeReplyDepth(ROOT, items)).toBe(5);
	});

	it("counts realistic 'Mosseri signal' threshold (depth ≥ 4)", () => {
		// Exactly the boundary case the Analytics widget flags.
		const items: ConversationItem[] = [
			{ id: "r1", replied_to: { id: ROOT } },
			{ id: "r2", replied_to: { id: "r1" } },
			{ id: "r3", replied_to: { id: "r2" } },
		];
		expect(computeReplyDepth(ROOT, items)).toBe(4);
	});
});
