import { describe, it, expect, beforeEach, vi } from "vitest";
import { useAIProviderStore } from "@/src/stores/useAIProviderStore";
import { DEFAULT_AI_CONFIG } from "@/types/aiProvider";

// Mock external dependencies
vi.mock("@/services/supabase", () => ({
  supabase: {
    auth: {
      getSession: vi.fn().mockResolvedValue({ data: { session: null } }),
      onAuthStateChange: vi.fn().mockReturnValue({
        data: { subscription: { unsubscribe: vi.fn() } },
      }),
    },
    from: vi.fn().mockReturnValue({
      select: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
        }),
      }),
      upsert: vi.fn().mockResolvedValue({ error: null }),
    }),
  },
}));

vi.mock("@/utils/logger", () => ({
  logger: { error: vi.fn(), log: vi.fn(), warn: vi.fn(), info: vi.fn(), debug: vi.fn() },
}));

vi.mock("@/services/aiService", () => ({
  clearAIConfigCache: vi.fn(),
}));

describe("aiProviderStore", () => {
  beforeEach(() => {
    useAIProviderStore.getState().reset();
  });

  describe("initial state", () => {
    it("has default config", () => {
      const state = useAIProviderStore.getState();
      expect(state.config.provider).toBe("gemini");
      expect(state.config.apiKey).toBe("");
    });

    it("is not loading after reset", () => {
      expect(useAIProviderStore.getState().isLoading).toBe(false);
    });

    it("is not configured by default", () => {
      expect(useAIProviderStore.getState().isConfigured).toBe(false);
    });
  });

  describe("updateConfig", () => {
    it("merges partial config", () => {
      useAIProviderStore.getState().updateConfig({ provider: "openai" });
      expect(useAIProviderStore.getState().config.provider).toBe("openai");
      expect(useAIProviderStore.getState().config.apiKey).toBe(""); // preserved
    });

    it("sets isConfigured when apiKey is provided", () => {
      useAIProviderStore.getState().updateConfig({ apiKey: "sk-test-key-123" });
      expect(useAIProviderStore.getState().isConfigured).toBe(true);
    });

    it("sets isConfigured to false when apiKey is empty", () => {
      useAIProviderStore.getState().updateConfig({ apiKey: "sk-test" });
      useAIProviderStore.getState().updateConfig({ apiKey: "" });
      expect(useAIProviderStore.getState().isConfigured).toBe(false);
    });

    it("updates multiple fields at once", () => {
      useAIProviderStore.getState().updateConfig({
        provider: "anthropic",
        apiKey: "sk-ant-test",
        model: "claude-3-5-sonnet-20241022",
      });
      const config = useAIProviderStore.getState().config;
      expect(config.provider).toBe("anthropic");
      expect(config.apiKey).toBe("sk-ant-test");
      expect(config.model).toBe("claude-3-5-sonnet-20241022");
    });
  });

  describe("reset", () => {
    it("resets to default config", () => {
      useAIProviderStore.getState().updateConfig({
        provider: "openai",
        apiKey: "sk-test",
      });
      useAIProviderStore.getState().reset();
      expect(useAIProviderStore.getState().config).toEqual(DEFAULT_AI_CONFIG);
    });

    it("resets isConfigured to false", () => {
      useAIProviderStore.getState().updateConfig({ apiKey: "test" });
      useAIProviderStore.getState().reset();
      expect(useAIProviderStore.getState().isConfigured).toBe(false);
    });

    it("sets isLoading to false", () => {
      useAIProviderStore.setState({ isLoading: true });
      useAIProviderStore.getState().reset();
      expect(useAIProviderStore.getState().isLoading).toBe(false);
    });
  });

  describe("saveConfig", () => {
    it("returns false when no user session", async () => {
      const result = await useAIProviderStore.getState().saveConfig();
      expect(result).toBe(false);
    });
  });

  describe("loadConfig", () => {
    it("sets isLoading to false when no session", async () => {
      useAIProviderStore.setState({ isLoading: true });
      await useAIProviderStore.getState().loadConfig();
      expect(useAIProviderStore.getState().isLoading).toBe(false);
    });
  });
});
