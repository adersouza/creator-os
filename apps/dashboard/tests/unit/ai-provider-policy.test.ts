import { describe, expect, it } from "vitest";
import { redactAIActionText } from "@/api/_lib/handlers/auto-post/aiProviders";
import { resolveProvider } from "@/api/_lib/aiConfig";

describe("AI provider policy", () => {
	it("does not silently route user-key configs to platform fallback providers", () => {
		const config = {
			provider: "gemini",
			apiKey: "user-gemini-key",
			source: "user" as const,
		};

		const resolved = resolveProvider(config, {
			workspaceProvider: "xai",
			isHeroPost: true,
			xaiLoadSplitRatio: 1,
		});

		expect(resolved).toEqual(config);
	});

	it("redacts sensitive AI action log text", () => {
		expect(
			redactAIActionText("email me a@b.com or call 555-123-4567 with sk-abc1234567890DEF"),
		).toBe("email me [EMAIL] or call [PHONE] with sk-[REDACTED]");
	});
});
