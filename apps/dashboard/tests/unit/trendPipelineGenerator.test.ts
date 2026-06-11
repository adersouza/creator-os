import { beforeEach, describe, expect, it, vi } from "vitest";

const mockGenerateContent = vi.fn();
const mockGoogleGenAI = vi.fn().mockImplementation(function MockGoogleGenAI() {
	return {
	models: {
		generateContent: mockGenerateContent,
	},
	};
});
const mockLoggerWarn = vi.fn();

vi.mock("@google/genai", () => ({
	GoogleGenAI: mockGoogleGenAI,
}));

vi.mock("../../api/_lib/geminiRetry.js", () => ({
	withGeminiRetry: (fn: () => Promise<unknown>) => fn(),
}));

vi.mock("../../api/_lib/aiUsageTracking.js", () => ({
	trackGeminiResponseCost: vi.fn(),
}));

vi.mock("../../api/_lib/logger.js", () => ({
	logger: {
		warn: (...args: unknown[]) => mockLoggerWarn(...args),
		error: vi.fn(),
		info: vi.fn(),
		debug: vi.fn(),
	},
}));

const TREND = {
	topic: "New launch",
	context: "A launch is trending",
	relevanceScore: 90,
	topicHash: "hash-1",
	accelerationScore: 2,
	trendShape: "spike" as const,
	isHighPriority: true,
	sources: [],
};

describe("trend pipeline generator", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		delete process.env.GEMINI_API_KEY;
		mockGenerateContent.mockResolvedValue({ text: "generated post" });
	});

	it("skips non-Gemini user AI configs when no Gemini fallback key exists", async () => {
		const { generateTrendPost } = await import(
			"../../api/_lib/handlers/trend-pipeline/generator"
		);

		const result = await generateTrendPost({
			trend: TREND,
			format: "hot_take",
			voiceProfile: null,
			extractedStyle: null,
			userAIConfig: {
				provider: "xai",
				apiKey: "xai-key",
				model: "grok-4-1-fast",
				source: "env_fallback",
			},
			userId: "user-1",
		});

		expect(result).toBeNull();
		expect(mockGoogleGenAI).not.toHaveBeenCalled();
		expect(mockLoggerWarn).toHaveBeenCalledWith(
			"[trend-scanner] Gemini key unavailable for trend generation",
			expect.objectContaining({
				provider: "xai",
				model: "grok-4-1-fast",
			}),
		);
	});

	it("uses the platform Gemini key instead of a non-Gemini user config", async () => {
		process.env.GEMINI_API_KEY = "platform-gemini-key";
		const { generateTrendPost } = await import(
			"../../api/_lib/handlers/trend-pipeline/generator"
		);

		const result = await generateTrendPost({
			trend: TREND,
			format: "hot_take",
			voiceProfile: null,
			extractedStyle: null,
			userAIConfig: {
				provider: "openai",
				apiKey: "openai-key",
				model: "gpt-4o-mini",
				source: "env_fallback",
			},
			userId: "user-1",
		});

		expect(result).toBe("generated post");
		expect(mockGoogleGenAI).toHaveBeenCalledWith({
			apiKey: "platform-gemini-key",
		});
		expect(mockGenerateContent).toHaveBeenCalledWith(
			expect.objectContaining({
				model: "gemini-2.5-flash",
			}),
		);
	});
});
