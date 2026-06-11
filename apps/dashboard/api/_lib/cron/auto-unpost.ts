// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import type { SupabaseClient } from "@supabase/supabase-js";
import { logRun } from "../autopilotRunLogger.js";
import { logger as defaultLogger } from "../logger.js";
import { deleteFromThreads } from "../threadsApi.js";

const MAX_DELETES_PER_RUN = 50;
const MAX_DELETES_PER_ACCOUNT_PER_DAY = 5;

type LogLike = Pick<typeof defaultLogger, "info" | "warn" | "error">;

interface AutoUnpostSettings {
	enabled: boolean;
	windowHours: number;
	keepTop: number;
}

interface WorkspaceConfigRow {
	workspace_id: string;
	posting_times: Record<string, unknown> | null;
}

interface WorkspaceRow {
	id: string;
	owner_id: string;
}

interface GroupConfigRow {
	group_id: string;
	content_sources: Record<string, unknown> | null;
}

interface AccountRow {
	id: string;
	group_id: string | null;
	username: string;
	threads_access_token_encrypted: string | null;
}

interface CandidatePost {
	id: string;
	user_id: string;
	account_id: string | null;
	threads_post_id: string | null;
	platform: string | null;
	status: string | null;
	source: string | null;
	published_at: string | null;
	cross_post_group_id: string | null;
	likes_count: number | null;
	replies_count: number | null;
	reposts_count: number | null;
	metadata: Record<string, unknown> | null;
	accounts?: AccountRow | AccountRow[] | null | undefined;
}

interface AutoUnpostResult {
	scannedGroups: number;
	skippedGroups: number;
	deleted: number;
	failed: number;
}

function autoUnpostSettings(row: WorkspaceConfigRow): AutoUnpostSettings {
	const postingTimes = row.posting_times ?? {};
	return {
		enabled: Boolean(postingTimes.auto_unpost_duplicates ?? false),
		windowHours: Math.min(
			Math.max(Number(postingTimes.auto_unpost_window_hours ?? 6), 1),
			168,
		),
		keepTop: Math.min(
			Math.max(Number(postingTimes.auto_unpost_keep_top ?? 1), 1),
			10,
		),
	};
}

function accountOf(post: CandidatePost): AccountRow | null {
	if (Array.isArray(post.accounts)) return post.accounts[0] ?? null;
	return post.accounts ?? null;
}

function engagementScore(post: CandidatePost): number {
	return (
		(post.likes_count ?? 0) +
		(post.replies_count ?? 0) * 2 +
		(post.reposts_count ?? 0) * 3
	);
}

function isPinnedOrHuman(post: CandidatePost): boolean {
	const metadata = post.metadata ?? {};
	const pinned =
		metadata.pinned === true ||
		metadata.is_pinned === true ||
		metadata.locked === true ||
		metadata.recycling_pinned === true;
	const source = String(post.source ?? "").toLowerCase();
	const autoSource =
		source === "auto-poster" ||
		source === "autoposter" ||
		source === "auto_post" ||
		source === "auto-post";
	return pinned || !autoSource;
}

function alreadyAudited(post: CandidatePost): boolean {
	const metadata = post.metadata ?? {};
	return Boolean(metadata.auto_unposted_at || metadata.auto_unpost_kept_at);
}

async function logAgentAction(
	db: SupabaseClient,
	userId: string,
	params: Record<string, unknown>,
	reason: string,
	success: boolean,
	resultSummary: string,
) {
	try {
		await db.from("agent_actions").insert({
			user_id: userId,
			session_id: "auto-unpost",
			tool_name: "auto_unpost",
			params_json: params,
			reason,
			result_summary: resultSummary,
			success,
			duration_ms: null,
		});
	} catch (error) {
		defaultLogger.warn("[auto-unpost] agent action insert skipped", {
			error: error instanceof Error ? error.message : String(error),
		});
	}
}

async function todaysAutoUnpostCount(
	db: SupabaseClient,
	accountId: string,
): Promise<number> {
	const since = new Date();
	since.setUTCHours(0, 0, 0, 0);
	const { count } = await db
		.from("posts")
		.select("id", { count: "exact", head: true })
		.eq("account_id", accountId)
		.eq("status", "deleted")
		.gte("updated_at", since.toISOString())
		.contains("metadata", { auto_unpost: true });
	return count ?? 0;
}

async function deletePostFromPlatform(
	post: CandidatePost,
): Promise<{ success: boolean; error?: string | undefined }> {
	if (post.platform === "instagram") {
		return {
			success: false,
			error: "Auto-unpost v1 only deletes same-platform Threads fanout.",
		};
	}
	const account = accountOf(post);
	if (!post.threads_post_id || !account?.threads_access_token_encrypted) {
		return { success: false, error: "Missing Threads post id or account token." };
	}
	return deleteFromThreads(account.threads_access_token_encrypted, post.threads_post_id);
}

export async function processAutoUnpost(
	db: SupabaseClient,
	logger: LogLike = defaultLogger,
): Promise<AutoUnpostResult> {
	const result: AutoUnpostResult = {
		scannedGroups: 0,
		skippedGroups: 0,
		deleted: 0,
		failed: 0,
	};
	const startedAt = Date.now();

	const { data: configs, error: configError } = await db
		.from("auto_post_config")
		.select("workspace_id, posting_times");
	if (configError) throw configError;

	const enabledConfigs = ((configs ?? []) as WorkspaceConfigRow[])
		.map((config) => ({ config, settings: autoUnpostSettings(config) }))
		.filter(({ settings }) => settings.enabled);

	if (enabledConfigs.length === 0) {
		logger.info("[auto-unpost] No workspaces opted in");
		return result;
	}

	for (const { config, settings } of enabledConfigs) {
		if (result.deleted >= MAX_DELETES_PER_RUN) break;

		const { data: workspace } = await db
			.from("workspaces")
			.select("id, owner_id")
			.eq("id", config.workspace_id)
			.maybeSingle();
		const ownerId = (workspace as WorkspaceRow | null)?.owner_id;
		if (!ownerId) {
			result.skippedGroups += 1;
			continue;
		}

		const runLogger = await logRun({
			db,
			userId: ownerId,
			runType: "auto_unpost",
			trigger: "cron",
			metadata: {
				workspaceId: config.workspace_id,
				windowHours: settings.windowHours,
				keepTop: settings.keepTop,
			},
		});

		const { data: workspaceGroupConfigs } = await db
			.from("auto_post_group_config")
			.select("group_id, content_sources")
			.eq("workspace_id", config.workspace_id);
		const workspaceGroups = ((workspaceGroupConfigs ?? []) as GroupConfigRow[])
			.map((row) => row.group_id)
			.filter(Boolean);
		const optOutGroups = new Set(
			((workspaceGroupConfigs ?? []) as GroupConfigRow[])
				.filter((row) => Boolean(row.content_sources?.auto_unpost_opt_out))
				.map((row) => row.group_id),
		);
		if (workspaceGroups.length === 0) {
			await runLogger.logStep({
				name: "select_groups",
				status: "skipped",
				inputs: { workspaceId: config.workspace_id },
				outputs: { reason: "no_group_configs" },
				durationMs: 0,
			});
			await runLogger.finishRun("partial", { reason: "no_group_configs" });
			continue;
		}

		const settleCutoff = new Date(
			Date.now() - settings.windowHours * 60 * 60 * 1000,
		).toISOString();
		const groupSelectStart = Date.now();
		const { data: candidateRows, error: candidateError } = await db
			.from("posts")
			.select(
				"id,user_id,account_id,threads_post_id,platform,status,source,published_at,cross_post_group_id,likes_count,replies_count,reposts_count,metadata,accounts!posts_account_id_fkey(id,group_id,username,threads_access_token_encrypted)",
			)
			.eq("user_id", ownerId)
			.eq("status", "published")
			.not("cross_post_group_id", "is", null)
			.lte("published_at", settleCutoff)
			.limit(500);

		if (candidateError) {
			await runLogger.logStep({
				name: "select_groups",
				status: "failed",
				inputs: { workspaceId: config.workspace_id, settleCutoff },
				error: candidateError.message,
				durationMs: Date.now() - groupSelectStart,
			});
			await runLogger.finishRun("failed", { error: candidateError.message });
			throw candidateError;
		}

		const byGroup = new Map<string, CandidatePost[]>();
		for (const post of (candidateRows ?? []) as CandidatePost[]) {
			if (!post.cross_post_group_id) continue;
			const accountGroupId = accountOf(post)?.group_id;
			if (!accountGroupId || !workspaceGroups.includes(accountGroupId)) continue;
			const list = byGroup.get(post.cross_post_group_id) ?? [];
			list.push(post);
			byGroup.set(post.cross_post_group_id, list);
		}

		await runLogger.logStep({
			name: "select_groups",
			status: "success",
			inputs: { workspaceId: config.workspace_id, settleCutoff },
			outputs: { groups: byGroup.size, posts: candidateRows?.length ?? 0 },
			durationMs: Date.now() - groupSelectStart,
		});

		const accountDeleteCounts = new Map<string, number>();
		for (const [crossPostGroupId, posts] of byGroup) {
			if (result.deleted >= MAX_DELETES_PER_RUN) break;
			result.scannedGroups += 1;

			const groupStepStart = Date.now();
			const groupId = accountOf(posts[0]!)?.group_id ?? null;
			if (groupId && optOutGroups.has(groupId)) {
				result.skippedGroups += 1;
				await runLogger.logStep({
					name: "rank_group",
					status: "skipped",
					inputs: { crossPostGroupId, groupId },
					outputs: { reason: "group_opt_out" },
					durationMs: Date.now() - groupStepStart,
				});
				continue;
			}
			if (posts.length <= settings.keepTop) {
				result.skippedGroups += 1;
				continue;
			}
			if (posts.some(isPinnedOrHuman)) {
				result.skippedGroups += 1;
				await runLogger.logStep({
					name: "rank_group",
					status: "skipped",
					inputs: { crossPostGroupId, postCount: posts.length },
					outputs: { reason: "pinned_or_human_seed" },
					durationMs: Date.now() - groupStepStart,
				});
				continue;
			}
			if (posts.some(alreadyAudited)) {
				result.skippedGroups += 1;
				await runLogger.logStep({
					name: "rank_group",
					status: "skipped",
					inputs: { crossPostGroupId, postCount: posts.length },
					outputs: { reason: "already_audited" },
					durationMs: Date.now() - groupStepStart,
				});
				continue;
			}

			const ranked = [...posts].sort((a, b) => engagementScore(b) - engagementScore(a));
			const kept = ranked.slice(0, settings.keepTop);
			const losers = ranked.slice(settings.keepTop);
			await runLogger.logStep({
				name: "rank_group",
				status: "success",
				inputs: { crossPostGroupId, keepTop: settings.keepTop },
				outputs: ranked.map((post) => ({
					postId: post.id,
					account: accountOf(post)?.username ?? post.account_id,
					groupId: accountOf(post)?.group_id ?? null,
					score: engagementScore(post),
					decision: kept.some((item) => item.id === post.id) ? "keep" : "delete",
				})),
				durationMs: Date.now() - groupStepStart,
			});

			for (const loser of losers) {
				if (result.deleted >= MAX_DELETES_PER_RUN) break;
				const accountId = loser.account_id;
				if (!accountId) {
					result.failed += 1;
					continue;
				}

				const todayCount =
					accountDeleteCounts.get(accountId) ??
					(await todaysAutoUnpostCount(db, accountId));
				if (todayCount >= MAX_DELETES_PER_ACCOUNT_PER_DAY) {
					result.skippedGroups += 1;
					await runLogger.logStep({
						name: "delete_loser",
						status: "skipped",
						inputs: { postId: loser.id, accountId },
						outputs: { reason: "account_daily_delete_cap" },
						durationMs: 0,
					});
					continue;
				}

				const winner = kept[0] ?? ranked[0];
				const loserHandle = accountOf(loser)?.username ?? "unknown";
				const winnerHandle = accountOf(winner!)?.username ?? "winner";
				const loserScore = engagementScore(loser);
				const winnerScore = engagementScore(winner!);
				const reason = `Removed @${loserHandle}'s copy of cross-post group; kept @${winnerHandle} (engagement: ${winnerScore} vs ${loserScore}).`;
				const deleteStart = Date.now();
				const deleteResult = await deletePostFromPlatform(loser);

				await runLogger.logStep({
					name: "delete_loser",
					status: deleteResult.success ? "success" : "failed",
					inputs: {
						postId: loser.id,
						accountId,
						crossPostGroupId,
						threadsPostId: loser.threads_post_id,
					},
					outputs: deleteResult.success
						? { reason, keptPostId: winner!.id }
						: null,
					error: deleteResult.error,
					durationMs: Date.now() - deleteStart,
				});

				if (!deleteResult.success) {
					result.failed += 1;
					await logAgentAction(
						db,
						ownerId,
						{ postId: loser.id, crossPostGroupId, accountId },
						reason,
						false,
						deleteResult.error ?? "delete failed",
					);
					continue;
				}

				const nowIso = new Date().toISOString();
				await db
					.from("posts")
					.update({
						status: "deleted",
						updated_at: nowIso,
						metadata: {
							...(loser.metadata ?? {}),
							auto_unpost: true,
							auto_unposted_at: nowIso,
							auto_unpost_kept_post_id: winner!.id,
							auto_unpost_kept_account: winnerHandle,
							auto_unpost_reason: reason,
						},
					})
					.eq("id", loser.id);
				accountDeleteCounts.set(accountId, todayCount + 1);
				result.deleted += 1;
				await logAgentAction(
					db,
					ownerId,
					{ postId: loser.id, keptPostId: winner!.id, crossPostGroupId },
					reason,
					true,
					"deleted",
				);
			}

			const nowIso = new Date().toISOString();
			for (const winner of kept) {
				await db
					.from("posts")
					.update({
						metadata: {
							...(winner.metadata ?? {}),
							auto_unpost_kept_at: nowIso,
						},
					})
					.eq("id", winner.id);
			}
		}

		await runLogger.finishRun(result.failed > 0 ? "partial" : "success", {
			workspaceId: config.workspace_id,
			deleted: result.deleted,
			failed: result.failed,
			scannedGroups: result.scannedGroups,
			durationMs: Date.now() - startedAt,
		});
	}

	logger.info("[auto-unpost] Complete", { ...result });
	return result;
}
