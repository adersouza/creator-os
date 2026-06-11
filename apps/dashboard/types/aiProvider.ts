// AI Provider Types

export type AIProviderType =
  | "gemini"
  | "openai"
  | "anthropic"
  | "groq"
  | "custom";

export interface AIProviderConfig {
  provider: AIProviderType;
  apiKey: string;
  baseUrl?: string | undefined; // Only for custom OpenAI-compatible endpoints
  model?: string | undefined; // Optional model override
  lastValidatedAt?: Date | undefined;
}

export const AI_PROVIDERS = [
  {
    id: "gemini" as AIProviderType,
    name: "Google Gemini",
    description: "Gemini 2.5 Flash - Best quality & speed",
    icon: "✨",
    defaultModel: "gemini-2.5-flash",
    models: [
      "gemini-2.5-flash",
      "gemini-2.5-flash-lite",
      "gemini-2.0-flash",
      "gemini-2.0-flash-lite",
    ],
    placeholder: "AIza...",
    helpUrl: "https://aistudio.google.com/apikey",
  },
  {
    id: "openai" as AIProviderType,
    name: "OpenAI",
    description: "GPT-4o & GPT-4o-mini",
    icon: "🤖",
    defaultModel: "gpt-4o-mini",
    models: ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
    placeholder: "sk-...",
    helpUrl: "https://platform.openai.com/api-keys",
  },
  {
    id: "anthropic" as AIProviderType,
    name: "Anthropic",
    description: "Claude Sonnet 4",
    icon: "🧠",
    defaultModel: "claude-sonnet-4-20250514",
    models: ["claude-sonnet-4-20250514", "claude-haiku-4-5-20251001"],
    placeholder: "sk-ant-...",
    helpUrl: "https://console.anthropic.com/settings/keys",
  },
  {
    id: "groq" as AIProviderType,
    name: "Groq",
    description: "Llama 3.3 70B - Ultra fast",
    icon: "⚡",
    defaultModel: "llama-3.3-70b-versatile",
    models: [
      "llama-3.3-70b-versatile",
      "llama-3.1-8b-instant",
      "llama-3.1-70b-versatile",
    ],
    placeholder: "gsk_...",
    helpUrl: "https://console.groq.com/keys",
  },
  {
    id: "custom" as AIProviderType,
    name: "Custom Endpoint",
    description: "OpenAI-compatible API",
    icon: "🔧",
    defaultModel: "default",
    models: [],
    placeholder: "Your API key",
    helpUrl: "",
  },
] as const;

export const getProviderInfo = (providerId: AIProviderType) => {
  return AI_PROVIDERS.find((p) => p.id === providerId) || AI_PROVIDERS[0];
};

export const DEFAULT_AI_CONFIG: AIProviderConfig = {
  provider: "gemini",
  apiKey: "",
  baseUrl: undefined,
  model: undefined,
  lastValidatedAt: undefined,
};
