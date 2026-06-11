import { describe, expect, it } from "vitest";
import { evaluateQueueProvenance } from "../../api/_lib/handlers/auto-post/provenanceGate.js";

describe("autoposter provenance gate", () => {
	it("allows manual rows without generated provenance", () => {
		const result = evaluateQueueProvenance({ source_type: "manual" });

		expect(result.decision).toBe("manual_allowed");
		expect(result.reasons).toEqual([]);
	});

	it("requires AI rows to carry source, content, quality, generation, and judge evidence", () => {
		const result = evaluateQueueProvenance({
			source_type: "ai",
			publish_fingerprint: "publish-fp",
			metadata: { quality_gate: { decision: "pass" } },
		});

		expect(result.decision).toBe("missing");
		expect(result.reasons).toContain("missing_generation_id");
		expect(result.reasons).toContain("missing_judge_result");
	});

	it("passes AI rows with complete provenance", () => {
		const result = evaluateQueueProvenance({
			source_type: "ai",
			content_fingerprint: "content-fp",
			generation_id: "gen-1",
			source_id: "group:group-1",
			metadata: {
				quality_gate: { decision: "pass" },
				judge: { score: 4.2 },
			},
		});

		expect(result.decision).toBe("pass");
		expect(result.reasons).toEqual([]);
	});

	it("requires competitor rows to carry source ids", () => {
		const result = evaluateQueueProvenance({
			source_type: "competitor_copy",
			content_fingerprint: "content-fp",
			metadata: { quality_gate: { decision: "pass" } },
		});

		expect(result.decision).toBe("missing");
		expect(result.reasons).toContain("missing_source_id");
	});
});
