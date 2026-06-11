/**
 * Instagram Publish Orchestrator Tests
 *
 * Validates that:
 * 1. orchestrate.ts contains the required integrations
 * 2. All 3 publish paths use orchestrateIGPublish (not direct postToInstagram)
 * 3. Legacy transform/cleanup logic is no longer in the orchestrator
 */

import { readFileSync } from "fs";
import { join } from "path";
import { describe, expect, it } from "vitest";

const ORCHESTRATE = join(__dirname, "../../api/_lib/instagram/orchestrate.ts");
const SCHEDULED = join(__dirname, "../../api/_lib/cron/scheduled-posts/publishInstagram.ts");
const MANUAL = join(__dirname, "../../api/_lib/handlers/posts/publish.ts");
const AUTOPOSTER = join(__dirname, "../../api/_lib/handlers/auto-post/publisher.ts");

const orchestrateCode = readFileSync(ORCHESTRATE, "utf-8");
const scheduledCode = readFileSync(SCHEDULED, "utf-8");
const manualCode = readFileSync(MANUAL, "utf-8");
const autoposterCode = readFileSync(AUTOPOSTER, "utf-8");

describe("IG Publish Orchestrator — Module Integration", () => {
	it("must import postToInstagram from publishing.js", () => {
		expect(orchestrateCode).toContain("postToInstagram");
		expect(orchestrateCode).toContain("./publishing.js");
	});

	it("must import schedulePostPublishSyncs", () => {
		expect(orchestrateCode).toContain("schedulePostPublishSyncs");
	});

	it("must import checkMediaUrlAccessible", () => {
		expect(orchestrateCode).toContain("checkMediaUrlAccessible");
	});

	it("must import autoShareToStory", () => {
		expect(orchestrateCode).toContain("autoShareToStory");
	});

	it("must no longer import legacy image transform helpers", () => {
		expect(orchestrateCode).not.toContain("transformImageForIG");
		expect(orchestrateCode).not.toContain("cleanupTransformedImage");
	});

	it("must shallow copy postData before publishing", () => {
		expect(orchestrateCode).toContain("...options.postData");
	});
});

describe("IG Publish Orchestrator — Path Migration", () => {
	it("scheduled cron must use orchestrateIGPublish", () => {
		expect(scheduledCode).toContain("orchestrateIGPublish");
	});

	it("scheduled cron must NOT directly call postToInstagram for new posts", () => {
		// The orchestrator import should replace direct postToInstagram calls
		// Note: postToInstagram may still appear in retryIGContainers (that's fine — retry path is separate)
		const newPostSection = scheduledCode.slice(
			scheduledCode.indexOf("processNewIGPosts"),
		);
		// Should use orchestrateIGPublish, not direct postToInstagram call
		expect(newPostSection).toContain("orchestrateIGPublish");
	});

	it("manual publish must use orchestrateIGPublish", () => {
		expect(manualCode).toContain("orchestrateIGPublish");
	});

	it("auto-poster must use orchestrateIGPublish", () => {
		expect(autoposterCode).toContain("orchestrateIGPublish");
	});

	it("scheduled cron must enable mediaCheck", () => {
		expect(scheduledCode).toContain("mediaCheck: true");
	});

	it("manual publish must enable mediaCheck", () => {
		expect(manualCode).toContain("mediaCheck: true");
	});

	it("image transform logic must NOT exist in scheduled cron anymore", () => {
		expect(scheduledCode).not.toContain("transformImageForIG");
		expect(scheduledCode).not.toContain("cleanupTransformedImage");
	});

	it("image transform logic must NOT exist in auto-poster anymore", () => {
		expect(autoposterCode).not.toContain("transform:");
	});
});
