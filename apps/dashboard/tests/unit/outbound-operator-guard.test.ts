import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = join(__dirname, "../..");

function read(relativePath: string) {
	return readFileSync(join(ROOT, relativePath), "utf8");
}

describe("outbound operator guard wiring", () => {
	it("provides one shared helper for kill-switch and audit enforcement", () => {
		const helper = read("api/_lib/outboundOperatorGuard.ts");

		expect(helper).toContain("enforceOutboundOperatorGuard");
		expect(helper).toContain("requireOperatorActionAudit");
		expect(helper).toContain("checkOperatorKillSwitch");
		expect(helper).toContain("Execution audit persistence is required for outbound writes");
		expect(helper).toContain("recordOutboundOperatorResult");
	});

	it("guards scheduled publish before platform dispatch and treats blocks as non-retryable", () => {
		const publishPost = read("api/_lib/publishPost.ts");
		const receiver = read("api/scheduled-post-publish.ts");
		const guardIndex = publishPost.indexOf("await enforceOutboundOperatorGuard");
		const threadsIndex = publishPost.indexOf("publishThreadsPost(postId)");
		const igIndex = publishPost.indexOf("publishInstagramPost(postId)");

		expect(publishPost).toContain('actionName: "publish_post"');
		expect(publishPost).toContain('riskLevel: "critical"');
		expect(guardIndex).toBeGreaterThan(0);
		expect(threadsIndex).toBeGreaterThan(guardIndex);
		expect(igIndex).toBeGreaterThan(guardIndex);
		expect(receiver).toContain('"kill_switch"');
		expect(receiver).toContain('"audit_failed"');
	});

	it("guards queue fill dispatch and receiver paths", () => {
		const receiver = read("api/queue-fill.ts");
		const manual = read("api/_lib/handlers/auto-post/route/queueHandlers.ts");

		expect(receiver).toContain("withIdempotency");
		expect(receiver).toContain("queueFillKey");
		expect(receiver).toContain("requireKey: true");
		expect(receiver).toContain("failClosed: true");
		expect(receiver).toContain("await enforceOutboundOperatorGuard");
		expect(receiver).toContain('actionName: "queue_fill"');
		expect(receiver).toContain('riskLevel: "high"');
		expect(manual).toContain("Manual queue-fill blocked by outbound operator guard");
		expect(manual).toContain('actionName: "queue_fill"');
	});

	it("guards public reply and auto-reply sends", () => {
		const reply = read("api/_lib/handlers/replies/postReply.ts");
		const autoReply = read("api/_lib/handlers/auto-post/autoReply.ts");

		expect(reply).toContain('actionName: "send_reply"');
		expect(reply).toContain("Reply blocked by outbound operator guard");
		expect(reply).toContain("recordOutboundOperatorResult");
		expect(autoReply).toContain('actionName: "auto_reply"');
		expect(autoReply).toContain("releasePublishClaim");
		expect(autoReply).toContain("recordOutboundOperatorResult");
	});

	it("guards remaining cron and worker outbound publish paths", () => {
		const threadsCron = read(
			"api/_lib/cron/scheduled-posts/publishThreads.ts",
		);
		const crossReply = read("api/_lib/crossReplyPublisher.ts");
		const ctaReply = read("api/cron/cta-reply-worker.ts");

		expect(threadsCron).toContain("guardThreadsCronPublish");
		expect(threadsCron).toContain('"scheduled-posts-cron"');
		expect(threadsCron).toContain("recordThreadsCronPublishResult");
		expect(threadsCron).toContain('actionName: "publish_post"');
		expect(threadsCron).toContain('riskLevel: "critical"');

		expect(crossReply).toContain('actionName: "cross_reply"');
		expect(crossReply).toContain("cross-reply-publish");
		expect(crossReply).toContain("recordOutboundOperatorResult");

		expect(ctaReply).toContain('actionName: "cta_reply"');
		expect(ctaReply).toContain("CTA reply blocked by outbound guard");
		expect(ctaReply).toContain("recordOutboundOperatorResult");
	});

	it("guards operator replay and DLQ recovery writes with idempotency and audit", () => {
		const replay = read("api/autopilot-replay.ts");
		const replayService = read("src/services/autopilotService.ts");
		const dlq = read("api/_lib/handlers/admin/dead-letters.ts");
		const postsApi = read("api/posts.ts");
		const postsService = read("src/services/api/posts.ts");

		expect(replay).toContain("withIdempotency");
		expect(replay).toContain("route: \"autopilot-replay\"");
		expect(replay).toContain("requireKey: true");
		expect(replay).toContain("await enforceOutboundOperatorGuard");
		expect(replay).toContain('actionName: "queue_fill_replay"');
		expect(replayService).toContain("'Idempotency-Key': `autopilot-replay:${runId}:${stepId}`");

		expect(dlq).toContain("withIdempotency");
		expect(dlq).toContain("route: \"admin/dead-letters\"");
		expect(dlq).toContain("requireKey: true");
		expect(dlq).toContain("admin.dead-letter.retry");

		expect(postsApi).toContain('"delete"');
		expect(postsApi).toContain('"repost"');
		expect(postsService).toContain("delete-post:${id}:");
		expect(postsService).toContain("repost:${accountId}:${mediaId}");
	});
});
