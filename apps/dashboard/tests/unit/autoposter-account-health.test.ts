import { describe, expect, it } from "vitest";
import {
	calculateAutoposterAccountHealth,
	classifyAutoposterHealthScore,
	isPublishAttemptFailureForAccountHealth,
} from "../../api/_lib/handlers/auto-post/accountHealth.js";

describe("autoposter account health scoring", () => {
	it("keeps a clean account in the normal tier", () => {
		const result = calculateAutoposterAccountHealth({
			recentPublishSuccesses: 6,
			engagementFetchSuccesses: 6,
		});

		expect(result.score).toBeGreaterThanOrEqual(80);
		expect(result.reason).toContain("recent_publish_success");
		expect(classifyAutoposterHealthScore(result.score)).toBe("normal");
	});

	it("deprioritizes accounts with transient failures and quota pressure", () => {
		const result = calculateAutoposterAccountHealth({
			transientPublishFailures: 2,
			quotaWarnings: 1,
			recentPublishSuccesses: 1,
		});

		expect(result.score).toBeGreaterThanOrEqual(60);
		expect(result.score).toBeLessThan(80);
		expect(result.reason).toContain("transient_publish_failures:2");
		expect(result.reason).toContain("quota_warnings:1");
		expect(classifyAutoposterHealthScore(result.score)).toBe("deprioritized");
	});

	it("suppresses accounts with OAuth failures, dead letters, and shadowban signals", () => {
		const result = calculateAutoposterAccountHealth({
			oauthFailures: 1,
			deadLetters: 2,
			isShadowbanned: true,
			isSuppressed: true,
			duplicateBlocks: 1,
		});

		expect(result.score).toBeLessThan(40);
		expect(result.reason).toContain("oauth_failures:1");
		expect(result.reason).toContain("dead_letters:2");
		expect(result.reason).toContain("shadowban_or_suppression");
		expect(classifyAutoposterHealthScore(result.score)).toBe("suppressed");
	});

	it("does not treat active-window requeues as account health failures", () => {
		expect(
			isPublishAttemptFailureForAccountHealth({
				result: "requeued",
				errorCode: "outside_active_window",
				errorMessage: "No fallback account satisfied active-window constraints",
			}),
		).toBe(false);

		expect(
			isPublishAttemptFailureForAccountHealth({
				result: "requeued",
				errorCode: "meta_transient_error",
				errorMessage: "An unexpected Instagram error occurred.",
			}),
		).toBe(true);
	});

	it("does not treat cap-control requeues as account health failures", () => {
		const capReasons = [
			"suppressed_cap_zero",
			"warmup_cap_exceeded",
			"held_cap_exceeded",
			"performance_recommended_cap_exceeded",
			"daily_cap",
			"stale_warmup_cap_exceeded",
		];

		for (const reason of capReasons) {
			expect(
				isPublishAttemptFailureForAccountHealth({
					result: "requeued",
					errorCode: reason,
					errorMessage: `${reason} — requeued`,
				}),
			).toBe(false);
		}
	});

	it("does not treat system claim failures as account health failures", () => {
		expect(
			isPublishAttemptFailureForAccountHealth({
				result: "claim_failed",
				errorCode: "claim_failed",
				errorMessage:
					"Atomic claim did not match pending/queued due queue item predicates",
			}),
		).toBe(false);
	});

	it("does not treat Meta code=1 unknown OAuthException as account health failure", () => {
		expect(
			isPublishAttemptFailureForAccountHealth({
				result: "requeued",
				errorCode: "retryable_publish_failure",
				errorMessage:
					"An unknown error occurred (code=1, type=OAuthException)",
			}),
		).toBe(false);
	});
});
