import type { Database } from "../../types/supabase.js";
import { getSupabaseAny } from "./supabase.js";

export const RESTRICTION_TYPES = [
	"link_sharing_restricted",
	"recommendation_limited",
	"not_recommended",
	"manual_review_required",
	"publish_blocked",
] as const;

export const RECOMMENDATION_ELIGIBILITY_STATES = [
	"eligible",
	"unknown",
	"limited",
	"not_recommended",
	"manual_review_required",
] as const;

export const RESTRICTION_SEVERITIES = ["info", "warning", "blocking"] as const;
export const SOURCE_CONFIDENCE = ["low", "medium", "high"] as const;

export type RestrictionType = typeof RESTRICTION_TYPES[number];
export type RecommendationEligibilityState = typeof RECOMMENDATION_ELIGIBILITY_STATES[number];
export type RestrictionSeverity = typeof RESTRICTION_SEVERITIES[number];
type RestrictionEventRow = Database["public"]["Tables"]["instagram_account_restriction_events"]["Row"];
type RestrictionAccountRow = Pick<
	Database["public"]["Tables"]["instagram_accounts"]["Row"],
	"id" | "user_id" | "username" | "group_id"
>;
type RestrictionEventRecord = Partial<Pick<
	RestrictionEventRow,
	| "id"
	| "instagram_account_id"
	| "restriction_type"
	| "status"
	| "severity"
	| "recommendation_eligibility_state"
	| "review_required"
	| "started_at"
	| "ends_at"
	| "resolved_at"
>>;

export type RestrictionMarkInput = {
	userId: string;
	accountIds?: string[];
	usernames?: string[];
	creator?: string | null;
	restrictionType: RestrictionType;
	severity?: RestrictionSeverity;
	recommendationEligibilityState?: RecommendationEligibilityState;
	reviewRequired?: boolean;
	startedAt?: string;
	endsAt?: string | null;
	source?: string;
	sourceConfidence?: typeof SOURCE_CONFIDENCE[number];
	notes?: string;
	evidence?: Record<string, unknown>;
	actor?: string;
	dryRun?: boolean;
};

export type RestrictionProjection = {
	restrictionStatus: {
		active: boolean;
		type: string;
		status: string;
		severity: string;
		startedAt: string | null;
		endsAt: string | null;
	};
	activeRestrictionCount: number;
	restrictionTypes: string[];
	linkSharingRestricted: boolean;
	recommendationEligibilityState: RecommendationEligibilityState;
	reviewRequired: boolean;
	needsReviewAfterExpiry: boolean;
	accountTrustState: string;
	blockers: string[];
};

const db = () => getSupabaseAny();
const POST_EXPIRY_REVIEW_MS = 48 * 60 * 60 * 1000;

function normalizeCreator(value: string | null | undefined): string | null {
	if (!value) return null;
	const normalized = value.trim().toLowerCase();
	if (!normalized) return null;
	if (normalized.includes("stacey") || normalized.includes("bennett")) return "Stacey";
	if (normalized.includes("larissa")) return "Larissa";
	if (normalized.includes("lola")) return "Lola";
	return value.trim();
}

function normalizeUsername(value: string): string {
	return value.trim().replace(/^@/, "").toLowerCase();
}

function normalizeIso(value: string | null | undefined): string | null {
	if (!value) return null;
	const date = new Date(value);
	return Number.isFinite(date.getTime()) ? date.toISOString() : null;
}

function rankRecommendationState(value: string | null | undefined): number {
	switch (value) {
		case "manual_review_required": return 4;
		case "not_recommended": return 3;
		case "limited": return 2;
		case "unknown": return 1;
		default: return 0;
	}
}

function isRestrictionActive(row: RestrictionEventRecord, now = Date.now()): boolean {
	if (row.status !== "active") return false;
	if (row.resolved_at) return false;
	if (!row.ends_at) return true;
	const ends = Date.parse(row.ends_at);
	return Number.isFinite(ends) && ends > now;
}

function needsReviewAfterExpiry(row: RestrictionEventRecord, now = Date.now()): boolean {
	if (row.resolved_at) return false;
	const ends = row.ends_at ? Date.parse(row.ends_at) : null;
	if (!ends || !Number.isFinite(ends) || ends > now) return false;
	if (now - ends > POST_EXPIRY_REVIEW_MS) return false;
	return row.severity === "blocking" || row.review_required === true;
}

export function projectRestrictionEvents(rows: RestrictionEventRecord[], now = Date.now()): RestrictionProjection {
	const activeRows = rows.filter((row) => isRestrictionActive(row, now));
	const restrictionTypes = Array.from(new Set(activeRows.map((row) => String(row.restriction_type)).filter(Boolean)));
	const linkSharingRestricted = activeRows.some((row) => row.restriction_type === "link_sharing_restricted");
	const reviewRequired = activeRows.some((row) => row.review_required === true);
	const blockingRows = activeRows.filter((row) => row.severity === "blocking");
	let recommendationEligibilityState: RecommendationEligibilityState = "eligible";
	for (const row of activeRows) {
		const state = String(row.recommendation_eligibility_state || "unknown") as RecommendationEligibilityState;
		if (rankRecommendationState(state) > rankRecommendationState(recommendationEligibilityState)) {
			recommendationEligibilityState = state;
		}
	}
	const blockers = new Set<string>();
	if (linkSharingRestricted) blockers.add("account_link_sharing_restricted");
	if (reviewRequired) blockers.add("account_manual_review_required");
	if (blockingRows.length > 0) blockers.add("account_restriction_active");
	if (["limited", "not_recommended", "manual_review_required"].includes(recommendationEligibilityState)) {
		blockers.add("recommendation_not_eligible");
	}
	const primary = blockingRows[0] ?? activeRows[0] ?? {};
	return {
		restrictionStatus: {
			active: activeRows.length > 0,
			type: String(primary.restriction_type || ""),
			status: activeRows.length > 0 ? "active" : "clear",
			severity: String(primary.severity || ""),
			startedAt: primary.started_at ?? null,
			endsAt: primary.ends_at ?? null,
		},
		activeRestrictionCount: activeRows.length,
		restrictionTypes,
		linkSharingRestricted,
		recommendationEligibilityState,
		reviewRequired,
		needsReviewAfterExpiry: rows.some((row) => needsReviewAfterExpiry(row, now)),
		accountTrustState: activeRows.length > 0 ? "restricted" : "normal",
		blockers: Array.from(blockers),
	};
}

export async function restrictionProjectionsForUser(userId: string): Promise<Map<string, RestrictionProjection>> {
	const { data, error } = await db()
		.from("instagram_account_restriction_events")
		.select("id,instagram_account_id,restriction_type,status,severity,recommendation_eligibility_state,review_required,started_at,ends_at,resolved_at")
		.eq("user_id", userId)
		.in("status", ["active", "expired"]);
	if (error) throw error;
	const grouped = new Map<string, RestrictionEventRecord[]>();
	for (const row of (data ?? []) as RestrictionEventRecord[]) {
		const accountId = String(row.instagram_account_id || "");
		if (!accountId) continue;
		const list = grouped.get(accountId) ?? [];
		list.push(row);
		grouped.set(accountId, list);
	}
	return new Map(Array.from(grouped.entries()).map(([accountId, rows]) => [accountId, projectRestrictionEvents(rows)]));
}

async function fetchRestrictionAccounts(input: RestrictionMarkInput): Promise<{
	matched: RestrictionAccountRow[];
	unmatchedUsernames: string[];
}> {
	const ids = Array.from(new Set((input.accountIds ?? []).map((id) => id.trim()).filter(Boolean)));
	const usernames = Array.from(new Set((input.usernames ?? []).map(normalizeUsername).filter(Boolean)));
	const byId = new Map<string, RestrictionAccountRow>();
	if (ids.length > 0) {
		const { data, error } = await db()
			.from("instagram_accounts")
			.select("id,user_id,username,group_id")
			.eq("user_id", input.userId)
			.in("id", ids);
		if (error) throw error;
		for (const row of (data ?? []) as RestrictionAccountRow[]) byId.set(String(row.id), row);
	}
	const usernameMatches = new Map<string, RestrictionAccountRow>();
	if (usernames.length > 0) {
		const { data, error } = await db()
			.from("instagram_accounts")
			.select("id,user_id,username,group_id")
			.eq("user_id", input.userId);
		if (error) throw error;
		for (const row of (data ?? []) as RestrictionAccountRow[]) {
			const username = typeof row.username === "string" ? normalizeUsername(row.username) : "";
			if (usernames.includes(username)) usernameMatches.set(username, row);
		}
	}
	const matched = new Map<string, RestrictionAccountRow>();
	for (const row of byId.values()) matched.set(String(row.id), row);
	for (const row of usernameMatches.values()) matched.set(String(row.id), row);
	const unmatchedUsernames = usernames.filter((username) => !usernameMatches.has(username));
	if (input.creator) {
		const creator = normalizeCreator(input.creator);
		return {
			matched: Array.from(matched.values()).filter((row) => !creator || normalizeCreator(row.username) === creator),
			unmatchedUsernames,
		};
	}
	return { matched: Array.from(matched.values()), unmatchedUsernames };
}

async function activeEventByAccount(userId: string, accountIds: string[], restrictionType: RestrictionType): Promise<Map<string, RestrictionEventRecord>> {
	if (accountIds.length === 0) return new Map();
	const { data, error } = await db()
		.from("instagram_account_restriction_events")
		.select("id,instagram_account_id,restriction_type,status")
		.eq("user_id", userId)
		.eq("restriction_type", restrictionType)
		.eq("status", "active")
		.in("instagram_account_id", accountIds);
	if (error) throw error;
	return new Map(((data ?? []) as RestrictionEventRecord[]).map((row) => [String(row.instagram_account_id), row]));
}

export async function markInstagramAccountRestrictions(input: RestrictionMarkInput) {
	const accounts = await fetchRestrictionAccounts(input);
	const accountIds = accounts.matched.map((row) => String(row.id));
	const existing = await activeEventByAccount(input.userId, accountIds, input.restrictionType);
	const existingActiveEventsUpdated = accountIds.filter((id) => existing.has(id)).length;
	const newEventsCreated = accountIds.length - existingActiveEventsUpdated;
	const responseBase = {
		schema: "threadsdashboard.instagram_account_restrictions.v1",
		wouldWrite: false,
		wouldMark: accountIds.length,
		matchedUsernames: accounts.matched.length,
		unmatchedUsernames: accounts.unmatchedUsernames,
		existingActiveEventsUpdated,
		newEventsCreated,
		accountIds,
	};
	if (input.dryRun) return responseBase;
	const now = new Date().toISOString();
	const payload = {
		user_id: input.userId,
		restriction_type: input.restrictionType,
		status: "active",
		severity: input.severity ?? "blocking",
		recommendation_eligibility_state: input.recommendationEligibilityState ?? "unknown",
		review_required: input.reviewRequired ?? false,
		started_at: normalizeIso(input.startedAt) ?? now,
		ends_at: normalizeIso(input.endsAt),
		resolved_at: null,
		source: input.source ?? "operator",
		source_confidence: input.sourceConfidence ?? "medium",
		notes: input.notes ?? null,
		evidence: input.evidence ?? {},
		updated_by: input.actor ?? "operator",
		updated_at: now,
	};
	for (const account of accounts.matched) {
		const accountId = String(account.id);
		const active = existing.get(accountId);
		if (active?.id) {
			await db()
				.from("instagram_account_restriction_events")
				.update(payload)
				.eq("id", active.id)
				.eq("user_id", input.userId);
			continue;
		}
		await db()
			.from("instagram_account_restriction_events")
			.insert({
				...payload,
				instagram_account_id: accountId,
				created_by: input.actor ?? "operator",
				created_at: now,
			});
	}
	return { ...responseBase, wouldWrite: true };
}

export async function listInstagramAccountRestrictions(userId: string, filters: { accountId?: string; status?: string } = {}) {
	let query = db()
		.from("instagram_account_restriction_events")
		.select("*")
		.eq("user_id", userId);
	if (filters.accountId) query = query.eq("instagram_account_id", filters.accountId);
	if (filters.status) query = query.eq("status", filters.status);
	const { data, error } = await query;
	if (error) throw error;
	return {
		schema: "threadsdashboard.instagram_account_restrictions.list.v1",
		wouldWrite: false,
		events: data ?? [],
	};
}

export async function resolveInstagramAccountRestriction(userId: string, input: {
	eventId: string;
	resolvedReason: string;
	actor?: string;
}) {
	if (!input.resolvedReason?.trim()) {
		return { ok: false, reason: "resolved_reason_required" };
	}
	const now = new Date().toISOString();
	const { data, error } = await db()
		.from("instagram_account_restriction_events")
		.update({
			status: "resolved",
			resolved_at: now,
			resolved_reason: input.resolvedReason,
			resolved_by: input.actor ?? "operator",
			updated_by: input.actor ?? "operator",
			updated_at: now,
		})
		.eq("id", input.eventId)
		.eq("user_id", userId)
		.select("id");
	if (error) throw error;
	return {
		schema: "threadsdashboard.instagram_account_restrictions.resolve.v1",
		ok: Array.isArray(data) ? data.length > 0 : Boolean(data),
		eventId: input.eventId,
		wouldWrite: true,
	};
}
