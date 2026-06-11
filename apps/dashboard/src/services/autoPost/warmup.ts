// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Auto-Post Service — account warm-up.
 * Gradual ramp-up for new/inactive accounts to avoid spam detection.
 */

import { createServiceLogger, supabase } from "../api/shared";
import type { AccountWarmupConfig } from "./types";

const log = createServiceLogger("autoPostService.warmup");

export const DEFAULT_WARMUP_CONFIG: AccountWarmupConfig = {
	warmup_enabled: false,
	warmup_start_posts: 2,
	warmup_increment: 2,
	warmup_target: 15,
	warmup_start_date: null,
	warmup_completed_at: null,
};

/**
 * Get warm-up configuration for an account
 */
export const getAccountWarmupConfig = async (
	accountId: string,
): Promise<AccountWarmupConfig> => {
	try {
		const { data, error } = await supabase
			.from("accounts")
			.select("ai_config")
			.eq("id", accountId)
			.maybeSingle();

		if (error || !data?.ai_config) {
			return { ...DEFAULT_WARMUP_CONFIG };
		}

		const aiConfig = data.ai_config as { warmup?: AccountWarmupConfig | undefined };
		return aiConfig.warmup
			? { ...DEFAULT_WARMUP_CONFIG, ...aiConfig.warmup }
			: { ...DEFAULT_WARMUP_CONFIG };
	} catch (error) {
		log.error("Failed to get warmup config:", error);
		return { ...DEFAULT_WARMUP_CONFIG };
	}
};

/**
 * Save warm-up configuration for an account
 */
export const saveAccountWarmupConfig = async (
	accountId: string,
	warmupConfig: Partial<AccountWarmupConfig>,
): Promise<boolean> => {
	try {
		// Get existing ai_config
		const { data: existingData } = await supabase
			.from("accounts")
			.select("ai_config")
			.eq("id", accountId)
			.maybeSingle();

		const existingAIConfig = (existingData?.ai_config || {}) as Record<
			string,
			unknown
		>;
		const existingWarmup =
			(existingAIConfig.warmup as AccountWarmupConfig) || DEFAULT_WARMUP_CONFIG;

		const updatedWarmup = {
			...existingWarmup,
			...warmupConfig,
		};

		const { error } = await supabase
			.from("accounts")
			.update({
				ai_config: {
					...existingAIConfig,
					warmup: updatedWarmup,
				},
			})
			.eq("id", accountId);

		if (error) throw error;
		return true;
	} catch (error) {
		log.error("Failed to save warmup config:", error);
		return false;
	}
};

/**
 * Enable warm-up for an account (sets start date to today)
 */
export const enableAccountWarmup = async (
	accountId: string,
	config?: Partial<AccountWarmupConfig>,
): Promise<boolean> => {
	return saveAccountWarmupConfig(accountId, {
		...config,
		warmup_enabled: true,
		warmup_start_date: new Date().toISOString().split("T")[0]!,
		warmup_completed_at: null, // Reset completion
	});
};

/**
 * Disable warm-up for an account
 */
export const disableAccountWarmup = async (
	accountId: string,
): Promise<boolean> => {
	return saveAccountWarmupConfig(accountId, {
		warmup_enabled: false,
	});
};

/**
 * Calculate warm-up progress for display
 */
export const getWarmupProgress = (
	config: AccountWarmupConfig,
): {
	currentDay: number;
	totalDays: number;
	todayAllowance: number;
	isComplete: boolean;
	percentComplete: number;
} => {
	if (!config.warmup_enabled || !config.warmup_start_date) {
		return {
			currentDay: 0,
			totalDays: 0,
			todayAllowance: 15,
			isComplete: true,
			percentComplete: 100,
		};
	}

	// If already completed, return completed state
	if (config.warmup_completed_at) {
		const postsToAdd = config.warmup_target - config.warmup_start_posts;
		const totalDays = Math.ceil(postsToAdd / config.warmup_increment) + 1;
		return {
			currentDay: totalDays,
			totalDays,
			todayAllowance: config.warmup_target,
			isComplete: true,
			percentComplete: 100,
		};
	}

	const startDate = new Date(config.warmup_start_date);
	const today = new Date();
	startDate.setHours(0, 0, 0, 0);
	today.setHours(0, 0, 0, 0);

	const daysSinceStart = Math.floor(
		(today.getTime() - startDate.getTime()) / (1000 * 60 * 60 * 24),
	);

	const currentDay = daysSinceStart + 1;
	const todayAllowance = Math.min(
		config.warmup_start_posts + daysSinceStart * config.warmup_increment,
		config.warmup_target,
	);

	const isComplete = todayAllowance >= config.warmup_target;
	const totalDays =
		config.warmup_increment > 0
			? Math.ceil(
					(config.warmup_target - config.warmup_start_posts) /
						config.warmup_increment,
				) + 1
			: 1;
	const percentComplete = isComplete
		? 100
		: Math.min(99, Math.round((currentDay / totalDays) * 100));

	return {
		currentDay,
		totalDays,
		todayAllowance,
		isComplete,
		percentComplete,
	};
};

/**
 * Calculate warm-up allowance for use in auto-post-worker
 * Returns null if warm-up is disabled or completed (use normal limit)
 */
export const calculateWarmupAllowance = (
	warmup: AccountWarmupConfig | null,
): number | null => {
	if (!warmup?.warmup_enabled || !warmup.warmup_start_date) {
		return null;
	}

	// If already completed, return null (use normal limit)
	if (warmup.warmup_completed_at) {
		return null;
	}

	const startDate = new Date(warmup.warmup_start_date);
	const today = new Date();
	startDate.setHours(0, 0, 0, 0);
	today.setHours(0, 0, 0, 0);

	// DST note: This day-level calculation is DST-safe because both dates are
	// normalized to local midnight (setHours(0,0,0,0)). A DST transition shifts
	// both by the same offset, so the difference in milliseconds still yields the
	// correct whole-day count. The ±1h DST delta is absorbed by Math.floor on a
	// 86,400,000ms divisor and never crosses a day boundary.
	const daysSinceStart = Math.floor(
		(today.getTime() - startDate.getTime()) / (1000 * 60 * 60 * 24),
	);

	const allowance =
		warmup.warmup_start_posts + daysSinceStart * warmup.warmup_increment;

	// Cap at target
	return Math.min(allowance, warmup.warmup_target);
};
