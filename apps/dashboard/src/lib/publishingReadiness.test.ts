import { describe, expect, it } from "vitest";
import {
	buildPublishingReadinessIssues,
	summarizeReadinessState,
} from "./publishingReadiness";

describe("publishing readiness", () => {
	it("blocks first-time publishing when no Instagram account is connected", () => {
		const issues = buildPublishingReadinessIssues({
			hasInstagramAccount: false,
			pushState: "subscribed",
			pwaState: "installed-ios",
			instagramReady: true,
			lastHandoffCompleted: true,
		});
		expect(issues.find((issue) => issue.id === "instagram-account")?.state).toBe("blocked");
		expect(summarizeReadinessState(issues)).toBe("blocked");
	});

	it("treats denied push as warning because Notify Me fallback still works", () => {
		const issues = buildPublishingReadinessIssues({
			hasInstagramAccount: true,
			pushState: "denied",
			pwaState: "installed-ios",
			instagramReady: true,
			lastHandoffCompleted: true,
		});
		expect(issues.find((issue) => issue.id === "notify-push")?.state).toBe("warning");
		expect(summarizeReadinessState(issues)).toBe("warning");
	});

	it("marks the full first-post path ready when all signals are complete", () => {
		const issues = buildPublishingReadinessIssues({
			hasInstagramAccount: true,
			pushState: "subscribed",
			pwaState: "installed-ios",
			instagramReady: true,
			lastHandoffCompleted: true,
		});
		expect(issues.every((issue) => issue.state === "ready")).toBe(true);
		expect(summarizeReadinessState(issues)).toBe("ready");
	});
});
