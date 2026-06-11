// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Config Resolver — single source of truth for merged autoposter config
 *
 * Merges 5 config sources in priority order (highest wins):
 * 1. auto_post_account_overrides (per-account)
 * 2. auto_post_group_config (per-group)
 * 3. auto_post_config (workspace-level)
 * 4. account_groups.voice_profile + content_strategy
 * 5. user ai_config (provider/model)
 *
 * All modules that need config should call resolveConfig() instead of
 * querying multiple tables independently.
 */

import { getUserAIConfig, resolveProvider } from "../../aiConfig.js";
import { logger } from "../../logger.js";
import { getSupabaseAny } from "../../supabase.js";
import { getWorkspaceVoiceProfile } from "./contentSelection.js";
import type { AutoPostConfig, VoiceProfile } from "./types.js";

const db = () => getSupabaseAny();

// ============================================================================
// Types
// ============================================================================

export interface ContentStrategy {
	pillars?: string[] | undefined;
	topics_to_avoid?: string[] | undefined;
	cta_rotation?: string[] | undefined;
	tone_notes?: string | undefined;
	weekly_target?: number | undefined;
	competitor_ids?: string[] | undefined;
	data_driven_insights?: Record<string, unknown> | undefined;
	peak_windows?: Array<{ day: string; hour: number }> | undefined;
}

export interface GroupTimingConfig {
	media_attachment_chance?: number | undefined;
	/** Override: pull media from this group's library instead of the current group */
	media_group_id?: string | null | undefined;
	active_hours_start?: number | undefined;
	active_hours_end?: number | undefined;
	timezone?: string | undefined;
	min_interval_minutes?: number | undefined;
	posts_per_account_per_day?: number | undefined;
	post_on_weekends?: boolean | undefined;
	enabled?: boolean | undefined;
	/** LLM quality judge — opt-in per group. Default false. */
	llm_judge_enabled?: boolean | undefined;
	/** Composite reject threshold (1.0–5.0). Default 3.0. */
	llm_judge_min_score?: number | undefined;
}

export interface AccountOverride {
	account_id: string;
	paused?: boolean | undefined;
	max_posts_per_day?: number | undefined;
	min_interval_minutes?: number | undefined;
	custom_voice?: string | undefined;
}

export interface ResolvedConfig {
	// Workspace level
	workspace: AutoPostConfig;

	// Group level
	groupId: string | undefined;
	groupName: string;
	groupTimingConfig: GroupTimingConfig | null;
	groupAccountIds: string[];

	// Voice & strategy
	voiceProfile: VoiceProfile | null;
	contentStrategy: ContentStrategy | null;

	// AI provider
	aiProvider: string | undefined;
	aiApiKey: string | undefined;
	aiModel: string | undefined;
	aiBaseUrl: string | undefined;

	// Per-account overrides (keyed by "groupId:accountId")
	accountOverrides: Map<string, AccountOverride>;

	// Computed values
	targetPlatform: "threads" | "instagram";
	slotMediaChance: number;
}

// ============================================================================
// Resolver
// ============================================================================

/**
 * Resolve all config sources into a single immutable config object.
 * Call once at the start of a pipeline run, then pass the result to all modules.
 */
export async function resolveConfig(
	workspaceConfig: AutoPostConfig,
	workspaceId: string,
	ownerId: string,
	groupId?: string,
): Promise<ResolvedConfig> {
	const targetPlatform =
		workspaceConfig.platform === "instagram" ? "instagram" : "threads";

	// ── Group config ──
	let groupTimingConfig: GroupTimingConfig | null = null;
	let groupName = "";
	let groupAccountIds: string[] = [];
	let voiceProfile: VoiceProfile | null = null;
	let contentStrategy: ContentStrategy | null = null;

	if (groupId) {
		// Fetch group metadata + voice profile + content strategy in one query
		const { data: groupData } = await db()
			.from("account_groups")
			.select(
				"name, voice_profile, content_strategy, vulnerability_ratio, sentence_length_target, time_of_day_modifiers, account_ids",
			)
			.eq("id", groupId)
			.maybeSingle();

		if (groupData) {
			groupName = groupData.name || "";
			groupAccountIds = (groupData.account_ids || []) as string[];

			// Parse voice profile
			if (groupData.voice_profile) {
				const raw = groupData.voice_profile;
				if (typeof raw === "string") {
					voiceProfile = { voice_profile: raw };
				} else {
					voiceProfile = raw as VoiceProfile;
				}
				if (groupData.vulnerability_ratio != null) {
					voiceProfile.vulnerability_ratio =
						groupData.vulnerability_ratio as number;
				}
				if (groupData.sentence_length_target) {
					voiceProfile.sentence_length_target =
						groupData.sentence_length_target as VoiceProfile["sentence_length_target"];
				}
				if (groupData.time_of_day_modifiers) {
					voiceProfile.time_of_day_modifiers =
						groupData.time_of_day_modifiers as VoiceProfile["time_of_day_modifiers"];
				}
			}

			if (groupData.content_strategy) {
				contentStrategy =
					groupData.content_strategy as unknown as ContentStrategy;
			}
		}

		// Fetch group timing config
		const { data: gc } = await db()
			.from("auto_post_group_config")
			.select(
				"media_attachment_chance, media_group_id, active_hours_start, active_hours_end, timezone, min_interval_minutes, posts_per_account_per_day, post_on_weekends, enabled, llm_judge_enabled, llm_judge_min_score",
			)
			.eq("workspace_id", workspaceId)
			.eq("group_id", groupId)
			.maybeSingle();

		if (gc) {
			groupTimingConfig = gc as GroupTimingConfig;
		}
	}

	// ── Voice profile fallback chain ──
	if (!voiceProfile) {
		const selectedGroups = workspaceConfig.posting_times?.selected_groups;
		if (selectedGroups && selectedGroups.length > 0) {
			const { data: groupData } = await db()
				.from("account_groups")
				.select("voice_profile")
				.in("id", selectedGroups)
				.not("voice_profile", "is", null)
				.limit(1);

			if (groupData && groupData.length > 0 && groupData[0]!.voice_profile) {
				const raw = groupData[0]!.voice_profile;
				if (typeof raw === "string") {
					voiceProfile = { voice_profile: raw };
				} else {
					voiceProfile = raw as VoiceProfile;
				}
			}
		}
	}
	if (!voiceProfile) {
		voiceProfile = await getWorkspaceVoiceProfile(ownerId);
	}

	// ── AI provider resolution ──
	const workspaceProvider = (
		workspaceConfig as unknown as Record<string, unknown>
	).ai_provider as string | undefined;
	const aiConfig = resolveProvider(await getUserAIConfig(ownerId), {
		workspaceProvider,
	});

	// Validate key health (cached in Redis, fail-open)
	if (aiConfig) {
		const { isKeyHealthy } = await import("../../aiConfig.js");
		if (!(await isKeyHealthy(aiConfig, ownerId))) {
			logger.warn("[configResolver] AI key failed health check", {
				ownerId,
				provider: aiConfig.provider,
			});
		}
	}

	// ── Per-account overrides ──
	const accountOverrides = new Map<string, AccountOverride>();
	if (groupId) {
		try {
			const { data: overrides } = await db()
				.from("auto_post_account_overrides")
				.select("*")
				.eq("group_id", groupId);

			if (overrides) {
				for (const o of overrides) {
					const blob = (o as Record<string, unknown>).overrides as Record<
						string,
						unknown
					> | null;
					accountOverrides.set(`${groupId}:${o.account_id}`, {
						account_id: o.account_id,
						paused: blob?.paused as boolean | undefined,
						max_posts_per_day: blob?.max_posts_per_day as number | undefined,
						min_interval_minutes: blob?.min_interval_minutes as
							| number
							| undefined,
						custom_voice: blob?.custom_voice as string | undefined,
					});
				}
			}
		} catch {
			logger.warn("[configResolver] Failed to load account overrides", {
				groupId,
			});
		}
	}

	// ── Computed: media attachment chance ──
	const platformMediaDefault = targetPlatform === "instagram" ? 95 : 22;
	let slotMediaChance =
		workspaceConfig.posting_times?.media_chance ?? platformMediaDefault;
	if (groupTimingConfig?.media_attachment_chance != null) {
		slotMediaChance = groupTimingConfig.media_attachment_chance;
	}

	return {
		workspace: workspaceConfig,
		groupId,
		groupName,
		groupTimingConfig,
		groupAccountIds,
		voiceProfile,
		contentStrategy,
		aiProvider: aiConfig?.provider,
		aiApiKey: aiConfig?.apiKey,
		aiModel: aiConfig?.model,
		aiBaseUrl: aiConfig?.baseUrl,
		accountOverrides,
		targetPlatform,
		slotMediaChance,
	};
}

/**
 * Get the effective posts_per_account_per_day for a group.
 * Group config overrides workspace default.
 */
export function getEffectivePostsPerDay(resolved: ResolvedConfig): number {
	return resolved.groupTimingConfig?.posts_per_account_per_day ?? 1;
}

/**
 * Check if an account is paused via override.
 */
export function isAccountPaused(
	resolved: ResolvedConfig,
	accountId: string,
): boolean {
	const key = `${resolved.groupId}:${accountId}`;
	return resolved.accountOverrides.get(key)?.paused === true;
}

/**
 * Get account-specific max posts per day (override > group > default).
 */
export function getAccountMaxPostsPerDay(
	resolved: ResolvedConfig,
	accountId: string,
): number {
	const key = `${resolved.groupId}:${accountId}`;
	const override = resolved.accountOverrides.get(key);
	if (override?.max_posts_per_day != null) return override.max_posts_per_day;
	return resolved.groupTimingConfig?.posts_per_account_per_day ?? 1;
}
