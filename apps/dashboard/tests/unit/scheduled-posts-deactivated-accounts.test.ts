/**
 * Tests for deactivated-account guard in scheduled-posts.ts
 *
 * Verifies that posts belonging to accounts deactivated via enforceAccountLimits()
 * (tier downgrade) are silently skipped — not published, not marked as failed.
 *
 * Mirrors the exact guard logic added to the Threads and Instagram post loops.
 */

import { describe, expect, it } from "vitest";

// ---------------------------------------------------------------------------
// Mirror the exact guard from scheduled-posts.ts
// (both Threads and IG loops share the same predicate)
// ---------------------------------------------------------------------------

function shouldSkipDeactivatedAccount(
	isActive: boolean | null | undefined,
): boolean {
	return isActive === false;
}

// ---------------------------------------------------------------------------
// Mirror the publish decision: only proceed if account is active and has a token
// ---------------------------------------------------------------------------

interface ThreadsAccountStub {
	id: string;
	threads_user_id: string | null;
	threads_access_token_encrypted: string | null;
	username: string | null;
	is_active: boolean;
}

interface IgAccountStub {
	id: string;
	instagram_user_id: string;
	instagram_access_token_encrypted: string;
	username: string | null;
	is_active: boolean;
}

type PublishDecision = "publish" | "skip_deactivated" | "skip_no_token";

function resolveThreadsPublishDecision(
	account: ThreadsAccountStub | null,
): PublishDecision {
	if (shouldSkipDeactivatedAccount(account?.is_active)) return "skip_deactivated";
	if (!account?.threads_access_token_encrypted || !account?.threads_user_id)
		return "skip_no_token";
	return "publish";
}

function resolveIgPublishDecision(
	account: IgAccountStub | null,
): PublishDecision {
	if (shouldSkipDeactivatedAccount(account?.is_active)) return "skip_deactivated";
	if (!account?.instagram_access_token_encrypted) return "skip_no_token";
	return "publish";
}

// ---------------------------------------------------------------------------
// Tests: guard predicate
// ---------------------------------------------------------------------------

describe("shouldSkipDeactivatedAccount", () => {
	it("skips when is_active is false", () => {
		expect(shouldSkipDeactivatedAccount(false)).toBe(true);
	});

	it("does NOT skip when is_active is true", () => {
		expect(shouldSkipDeactivatedAccount(true)).toBe(false);
	});

	it("does NOT skip when is_active is undefined (legacy rows)", () => {
		expect(shouldSkipDeactivatedAccount(undefined)).toBe(false);
	});

	it("does NOT skip when is_active is null", () => {
		expect(shouldSkipDeactivatedAccount(null)).toBe(false);
	});
});

// ---------------------------------------------------------------------------
// Tests: Threads publish decision
// ---------------------------------------------------------------------------

describe("Threads post loop: deactivated account guard", () => {
	const validAccount: ThreadsAccountStub = {
		id: "acc-1",
		threads_user_id: "t-user-1",
		threads_access_token_encrypted: "encrypted-token",
		username: "testuser",
		is_active: true,
	};

	it("publishes post when account is active with valid token", () => {
		expect(resolveThreadsPublishDecision(validAccount)).toBe("publish");
	});

	it("skips — does NOT publish — when account is deactivated after downgrade", () => {
		const deactivated: ThreadsAccountStub = { ...validAccount, is_active: false };
		expect(resolveThreadsPublishDecision(deactivated)).toBe("skip_deactivated");
	});

	it("deactivated check fires BEFORE token check (correct guard order)", () => {
		// Even if the token is missing, deactivated should be the reported reason
		const deactivatedNoToken: ThreadsAccountStub = {
			...validAccount,
			is_active: false,
			threads_access_token_encrypted: null,
		};
		expect(resolveThreadsPublishDecision(deactivatedNoToken)).toBe(
			"skip_deactivated",
		);
	});

	it("skips with no-token reason when active but token missing", () => {
		const noToken: ThreadsAccountStub = {
			...validAccount,
			threads_access_token_encrypted: null,
		};
		expect(resolveThreadsPublishDecision(noToken)).toBe("skip_no_token");
	});

	it("skips with no-token reason when active but threads_user_id missing", () => {
		const noUserId: ThreadsAccountStub = {
			...validAccount,
			threads_user_id: null,
		};
		expect(resolveThreadsPublishDecision(noUserId)).toBe("skip_no_token");
	});

	it("skips gracefully when account is null (falls through to token check)", () => {
		// !inner join prevents null accounts in practice, but the existing
		// token-check guard catches this defensively — skip_no_token is correct.
		expect(resolveThreadsPublishDecision(null)).toBe("skip_no_token");
	});
});

// ---------------------------------------------------------------------------
// Tests: Instagram publish decision
// ---------------------------------------------------------------------------

describe("Instagram post loop: deactivated account guard", () => {
	const validIgAccount: IgAccountStub = {
		id: "ig-acc-1",
		instagram_user_id: "ig-user-1",
		instagram_access_token_encrypted: "encrypted-ig-token",
		username: "iguser",
		is_active: true,
	};

	it("publishes post when IG account is active with valid token", () => {
		expect(resolveIgPublishDecision(validIgAccount)).toBe("publish");
	});

	it("skips — does NOT publish — when IG account is deactivated after downgrade", () => {
		const deactivated: IgAccountStub = { ...validIgAccount, is_active: false };
		expect(resolveIgPublishDecision(deactivated)).toBe("skip_deactivated");
	});

	it("deactivated check fires BEFORE token check for IG accounts", () => {
		const deactivatedNoToken: IgAccountStub = {
			...validIgAccount,
			is_active: false,
			instagram_access_token_encrypted: "",
		};
		expect(resolveIgPublishDecision(deactivatedNoToken)).toBe(
			"skip_deactivated",
		);
	});

	it("skips with no-token reason when IG account active but token missing", () => {
		const noToken: IgAccountStub = {
			...validIgAccount,
			instagram_access_token_encrypted: "",
		};
		expect(resolveIgPublishDecision(noToken)).toBe("skip_no_token");
	});
});

// ---------------------------------------------------------------------------
// Tests: end-to-end simulation of mixed post batch
// ---------------------------------------------------------------------------

describe("mixed batch: active and deactivated accounts", () => {
	const posts = [
		{
			id: "post-1",
			account: {
				id: "acc-active",
				threads_user_id: "t-1",
				threads_access_token_encrypted: "token",
				username: "alice",
				is_active: true,
			} as ThreadsAccountStub,
		},
		{
			id: "post-2",
			account: {
				id: "acc-deactivated",
				threads_user_id: "t-2",
				threads_access_token_encrypted: "token",
				username: "bob",
				is_active: false, // ← downgraded user
			} as ThreadsAccountStub,
		},
		{
			id: "post-3",
			account: {
				id: "acc-also-active",
				threads_user_id: "t-3",
				threads_access_token_encrypted: "token",
				username: "carol",
				is_active: true,
			} as ThreadsAccountStub,
		},
	];

	it("only active-account posts proceed to publish", () => {
		const toPublish = posts.filter(
			(p) => resolveThreadsPublishDecision(p.account) === "publish",
		);
		expect(toPublish.map((p) => p.id)).toEqual(["post-1", "post-3"]);
	});

	it("deactivated-account posts are silently skipped, not failed", () => {
		const skipped = posts.filter(
			(p) => resolveThreadsPublishDecision(p.account) === "skip_deactivated",
		);
		expect(skipped.map((p) => p.id)).toEqual(["post-2"]);
	});

	it("no post is incorrectly blocked or incorrectly allowed", () => {
		const decisions = posts.map((p) => ({
			id: p.id,
			decision: resolveThreadsPublishDecision(p.account),
		}));
		expect(decisions).toEqual([
			{ id: "post-1", decision: "publish" },
			{ id: "post-2", decision: "skip_deactivated" },
			{ id: "post-3", decision: "publish" },
		]);
	});
});
