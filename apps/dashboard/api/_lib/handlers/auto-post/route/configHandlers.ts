/**
 * Config handler modules for auto-post API.
 * Handles: group configs, workspace configs, account overrides
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../../apiResponse.js";
import { logger } from "../../../logger.js";
import { validateUrlNotPrivate } from "../../../ssrfProtection.js";
import { requireMinTier } from "../../../tierGate.js";
import {
	AutoPostConfigSchema,
	AutoPostGroupConfigInnerSchema,
	parseBodyOrError,
	WorkspaceConfigSchema,
} from "../../../validation.js";
import { cancelQueueItemsByIds } from "../queueState.js";
import {
	db,
	resolveWorkspaceId,
	verifyAccountBelongsToGroup,
	verifyGroupBelongsToWorkspace,
	verifyWorkspaceAccess,
	verifyWorkspaceWriteAccess,
} from "./routeHelpers.js";

export async function handleGetGroupConfigs(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;

	const workspaceId = await resolveWorkspaceId(
		req.body?.workspaceId,
		userId,
		res,
	);
	if (!workspaceId) return;

	if (!(await verifyWorkspaceAccess(userId, workspaceId, res))) return;

	const { data, error } = await db()
		.from("auto_post_group_config")
		.select("*")
		.eq("workspace_id", workspaceId);

	if (error) {
		logger.error("Failed to fetch group configs", {
			workspaceId,
			userId,
			error: String(error),
		});
		return apiError(res, 500, "Internal server error");
	}

	return apiSuccess(res, { configs: data || [] });
}

export async function handleUpsertGroupConfig(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;

	const parsed = parseBodyOrError(res, AutoPostConfigSchema, req.body);
	if (!parsed) return;
	const { workspaceId, groupId, config } = parsed;

	if (!(await verifyWorkspaceWriteAccess(userId, workspaceId, res))) return;
	if (!(await verifyGroupBelongsToWorkspace(groupId, workspaceId, res))) return;

	// Build upsert payload — use two-path approach to avoid overwriting
	// existing values with defaults on partial updates
	const upsertPayload: Record<string, unknown> = {
		workspace_id: workspaceId,
		group_id: groupId,
		updated_at: new Date().toISOString(),
	};

	// Map of config fields → their defaults (used only for initial insert)
	const fieldDefaults: Record<string, unknown> = {
		posts_per_account_per_day: 4,
		min_interval_minutes: 90,
		max_interval_minutes: null,
		active_hours_start: 8,
		active_hours_end: 22,
		timezone: "America/New_York",
		post_on_weekends: true,
		enabled: true,
		enable_auto_reply: false,
		auto_reply_trigger_count: 1,
		auto_reply_window_hours: 24,
		auto_reply_daily_limit: 5,
		auto_reply_ratio: 0.5,
		// M2 fix: fields that were accepted by MCP/Zod but silently dropped
		content_sources: null,
		platform: null,
		round_robin_enabled: true,
		media_attachment_chance: 0,
		media_source: "global",
		require_approval: false,
		crossreshare_to_ig: false,
		crossreshare_to_ig_dark_mode: false,
		// CTA reply system fields
		cta_reply_enabled: false,
		cta_reply_min_likes: 5,
		cta_reply_delay_hours: 16,
		cta_templates: null,
		// Media group reference
		media_group_id: null,
		// Human randomness — variable daily posts + rest days
		min_posts_per_account_per_day: null,
		rest_days_per_week: 0,
	};

	// Check if row already exists
	const { data: existing } = await db()
		.from("auto_post_group_config")
		.select("id")
		.eq("workspace_id", workspaceId)
		.eq("group_id", groupId)
		.maybeSingle();

	if (existing) {
		// UPDATE path: only set fields explicitly provided — don't touch the rest
		for (const key of Object.keys(fieldDefaults)) {
			const val = config?.[key as keyof typeof config];
			if (val !== undefined) {
				upsertPayload[key] = val;
			}
		}
	} else {
		// INSERT path: apply defaults for any missing fields
		for (const [key, defaultVal] of Object.entries(fieldDefaults)) {
			const val = config?.[key as keyof typeof config];
			upsertPayload[key] = val !== undefined ? val : defaultVal;
		}
	}

	const { data, error } = await db()
		.from("auto_post_group_config")
		.upsert(upsertPayload, { onConflict: "workspace_id,group_id" })
		.select()
		.maybeSingle();

	if (error) {
		logger.error("Failed to upsert group config", {
			workspaceId,
			groupId,
			userId,
			error: String(error),
		});
		return apiError(res, 500, "Internal server error");
	}

	return apiSuccess(res, { config: data });
}

export async function handleDeleteGroupConfig(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;

	const { workspaceId, groupId } = req.body;
	if (!workspaceId || !groupId)
		return apiError(res, 400, "workspaceId and groupId are required");

	if (!(await verifyWorkspaceWriteAccess(userId, workspaceId, res))) return;
	if (!(await verifyGroupBelongsToWorkspace(groupId, workspaceId, res))) return;

	const { error } = await db()
		.from("auto_post_group_config")
		.delete()
		.eq("workspace_id", workspaceId)
		.eq("group_id", groupId);

	if (error) {
		logger.error("Failed to delete group config", {
			workspaceId,
			groupId,
			userId,
			error: String(error),
		});
		return apiError(res, 500, "Internal server error");
	}

	return apiSuccess(res);
}

export async function handleToggleGroupMode(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;

	const { workspaceId, groupId, enabled, scope } = req.body;
	if (!workspaceId) return apiError(res, 400, "workspaceId is required");

	if (!(await verifyWorkspaceAccess(userId, workspaceId, res))) return;

	// Support groupIds array for phased activation
	const groupIds: string[] | undefined = req.body.groupIds;

	// HARD GUARD: When enabling, check for overdue queue items that would burst-publish
	if (enabled) {
		const overdueFilter = db()
			.from("auto_post_queue")
			.select("id", { count: "exact", head: true })
			.eq("workspace_id", workspaceId)
			.in("status", ["pending", "queued"])
			.lte("scheduled_for", new Date().toISOString());

		// If enabling specific groups, scope the check
		if (groupId) {
			overdueFilter.eq("group_id", groupId);
		} else if (groupIds && groupIds.length > 0) {
			overdueFilter.in("group_id", groupIds);
		}

		const { count: overdueCount } = await overdueFilter;
		if (overdueCount && overdueCount > 0) {
			return apiError(
				res,
				409,
				`Cannot enable: ${overdueCount} items have past scheduled_for timestamps and will publish immediately. Flush queue first with bulk_clear_all_queues.`,
			);
		}
	}

	// Handle groupIds array — enable/disable multiple groups at once
	if (groupIds && groupIds.length > 0) {
		for (const gid of groupIds) {
			if (!(await verifyGroupBelongsToWorkspace(gid, workspaceId, res))) return;
		}
		const { error } = await db()
			.from("auto_post_group_config")
			.update({ enabled } as Record<string, boolean>)
			.eq("workspace_id", workspaceId)
			.in("group_id", groupIds);
		if (error) {
			logger.error("Failed to toggle multiple group configs", {
				workspaceId,
				groupIds,
				enabled,
				userId,
				error: String(error),
			});
			return apiError(res, 500, "Internal server error");
		}

		// When disabling, cancel pending items for those groups
		if (!enabled) {
			const { data: queueItems } = await db()
				.from("auto_post_queue")
				.select("id")
				.eq("workspace_id", workspaceId)
				.in("group_id", groupIds)
				.in("status", ["pending", "queued", "scheduled"]);
			await cancelQueueItemsByIds(
				((queueItems ?? []) as Array<{ id: string }>).map((item) => item.id),
				"Group disabled by user",
			);
		}

		return apiSuccess(res, {
			enabled,
			scope: "groups",
			groupIds,
		});
	}

	if (groupId) {
		// Per-group toggle
		if (!(await verifyGroupBelongsToWorkspace(groupId, workspaceId, res)))
			return;
		const { error } = await db()
			.from("auto_post_group_config")
			.update({ enabled } as Record<string, boolean>)
			.eq("workspace_id", workspaceId)
			.eq("group_id", groupId);
		if (error) {
			logger.error("Failed to toggle group config", {
				workspaceId,
				groupId,
				enabled,
				userId,
				error: String(error),
			});
			return apiError(res, 500, "Internal server error");
		}

		// When disabling a group, cancel all pending/queued items
		if (!enabled) {
			const { data: queueItems } = await db()
				.from("auto_post_queue")
				.select("id")
				.eq("workspace_id", workspaceId)
				.eq("group_id", groupId)
				.in("status", ["pending", "queued", "scheduled"]);
			await cancelQueueItemsByIds(
				((queueItems ?? []) as Array<{ id: string }>).map((item) => item.id),
				"Group disabled by user",
			);
		}
	} else if (scope === "group_mode") {
		// Workspace-level group_mode_enabled flag
		const { error } = await db()
			.from("auto_post_config")
			.update({ group_mode_enabled: enabled } as Record<string, boolean>)
			.eq("workspace_id", workspaceId);
		if (error) {
			logger.error("Failed to toggle workspace group mode", {
				workspaceId,
				enabled,
				userId,
				error: String(error),
			});
			return apiError(res, 500, "Internal server error");
		}
	} else {
		// Default: master on/off switch (is_enabled)
		const { error } = await db()
			.from("auto_post_config")
			.update({ is_enabled: enabled } as Record<string, boolean>)
			.eq("workspace_id", workspaceId);
		if (error) {
			logger.error("Failed to toggle workspace auto-post config", {
				workspaceId,
				enabled,
				userId,
				error: String(error),
			});
			return apiError(res, 500, "Internal server error");
		}
	}

	return apiSuccess(res, {
		enabled,
		scope: groupId ? "group" : scope || "master",
	});
}

export async function handleGetWorkspaceConfig(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;

	const workspaceId = await resolveWorkspaceId(
		req.body?.workspaceId,
		userId,
		res,
	);
	if (!workspaceId) return;

	if (!(await verifyWorkspaceAccess(userId, workspaceId, res))) return;

	const { data, error } = await db()
		.from("auto_post_config")
		.select("*")
		.eq("workspace_id", workspaceId)
		.maybeSingle();

	if (error) {
		logger.error("Failed to fetch workspace config", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}

	if (!data) {
		return apiError(
			res,
			404,
			"No workspace config found — auto-poster not initialized for this workspace",
		);
	}

	// Mask discord_webhook_url for security
	const config = { ...data };
	if (config.discord_webhook_url) {
		config.discord_webhook_url = "configured";
	} else {
		config.discord_webhook_url = "not set";
	}

	return apiSuccess(res, { config });
}

export async function handleUpsertWorkspaceConfig(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;

	const parsed = parseBodyOrError(res, WorkspaceConfigSchema, req.body);
	if (!parsed) return;
	const { workspaceId, ...fields } = parsed;

	if (!(await verifyWorkspaceWriteAccess(userId, workspaceId, res))) return;

	// SSRF validation for Discord webhook URL (defense-in-depth — Zod checks prefix, this checks DNS)
	if (fields.discord_webhook_url) {
		const ssrfError = await validateUrlNotPrivate(fields.discord_webhook_url);
		if (ssrfError) {
			return apiError(res, 400, `Invalid Discord webhook URL: ${ssrfError}`);
		}
	}

	// Only set fields that were explicitly provided
	const update: Record<string, unknown> = {
		updated_at: new Date().toISOString(),
	};
	const settableFields = [
		"is_enabled",
		"posting_times",
		"enable_ai_queue_fill",
		"ai_queue_min_threshold",
		"ai_posts_per_fill",
		"ai_daily_generation_limit",
		"ai_style_guidelines",
		"group_mode_enabled",
		"pause_on_low_performance",
		"performance_threshold",
		"enable_velocity_monitoring",
		"boost_on_viral",
		"viral_interval_reduction_pct",
		"use_smart_timing",
		"competitor_copy_ratio",
		"competitor_copy_max_words",
		"content_filter_patterns",
		"content_filter_min_length",
		"content_filter_max_length",
		"content_filter_max_emojis",
		"discord_webhook_url",
		"ai_provider",
	];
	for (const key of settableFields) {
		if ((fields as Record<string, unknown>)[key] !== undefined) {
			update[key] = (fields as Record<string, unknown>)[key];
		}
	}

	if (Object.keys(update).length <= 1) {
		return apiError(res, 400, "No valid config fields provided");
	}

	const { data, error } = await db()
		.from("auto_post_config")
		.upsert({ workspace_id: workspaceId, ...update }, { onConflict: "workspace_id" })
		.select()
		.maybeSingle();

	if (error) {
		logger.error("Failed to update workspace config", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}

	if (!data) return apiError(res, 500, "Workspace config was not saved");

	return apiSuccess(res, { config: data });
}

export async function handleGetAccountOverrides(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;

	const { workspaceId, groupId, accountId } = req.body || {};
	if (!workspaceId) return apiError(res, 400, "workspaceId is required");

	if (!(await verifyWorkspaceAccess(userId, workspaceId, res))) return;

	let query = db()
		.from("auto_post_account_overrides")
		.select(
			"id, workspace_id, group_id, account_id, overrides, created_at, updated_at",
		)
		.eq("workspace_id", workspaceId);

	if (groupId) query = query.eq("group_id", groupId);
	if (accountId) query = query.eq("account_id", accountId);

	const { data, error } = await query;
	if (error) {
		logger.error("Failed to fetch account overrides", { error: error.message });
		return apiError(res, 500, "Internal server error");
	}

	return apiSuccess(res, { overrides: data || [] });
}

export async function handleUpsertAccountOverride(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;

	const { workspaceId, groupId, accountId, overrides } = req.body || {};
	if (!workspaceId || !groupId || !accountId)
		return apiError(
			res,
			400,
			"workspaceId, groupId, and accountId are required",
		);
	if (!overrides || typeof overrides !== "object")
		return apiError(res, 400, "overrides object is required");

	if (!(await verifyWorkspaceWriteAccess(userId, workspaceId, res))) return;
	if (!(await verifyGroupBelongsToWorkspace(groupId, workspaceId, res))) return;
	if (!(await verifyAccountBelongsToGroup(accountId, groupId, res))) return;

	// Validate overrides against the group config schema (partial — all fields optional)
	const partialSchema = AutoPostGroupConfigInnerSchema.partial();
	const result = partialSchema.safeParse(overrides);
	if (!result.success) {
		const messages = result.error.issues
			.map((i) => `${i.path.join(".")}: ${i.message}`)
			.join("; ");
		return apiError(res, 400, `Invalid overrides: ${messages}`);
	}

	// Strip undefined values — only persist explicitly set fields
	const cleanOverrides: Record<string, unknown> = {};
	for (const [key, val] of Object.entries(result.data)) {
		if (val !== undefined) cleanOverrides[key] = val;
	}

	if (Object.keys(cleanOverrides).length === 0)
		return apiError(res, 400, "No valid override fields provided");

	const { data, error } = await db()
		.from("auto_post_account_overrides")
		.upsert(
			{
				workspace_id: workspaceId,
				group_id: groupId,
				account_id: accountId,
				overrides: cleanOverrides,
				updated_at: new Date().toISOString(),
			},
			{ onConflict: "group_id,account_id" },
		)
		.select()
		.maybeSingle();

	if (error) {
		logger.error("Failed to upsert account override", { error: error.message });
		return apiError(res, 500, "Internal server error");
	}

	return apiSuccess(res, { override: data });
}

export async function handleDeleteAccountOverride(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;

	const { workspaceId, groupId, accountId, dryRun } = req.body || {};
	if (!workspaceId || !groupId || !accountId)
		return apiError(
			res,
			400,
			"workspaceId, groupId, and accountId are required",
		);

	if (!(await verifyWorkspaceWriteAccess(userId, workspaceId, res))) return;

	if (dryRun !== false) {
		const { data } = await db()
			.from("auto_post_account_overrides")
			.select("id, overrides")
			.eq("workspace_id", workspaceId)
			.eq("group_id", groupId)
			.eq("account_id", accountId)
			.maybeSingle();

		return apiSuccess(res, {
			dryRun: true,
			wouldDelete: !!data,
			override: data || null,
		});
	}

	const { error } = await db()
		.from("auto_post_account_overrides")
		.delete()
		.eq("workspace_id", workspaceId)
		.eq("group_id", groupId)
		.eq("account_id", accountId);

	if (error) {
		logger.error("Failed to delete account override", { error: error.message });
		return apiError(res, 500, "Internal server error");
	}

	return apiSuccess(res, { deleted: true });
}
