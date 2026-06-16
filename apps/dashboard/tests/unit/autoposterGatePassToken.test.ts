import { beforeEach, describe, expect, it } from "vitest";
import {
	createAutopublishGatePassToken,
	verifyAutopublishGatePassToken,
} from "../../api/_lib/handlers/auto-post/gatePassToken";

const safeDiscoverability = {
	discoverabilitySafe: true,
	blockedTerms: [],
	blockedReason: "",
};

describe("autoposter gate pass token", () => {
	beforeEach(() => {
		process.env.AUTOPOSTER_GATE_TOKEN_SECRET = "test-gate-secret";
	});

	it("verifies a token signed for the final content and gate verdicts", () => {
		const token = createAutopublishGatePassToken({
			content: "would you date a girl who loves anime?",
			platform: "threads",
			sourceType: "ai",
			contentFingerprint: "content-fp",
			publishFingerprint: "publish-fp",
			qualityGateDecision: "pass",
			qualityGateReason: "quality_gate_passed",
			provenanceStatus: "verified",
			provenanceError: null,
			dnaDecision: "pass",
			discoverability: safeDiscoverability,
		});

		expect(token).toBeTruthy();
		expect(
			verifyAutopublishGatePassToken({
				content: "would you date a girl who loves anime?",
				token,
			}),
		).toMatchObject({ ok: true });
	});

	it("rejects missing tokens", () => {
		expect(
			verifyAutopublishGatePassToken({
				content: "safe text",
				token: null,
			}),
		).toMatchObject({
			ok: false,
			reason: "missing_gate_pass_token",
		});
	});

	it("rejects when queued content is mutated after fill", () => {
		const token = createAutopublishGatePassToken({
			content: "am i still cute after taking my headset off?",
			platform: "threads",
			sourceType: "winner_clone",
			contentFingerprint: "content-fp",
			publishFingerprint: "publish-fp",
			qualityGateDecision: "pass",
			qualityGateReason: "quality_gate_passed",
			provenanceStatus: "verified",
			provenanceError: null,
			dnaDecision: "pass",
			discoverability: safeDiscoverability,
		});

		expect(
			verifyAutopublishGatePassToken({
				content: "dm me after taking my headset off",
				token,
			}),
		).toMatchObject({
			ok: false,
			reason: "gate_pass_content_hash_mismatch",
		});
	});
});
