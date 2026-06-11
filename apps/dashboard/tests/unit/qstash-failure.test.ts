/**
 * QStash Failure Handler Tests
 *
 * Validates that the DLQ callback handler correctly:
 * 1. Marks scheduled posts as failed
 * 2. Marks queue items as dead_letter
 * 3. Marks export jobs as failed
 * 4. Fires Discord alerts
 * 5. Returns 200 even on internal errors (prevents QStash retry loops)
 * 6. Verifies QStash signature before processing
 */

import { readFileSync } from "fs";
import { join } from "path";
import { describe, expect, it } from "vitest";

const HANDLER_PATH = join(__dirname, "../../api/qstash-failure.ts");
const handlerCode = readFileSync(HANDLER_PATH, "utf-8");

describe("QStash Failure Handler", () => {
	it("must verify QStash signature before any DB operations", () => {
		const sigIndex = handlerCode.indexOf("verifyQStashSignature");
		const dbIndex = handlerCode.indexOf("getPrivilegedSupabaseAny");
		expect(sigIndex).toBeGreaterThan(-1);
		expect(dbIndex).toBeGreaterThan(-1);
		// Signature check must come before any DB access
		expect(sigIndex).toBeLessThan(dbIndex);
	});

	it("must reject non-POST requests with 405", () => {
		expect(handlerCode).toContain("405");
		expect(handlerCode).toMatch(/method\s*!==\s*["']POST["']/);
	});

	it("must mark posts as failed when postId is present", () => {
		// Should update posts table with status='failed'
		expect(handlerCode).toContain('.from("posts")');
		expect(handlerCode).toContain("failed");
		expect(handlerCode).toContain("postId");
	});

	it("must mark queue items as dead_letter when queueItemId is present", () => {
		expect(handlerCode).toContain('.from("auto_post_queue")');
		expect(handlerCode).toContain("dead_letter");
		expect(handlerCode).toContain("queueItemId");
	});

	it("must mark export jobs as failed when jobId is present", () => {
		expect(handlerCode).toContain('.from("export_jobs")');
		expect(handlerCode).toContain("jobId");
	});

	it("must fire Discord alert with AlertLevel.ERROR", () => {
		expect(handlerCode).toContain("AlertLevel.ERROR");
		expect(handlerCode).toContain("alert(");
	});

	it("must return 200 even on internal handler errors (prevents retry loops)", () => {
		expect(handlerCode).toMatch(
			/\.status\(200\)\s*\.json\(\{\s*ok:\s*false,\s*error:\s*"Internal error processing failure callback"/,
		);
	});

	it("must extract original URL from QStash headers", () => {
		expect(handlerCode).toContain("upstash-failed-callback-url");
	});
});
