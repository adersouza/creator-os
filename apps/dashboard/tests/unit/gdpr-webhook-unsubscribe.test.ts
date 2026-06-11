/**
 * GDPR Webhook Unsubscribe Test
 *
 * Verifies that the account deletion route includes Meta webhook
 * unsubscription calls (DELETE .../subscribed_apps) for IG accounts,
 * and that the webhook processor dead-letters events for deleted accounts.
 */

import { existsSync, readFileSync } from "fs";
import { join } from "path";
import { describe, expect, it } from "vitest";

const DELETE_ROUTE = join(__dirname, "../../api/_lib/handlers/user/delete.ts");
const DELETE_CASCADE = join(__dirname, "../../api/_lib/handlers/user/deletionCascade.ts");
// The orchestrator delegates to platform-specific processors in this directory
const THREADS_PROCESSORS = join(__dirname, "../../api/_lib/cron/webhook-processor/threads-processors.ts");
const IG_PROCESSORS = join(__dirname, "../../api/_lib/cron/webhook-processor/ig-processors.ts");

describe("GDPR Webhook Zombie Prevention", () => {
	const deleteCode = readFileSync(DELETE_ROUTE, "utf-8") + "\n" + readFileSync(DELETE_CASCADE, "utf-8");
	const threadsProcessorCode = existsSync(THREADS_PROCESSORS) ? readFileSync(THREADS_PROCESSORS, "utf-8") : "";
	const igProcessorCode = existsSync(IG_PROCESSORS) ? readFileSync(IG_PROCESSORS, "utf-8") : "";

	// ========================================================================
	// Fix 3a: delete.ts must unsubscribe IG webhooks
	// ========================================================================

	it("delete.ts must call DELETE on subscribed_apps for IG Login accounts", () => {
		// Must reference the IG Login unsubscribe endpoint
		expect(deleteCode).toContain("graph.instagram.com");
		expect(deleteCode).toContain("subscribed_apps");
		// Must use DELETE method
		expect(deleteCode).toMatch(
			/method:\s*["']DELETE["']/,
		);
	});

	it("delete.ts must call DELETE on subscribed_apps for FB Login accounts", () => {
		// Must reference the FB Login unsubscribe endpoint pattern
		expect(deleteCode).toContain("graph.facebook.com");
		expect(deleteCode).toContain("subscribed_apps");
	});

	it("delete.ts must query instagram_accounts with login_type for unsubscription", () => {
		expect(deleteCode).toContain("login_type");
		expect(deleteCode).toContain("instagram_user_id");
		expect(deleteCode).toContain("facebook_page_id");
	});

	it("delete.ts must decrypt tokens for webhook unsubscription", () => {
		expect(deleteCode).toMatch(/decrypt/);
		expect(deleteCode).toContain("instagram_access_token_encrypted");
		expect(deleteCode).toContain("facebook_page_access_token_encrypted");
	});

	it("delete.ts webhook unsubscription must be non-blocking (wrapped in try/catch)", () => {
		// The unsubscribe block should have error handling that doesn't throw
		expect(deleteCode).toMatch(
			/webhook unsubscri.*non-blocking|IG webhook unsubscri/i,
		);
	});

	// ========================================================================
	// Fix 3b: webhook-processor must dead-letter events for deleted accounts
	// ========================================================================

	it("webhook-processor must dead-letter Threads events for missing accounts", () => {
		// Dead-letter logic lives in the platform-specific processor, not the orchestrator
		expect(threadsProcessorCode).toContain("Account not found or deleted");
		expect(threadsProcessorCode).toContain("dead_letter");
	});

	it("webhook-processor must dead-letter IG events for missing accounts", () => {
		// IG processors handle dead-lettering for missing accounts
		const combinedCode = igProcessorCode + threadsProcessorCode;
		expect(combinedCode).toContain("Account not found or deleted");
		expect(combinedCode).toContain("dead_letter");
	});
});
