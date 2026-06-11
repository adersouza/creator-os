import { useEffect } from "react";
import { create } from "zustand";
import { supabase } from "@/services/supabase";
import {
	type AIProviderConfig,
	type AIProviderType,
	DEFAULT_AI_CONFIG,
} from "@/types/aiProvider";
import { logger } from "@/utils/logger";

import { apiUrl } from '@/lib/apiUrl';
// Dynamically import clearAIConfigCache to avoid pulling 191KB AI service
// surface into the main chunk.
const lazyClearAIConfigCache = async () => {
	const { clearAIConfigCache } = await import("@/services/ai");
	clearAIConfigCache();
};

// Module-scoped variable (replaces useRef for tracking loaded user)
let loadedForUser: string | null = null;

interface AIProviderState {
	config: AIProviderConfig;
	isLoading: boolean;
	isConfigured: boolean;
	updateConfig: (newConfig: Partial<AIProviderConfig>) => void;
	saveConfig: (configToSave?: Partial<AIProviderConfig>) => Promise<boolean>;
	reloadConfig: () => Promise<void>;
	loadConfig: (force?: boolean, providedAccessToken?: string) => Promise<void>;
	reset: () => void;
}

export const useAIProviderStore = create<AIProviderState>()((set, get) => ({
	config: DEFAULT_AI_CONFIG,
	isLoading: true,
	isConfigured: false,

	updateConfig: (newConfig: Partial<AIProviderConfig>) => {
		const merged = { ...get().config, ...newConfig };
		set({
			config: merged,
			isConfigured: Boolean(merged.apiKey && merged.apiKey.length > 0),
		});
	},

	saveConfig: async (
		configToSave?: Partial<AIProviderConfig>,
	): Promise<boolean> => {
		const { config } = get();
		const finalConfig = configToSave ? { ...config, ...configToSave } : config;

		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session?.user?.id) {
			logger.error("Cannot save AI config: No user logged in");
			return false;
		}

		logger.log("Saving AI config via API...", {
			provider: finalConfig.provider,
			hasApiKey: !!finalConfig.apiKey,
		});

		try {
			const res = await fetch(apiUrl("/api/ai/keys"), {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Authorization: `Bearer ${session.access_token}`,
				},
				body: JSON.stringify({
					provider: finalConfig.provider,
					apiKey: finalConfig.apiKey,
					model: finalConfig.model || null,
					baseUrl: finalConfig.baseUrl || null,
				}),
			});

			if (!res.ok) {
				const body = await res.json().catch(() => ({}));
				throw new Error(body.error || `Save failed (${res.status})`);
			}

			logger.log("AI config saved successfully via API");
			lazyClearAIConfigCache();
			return true;
		} catch (error) {
			logger.error("Failed to save AI config:", error);
			return false;
		}
	},

	loadConfig: async (force = false, providedAccessToken?: string) => {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		const userId = session?.user?.id;
		if (!userId) {
			set({ isLoading: false });
			return;
		}
		const accessToken = providedAccessToken || session?.access_token;
		if (!accessToken) {
			set({ isLoading: false });
			return;
		}

		// If a different user logged in, clear stale config before loading
		if (loadedForUser && loadedForUser !== userId) {
			loadedForUser = null;
			set({ config: DEFAULT_AI_CONFIG, isConfigured: false });
		}

		// Prevent duplicate loads for same user unless forced
		if (!force && loadedForUser === userId) {
			set({ isLoading: false });
			return;
		}

		try {
			const res = await fetch(apiUrl("/api/ai/keys"), {
				headers: {
					Authorization: `Bearer ${accessToken}`,
				},
			});

			if (res.ok) {
				const data = await res.json();
				const loaded: AIProviderConfig = {
					provider: (data.provider || "gemini") as AIProviderType,
					apiKey: data.apiKey || "",
					baseUrl: data.baseUrl || undefined,
					model: data.model || undefined,
					lastValidatedAt: data.updatedAt
						? new Date(data.updatedAt)
						: undefined,
				};
				set({
					config: loaded,
					isConfigured: data.hasKey === true,
				});
			}
			loadedForUser = userId;
		} catch (error) {
			logger.warn("AI config not found, using defaults:", error);
		} finally {
			set({ isLoading: false });
		}
	},

	reloadConfig: async () => {
		set({ isLoading: true });
		await lazyClearAIConfigCache();
		await get().loadConfig(true);
	},

	reset: () => {
		loadedForUser = null;
		set({
			config: DEFAULT_AI_CONFIG,
			isLoading: false,
			isConfigured: false,
		});
	},
}));

// Init hook — call once in App.tsx
export function useAIProviderInit() {
	useEffect(() => {
		const { loadConfig, reset } = useAIProviderStore.getState();

		// Load config for initial session (only if token is not expired)
		supabase.auth
			.getSession()
			.then(({ data: { session } }) => {
				if (session?.user) {
					const expiresAt = session.expires_at;
					const tokenFresh =
						!expiresAt || expiresAt > Math.floor(Date.now() / 1000);
					if (tokenFresh) {
						loadConfig(false, session.access_token);
					}
					// If expired, TOKEN_REFRESHED event will trigger loadConfig
				} else {
					reset();
				}
			})
			.catch((error) => {
				logger.error("Failed to get session for AI config:", error);
				useAIProviderStore.setState({ isLoading: false });
			});

		// Listen for auth state changes
		const {
			data: { subscription: authSubscription },
		} = supabase.auth.onAuthStateChange((event, session) => {
			if (
				(event === "SIGNED_IN" || event === "TOKEN_REFRESHED") &&
				session?.user
			) {
				// Skip if token is expired — TOKEN_REFRESHED will follow with a fresh one
				const expiresAt = session.expires_at;
				const tokenFresh =
					!expiresAt || expiresAt > Math.floor(Date.now() / 1000);
				if (tokenFresh) {
					loadConfig(false, session.access_token);
				}
			} else if (event === "SIGNED_OUT") {
				reset();
			}
		});

		return () => authSubscription.unsubscribe();
	}, []);
}
