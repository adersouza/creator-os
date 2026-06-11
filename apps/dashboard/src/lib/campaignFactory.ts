export type CampaignFactoryMetadata = {
	asset_state?: CampaignFactoryAssetState | string | undefined;
	approved?: boolean | undefined;
	captioned_render_present?: boolean | undefined;
	visible_caption_verification?: string | undefined;
	expected_visual_verification?: string | undefined;
	content_fingerprint?: string | undefined;
	readiness_checks_pass?: boolean | undefined;
	handoff_manifest?: HandoffManifest | undefined;
	handoffManifest?: HandoffManifest | undefined;
	quarantined?: boolean | undefined;
	quarantine?: Record<string, unknown> | undefined;
	manual_override?: boolean | undefined;
	manual_override_contaminated?: boolean | undefined;
	metrics_eligible?: boolean | undefined;
	publishability_failure_reasons?: string[] | undefined;
	blockingReason?: string | undefined;
	rootCause?: string | undefined;
	graph_id?: string | undefined;
	campaign_graph_id?: string | undefined;
	source_asset_graph_id?: string | undefined;
	rendered_asset_graph_id?: string | undefined;
	audit_graph_id?: string | undefined;
	campaign_id?: string | undefined;
	source_asset_id?: string | undefined;
	rendered_asset_id?: string | undefined;
	content_hash?: string | undefined;
	rendered_hash?: string | undefined;
	source_content_hash?: string | undefined;
	caption_hash?: string | undefined;
	instagram_post_caption?: string | undefined;
	instagram_post_caption_hash?: string | undefined;
	caption_cta?: string | undefined;
	hashtags?: string[] | undefined;
	post_caption_style?: string | undefined;
	burned_caption_text?: string | undefined;
	burned_caption_hash?: string | undefined;
	captionOutcomeContext?: Record<string, unknown> | undefined;
	caption_outcome_context?: Record<string, unknown> | undefined;
	recipe?: string | undefined;
	export_id?: string | undefined;
	audit_status?: string | undefined;
	readiness_status?: string | undefined;
	model_id?: string | undefined;
	model_slug?: string | undefined;
	account_profile?: Record<string, unknown> | undefined;
	content_pillar?: string | undefined;
	cta_type?: string | undefined;
	language?: string | undefined;
	content_surface?: string | undefined;
	distribution_surface?: string | undefined;
	distribution_plan_id?: string | undefined;
	paired_rendered_asset_id?: string | undefined;
	distribution_reason_code?: string | undefined;
	smart_link?: string | undefined;
	cta_text?: string | undefined;
	trialReels?: boolean | undefined;
	trial_reel?: boolean | undefined;
	preview_schedule_only?: boolean | undefined;
	schedule_mode?: string | undefined;
	contentforge_run_id?: string | undefined;
	contentforge_report_id?: string | undefined;
	planned_account_id?: string | undefined;
	planned_account_handle?: string | undefined;
	planned_window_start?: string | undefined;
	planned_window_end?: string | undefined;
	assignment_notes?: string | undefined;
	caption_generation?: Record<string, unknown> | undefined;
	reference_pattern?: Record<string, unknown> | undefined;
	source_prompt?: Record<string, unknown> | undefined;
	generated_asset_lineage?: CampaignFactoryGeneratedAssetLineage | undefined;
	audio_intent?: CampaignFactoryAudioIntent | undefined;
	daily_production?: CampaignFactoryDailyProduction | undefined;
	created_at?: string | undefined;
	exported_at?: string | undefined;
	export_timestamp?: string | undefined;
};

export type CampaignFactoryAssetState =
	| "approved_but_not_publishable"
	| "publishable_candidate"
	| "exportable"
	| "invalid_retired_draft";

export type CampaignFactoryPublishabilityReason =
	| "missing_burned_captions"
	| "wrong_visual"
	| "missing_caption_hash"
	| "missing_caption_outcome_context"
	| "missing_content_fingerprint"
	| "missing_audio"
	| "readiness_failed"
	| "not_approved"
	| "quarantined_asset";

export type PublishabilityDecision = {
	decision: "pass" | "blocked";
	state: "publishable_candidate" | "approved_but_not_publishable";
	reasons: string[];
	checks: {
		creative_approved: boolean;
		captioned_render_present: boolean;
		visible_caption_verification: boolean;
		expected_visual_verification: boolean;
		content_fingerprint_present: boolean;
		caption_hash_present: boolean;
		captionOutcomeContext_present: boolean;
		audio_assigned: boolean;
		readiness_checks_pass: boolean;
		quarantine_clear: boolean;
	};
};

export type HandoffManifest = {
	manifest_version: 1;
	asset_id: string;
	render_file_id: string;
	content_fingerprint: string;
	caption_hash: string;
	instagram_post_caption?: string | undefined;
	instagram_post_caption_hash?: string | undefined;
	caption_cta?: string | null | undefined;
	hashtags?: string[] | undefined;
	post_caption_style?: string | undefined;
	burned_caption_text?: string | undefined;
	burned_caption_hash?: string | undefined;
	captionOutcomeContext: unknown;
	visual_verification_id: string;
	caption_verification_id: string;
	audio_id: string;
	distribution_plan_id: string;
	exported_by_system: "campaign_factory";
	exported_at: string;
};

export type CampaignFactoryGeneratedAssetLineage = {
	schema?: string | undefined;
	source?: Record<string, unknown> | undefined;
	generation?: Record<string, unknown> | undefined;
	review?: Record<string, unknown> | undefined;
	quality?: Record<string, unknown> | undefined;
	captionOutcomeContext?: Record<string, unknown> | undefined;
};

export type CampaignFactoryDailyProduction = {
	schema?: string | undefined;
	targetBaseVideos?: number | undefined;
	promptReady?: number | undefined;
	generated?: number | undefined;
	sentToPipeline?: number | undefined;
	reviewed?: number | undefined;
	postedOrScheduled?: number | undefined;
	remainingBaseVideos?: number | undefined;
	primaryMetric?: string | undefined;
};

export type CampaignFactoryAudioStatus =
	| "not_required"
	| "recommended"
	| "needs_operator_selection"
	| "selected"
	| "attached"
	| "verified"
	| "skipped"
	| "blocked"
	| "needs_review"
	| "burned";

export type CampaignFactoryAudioIntent = {
	schema?: string | undefined;
	mode?: string | undefined;
	required?: boolean | undefined;
	status?: CampaignFactoryAudioStatus | string | undefined;
	platform?: string | undefined;
	surface?: string | undefined;
	recommendations?: Array<Record<string, unknown>> | undefined;
	decision?: Record<string, unknown> | undefined;
	operator_selection?: Record<string, unknown> | undefined;
	task?: CampaignFactoryAudioTask | undefined;
	gates?: Record<string, unknown> | undefined;
};

export type CampaignFactoryAudioTaskStatus =
	| "open"
	| "selected"
	| "proof_missing"
	| "needs_review"
	| "blocked"
	| "completed"
	| "not_required";

export type CampaignFactoryAudioTask = {
	schema?: string | undefined;
	status?: CampaignFactoryAudioTaskStatus | string | undefined;
	assignee?: string | undefined;
	due_at?: string | undefined;
	proof_required?: boolean | undefined;
	created_at?: string | undefined;
	updated_at?: string | undefined;
	completed_at?: string | undefined;
};

export type CampaignFactoryAudioBatchAction =
	| "apply_primary_audio"
	| "apply_first_recommendation"
	| "selected"
	| "attached"
	| "verified"
	| "skipped"
	| "blocked";

export type CampaignFactoryFilters = {
	only?: boolean | undefined;
	campaignId?: string | undefined;
	modelId?: string | undefined;
	sourceAssetId?: string | undefined;
	renderedAssetId?: string | undefined;
	auditStatus?: string | undefined;
	contentPillar?: string | undefined;
	ctaType?: string | undefined;
	language?: string | undefined;
	recipe?: string | undefined;
	instagramAccountId?: string | undefined;
	status?: string | undefined;
	audioState?:
		| "all"
		| "needs_audio"
		| "selected_not_attached"
		| "missing_proof"
		| "blocked"
		| "ready"
		| "needs_handoff"
		| undefined;
};

export type CampaignFactoryAudioQueueLane =
	| "needs_audio"
	| "selected_not_attached"
	| "missing_proof"
	| "blocked"
	| "ready"
	| "needs_handoff";

export type CampaignFactoryReuseCounts = {
	renderedAsset: number;
	sourceAsset: number;
	contentHash: number;
	sourceContentHash: number;
	captionHash: number;
	recipe: number;
};

export type CampaignFactoryPerformancePayload = {
	post_id: string | null;
	status: string | null;
	views: number;
	likes: number;
	comments: number;
	replies: number;
	shares: number;
	saves: number;
	reach: number;
	published_at: string | null;
	permalink: string | null;
	instagram_account_id: string | null;
	media_urls: string[];
	campaign_factory: CampaignFactoryMetadata | null;
	lineage: Pick<
		CampaignFactoryMetadata,
		| "rendered_asset_id"
		| "source_asset_id"
		| "campaign_id"
		| "content_hash"
		| "caption_hash"
	> | null;
};

type CampaignFactoryPostLike = {
	id?: string | null | undefined;
	status?: string | null | undefined;
	platform?: string | null | undefined;
	createdAt?: string | null | undefined;
	created_at?: string | null | undefined;
	accountId?: string | null | undefined;
	account_id?: string | null | undefined;
	instagramAccountId?: string | null | undefined;
	instagram_account_id?: string | null | undefined;
	mediaUrls?: string[] | null | undefined;
	media_urls?: string[] | null | undefined;
	publishedAt?: string | null | undefined;
	published_at?: string | null | undefined;
	permalink?: string | null | undefined;
	views?: number | null | undefined;
	views_count?: number | null | undefined;
	ig_views?: number | null | undefined;
	ig_video_views?: number | null | undefined;
	ig_reels_plays?: number | null | undefined;
	likes?: number | null | undefined;
	likes_count?: number | null | undefined;
	comments?: number | null | undefined;
	ig_comment_count?: number | null | undefined;
	replies?: number | null | undefined;
	replies_count?: number | null | undefined;
	shares?: number | null | undefined;
	shares_count?: number | null | undefined;
	ig_shares?: number | null | undefined;
	saves?: number | null | undefined;
	ig_saved?: number | null | undefined;
	reach?: number | null | undefined;
	ig_reach?: number | null | undefined;
	metadata?: Record<string, unknown> | null | undefined;
	campaignFactory?: CampaignFactoryMetadata | null | undefined;
};

const COUNTED_STATUSES = new Set(["draft", "scheduled", "published"]);

function asRecord(value: unknown): Record<string, unknown> | null {
	return value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: null;
}

function stringValue(value: unknown): string | undefined {
	return typeof value === "string" && value.trim().length > 0
		? value.trim()
		: undefined;
}

function firstStringValue(...values: unknown[]): string | undefined {
	for (const value of values) {
		const parsed = stringValue(value);
		if (parsed) return parsed;
	}
	return undefined;
}

function numberValue(...values: unknown[]): number {
	for (const value of values) {
		if (typeof value === "number" && Number.isFinite(value)) return value;
		if (typeof value === "string" && value.trim()) {
			const parsed = Number(value);
			if (Number.isFinite(parsed)) return parsed;
		}
	}
	return 0;
}

function stringArrayValue(value: unknown): string[] {
	return Array.isArray(value)
		? value.filter(
				(item): item is string => typeof item === "string" && item.length > 0,
			)
		: [];
}

function normalizedKey(value: string | undefined): string | undefined {
	return value?.trim().toLowerCase();
}

function metadataString(
	raw: Record<string, unknown>,
	key: string,
	fallbackKeys: string[] = [],
): string | undefined {
	return firstStringValue(
		raw[key],
		...fallbackKeys.map((fallback) => raw[fallback]),
	);
}

export function getCampaignFactoryMetadata(
	post: CampaignFactoryPostLike | null | undefined,
): CampaignFactoryMetadata | null {
	if (!post) return null;
	if (post.campaignFactory) return post.campaignFactory;
	const metadata = asRecord(post.metadata);
	const raw = asRecord(metadata?.campaign_factory);
	if (!raw) return null;
	const cf: CampaignFactoryMetadata = {
		campaign_id: stringValue(raw.campaign_id),
		graph_id: stringValue(raw.graph_id),
		campaign_graph_id: stringValue(raw.campaign_graph_id),
		source_asset_graph_id: stringValue(raw.source_asset_graph_id),
		rendered_asset_graph_id: stringValue(raw.rendered_asset_graph_id),
		audit_graph_id: stringValue(raw.audit_graph_id),
		source_asset_id: stringValue(raw.source_asset_id),
		rendered_asset_id: stringValue(raw.rendered_asset_id),
		asset_state: stringValue(raw.asset_state),
		approved: raw.approved === true,
		captioned_render_present: raw.captioned_render_present === true,
		visible_caption_verification: stringValue(raw.visible_caption_verification),
		expected_visual_verification: stringValue(raw.expected_visual_verification),
		content_fingerprint: metadataString(raw, "content_fingerprint", [
			"contentFingerprint",
		]),
		readiness_checks_pass: raw.readiness_checks_pass === true,
		handoff_manifest:
			(asRecord(raw.handoff_manifest) as HandoffManifest | null) ?? undefined,
		handoffManifest:
			(asRecord(raw.handoffManifest) as HandoffManifest | null) ?? undefined,
		quarantined: raw.quarantined === true,
		quarantine: asRecord(raw.quarantine) ?? undefined,
		manual_override: raw.manual_override === true,
		manual_override_contaminated: raw.manual_override_contaminated === true,
		metrics_eligible: raw.metrics_eligible === true,
		publishability_failure_reasons: stringArrayValue(
			raw.publishability_failure_reasons,
		),
		blockingReason: stringValue(raw.blockingReason ?? raw.blocking_reason),
		rootCause: stringValue(raw.rootCause ?? raw.root_cause),
		content_hash: stringValue(raw.content_hash),
		rendered_hash: metadataString(raw, "rendered_hash", [
			"rendered_content_hash",
			"content_hash",
		]),
		source_content_hash: metadataString(raw, "source_content_hash", [
			"source_hash",
		]),
		caption_hash: stringValue(raw.caption_hash),
		captionOutcomeContext: asRecord(raw.captionOutcomeContext) ?? undefined,
		caption_outcome_context: asRecord(raw.caption_outcome_context) ?? undefined,
		recipe: stringValue(raw.recipe),
		export_id: stringValue(raw.export_id),
		audit_status: stringValue(raw.audit_status),
		readiness_status: metadataString(raw, "readiness_status", [
			"readiness",
			"review_readiness",
		]),
		model_id: stringValue(raw.model_id),
		model_slug: stringValue(raw.model_slug),
		account_profile: asRecord(raw.account_profile) ?? undefined,
		content_pillar: stringValue(raw.content_pillar),
		cta_type: stringValue(raw.cta_type),
		language: stringValue(raw.language),
		content_surface: stringValue(raw.content_surface),
		distribution_surface: stringValue(raw.distribution_surface),
		distribution_plan_id: stringValue(raw.distribution_plan_id),
		paired_rendered_asset_id: stringValue(raw.paired_rendered_asset_id),
		distribution_reason_code: stringValue(raw.distribution_reason_code),
		smart_link: stringValue(raw.smart_link),
		cta_text: stringValue(raw.cta_text),
		trialReels: raw.trialReels === true,
		trial_reel: raw.trial_reel === true,
		preview_schedule_only: raw.preview_schedule_only === true,
		schedule_mode: stringValue(raw.schedule_mode),
		contentforge_run_id: metadataString(raw, "contentforge_run_id", [
			"content_forge_run_id",
			"run_id",
		]),
		contentforge_report_id: metadataString(raw, "contentforge_report_id", [
			"content_forge_report_id",
			"report_id",
		]),
		planned_account_id: metadataString(raw, "planned_account_id", [
			"assigned_account_id",
			"account_assignment_id",
		]),
		planned_account_handle: metadataString(raw, "planned_account_handle", [
			"assigned_account_handle",
			"account_assignment",
		]),
		planned_window_start: stringValue(raw.planned_window_start),
		planned_window_end: stringValue(raw.planned_window_end),
		assignment_notes: stringValue(raw.assignment_notes),
		caption_generation: asRecord(raw.caption_generation) ?? undefined,
		reference_pattern: asRecord(raw.reference_pattern) ?? undefined,
		source_prompt: asRecord(raw.source_prompt) ?? undefined,
		generated_asset_lineage: parseCampaignFactoryGeneratedAssetLineage(
			raw.generated_asset_lineage ?? raw.generatedAssetLineage,
		),
		audio_intent: parseCampaignFactoryAudioIntent(raw.audio_intent),
		daily_production: parseCampaignFactoryDailyProduction(
			raw.daily_production ?? raw.dailyProduction,
		),
		created_at: stringValue(raw.created_at),
		exported_at: stringValue(raw.exported_at),
		export_timestamp: stringValue(raw.export_timestamp),
	};
	return Object.values(cf).some(Boolean) ? cf : null;
}

function lineageRecord(
	cf: CampaignFactoryMetadata | null | undefined,
	key: "review" | "quality" | "captionOutcomeContext",
): Record<string, unknown> | undefined {
	const value = cf?.generated_asset_lineage?.[key];
	return asRecord(value) ?? undefined;
}

function metadataBool(...values: unknown[]): boolean | undefined {
	for (const value of values) {
		if (typeof value === "boolean") return value;
	}
	return undefined;
}

function metadataPass(value: unknown): boolean {
	return (
		String(value || "")
			.trim()
			.toLowerCase() === "pass"
	);
}

function campaignFactoryCaptionOutcomeContext(
	cf: CampaignFactoryMetadata | null | undefined,
): Record<string, unknown> | undefined {
	return (
		cf?.captionOutcomeContext ??
		cf?.caption_outcome_context ??
		lineageRecord(cf, "captionOutcomeContext")
	);
}

function campaignFactoryHandoffManifest(
	cf: CampaignFactoryMetadata | null | undefined,
): HandoffManifest | undefined {
	return cf?.handoff_manifest ?? cf?.handoffManifest;
}

function campaignFactoryHasAssignedAudio(
	cf: CampaignFactoryMetadata | null | undefined,
): boolean {
	const intent = cf?.audio_intent;
	if (!intent) return false;
	const required = intent.required === true;
	const status = String(intent.status || "")
		.trim()
		.toLowerCase();
	if (!required || status === "not_required" || status === "skipped")
		return true;
	if (!["selected", "attached", "verified"].includes(status)) return false;
	const selection = intent.operator_selection || {};
	const decision = asRecord(intent.decision) || {};
	const primaryAudio =
		asRecord(decision.primaryAudio) ?? asRecord(decision.primary_audio) ?? {};
	return [
		selection.platform_audio_id,
		selection.platform_url,
		selection.native_audio_id,
		selection.native_audio_url,
		selection.audio_id,
		primaryAudio.platform_audio_id,
		primaryAudio.platformAudioId,
		primaryAudio.platform_url,
		primaryAudio.platformUrl,
		primaryAudio.audioId,
	].some((value) => typeof value === "string" && value.trim().length > 0);
}

function campaignFactoryIsQuarantined(
	cf: CampaignFactoryMetadata | null | undefined,
): boolean {
	const quarantine = cf?.quarantine || {};
	return (
		cf?.quarantined === true ||
		quarantine.active === true ||
		String(cf?.asset_state || "")
			.trim()
			.toLowerCase() === "invalid_retired_draft"
	);
}

export function explainCampaignFactoryPublishability(
	cf: CampaignFactoryMetadata | null | undefined,
): PublishabilityDecision {
	if (!cf) {
		return {
			decision: "blocked",
			state: "approved_but_not_publishable",
			reasons: ["not_approved"],
			checks: {
				creative_approved: false,
				captioned_render_present: false,
				visible_caption_verification: false,
				expected_visual_verification: false,
				content_fingerprint_present: false,
				caption_hash_present: false,
				captionOutcomeContext_present: false,
				audio_assigned: false,
				readiness_checks_pass: false,
				quarantine_clear: true,
			},
		};
	}
	const review = lineageRecord(cf, "review") || {};
	const quality = lineageRecord(cf, "quality") || {};
	const captionContext = campaignFactoryCaptionOutcomeContext(cf);
	const approved =
		metadataBool(cf.approved, review.approved) === true ||
		String(review.status || "")
			.trim()
			.toLowerCase() === "approved";
	const captionedRenderPresent =
		metadataBool(
			cf.captioned_render_present,
			quality.captioned_render_present,
			quality.captionedRenderPresent,
		) === true;
	const visibleCaptionVerification =
		cf.visible_caption_verification ??
		stringValue(quality.visible_caption_verification) ??
		stringValue(quality.visibleCaptionVerification);
	const expectedVisualVerification =
		cf.expected_visual_verification ??
		stringValue(quality.expected_visual_verification) ??
		stringValue(quality.expectedVisualVerification);
	const captionHash =
		cf.caption_hash ??
		stringValue(captionContext?.caption_hash) ??
		stringValue(captionContext?.captionHash);
	const contentFingerprint =
		cf.content_fingerprint ??
		stringValue(quality.content_fingerprint) ??
		stringValue(quality.contentFingerprint);
	const readinessChecksPass =
		metadataBool(
			cf.readiness_checks_pass,
			quality.readiness_checks_pass,
			quality.readinessChecksPass,
		) === true;
	const checks = {
		creative_approved: approved,
		captioned_render_present: captionedRenderPresent,
		visible_caption_verification: metadataPass(visibleCaptionVerification),
		expected_visual_verification: metadataPass(expectedVisualVerification),
		content_fingerprint_present: Boolean(contentFingerprint),
		caption_hash_present: Boolean(captionHash),
		captionOutcomeContext_present: Boolean(captionContext),
		audio_assigned: campaignFactoryHasAssignedAudio(cf),
		readiness_checks_pass: readinessChecksPass,
		quarantine_clear: !campaignFactoryIsQuarantined(cf),
	};
	const failures: CampaignFactoryPublishabilityReason[] = [];
	if (!checks.creative_approved) failures.push("not_approved");
	if (
		!checks.captioned_render_present ||
		!checks.visible_caption_verification
	) {
		failures.push("missing_burned_captions");
	}
	if (!checks.expected_visual_verification) failures.push("wrong_visual");
	if (!checks.caption_hash_present) failures.push("missing_caption_hash");
	if (!checks.captionOutcomeContext_present)
		failures.push("missing_caption_outcome_context");
	if (!checks.content_fingerprint_present)
		failures.push("missing_content_fingerprint");
	if (!checks.audio_assigned) failures.push("missing_audio");
	if (!checks.readiness_checks_pass) failures.push("readiness_failed");
	if (!checks.quarantine_clear) failures.push("quarantined_asset");
	return {
		decision: failures.length === 0 ? "pass" : "blocked",
		state:
			failures.length === 0
				? "publishable_candidate"
				: "approved_but_not_publishable",
		reasons: failures,
		checks,
	};
}

export function campaignFactoryPublishabilityFailureReasons(
	cf: CampaignFactoryMetadata | null | undefined,
): CampaignFactoryPublishabilityReason[] {
	return explainCampaignFactoryPublishability(cf)
		.reasons as CampaignFactoryPublishabilityReason[];
}

export function explainPublishability(
	assetId: string,
	candidates: Array<
		| CampaignFactoryMetadata
		| CampaignFactoryPostLike
		| Record<string, unknown>
		| null
		| undefined
	>,
): PublishabilityDecision {
	const target = candidates
		.map((candidate) => {
			if (!candidate) return null;
			if ("metadata" in candidate || "campaignFactory" in candidate) {
				return getCampaignFactoryMetadata(candidate as CampaignFactoryPostLike);
			}
			if ("campaign_factory" in candidate) {
				return getCampaignFactoryMetadata({
					metadata: candidate as Record<string, unknown>,
				});
			}
			return candidate as CampaignFactoryMetadata;
		})
		.find(
			(cf) =>
				cf?.rendered_asset_id === assetId ||
				cf?.source_asset_id === assetId ||
				(cf as Record<string, unknown> | undefined)?.asset_id === assetId,
		);
	return explainCampaignFactoryPublishability(target);
}

export function campaignFactoryAssetStateAllowsExport(
	cf: CampaignFactoryMetadata | null | undefined,
): boolean {
	const state = String(cf?.asset_state || "")
		.trim()
		.toLowerCase();
	return state === "publishable_candidate" || state === "exportable";
}

export function campaignFactoryCanExport(
	cf: CampaignFactoryMetadata | null | undefined,
): boolean {
	return (
		campaignFactoryAssetStateAllowsExport(cf) &&
		explainCampaignFactoryPublishability(cf).decision === "pass" &&
		validateCampaignFactoryHandoffManifest(cf).length === 0
	);
}

export function validateCampaignFactoryHandoffManifest(
	cf: CampaignFactoryMetadata | null | undefined,
): string[] {
	const manifest = campaignFactoryHandoffManifest(cf);
	if (!manifest) return ["handoff_manifest is required"];
	const errors: string[] = [];
	if (manifest.manifest_version !== 1) {
		errors.push("handoff_manifest.manifest_version must be 1");
	}
	if (manifest.exported_by_system !== "campaign_factory") {
		errors.push("handoff_manifest.exported_by_system must be campaign_factory");
	}
	for (const [field, value] of [
		["asset_id", manifest.asset_id],
		["render_file_id", manifest.render_file_id],
		["content_fingerprint", manifest.content_fingerprint],
		["caption_hash", manifest.caption_hash],
		["visual_verification_id", manifest.visual_verification_id],
		["caption_verification_id", manifest.caption_verification_id],
		["audio_id", manifest.audio_id],
		["distribution_plan_id", manifest.distribution_plan_id],
		["exported_at", manifest.exported_at],
	] as const) {
		if (!stringValue(value))
			errors.push(`handoff_manifest.${field} is required`);
	}
	if (!asRecord(manifest.captionOutcomeContext)) {
		errors.push("handoff_manifest.captionOutcomeContext must be an object");
	}
	const quality = lineageRecord(cf, "quality") || {};
	const captionContext = campaignFactoryCaptionOutcomeContext(cf);
	const expectedAssetId = firstStringValue(
		(cf as Record<string, unknown> | null | undefined)?.asset_id,
		cf?.rendered_asset_id,
		cf?.source_asset_id,
	);
	if (
		expectedAssetId &&
		manifest.asset_id &&
		manifest.asset_id !== expectedAssetId
	) {
		errors.push("handoff_manifest.asset_id mismatch");
	}
	const expectedFingerprint = firstStringValue(
		cf?.content_fingerprint,
		quality.content_fingerprint,
		quality.contentFingerprint,
	);
	if (
		expectedFingerprint &&
		manifest.content_fingerprint &&
		manifest.content_fingerprint !== expectedFingerprint
	) {
		errors.push("handoff_manifest.content_fingerprint mismatch");
	}
	const expectedCaptionHash = firstStringValue(
		cf?.caption_hash,
		captionContext?.caption_hash,
		captionContext?.captionHash,
	);
	if (
		expectedCaptionHash &&
		manifest.caption_hash &&
		manifest.caption_hash !== expectedCaptionHash
	) {
		errors.push("handoff_manifest.caption_hash mismatch");
	}
	if (
		cf?.instagram_post_caption_hash &&
		manifest.instagram_post_caption_hash &&
		manifest.instagram_post_caption_hash !== cf.instagram_post_caption_hash
	) {
		errors.push("handoff_manifest.instagram_post_caption_hash mismatch");
	}
	const manifestCaptionContext = asRecord(manifest.captionOutcomeContext);
	if (
		manifestCaptionContext &&
		expectedCaptionHash &&
		stringValue(manifestCaptionContext.caption_hash) &&
		manifestCaptionContext.caption_hash !== expectedCaptionHash
	) {
		errors.push("handoff_manifest.captionOutcomeContext.caption_hash mismatch");
	}
	if (campaignFactoryIsQuarantined(cf)) {
		errors.push("handoff_manifest asset is quarantined");
	}
	return errors;
}

export function campaignFactoryMetricsEligible(
	cf: CampaignFactoryMetadata | null | undefined,
	values: {
		lineageValid?: boolean;
		draftValidated?: boolean;
		publishedPostId?: string | null;
		contentFingerprintMatch?: boolean;
		captionHashMatch?: boolean;
		manualOverrideContaminated?: boolean;
	} = {},
): boolean {
	return (
		values.lineageValid === true &&
		values.draftValidated === true &&
		Boolean(values.publishedPostId) &&
		values.contentFingerprintMatch === true &&
		values.captionHashMatch === true &&
		!campaignFactoryIsQuarantined(cf) &&
		values.manualOverrideContaminated !== true &&
		cf?.manual_override_contaminated !== true
	);
}

export function parseCampaignFactoryGeneratedAssetLineage(
	value: unknown,
): CampaignFactoryGeneratedAssetLineage | undefined {
	const raw = asRecord(value);
	if (!raw) return undefined;
	const parsed: CampaignFactoryGeneratedAssetLineage = {
		schema: stringValue(raw.schema),
		source: asRecord(raw.source) ?? undefined,
		generation: asRecord(raw.generation) ?? undefined,
		review: asRecord(raw.review) ?? undefined,
		quality: asRecord(raw.quality) ?? undefined,
		captionOutcomeContext: asRecord(raw.captionOutcomeContext) ?? undefined,
	};
	return Object.entries(parsed).some(([key, item]) => key !== "schema" && item)
		? parsed
		: undefined;
}

export function parseCampaignFactoryDailyProduction(
	value: unknown,
): CampaignFactoryDailyProduction | undefined {
	const raw = asRecord(value);
	if (!raw) return undefined;
	const parsed: CampaignFactoryDailyProduction = {
		schema: stringValue(raw.schema),
		targetBaseVideos: numberValue(raw.targetBaseVideos, raw.target_base_videos),
		promptReady: numberValue(raw.promptReady, raw.prompt_ready),
		generated: numberValue(raw.generated),
		sentToPipeline: numberValue(raw.sentToPipeline, raw.sent_to_pipeline),
		reviewed: numberValue(raw.reviewed),
		postedOrScheduled: numberValue(
			raw.postedOrScheduled,
			raw.posted_or_scheduled,
		),
		remainingBaseVideos: numberValue(
			raw.remainingBaseVideos,
			raw.remaining_base_videos,
		),
		primaryMetric: stringValue(raw.primaryMetric ?? raw.primary_metric),
	};
	return Object.entries(parsed).some(([key, item]) => key !== "schema" && item)
		? parsed
		: undefined;
}

export function parseCampaignFactoryAudioIntent(
	value: unknown,
): CampaignFactoryAudioIntent | undefined {
	const raw = asRecord(value);
	if (!raw) return undefined;
	const status = stringValue(raw.status);
	const recommendations = Array.isArray(raw.recommendations)
		? raw.recommendations.filter(
				(item): item is Record<string, unknown> => !!asRecord(item),
			)
		: [];
	return {
		schema: stringValue(raw.schema),
		mode: stringValue(raw.mode),
		required: raw.required === true,
		status,
		platform: stringValue(raw.platform),
		surface: stringValue(raw.surface),
		recommendations,
		decision: asRecord(raw.decision) ?? undefined,
		operator_selection: asRecord(raw.operator_selection) ?? undefined,
		task: parseCampaignFactoryAudioTask(raw.task),
		gates: asRecord(raw.gates) ?? undefined,
	};
}

export function parseCampaignFactoryAudioTask(
	value: unknown,
): CampaignFactoryAudioTask | undefined {
	const raw = asRecord(value);
	if (!raw) return undefined;
	return {
		schema: stringValue(raw.schema),
		status: stringValue(raw.status),
		assignee: stringValue(raw.assignee),
		due_at: stringValue(raw.due_at),
		proof_required: raw.proof_required === true,
		created_at: stringValue(raw.created_at),
		updated_at: stringValue(raw.updated_at),
		completed_at: stringValue(raw.completed_at),
	};
}

export function campaignFactoryNeedsNativeAudio(
	cf: CampaignFactoryMetadata | null | undefined,
): boolean {
	return cf?.audio_intent?.required === true;
}

export function campaignFactoryAudioAllowsLive(
	cf: CampaignFactoryMetadata | null | undefined,
): boolean {
	if (!campaignFactoryNeedsNativeAudio(cf)) return true;
	const intent = cf?.audio_intent;
	const status = String(intent?.status || "")
		.trim()
		.toLowerCase();
	if (status === "skipped" || status === "not_required") return true;
	if (status !== "attached" && status !== "verified") return false;
	return campaignFactoryAudioHasNativeProof(intent);
}

export function campaignFactoryAudioHasNativeProof(
	intent: CampaignFactoryAudioIntent | null | undefined,
): boolean {
	const selection = intent?.operator_selection || {};
	const status = String(intent?.status || "")
		.trim()
		.toLowerCase();
	if (status !== "attached" && status !== "verified") return false;
	const hasNativeLocator = [
		selection.platform_audio_id,
		selection.platform_url,
		selection.native_audio_id,
		selection.native_audio_url,
		selection.audio_id,
	].some((value) => typeof value === "string" && value.trim().length > 0);
	const hasSelectedAt =
		typeof selection.selected_at === "string" &&
		selection.selected_at.trim().length > 0;
	const finalTimestampKey =
		status === "verified" ? "verified_at" : "attached_at";
	const hasFinalTimestamp =
		typeof selection[finalTimestampKey] === "string" &&
		String(selection[finalTimestampKey]).trim().length > 0;
	return hasNativeLocator && hasSelectedAt && hasFinalTimestamp;
}

export function campaignFactoryAudioMissingNativeProof(
	cf: CampaignFactoryMetadata | null | undefined,
): boolean {
	if (!campaignFactoryNeedsNativeAudio(cf)) return false;
	const status = String(cf?.audio_intent?.status || "")
		.trim()
		.toLowerCase();
	return (
		(status === "attached" || status === "verified") &&
		!campaignFactoryAudioHasNativeProof(cf?.audio_intent)
	);
}

export function buildCampaignFactoryAudioTask(
	cf: CampaignFactoryMetadata | null | undefined,
	nowIso?: string,
): CampaignFactoryAudioTask | null {
	const intent = cf?.audio_intent;
	if (!intent) return null;
	const existing = intent.task || {};
	const status = String(intent.status || "needs_operator_selection")
		.trim()
		.toLowerCase();
	const selection = intent.operator_selection || {};
	let taskStatus: CampaignFactoryAudioTaskStatus = "open";
	if (!intent.required || status === "not_required")
		taskStatus = "not_required";
	else if (status === "selected") taskStatus = "selected";
	else if (status === "blocked" || status === "burned") taskStatus = "blocked";
	else if (status === "needs_review") taskStatus = "needs_review";
	else if (status === "skipped") taskStatus = "completed";
	else if (status === "attached" || status === "verified") {
		taskStatus = campaignFactoryAudioHasNativeProof(intent)
			? "completed"
			: "proof_missing";
	}
	const completedAt =
		existing.completed_at ||
		(taskStatus === "completed"
			? firstStringValue(
					selection.verified_at,
					selection.attached_at,
					selection.skipped_at,
					nowIso,
				)
			: undefined);
	return {
		...existing,
		schema: existing.schema || "pipeline.audio_task.v1",
		status: taskStatus,
		proof_required:
			intent.required === true &&
			(status === "attached" || status === "verified"),
		completed_at: completedAt,
		updated_at: nowIso || existing.updated_at,
	};
}

export function formatCampaignFactoryAudioStatus(
	cf: CampaignFactoryMetadata | null | undefined,
): string | null {
	const intent = cf?.audio_intent;
	if (!intent) return null;
	const status = String(intent.status || "")
		.trim()
		.toLowerCase();
	if (!intent.required || status === "not_required")
		return "Audio not required";
	if (status === "needs_operator_selection") return "Needs audio";
	if (status === "recommended") return "Audio recommended";
	if (status === "selected") return "Audio selected";
	if (status === "attached") {
		return campaignFactoryAudioMissingNativeProof(cf)
			? "Audio attached - proof missing"
			: "Audio attached";
	}
	if (status === "verified") {
		return campaignFactoryAudioMissingNativeProof(cf)
			? "Audio verified - proof missing"
			: "Audio verified";
	}
	if (status === "skipped") return "Audio skipped";
	if (status === "blocked") return "Audio blocked";
	if (status === "needs_review") return "Audio needs review";
	if (status === "burned") return "Audio burned";
	return "Needs audio";
}

export function getCampaignFactoryAudioQueueLane(
	post: CampaignFactoryPostLike | null | undefined,
): CampaignFactoryAudioQueueLane | null {
	const cf = getCampaignFactoryMetadata(post);
	if (!cf?.audio_intent || !campaignFactoryNeedsNativeAudio(cf)) return null;
	const status = String(cf.audio_intent.status || "")
		.trim()
		.toLowerCase();
	if (campaignFactoryAudioMissingNativeProof(cf)) return "missing_proof";
	if (status === "selected") return "selected_not_attached";
	if (
		status === "blocked" ||
		status === "needs_review" ||
		status === "burned"
	) {
		return "blocked";
	}
	if (campaignFactoryAudioAllowsLive(cf)) {
		return post?.status === "scheduled" ? "needs_handoff" : "ready";
	}
	return "needs_audio";
}

export function summarizeCampaignFactoryAudioQueue(
	posts: CampaignFactoryPostLike[],
): Record<CampaignFactoryAudioQueueLane, number> {
	const counts: Record<CampaignFactoryAudioQueueLane, number> = {
		needs_audio: 0,
		selected_not_attached: 0,
		missing_proof: 0,
		blocked: 0,
		ready: 0,
		needs_handoff: 0,
	};
	for (const post of posts) {
		const lane = getCampaignFactoryAudioQueueLane(post);
		if (lane) counts[lane] += 1;
	}
	return counts;
}

export function updateCampaignFactoryAudioIntent(
	post: CampaignFactoryPostLike,
	patch: Partial<CampaignFactoryAudioIntent>,
): Record<string, unknown> {
	const metadata = { ...(asRecord(post.metadata) ?? {}) };
	const campaignFactory = { ...(asRecord(metadata.campaign_factory) ?? {}) };
	const existing =
		parseCampaignFactoryAudioIntent(campaignFactory.audio_intent) ??
		({
			schema: "pipeline.audio_intent.v1",
			required: false,
		} satisfies CampaignFactoryAudioIntent);
	const nextAudioIntent: CampaignFactoryAudioIntent = {
		...existing,
		...patch,
		schema: existing.schema || "pipeline.audio_intent.v1",
		operator_selection: {
			...(existing.operator_selection || {}),
			...(patch.operator_selection || {}),
		},
	};
	nextAudioIntent.task =
		patch.task ||
		buildCampaignFactoryAudioTask(
			{ audio_intent: nextAudioIntent } as CampaignFactoryMetadata,
			stringValue(patch.operator_selection?.updated_at),
		) ||
		existing.task;
	campaignFactory.audio_intent = nextAudioIntent;
	metadata.campaign_factory = campaignFactory;
	return metadata;
}

export function firstCampaignFactoryAudioRecommendation(
	cf: CampaignFactoryMetadata | null | undefined,
): Record<string, unknown> | null {
	const decision = asRecord(cf?.audio_intent?.decision);
	const primary = asRecord(decision?.primaryAudio);
	return (
		primary ??
		cf?.audio_intent?.recommendations?.find((item) => asRecord(item)) ??
		null
	);
}

export function applyCampaignFactoryAudioBatchAction(
	post: CampaignFactoryPostLike,
	action: CampaignFactoryAudioBatchAction,
	nowIso = new Date().toISOString(),
): Record<string, unknown> | null {
	const cf = getCampaignFactoryMetadata(post);
	if (!cf?.audio_intent) return null;
	if (
		action === "apply_first_recommendation" ||
		action === "apply_primary_audio"
	) {
		const recommendation = firstCampaignFactoryAudioRecommendation(cf);
		if (!recommendation) return null;
		return updateCampaignFactoryAudioIntent(post, {
			status: "selected",
			operator_selection: {
				audio_title:
					recommendation.audio_title ??
					recommendation.audioTitle ??
					recommendation.title ??
					null,
				artist_name:
					recommendation.artist_name ?? recommendation.artistName ?? null,
				platform_audio_id:
					recommendation.platform_audio_id ??
					recommendation.platformAudioId ??
					recommendation.audioId ??
					null,
				platform_url:
					recommendation.platform_url ?? recommendation.platformUrl ?? null,
				catalog_audio_id:
					recommendation.catalog_audio_id ??
					recommendation.catalogAudioId ??
					null,
				audio_memory_graph_id:
					recommendation.audioMemoryGraphId ??
					recommendation.audio_memory_graph_id ??
					null,
				selection_rank:
					recommendation.selectionRank ?? recommendation.selection_rank ?? null,
				source: recommendation.source ?? null,
				selected_at: nowIso,
				selection_source:
					action === "apply_primary_audio"
						? "batch_primary_audio_decision"
						: "batch_first_recommendation",
				updated_at: nowIso,
			},
		});
	}
	if (action === "attached" || action === "verified") {
		const timestampKey = action === "verified" ? "verified_at" : "attached_at";
		return updateCampaignFactoryAudioIntent(post, {
			status: action,
			operator_selection: {
				...(cf.audio_intent.operator_selection || {}),
				[timestampKey]: nowIso,
				proof_source: "operator_batch_action",
				updated_at: nowIso,
			},
		});
	}
	return updateCampaignFactoryAudioIntent(post, {
		status: action,
		operator_selection: {
			...(cf.audio_intent.operator_selection || {}),
			updated_at: nowIso,
			...(action === "skipped" ? { skipped_at: nowIso } : {}),
		},
	});
}

export function isCampaignFactoryPost(
	post: CampaignFactoryPostLike | null | undefined,
): boolean {
	return !!getCampaignFactoryMetadata(post);
}

export function isCampaignFactoryDraft(
	post: CampaignFactoryPostLike | null | undefined,
): boolean {
	const cf = getCampaignFactoryMetadata(post);
	if (!cf) return false;
	return post?.platform === "instagram" && post?.status === "draft";
}

function includesNeedle(
	value: string | undefined,
	needle: string | undefined,
): boolean {
	const query = needle?.trim().toLowerCase();
	if (!query) return true;
	return (value ?? "").toLowerCase().includes(query);
}

function equalsFilter(
	value: string | undefined,
	filter: string | undefined,
): boolean {
	const query = filter?.trim().toLowerCase();
	if (!query || query === "all") return true;
	return (value ?? "").toLowerCase() === query;
}

function hasConcreteFilter(value: string | undefined): boolean {
	const query = value?.trim().toLowerCase();
	return Boolean(query && query !== "all");
}

function matchesAudioStateFilter(
	post: CampaignFactoryPostLike,
	cf: CampaignFactoryMetadata | null,
	filter: CampaignFactoryFilters["audioState"],
): boolean {
	if (!filter || filter === "all") return true;
	if (filter === "ready") return campaignFactoryAudioAllowsLive(cf);
	if (filter === "blocked")
		return String(cf?.audio_intent?.status || "").toLowerCase() === "blocked";
	if (filter === "missing_proof")
		return campaignFactoryAudioMissingNativeProof(cf);
	if (filter === "selected_not_attached") {
		return String(cf?.audio_intent?.status || "").toLowerCase() === "selected";
	}
	if (filter === "needs_handoff") {
		return (
			getCampaignFactoryAudioQueueLane({ ...post, campaignFactory: cf }) ===
			"needs_handoff"
		);
	}
	if (filter === "needs_audio")
		return (
			campaignFactoryNeedsNativeAudio(cf) && !campaignFactoryAudioAllowsLive(cf)
		);
	return true;
}

export function hasActiveCampaignFactoryFilters(
	filters: CampaignFactoryFilters,
): boolean {
	return Boolean(
		filters.only ||
			filters.campaignId?.trim() ||
			filters.modelId?.trim() ||
			filters.sourceAssetId?.trim() ||
			filters.renderedAssetId?.trim() ||
			hasConcreteFilter(filters.auditStatus) ||
			filters.contentPillar?.trim() ||
			filters.ctaType?.trim() ||
			filters.language?.trim() ||
			filters.recipe?.trim() ||
			filters.instagramAccountId?.trim() ||
			hasConcreteFilter(filters.status) ||
			hasConcreteFilter(filters.audioState),
	);
}

export function matchesCampaignFactoryFilters(
	post: CampaignFactoryPostLike,
	filters: CampaignFactoryFilters,
): boolean {
	if (!hasActiveCampaignFactoryFilters(filters)) return true;
	const cf = getCampaignFactoryMetadata(post);
	if (!cf) return false;
	const instagramAccountId =
		post.instagramAccountId ?? post.instagram_account_id;
	return (
		includesNeedle(cf.campaign_id, filters.campaignId) &&
		(includesNeedle(cf.model_id, filters.modelId) ||
			includesNeedle(cf.model_slug, filters.modelId)) &&
		includesNeedle(cf.source_asset_id, filters.sourceAssetId) &&
		includesNeedle(cf.rendered_asset_id, filters.renderedAssetId) &&
		equalsFilter(cf.audit_status, filters.auditStatus) &&
		includesNeedle(cf.content_pillar, filters.contentPillar) &&
		includesNeedle(cf.cta_type, filters.ctaType) &&
		includesNeedle(cf.language, filters.language) &&
		includesNeedle(cf.recipe, filters.recipe) &&
		includesNeedle(
			instagramAccountId ?? undefined,
			filters.instagramAccountId,
		) &&
		equalsFilter(post.status ?? undefined, filters.status) &&
		matchesAudioStateFilter(post, cf, filters.audioState)
	);
}

export function filterCampaignFactoryPosts<T extends CampaignFactoryPostLike>(
	posts: T[],
	filters: CampaignFactoryFilters,
): T[] {
	return posts.filter((post) => matchesCampaignFactoryFilters(post, filters));
}

export function computeCampaignFactoryReuseCounts(
	posts: CampaignFactoryPostLike[],
	target: CampaignFactoryPostLike,
): CampaignFactoryReuseCounts {
	const targetCf = getCampaignFactoryMetadata(target);
	const counts: CampaignFactoryReuseCounts = {
		renderedAsset: 0,
		sourceAsset: 0,
		contentHash: 0,
		sourceContentHash: 0,
		captionHash: 0,
		recipe: 0,
	};
	if (!targetCf) return counts;

	for (const post of posts) {
		if (post.id && target.id && post.id === target.id) continue;
		if (!COUNTED_STATUSES.has(String(post.status ?? ""))) continue;
		const cf = getCampaignFactoryMetadata(post);
		if (!cf) continue;
		if (
			targetCf.rendered_asset_id &&
			cf.rendered_asset_id === targetCf.rendered_asset_id
		) {
			counts.renderedAsset += 1;
		}
		if (
			targetCf.source_asset_id &&
			cf.source_asset_id === targetCf.source_asset_id
		) {
			counts.sourceAsset += 1;
		}
		if (targetCf.content_hash && cf.content_hash === targetCf.content_hash) {
			counts.contentHash += 1;
		}
		if (
			targetCf.source_content_hash &&
			cf.source_content_hash === targetCf.source_content_hash
		) {
			counts.sourceContentHash += 1;
		}
		if (targetCf.caption_hash && cf.caption_hash === targetCf.caption_hash) {
			counts.captionHash += 1;
		}
		if (targetCf.recipe && cf.recipe === targetCf.recipe) {
			counts.recipe += 1;
		}
	}

	return counts;
}

function pluralize(count: number, singular: string): string {
	return `${count} ${singular}${count === 1 ? "" : "s"}`;
}

export function formatCampaignFactoryReuseLabels(
	counts: CampaignFactoryReuseCounts,
): string[] {
	const labels: string[] = [];
	if (counts.renderedAsset > 0) {
		labels.push(`same render used ${pluralize(counts.renderedAsset, "time")}`);
	}
	if (counts.sourceAsset > 0) {
		labels.push(
			`same source asset used ${pluralize(counts.sourceAsset, "time")}`,
		);
	}
	if (counts.contentHash > 0) {
		labels.push(`same content used ${pluralize(counts.contentHash, "time")}`);
	}
	if (counts.sourceContentHash > 0) {
		labels.push(
			`same source family used ${pluralize(counts.sourceContentHash, "time")}`,
		);
	}
	if (counts.captionHash > 0) {
		labels.push(`same caption used ${pluralize(counts.captionHash, "time")}`);
	}
	if (counts.recipe >= 3) {
		labels.push(`same recipe used ${pluralize(counts.recipe, "time")}`);
	}
	return labels;
}

export function formatCampaignFactoryAuditStatus(
	status: string | undefined,
): string {
	if (!status) return "Pending";
	return status
		.split("_")
		.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
		.join(" ");
}

export function formatCampaignFactorySurface(
	cf: CampaignFactoryMetadata | null | undefined,
): string {
	const raw = normalizedKey(cf?.distribution_surface || cf?.content_surface);
	if (cf?.trialReels || cf?.trial_reel || raw === "trial_reel") return "Trial";
	if (raw === "story_cta") return "Story CTA";
	if (raw === "regular_reel" || raw === "reel") return "Reel";
	if (!raw) return "Reel";
	return formatCampaignFactoryAuditStatus(raw);
}

export function formatCampaignFactoryScheduleMode(
	cf: CampaignFactoryMetadata | null | undefined,
): string | null {
	if (!cf) return null;
	if (cf.preview_schedule_only) return "Preview";
	const mode = normalizedKey(cf.schedule_mode);
	if (mode === "live") return "Live";
	if (mode === "preview") return "Preview";
	return null;
}

export function getCampaignFactoryExportTimestamp(
	cf: CampaignFactoryMetadata | null | undefined,
): string | undefined {
	return cf?.exported_at ?? cf?.export_timestamp ?? cf?.created_at;
}

export function getCampaignFactoryPerformanceLineage(
	post: CampaignFactoryPostLike,
): Pick<
	CampaignFactoryMetadata,
	| "rendered_asset_id"
	| "source_asset_id"
	| "campaign_id"
	| "content_hash"
	| "caption_hash"
> | null {
	const cf = getCampaignFactoryMetadata(post);
	if (!cf) return null;
	return {
		rendered_asset_id: cf.rendered_asset_id,
		source_asset_id: cf.source_asset_id,
		campaign_id: cf.campaign_id,
		content_hash: cf.content_hash,
		caption_hash: cf.caption_hash,
	};
}

export function campaignFactoryDraftUpdate(content: string): {
	content: string;
	status: "draft";
	scheduledDate: null;
} {
	return { content, status: "draft", scheduledDate: null };
}

export function getCampaignFactoryDetailRows(
	cf: CampaignFactoryMetadata,
): Array<{
	label: string;
	value: string | null | undefined;
	kind?: "id" | "timestamp" | undefined;
}> {
	const lineageSource = cf.generated_asset_lineage?.source;
	const lineageGeneration = cf.generated_asset_lineage?.generation;
	const referencePattern = cf.reference_pattern;
	return [
		{ label: "Campaign", value: cf.campaign_id },
		{ label: "Model", value: cf.model_slug ?? cf.model_id },
		{
			label: "Format",
			value: stringValue(
				lineageSource?.formatType ??
					referencePattern?.visualFormat ??
					cf.source_prompt?.formatType,
			),
		},
		{
			label: "Pattern",
			value: stringValue(
				lineageSource?.patternCardId ??
					lineageSource?.referencePattern ??
					referencePattern?.clusterKey ??
					referencePattern?.id,
			),
			kind: "id",
		},
		{
			label: "Prompt",
			value: stringValue(lineageSource?.promptId ?? cf.source_prompt?.promptId),
			kind: "id",
		},
		{ label: "Generator", value: stringValue(lineageGeneration?.tool) },
		{ label: "Surface", value: formatCampaignFactorySurface(cf) },
		{ label: "Recipe", value: cf.recipe },
		{
			label: "Audit",
			value: formatCampaignFactoryAuditStatus(cf.audit_status),
		},
		{
			label: "Readiness",
			value: formatCampaignFactoryReadiness(cf.readiness_status),
		},
		{ label: "Pillar", value: cf.content_pillar },
		{ label: "CTA", value: cf.cta_type },
		{ label: "Language", value: cf.language },
		{ label: "ContentForge run", value: cf.contentforge_run_id, kind: "id" },
		{
			label: "ContentForge report",
			value: cf.contentforge_report_id,
			kind: "id",
		},
		{
			label: "Planned account",
			value: cf.planned_account_handle ?? cf.planned_account_id,
			kind: "id",
		},
		{ label: "Smart link", value: cf.smart_link },
		{
			label: "Window start",
			value: cf.planned_window_start,
			kind: "timestamp",
		},
		{ label: "Window end", value: cf.planned_window_end, kind: "timestamp" },
		{ label: "Export", value: cf.export_id, kind: "id" },
		{
			label: "Exported",
			value: getCampaignFactoryExportTimestamp(cf),
			kind: "timestamp",
		},
	];
}

export function getCampaignFactoryDailyProductionRows(
	cf: CampaignFactoryMetadata,
): Array<{
	label: string;
	value: number | string | null | undefined;
}> {
	const daily = cf.daily_production;
	if (!daily) return [];
	return [
		{ label: "Prompt ready", value: daily.promptReady },
		{ label: "Generated", value: daily.generated },
		{ label: "Sent to pipeline", value: daily.sentToPipeline },
		{ label: "Reviewed", value: daily.reviewed },
		{ label: "Posted/scheduled", value: daily.postedOrScheduled },
		{ label: "Remaining", value: daily.remainingBaseVideos },
		{ label: "Metric", value: daily.primaryMetric },
	];
}

export function getCampaignFactoryLongDetailRows(
	cf: CampaignFactoryMetadata,
): Array<{
	label: string;
	value: string | null | undefined;
}> {
	const lineageSource = cf.generated_asset_lineage?.source;
	const lineageGeneration = cf.generated_asset_lineage?.generation;
	const lineageReview = cf.generated_asset_lineage?.review;
	return [
		{ label: "source_asset_id", value: cf.source_asset_id },
		{ label: "rendered_asset_id", value: cf.rendered_asset_id },
		{ label: "reference_id", value: stringValue(lineageSource?.referenceId) },
		{
			label: "pattern_card_id",
			value: stringValue(lineageSource?.patternCardId),
		},
		{ label: "prompt_id", value: stringValue(lineageSource?.promptId) },
		{
			label: "generation_model",
			value: stringValue(lineageGeneration?.modelProfile),
		},
		{
			label: "human_review_required",
			value: lineageReview?.humanReviewRequired === true ? "yes" : undefined,
		},
		{ label: "source_hash", value: cf.source_content_hash },
		{ label: "rendered_hash", value: cf.rendered_hash ?? cf.content_hash },
		{ label: "caption_hash", value: cf.caption_hash },
		{ label: "distribution_plan_id", value: cf.distribution_plan_id },
		{ label: "paired_rendered_asset_id", value: cf.paired_rendered_asset_id },
		{ label: "distribution_reason_code", value: cf.distribution_reason_code },
	];
}

export function formatCampaignFactoryReadiness(
	readiness: string | undefined,
): string {
	if (!readiness) return "Not set";
	return formatCampaignFactoryAuditStatus(readiness);
}

function readinessRank(post: CampaignFactoryPostLike): number {
	const readiness =
		getCampaignFactoryMetadata(post)?.readiness_status?.toLowerCase();
	if (!readiness) return 3;
	if (readiness.includes("blocked")) return 0;
	if (readiness.includes("warning") || readiness.includes("needs")) return 1;
	if (readiness.includes("ready") || readiness.includes("approved")) return 2;
	return 3;
}

export function sortCampaignFactoryDraftQueue<
	T extends CampaignFactoryPostLike,
>(posts: T[]): T[] {
	return [...posts].sort((a, b) => {
		const aDraft = isCampaignFactoryDraft(a) ? 0 : 1;
		const bDraft = isCampaignFactoryDraft(b) ? 0 : 1;
		if (aDraft !== bDraft) return aDraft - bDraft;

		const createdDiff =
			new Date(b.createdAt ?? b.created_at ?? 0).getTime() -
			new Date(a.createdAt ?? a.created_at ?? 0).getTime();
		if (createdDiff !== 0) return createdDiff;

		const readinessDiff = readinessRank(a) - readinessRank(b);
		if (readinessDiff !== 0) return readinessDiff;

		const aCf = getCampaignFactoryMetadata(a);
		const bCf = getCampaignFactoryMetadata(b);
		const campaignDiff = (aCf?.campaign_id ?? "").localeCompare(
			bCf?.campaign_id ?? "",
		);
		if (campaignDiff !== 0) return campaignDiff;

		const aAccount =
			a.instagramAccountId ??
			a.instagram_account_id ??
			a.accountId ??
			a.account_id ??
			"";
		const bAccount =
			b.instagramAccountId ??
			b.instagram_account_id ??
			b.accountId ??
			b.account_id ??
			"";
		return aAccount.localeCompare(bAccount);
	});
}

export function getCampaignFactoryPerformancePayload(
	post: CampaignFactoryPostLike,
): CampaignFactoryPerformancePayload {
	const cf = getCampaignFactoryMetadata(post);
	return {
		post_id: post.id ?? null,
		status: post.status ?? null,
		views: numberValue(
			post.ig_views,
			post.views,
			post.views_count,
			post.ig_video_views,
			post.ig_reels_plays,
		),
		likes: numberValue(post.likes, post.likes_count),
		comments: numberValue(
			post.comments,
			post.ig_comment_count,
			post.replies,
			post.replies_count,
		),
		replies: numberValue(
			post.replies,
			post.replies_count,
			post.ig_comment_count,
		),
		shares: numberValue(post.shares, post.ig_shares, post.shares_count),
		saves: numberValue(post.saves, post.ig_saved),
		reach: numberValue(post.reach, post.ig_reach),
		published_at: post.publishedAt ?? post.published_at ?? null,
		permalink: post.permalink ?? null,
		instagram_account_id:
			post.instagramAccountId ?? post.instagram_account_id ?? null,
		media_urls: stringArrayValue(post.mediaUrls ?? post.media_urls),
		campaign_factory: cf,
		lineage: getCampaignFactoryPerformanceLineage(post),
	};
}
