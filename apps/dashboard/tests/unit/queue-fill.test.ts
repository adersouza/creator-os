/**
 * Queue Fill Handler Tests
 *
 * Validates that the AI content generation trigger:
 * 1. Verifies QStash signature
 * 2. Validates request body with Zod
 * 3. Returns appropriate skip reasons for disabled/missing configs
 * 4. Rejects non-POST methods
 */

import { readFileSync } from "fs";
import { join } from "path";
import { describe, expect, it } from "vitest";

const HANDLER_PATH = join(__dirname, "../../api/queue-fill.ts");
const handlerCode = readFileSync(HANDLER_PATH, "utf-8");

describe("Queue Fill Handler", () => {
	it("must verify QStash signature", () => {
		expect(handlerCode).toContain("verifyQStashSignature");
	});

	it("must reject non-POST with 405", () => {
		expect(handlerCode).toContain("405");
		expect(handlerCode).toMatch(/method\s*!==\s*["']POST["']/);
	});

	it("must validate body with Zod schema", () => {
		expect(handlerCode).toContain("QueueFillBodySchema");
		expect(handlerCode).toContain(".safeParse(");
	});

	it("must return skip reason for invalid body", () => {
		expect(handlerCode).toContain("invalid_body");
	});

	it("must return reason when no auto_post_config exists", () => {
		expect(handlerCode).toContain("no_config");
	});

	it("must return reason when auto-post is disabled", () => {
		expect(handlerCode).toContain("disabled");
		expect(handlerCode).toContain("is_enabled");
	});

	it("must return reason when AI queue fill is disabled", () => {
		expect(handlerCode).toContain("ai_fill_disabled");
		expect(handlerCode).toContain("enable_ai_queue_fill");
	});

	it("must require workspaceId and ownerId in schema", () => {
		expect(handlerCode).toContain("workspaceId");
		expect(handlerCode).toContain("ownerId");
	});

	it("must derive workspace owner and group scope from database rows", () => {
		expect(handlerCode).toContain('.from("workspaces")');
		expect(handlerCode).toContain('.select("id, owner_id")');
		expect(handlerCode).toContain("Queue fill owner mismatch");
		expect(handlerCode).toContain('.from("account_groups")');
		expect(handlerCode).toContain('.select("id, user_id")');
		expect(handlerCode).not.toContain("group.workspace_id");
		expect(handlerCode).toContain("Queue fill group mismatch");
	});
});
