import { postAutoPostAction } from "./apiClient";
import { getWorkspaceId } from "./internal";

export type AccountDnaProfileSummary = {
	id: string;
	account_id: string;
	group_id: string | null;
	version: number;
	status: "draft" | "active" | "retired";
	confidence: number;
	archetype: string;
	sub_archetype: string | null;
	follower_promise: string;
	signature_phrases: string[];
	primary_topics: string[];
	taboo_topics: string[];
	emotional_baseline: string;
	uniqueness_score: number | null;
	sibling_collision_score: number | null;
	genericness_score: number | null;
	drift_score: number | null;
	uniqueness_decision: string | null;
	uniqueness_reason: string | null;
	updated_at?: string | null;
};

export type AccountDnaReviewItem = {
	id: string;
	account_id: string | null;
	group_id: string | null;
	content: string;
	dna_fit_score: number | null;
	uniqueness_score: number | null;
	sibling_collision_score: number | null;
	genericness_score: number | null;
	dna_decision: string | null;
	dna_reasons: string[] | null;
	created_at: string;
};

export type AccountDnaOpsSummary = {
	totalAutoposterAccounts: number;
	activeProfiles: number;
	draftProfiles: number;
	missingProfiles: number;
	reviewQueueCount: number;
	avgUniquenessScore: number | null;
	avgGenericnessScore: number | null;
	profiles: AccountDnaProfileSummary[];
	reviewItems: AccountDnaReviewItem[];
};

export type RestartWarmupOpsRow = {
	account_id: string;
	username: string;
	status: string;
	status_label: string;
	score: number | null;
	reason: string | null;
	last_recomputed_at: string | null;
	restart_warmup_status: string | null;
	restart_warmup_day: number | null;
	restart_warmup_allowed_posts_per_day: number | null;
	restart_warmup_reason: string | null;
	restart_warmup_next_ramp_at: string | null;
	restart_warmup_last_post_views: number | null;
	restart_warmup_last_evaluated_at: string | null;
	recommended_strategy_mode: string | null;
};

export type RestartWarmupOpsSummary = {
	rows: RestartWarmupOpsRow[];
	activeCount: number;
	heldCount: number;
	suppressedCount: number;
};

type OpsDashboardResponse = {
	accountDna?: AccountDnaOpsSummary;
	accountStates?: {
		health?: RestartWarmupOpsRow[];
	};
};

export type AccountDnaBackfillResponse = {
	workspaceId: string;
	accountsConsidered: number;
	created: number;
	skipped: number;
	failed: number;
	examplesCreated: number;
	rulesCreated: number;
	dryRun: boolean;
	errors: Array<{ account_id: string; error: string }>;
};

export async function fetchAccountDnaOpsSummary(): Promise<AccountDnaOpsSummary | null> {
	const workspaceId = await getWorkspaceId();
	if (!workspaceId) return null;
	const response = await postAutoPostAction<OpsDashboardResponse>(
		"ops-dashboard",
		{
			workspaceId,
		},
	);
	return response.accountDna ?? null;
}

export async function fetchRestartWarmupOpsSummary(): Promise<RestartWarmupOpsSummary> {
	const workspaceId = await getWorkspaceId();
	if (!workspaceId) {
		return { rows: [], activeCount: 0, heldCount: 0, suppressedCount: 0 };
	}
	const response = await postAutoPostAction<OpsDashboardResponse>(
		"ops-dashboard",
		{
			workspaceId,
		},
	);
	const rows = (response.accountStates?.health ?? []).filter((row) => {
		const status = row.restart_warmup_status;
		return status && status !== "none" && status !== "completed";
	});
	return {
		rows,
		activeCount: rows.filter((row) => row.restart_warmup_status === "warming")
			.length,
		heldCount: rows.filter((row) => row.restart_warmup_status === "held")
			.length,
		suppressedCount: rows.filter(
			(row) => row.restart_warmup_status === "suppressed",
		).length,
	};
}

export async function backfillAccountDna(
	options: { force?: boolean; dryRun?: boolean; limit?: number } = {},
): Promise<AccountDnaBackfillResponse> {
	const workspaceId = await getWorkspaceId();
	if (!workspaceId) throw new Error("No workspace found");
	return postAutoPostAction<AccountDnaBackfillResponse>(
		"backfill-account-dna",
		{
			workspaceId,
			force: options.force ?? false,
			dryRun: options.dryRun ?? false,
			limit: options.limit,
		},
	);
}
