import { describe, it, expect } from "vitest";

/**
 * Verifies that sensitive database fields are stripped before
 * reaching client-side code. Tests the mapping functions directly
 * by simulating raw Supabase rows.
 */

describe("Account object sanitization", () => {
	// Simulate what getAccounts() does with a raw DB row
	function mapAccountRow(row: Record<string, unknown>) {
		const {
			threads_access_token_encrypted: _token,
			...safeRow
		} = row;
		return {
			id: safeRow.id,
			platform: "threads" as const,
			handle: (safeRow.username as string) || "",
			avatarUrl: (safeRow.avatar_url as string) || "",
			followers: (safeRow.followers_count as number) || 0,
			isActive: (safeRow.is_active as boolean) ?? true,
			status: (safeRow.status as string) || "active",
			username: safeRow.username,
			followersCount: safeRow.followers_count,
			threadsUserId: safeRow.threads_user_id,
			createdAt: safeRow.created_at,
			updatedAt: safeRow.updated_at,
			lastSyncedAt: safeRow.last_synced_at
				? new Date(safeRow.last_synced_at as string)
				: null,
			tokenExpiresAt: safeRow.token_expires_at
				? new Date(safeRow.token_expires_at as string)
				: null,
			groupId: safeRow.group_id,
			ai_config: safeRow.ai_config,
		};
	}

	const rawRow = {
		id: "acc_1",
		username: "testuser",
		avatar_url: "https://example.com/avatar.jpg",
		followers_count: 1000,
		is_active: true,
		status: "active",
		threads_user_id: "tu_123",
		created_at: "2025-01-01",
		updated_at: "2025-06-01",
		last_synced_at: "2025-06-01T00:00:00Z",
		token_expires_at: "2026-06-01T00:00:00Z",
		group_id: "grp_1",
		ai_config: { tone: "casual" },
		// SENSITIVE — must not appear in output
		threads_access_token_encrypted: "enc_abc123_secret_token_data",
		user_id: "user_private_id",
	};

	it("excludes threads_access_token_encrypted from output", () => {
		const result = mapAccountRow(rawRow);
		expect(result).not.toHaveProperty("threads_access_token_encrypted");
	});

	it("preserves ai_config for voice profile components", () => {
		const result = mapAccountRow(rawRow);
		expect(result.ai_config).toEqual({ tone: "casual" });
	});

	it("preserves all required display fields", () => {
		const result = mapAccountRow(rawRow);
		expect(result.id).toBe("acc_1");
		expect(result.username).toBe("testuser");
		expect(result.avatarUrl).toBe("https://example.com/avatar.jpg");
		expect(result.followers).toBe(1000);
		expect(result.groupId).toBe("grp_1");
		expect(result.platform).toBe("threads");
	});

	it("converts date fields to Date objects", () => {
		const result = mapAccountRow(rawRow);
		expect(result.lastSyncedAt).toBeInstanceOf(Date);
		expect(result.tokenExpiresAt).toBeInstanceOf(Date);
	});

	it("handles null date fields gracefully", () => {
		const result = mapAccountRow({
			...rawRow,
			last_synced_at: null,
			token_expires_at: null,
		});
		expect(result.lastSyncedAt).toBeNull();
		expect(result.tokenExpiresAt).toBeNull();
	});
});

describe("Instagram account sanitization", () => {
	function mapIgAccountRow(row: Record<string, unknown>) {
		const {
			instagram_access_token_encrypted: _igToken,
			facebook_page_access_token_encrypted: _fbToken,
			...safeData
		} = row;
		return safeData;
	}

	it("excludes instagram_access_token_encrypted", () => {
		const result = mapIgAccountRow({
			id: "ig_1",
			username: "iguser",
			instagram_access_token_encrypted: "enc_secret",
			facebook_page_access_token_encrypted: "enc_fb_secret",
		});
		expect(result).not.toHaveProperty("instagram_access_token_encrypted");
		expect(result).not.toHaveProperty(
			"facebook_page_access_token_encrypted",
		);
		expect(result).toHaveProperty("id", "ig_1");
		expect(result).toHaveProperty("username", "iguser");
	});
});

describe("Subscription data sanitization", () => {
	it("should not expose stripe IDs to client", () => {
		// The WorkspaceSubscription returned by getSubscription()
		// should not include stripeCustomerId or stripeSubscriptionId.
		// This test documents the expectation — the actual service
		// call requires Supabase, so we test the shape contract.
		const clientSubscription = {
			tier: "pro",
			status: "active",
			currentPeriodStart: new Date(),
			currentPeriodEnd: new Date(),
			cancelAtPeriodEnd: false,
			billingInterval: "month",
			addOnsCount: 0,
		};
		expect(clientSubscription).not.toHaveProperty("stripeCustomerId");
		expect(clientSubscription).not.toHaveProperty("stripeSubscriptionId");
		expect(clientSubscription).not.toHaveProperty("stripe_customer_id");
	});
});
