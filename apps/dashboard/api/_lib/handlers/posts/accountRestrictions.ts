// biome-ignore-all lint/suspicious/noExplicitAny: operator payloads are normalized before DB writes.
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import {
	listInstagramAccountRestrictions,
	markInstagramAccountRestrictions,
	RECOMMENDATION_ELIGIBILITY_STATES,
	RESTRICTION_SEVERITIES,
	RESTRICTION_TYPES,
	resolveInstagramAccountRestriction,
	SOURCE_CONFIDENCE,
	type RecommendationEligibilityState,
	type RestrictionSeverity,
	type RestrictionType,
} from "../../instagramAccountRestrictions.js";
import { parseBodyOrError } from "../../validation.js";
import { z } from "../../zodCompat.js";

const RestrictionActionSchema = z.object({
	restrictionAction: z.enum(["list", "mark", "resolve", "dryRun"]).optional(),
	mode: z.enum(["list", "mark", "resolve", "dryRun"]).optional(),
	accountIds: z.array(z.string()).optional(),
	usernames: z.array(z.string()).optional(),
	creator: z.string().optional(),
	restrictionType: z.enum(RESTRICTION_TYPES).optional(),
	severity: z.enum(RESTRICTION_SEVERITIES).optional(),
	recommendationEligibilityState: z.enum(RECOMMENDATION_ELIGIBILITY_STATES).optional(),
	reviewRequired: z.boolean().optional(),
	startedAt: z.string().optional(),
	endsAt: z.string().nullable().optional(),
	source: z.string().optional(),
	sourceConfidence: z.enum(SOURCE_CONFIDENCE).optional(),
	notes: z.string().optional(),
	evidence: z.record(z.unknown()).optional(),
	eventId: z.string().optional(),
	resolvedReason: z.string().optional(),
	status: z.string().optional(),
	accountId: z.string().optional(),
});

function requestString(req: VercelRequest, key: string): string | null {
	const queryValue = req.query?.[key];
	if (typeof queryValue === "string" && queryValue.trim()) return queryValue.trim();
	if (Array.isArray(queryValue) && typeof queryValue[0] === "string" && queryValue[0].trim()) return queryValue[0].trim();
	const bodyValue = req.body?.[key];
	if (typeof bodyValue === "string" && bodyValue.trim()) return bodyValue.trim();
	return null;
}

export async function handleInstagramAccountRestrictions(req: VercelRequest, res: VercelResponse, userId: string) {
	const parsed = parseBodyOrError(res, RestrictionActionSchema, req.method === "GET" ? { ...req.query } : req.body);
	if (!parsed) return;
	const action = parsed.restrictionAction ?? parsed.mode ?? requestString(req, "restrictionAction") ?? "list";
	if (action === "list") {
		const filters: { accountId?: string; status?: string } = {};
		const accountId = parsed.accountId ?? requestString(req, "accountId");
		const status = parsed.status ?? requestString(req, "status");
		if (accountId) filters.accountId = accountId;
		if (status) filters.status = status;
		return apiSuccess(res, await listInstagramAccountRestrictions(userId, filters));
	}
	if (action === "mark" || action === "dryRun") {
		if (!parsed.restrictionType) return apiError(res, 400, "restrictionType is required");
		const markInput: Parameters<typeof markInstagramAccountRestrictions>[0] = {
			userId,
			restrictionType: parsed.restrictionType as RestrictionType,
			actor: userId,
			dryRun: action === "dryRun",
		};
		if (parsed.accountIds) markInput.accountIds = parsed.accountIds;
		if (parsed.usernames) markInput.usernames = parsed.usernames;
		if (parsed.creator) markInput.creator = parsed.creator;
		if (parsed.severity) markInput.severity = parsed.severity as RestrictionSeverity;
		if (parsed.recommendationEligibilityState) markInput.recommendationEligibilityState = parsed.recommendationEligibilityState as RecommendationEligibilityState;
		if (parsed.reviewRequired !== undefined) markInput.reviewRequired = parsed.reviewRequired;
		if (parsed.startedAt) markInput.startedAt = parsed.startedAt;
		if (parsed.endsAt !== undefined) markInput.endsAt = parsed.endsAt;
		if (parsed.source) markInput.source = parsed.source;
		if (parsed.sourceConfidence) markInput.sourceConfidence = parsed.sourceConfidence;
		if (parsed.notes) markInput.notes = parsed.notes;
		if (parsed.evidence) markInput.evidence = parsed.evidence;
		const payload = await markInstagramAccountRestrictions(markInput);
		return apiSuccess(res, payload);
	}
	if (action === "resolve") {
		if (!parsed.eventId) return apiError(res, 400, "eventId is required");
		if (!parsed.resolvedReason) return apiError(res, 400, "resolvedReason is required");
		const payload = await resolveInstagramAccountRestriction(userId, {
			eventId: parsed.eventId,
			resolvedReason: parsed.resolvedReason,
			actor: userId,
		});
		if (!payload.ok) return apiError(res, 400, payload.reason || "restriction_resolve_failed");
		return apiSuccess(res, payload);
	}
	return apiError(res, 400, `Unknown restriction action: ${action}`);
}
