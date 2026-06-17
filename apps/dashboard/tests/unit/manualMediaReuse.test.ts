import { describe, expect, it } from "vitest";
import {
	createManualMediaReuseOverrideToken,
	type ManualMediaReuseTokenContext,
	verifyManualMediaReuseOverrideToken,
} from "../../api/_lib/handlers/posts/manualMediaReuse.js";

const context: ManualMediaReuseTokenContext = {
	userId: "user-1",
	platform: "instagram",
	accountId: "ig-acc-1",
	normalizedTextHash: "text-hash-1",
	mediaFingerprint: "media-fingerprint-1",
	matchId: "previous-ig-post",
	matchType: "media_url_hash",
	matchedAccountId: "ig-acc-2",
};

describe("manual media reuse override tokens", () => {
	it("accepts a token for the exact publish context", () => {
		const { token } = createManualMediaReuseOverrideToken(context, {
			nowMs: 1_000,
			expiresAtMs: 60_000,
		});

		expect(
			verifyManualMediaReuseOverrideToken(token, context, { nowMs: 2_000 }),
		).toMatchObject({ valid: true });
	});

	it("rejects expired override tokens", () => {
		const { token } = createManualMediaReuseOverrideToken(context, {
			nowMs: 1_000,
			expiresAtMs: 2_000,
		});

		expect(
			verifyManualMediaReuseOverrideToken(token, context, { nowMs: 3_000 }),
		).toMatchObject({ valid: false, reason: "expired" });
	});

	it("rejects override tokens for a different account", () => {
		const { token } = createManualMediaReuseOverrideToken(context, {
			nowMs: 1_000,
			expiresAtMs: 60_000,
		});

		expect(
			verifyManualMediaReuseOverrideToken(token, {
				...context,
				accountId: "ig-acc-other",
			}, { nowMs: 2_000 }),
		).toMatchObject({ valid: false, reason: "mismatched_accountId" });
	});
});
