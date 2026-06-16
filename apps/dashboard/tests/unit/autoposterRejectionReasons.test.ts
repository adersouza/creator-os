import { describe, expect, it } from "vitest";
import { getAutoposterRejectionReason } from "../../api/_lib/handlers/auto-post/rejectionReason";

describe("autoposter rejection reason extraction", () => {
	it("uses top-level rejection reason first", () => {
		expect(
			getAutoposterRejectionReason({
				rejection_reason: "prefilter:trigram-dupe:1.000",
				metadata: {
					quality_gate: { reason: "confidence:uncertain_content" },
				},
			}),
		).toBe("prefilter:trigram-dupe:1.000");
	});

	it("falls back to quality gate reason stored in metadata", () => {
		expect(
			getAutoposterRejectionReason({
				rejection_reason: null,
				metadata: {
					quality_gate: { reason: "confidence:uncertain_content" },
				},
			}),
		).toBe("confidence:uncertain_content");
	});

	it("falls back to approval and dna reasons before unknown", () => {
		expect(
			getAutoposterRejectionReason({
				metadata: {
					approval: { reason: "dna_needs_review" },
				},
			}),
		).toBe("dna_needs_review");

		expect(
			getAutoposterRejectionReason({
				metadata: {
					dna: { reasons: ["high_genericness", "missing_profile_cue"] },
				},
			}),
		).toBe("dna:high_genericness");
	});
});
