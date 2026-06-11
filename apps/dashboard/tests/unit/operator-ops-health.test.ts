import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";

const ROOT = path.resolve(__dirname, "../..");

function read(relativePath: string) {
	return fs.readFileSync(path.join(ROOT, relativePath), "utf8");
}

describe("operator ops health", () => {
	it("adds opsHealth, fleet capacity, and AI eval summary to the operator snapshot", () => {
		const operatorApi = read("api/operator.ts");

		expect(operatorApi).toContain("loadOperatorOpsHealth");
		expect(operatorApi).toContain("loadOperatorFleetCapacity");
		expect(operatorApi).toContain("loadOperatorAIEvalSummary");
		expect(operatorApi).toContain("loadReliabilitySections");
		expect(operatorApi).toContain("persistReliabilitySloSnapshot");
		expect(operatorApi).toContain("buildAIEvalReport");
		expect(operatorApi).toContain("AI_EVAL_DIRECT_GENERATIVE_SURFACES");
		expect(operatorApi).toContain("AI_EVAL_DOCUMENTED_NON_GENERATIVE_SURFACES");
		expect(operatorApi).toContain("opsHealth");
		expect(operatorApi).toContain("fleetCapacity");
		expect(operatorApi).toContain("aiEvalSummary");
		expect(operatorApi).toContain("reliabilitySlo");
		expect(operatorApi).toContain("metaApiUsage");
		expect(operatorApi).toContain("webhookHealth");
		expect(operatorApi).toContain("tokenSlo");
		expect(operatorApi).toContain("accountDayRows");
		expect(operatorApi).toContain("unhealthyAccounts");
		expect(operatorApi).toContain("buildOpsHealthAccounts");
		expect(operatorApi).toContain("unhealthyAccountTotal");
		expect(operatorApi).toContain("recommendations.slice(0, 100)");
		expect(operatorApi).toContain("capacityStart");
		expect(operatorApi).toContain(".from(\"cron_runs\")");
		expect(operatorApi).toContain(".from(\"webhook_deliveries\")");
		expect(operatorApi).toContain(".from(\"threads_webhook_events\")");
		expect(operatorApi).toContain(".from(\"ig_webhook_events\")");
		expect(operatorApi).toContain(".from(\"auto_post_queue\")");
		expect(operatorApi).toContain("qstash_dlq");
		expect(operatorApi).toContain("qstash_dispatch_backlog");
		expect(operatorApi).toContain("review_auto_post_dlq");
		expect(operatorApi).toContain("inspect_qstash_dispatch_backlog");
		expect(operatorApi).toContain("publish_drift");
		expect(operatorApi).toContain("Publish drift avg");
		expect(operatorApi).toContain("overFiveMinuteDrift");
		expect(operatorApi).toContain("Scheduled publish drifted by");
		expect(operatorApi).toContain(".from(\"sync_jobs\")");
		expect(operatorApi).toContain(".from(\"accounts\")");
		expect(operatorApi).toContain(".from(\"instagram_accounts\")");
		expect(operatorApi).toContain(".from(\"ai_eval_snapshots\")");
	});

	it("parses and renders ops health, fleet capacity, and AI evals in the dashboard", () => {
		const hook = read("src/hooks/useOperatorSnapshot.ts");
		const dashboard = read("src/components/dashboard-v2/tiles/WidgetTheoryTiles.test.tsx");
		const tile = read("src/components/dashboard-v2/tiles/OpsHealthTile.tsx");
		const readinessTile = read("src/components/dashboard-v2/tiles/ManagerReadinessTile.tsx");

		expect(hook).toContain("opsHealthSchema");
		expect(hook).toContain("opsHealth: opsHealthSchema");
		expect(hook).toContain("opsHealthAccountSchema");
		expect(hook).toContain("unhealthyAccounts");
		expect(hook).toContain("fleetCapacitySchema");
		expect(hook).toContain("fleetCapacityAccountSchema");
		expect(hook).toContain("recommendations: z.array(jsonRecordSchema)");
		expect(hook).toContain("capacityStart");
		expect(hook).toContain("aiEvalSummarySchema");
		expect(hook).toContain("reliabilitySloSchema");
		expect(hook).toContain("metaApiUsageSchema");
		expect(hook).toContain("webhookHealthSchema");
		expect(hook).toContain("tokenSloSchema");
		expect(read("src/pages/Reliability.tsx")).toContain("Reliability Center");
		expect(hook).toContain("aiEvalTrendPointSchema");
		expect(hook).toContain("aiEvalSuiteRowSchema");
		expect(hook).toContain("directGenerativeCoveredCount");
		expect(hook).toContain("uncoveredDirectSurfaces");
		expect(dashboard).toContain("OpsHealthTile");
		expect(dashboard).toContain("FleetCapacityTile");
		expect(dashboard).toContain("AIEvalSummaryTile");
		expect(tile).toContain("Account issues");
		expect(tile).toContain("account connections, scheduled posts, and recovery work");
		expect(tile).toContain("Unhealthy accounts");
		expect(tile).toContain("accountPageSize");
		expect(tile).toContain("matchesScope");
		expect(tile).toContain("/reliability");
		expect(readinessTile).toContain("Posting coverage");
		expect(readinessTile).toContain("AI readiness");
		expect(readinessTile).toContain("direct AI surfaces covered");
		expect(readinessTile).toContain("AI eval pass-rate trend");
		expect(readinessTile).toContain("suiteRows");
		expect(readinessTile).toContain("latestFailures");
		expect(readinessTile).toContain("/calendar");
	});

	it("records live eval snapshots for direct provider AI bypasses", () => {
		const altText = read("api/ai/alt-text.ts");
		const visionScore = read("api/_lib/handlers/ai/vision-score.ts");
		const mediaVision = read("api/_lib/mediaVision.ts");
		const inspiration = read("api/_lib/handlers/inspiration/shared.ts");
		const trendGenerator = read("api/_lib/handlers/trend-pipeline/generator.ts");

		for (const file of [altText, visionScore, mediaVision, inspiration, trendGenerator]) {
			expect(file).toContain("recordDirectAIEvalSnapshot");
		}
		expect(altText).toContain('surface: "ai_alt_text"');
		expect(visionScore).toContain('surface: "ai_vision_score"');
		expect(mediaVision).toContain('surface: "media_vision"');
		expect(inspiration).toContain('surface: "inspiration_idea"');
		expect(trendGenerator).toContain('surface: "trend_pipeline_generator"');
	});
});
