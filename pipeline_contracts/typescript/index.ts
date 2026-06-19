import Ajv2020, { type ErrorObject, type ValidateFunction } from "ajv/dist/2020.js";
import {
	generatedPipelineContractSchemaManifest,
	generatedPipelineContractSchemas,
} from "./generated-schemas";
export {
	generatedPipelineContractSchemaManifest,
	generatedPipelineContractSchemas,
} from "./generated-schemas";

export const AUDIO_INTENT_SCHEMA_ID = "pipeline.audio_intent.v1" as const;
export const CAMPAIGN_DRAFT_PAYLOAD_SCHEMA_ID =
	"campaign_factory.threadsdash_drafts.v1" as const;
export const AUDIO_CATALOG_EXPORT_SCHEMA_ID =
	"reference_factory.audio_catalog_export.v1" as const;
export const PERFORMANCE_SYNC_SCHEMA_ID =
	"campaign_factory.performance_sync.v1" as const;
export const POST_METRIC_HISTORY_READ_SCHEMA_ID =
	"threadsdashboard.post_metric_history.read.v1" as const;
export const CAPTION_OUTCOME_CONTEXT_SCHEMA_ID =
	"campaign_factory.caption_outcome_context.v1" as const;
export const PATTERN_CARD_SCHEMA_ID = "reference_factory.pattern_card.v1" as const;
export const VIDEO_ANALYSIS_SCHEMA_ID = "reference_factory.video_analysis.v1" as const;
export const HIGGSFIELD_SOUL_IMAGE_PROMPT_SCHEMA_ID =
	"reference_factory.higgsfield_soul_image_prompt.v1" as const;
export const KLING_3_VIDEO_PROMPT_SCHEMA_ID =
	"reference_factory.kling_3_video_prompt.v1" as const;
export const GENERATED_ASSET_LINEAGE_SCHEMA_ID =
	"campaign_factory.generated_asset_lineage.v1" as const;
export const CREATIVE_PLAN_SCHEMA_ID =
	"campaign_factory.creative_plan.v1" as const;
export const RECOMMENDATION_ACCURACY_REPORT_SCHEMA_ID =
	"campaign_factory.recommendation_accuracy_report.v1" as const;
export const RECOMMENDATION_NEXT_BATCH_SCHEMA_ID =
	"campaign_factory.recommendations.next_batch.v1" as const;
export const REPURPOSING_PLAN_SCHEMA_ID =
	"campaign_factory.repurposing_plan.v1" as const;
export const VARIANT_ASSIGNMENT_SCHEMA_ID =
	"campaign_factory.variant_assignment.v1" as const;
export const MOTION_EDIT_RENDER_SCHEMA_ID =
	"reel_factory.motion_edit_render.v1" as const;
export const FRONT_GENERATION_PLAN_SCHEMA_ID =
	"campaign_factory.front_generation_plan.v1" as const;

export const EXPORTABLE_ASSET_STATES = [
	"publishable_candidate",
	"exportable",
] as const;

export const APPROVED_BUT_NOT_PUBLISHABLE_STATE =
	"approved_but_not_publishable" as const;

export const APPROVED_BUT_NOT_PUBLISHABLE_REASONS = [
	"missing_burned_captions",
	"wrong_visual",
	"missing_caption_hash",
	"missing_caption_outcome_context",
	"missing_content_fingerprint",
	"missing_audio",
	"readiness_failed",
	"not_approved",
	"quarantined_asset",
] as const;

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
	instagram_post_caption?: string;
	instagram_post_caption_hash?: string;
	caption_cta?: string | null;
	hashtags?: string[];
	post_caption_style?: string;
	burned_caption_text?: string;
	burned_caption_hash?: string;
	captionOutcomeContext: unknown;
	visual_verification_id: string;
	caption_verification_id: string;
	audio_id: string;
	distribution_plan_id: string;
	exported_by_system: "campaign_factory";
	exported_at: string;
	concept_id?: string;
	parent_asset_id?: string;
	parent_reel_id?: string;
	variant_family_id?: string;
	variant_id?: string;
	variant_index?: number;
	variant_operations?: unknown;
};

export const audioIntentSchema = {
	$schema: "https://json-schema.org/draft/2020-12/schema",
	$id: AUDIO_INTENT_SCHEMA_ID,
	title: "Pipeline Audio Intent",
	type: "object",
	required: ["schema", "mode", "required", "status", "platform", "recommendations", "gates"],
	properties: {
		schema: { const: AUDIO_INTENT_SCHEMA_ID },
		mode: { type: "string" },
		required: { type: "boolean" },
		status: {
			type: "string",
			enum: [
				"not_required",
				"recommended",
				"needs_operator_selection",
				"selected",
				"attached",
				"verified",
				"skipped",
				"blocked",
				"needs_review",
				"burned",
			],
		},
		platform: { type: "string" },
		recommendations: { type: "array" },
		decision: { type: ["object", "null"] },
		gates: {
			type: "object",
			required: ["allow_draft_export", "allow_publish"],
			properties: {
				allow_draft_export: { type: "boolean" },
				allow_publish: { type: "boolean" },
			},
		},
	},
} as const;

export const campaignDraftPayloadSchema = {
	$schema: "https://json-schema.org/draft/2020-12/schema",
	$id: CAMPAIGN_DRAFT_PAYLOAD_SCHEMA_ID,
	title: "Campaign Factory ThreadsDashboard Draft Payload",
	type: "object",
	required: ["schema", "campaign", "drafts"],
	properties: {
		schema: { const: CAMPAIGN_DRAFT_PAYLOAD_SCHEMA_ID },
		campaign: { type: "string" },
		drafts: { type: "array" },
	},
} as const;

export const repurposingPlanSchema = {
	$schema: "https://json-schema.org/draft/2020-12/schema",
	$id: REPURPOSING_PLAN_SCHEMA_ID,
	type: "object",
	additionalProperties: false,
	required: ["schema", "master_asset_id", "preset_name", "target_count", "platform"],
	properties: {
		schema: { const: REPURPOSING_PLAN_SCHEMA_ID },
		master_asset_id: { type: "string", pattern: "^[A-Za-z0-9._:-]+$" },
		preset_name: { type: "string", enum: ["tiktok_aggressive", "ig_subtle", "custom"] },
		target_count: { type: "integer", minimum: 1, maximum: 500 },
		platform: { type: "string" },
		custom_config: { type: "object" },
	},
} as const;

export const variantAssignmentSchema = {
	$schema: "https://json-schema.org/draft/2020-12/schema",
	$id: VARIANT_ASSIGNMENT_SCHEMA_ID,
	title: "Campaign Factory Variant Assignment",
	type: "object",
	additionalProperties: false,
	required: [
		"schema",
		"campaign_slug",
		"master_asset_id",
		"master_asset_path",
		"platform",
		"generated_at",
		"assignments",
	],
	properties: {
		schema: { const: VARIANT_ASSIGNMENT_SCHEMA_ID },
		campaign_slug: { type: "string", minLength: 1 },
		master_asset_id: { type: "string", pattern: "^[A-Za-z0-9._:-]+$" },
		master_asset_path: { type: "string", minLength: 1 },
		platform: { type: "string", minLength: 1 },
		generated_at: { type: "string", minLength: 1 },
		variation_enabled: { type: "boolean" },
		assignments: {
			type: "array",
			minItems: 1,
			items: {
				type: "object",
				additionalProperties: false,
				required: [
					"account_id",
					"variant_asset_id",
					"variant_path",
					"parent_master_asset_id",
					"preset_name",
					"distinctness_scores",
				],
				properties: {
					account_id: { type: "string", minLength: 1 },
					instagram_account_id: { type: ["string", "null"] },
					persona: { type: ["string", "null"] },
					variant_asset_id: { type: "string", pattern: "^[A-Za-z0-9._:-]+$" },
					variant_path: { type: "string", minLength: 1 },
					parent_master_asset_id: { type: "string", pattern: "^[A-Za-z0-9._:-]+$" },
					preset_name: { type: "string", minLength: 1 },
					distinctness_scores: {
						type: "object",
						additionalProperties: false,
						required: ["master_ssim", "sibling_max_ssim", "threshold"],
						properties: {
							master_ssim: { type: "number", minimum: 0, maximum: 1 },
							sibling_max_ssim: { type: "number", minimum: 0, maximum: 1 },
							threshold: { type: "number", minimum: 0, maximum: 1 },
						},
					},
					lineage: { type: "object" },
				},
			},
		},
	},
} as const;

export const motionEditRenderSchema = {
	$schema: "https://json-schema.org/draft/2020-12/schema",
	$id: MOTION_EDIT_RENDER_SCHEMA_ID,
	title: "Reel Factory Motion Edit Render",
	type: "object",
	additionalProperties: false,
	required: [
		"schema",
		"animationMode",
		"paidGeneration",
		"estimatedCostUsd",
		"stillPath",
		"outputPath",
		"durationSeconds",
		"caption",
		"audioIntentPath",
		"lineagePath",
		"quality",
		"ffmpegCommand",
	],
	properties: {
		schema: { const: MOTION_EDIT_RENDER_SCHEMA_ID },
		animationMode: { const: "motion_edit" },
		paidGeneration: { const: false },
		estimatedCostUsd: { const: 0 },
		stillPath: { type: "string", minLength: 1 },
		outputPath: { type: "string", minLength: 1 },
		durationSeconds: { type: "number", exclusiveMinimum: 0, maximum: 60 },
		caption: { type: "string" },
		audioIntentPath: { type: "string", minLength: 1 },
		lineagePath: { type: "string", minLength: 1 },
		quality: {
			type: "object",
			additionalProperties: false,
			required: ["status", "width", "height", "fps", "durationSeconds"],
			properties: {
				status: { type: "string", enum: ["planned", "passed", "failed"] },
				width: { type: "integer", minimum: 1 },
				height: { type: "integer", minimum: 1 },
				fps: { type: "number", exclusiveMinimum: 0 },
				durationSeconds: { type: "number", exclusiveMinimum: 0 },
				warnings: { type: "array", items: { type: "string" } },
			},
		},
		ffmpegCommand: { type: "array", items: { type: "string" } },
		dryRun: { type: "boolean" },
	},
} as const;

export const frontGenerationPlanSchema = {
	$schema: "https://json-schema.org/draft/2020-12/schema",
	$id: FRONT_GENERATION_PLAN_SCHEMA_ID,
	title: "Campaign Factory Front Generation Plan",
	type: "object",
	additionalProperties: false,
	required: [
		"schema",
		"campaign",
		"referenceImagePath",
		"soul",
		"animationMode",
		"dryRun",
		"paidGenerationEnabled",
		"projectedCostUsd",
		"budgetCapUsd",
		"budgetStatus",
		"humanReviewRequired",
		"publishingAllowed",
		"stages",
	],
	properties: {
		schema: { const: FRONT_GENERATION_PLAN_SCHEMA_ID },
		campaign: { type: "string", minLength: 1 },
		referenceImagePath: { type: "string", minLength: 1 },
		soul: {
			type: "object",
			additionalProperties: false,
			required: ["creator", "soulId", "soulName"],
			properties: {
				creator: { type: ["string", "null"] },
				soulId: { type: ["string", "null"] },
				soulName: { type: ["string", "null"] },
			},
		},
		animationMode: { type: "string", enum: ["kling", "motion_edit"] },
		dryRun: { type: "boolean" },
		paidGenerationEnabled: { type: "boolean" },
		projectedCostUsd: { type: "number", minimum: 0 },
		budgetCapUsd: { type: ["number", "null"], minimum: 0 },
		budgetStatus: {
			type: "string",
			enum: ["within_cap", "missing_cap", "exceeds_cap", "not_required"],
		},
		humanReviewRequired: { const: true },
		publishingAllowed: { const: false },
		stages: {
			type: "array",
			minItems: 1,
			items: {
				type: "object",
				additionalProperties: false,
				required: ["name", "status", "paid", "estimatedCostUsd", "commands"],
				properties: {
					name: {
						type: "string",
						enum: ["soul_reference_image", "still_accept_gate", "kling_video", "motion_edit", "variation"],
					},
					status: {
						type: "string",
						enum: ["planned", "blocked", "skipped", "submitted", "waiting_for_review"],
					},
					paid: { type: "boolean" },
					estimatedCostUsd: { type: "number", minimum: 0 },
					commands: {
						type: "array",
						items: { type: "array", items: { type: "string" } },
					},
					result: { type: "object" },
					reason: { type: "string" },
				},
			},
		},
	},
} as const;

export const audioCatalogExportSchema = {
	$schema: "https://json-schema.org/draft/2020-12/schema",
	$id: AUDIO_CATALOG_EXPORT_SCHEMA_ID,
	title: "Reference Factory Audio Catalog Export",
	type: "object",
	required: ["schema", "items"],
	properties: {
		schema: { const: AUDIO_CATALOG_EXPORT_SCHEMA_ID },
		items: { type: "array" },
	},
} as const;

export const performanceSyncSchema = {
	$schema: "https://json-schema.org/draft/2020-12/schema",
	$id: PERFORMANCE_SYNC_SCHEMA_ID,
	title: "Campaign Factory Performance Sync",
	type: "object",
	required: ["schema", "campaign", "userId", "pipelineJobId", "pipelineTraceId", "summary"],
	properties: {
		schema: { const: PERFORMANCE_SYNC_SCHEMA_ID },
		campaign: { type: "string" },
		userId: { type: "string" },
		pipelineJobId: { type: "string", minLength: 1 },
		pipelineTraceId: { type: "string", minLength: 1 },
		summary: { type: "object" },
	},
} as const;

export const postMetricHistoryReadSchema = {
	$schema: "https://json-schema.org/draft/2020-12/schema",
	$id: POST_METRIC_HISTORY_READ_SCHEMA_ID,
	title: "ThreadsDashboard Post Metric History Read",
	type: "object",
	required: ["schema", "rows"],
	properties: {
		schema: { const: POST_METRIC_HISTORY_READ_SCHEMA_ID },
		rows: {
			type: "array",
			items: {
				type: "object",
				required: [
					"id",
					"post_id",
					"account_id",
					"platform",
					"snapshot_at",
					"hours_since_publish",
					"views_count",
					"likes_count",
					"replies_count",
					"reposts_count",
					"quotes_count",
					"shares_count",
					"saves_count",
					"reach",
					"engagement_rate",
					"created_at",
				],
			},
		},
	},
} as const;

export const captionOutcomeContextSchema = {
	$schema: "https://json-schema.org/draft/2020-12/schema",
	$id: CAPTION_OUTCOME_CONTEXT_SCHEMA_ID,
	title: "Campaign Factory Caption Outcome Context",
	type: "object",
	required: ["schema"],
	properties: {
		schema: { const: CAPTION_OUTCOME_CONTEXT_SCHEMA_ID },
		caption_hash: { type: ["string", "null"] },
		caption_text: { type: ["string", "null"] },
		caption_bank: { type: ["string", "null"] },
		caption_banks: { type: ["array", "null"] },
		creator_mix: { type: ["string", "null"] },
		creator_model: { type: ["string", "null"] },
		frame_type: { type: ["string", "null"] },
		length_class: { type: ["string", "null"] },
		format_class: { type: ["string", "null"] },
		caption_fit_version: { type: ["string", "null"] },
		suitability_decision: { type: ["string", "null"] },
		suitability_reason: { type: ["string", "null"] },
		captionSceneTags: { type: ["array", "null"] },
		reelSceneTags: { type: ["array", "null"] },
		sceneCompatibilityDecision: { type: ["string", "null"] },
		sceneCompatibilityReason: { type: ["string", "null"] },
		captionSceneFitVersion: { type: ["string", "null"] },
		render_recipe: { type: ["string", "null"] },
		source_clip: { type: ["string", "null"] },
		rendered_output: { type: ["string", "null"] },
	},
} as const;

export const pipelineContractSchemas = {
	audioIntent: audioIntentSchema,
	campaignDraftPayload: campaignDraftPayloadSchema,
	audioCatalogExport: audioCatalogExportSchema,
	performanceSync: performanceSyncSchema,
	captionOutcomeContext: captionOutcomeContextSchema,
	variantAssignment: variantAssignmentSchema,
	motionEditRender: motionEditRenderSchema,
	frontGenerationPlan: frontGenerationPlanSchema,
	patternCard: {
		$id: PATTERN_CARD_SCHEMA_ID,
		type: "object",
		required: ["schema", "referenceId", "source", "visualFormat", "hookType", "captionArchetype"],
		properties: {
			schema: { const: PATTERN_CARD_SCHEMA_ID },
			referenceId: { type: "string" },
			source: { type: "object" },
			visualFormat: { type: "string" },
			hookType: { type: "string" },
			captionArchetype: { type: "string" },
			reviewTags: { type: "array" },
			promptPattern: { type: "object" },
			referenceUse: { type: "object" },
			qualityScore: { type: "number" },
			suggestedLabel: { type: "string" },
		},
	},
	videoAnalysis: {
		$id: VIDEO_ANALYSIS_SCHEMA_ID,
		type: "object",
		required: ["schema", "referenceId", "provider", "model", "analysis"],
		properties: {
			schema: { const: VIDEO_ANALYSIS_SCHEMA_ID },
			referenceId: { type: "string" },
			provider: { type: "string" },
			model: { type: "string" },
			analysis: { type: "object" },
			raw: { type: ["string", "null"] },
		},
	},
	higgsfieldSoulImagePrompt: {
		$id: HIGGSFIELD_SOUL_IMAGE_PROMPT_SCHEMA_ID,
		type: "object",
		required: ["schema", "tool", "status", "sourceReferenceId", "sourcePatternId", "modelProfile", "higgsfieldGridPrompt"],
		properties: {
			schema: { const: HIGGSFIELD_SOUL_IMAGE_PROMPT_SCHEMA_ID },
			tool: { const: "higgsfield_soul_id" },
			status: { type: "string" },
			sourceReferenceId: { type: "string" },
			sourcePatternId: { type: "string" },
			modelProfile: { type: ["string", "null"] },
			higgsfieldGridPrompt: { type: "string" },
			closenessControls: { type: "object" },
			formatCard: { type: "object" },
			aspectRatio: { type: "string" },
			reviewNotes: { type: "array" },
		},
	},
	kling3VideoPrompt: {
		$id: KLING_3_VIDEO_PROMPT_SCHEMA_ID,
		type: "object",
		required: ["schema", "tool", "status", "sourceReferenceId", "sourcePatternId", "modelProfile", "firstFrameInstruction", "mainPrompt", "negativePrompt", "closenessControls"],
		properties: {
			schema: { const: KLING_3_VIDEO_PROMPT_SCHEMA_ID },
			tool: { const: "kling_3_video" },
			status: { type: "string" },
			sourceReferenceId: { type: "string" },
			sourcePatternId: { type: "string" },
			modelProfile: { type: ["string", "null"] },
			firstFrameInstruction: { type: "string" },
			mainPrompt: { type: "string" },
			negativePrompt: { type: "string" },
			closenessControls: { type: "object" },
			scenes: { type: "array" },
			aspectRatio: { type: "string" },
			reviewNotes: { type: "array" },
		},
	},
	generatedAssetLineage: {
		$id: GENERATED_ASSET_LINEAGE_SCHEMA_ID,
		type: "object",
		required: ["schema", "pipelineTraceId", "source", "generation", "review"],
		properties: {
			schema: { const: GENERATED_ASSET_LINEAGE_SCHEMA_ID },
			pipelineTraceId: { type: "string", minLength: 1 },
			source: { type: "object" },
			generation: { type: "object" },
			review: { type: "object" },
			quality: { type: "object" },
			asset_state: { type: "string", enum: ["approved_but_not_publishable", "publishable_candidate", "exportable", "invalid_retired_draft"] },
			publishability_failure_reasons: { type: "array" },
			blockingReason: { type: ["string", "null"] },
			rootCause: { type: ["string", "null"] },
		},
	},
	creativePlan: {
		$id: CREATIVE_PLAN_SCHEMA_ID,
		type: "object",
		required: ["schema", "id", "name", "platform", "goal", "target_account", "daily_base_video_target", "style_lanes", "model_profile", "source_accounts", "status", "counts", "next_actions"],
		properties: {
			schema: { const: CREATIVE_PLAN_SCHEMA_ID },
			id: { type: "string" },
			name: { type: "string" },
			platform: { type: "string" },
			goal: { type: "string" },
			target_account: { type: "string" },
			daily_base_video_target: { type: "integer" },
			style_lanes: { type: "array", items: { type: "string" } },
			model_profile: { type: "string" },
			source_accounts: { type: "array", items: { type: "string" } },
			status: { type: "string", enum: ["planned", "references_selected", "prompts_ready", "generated", "ingested", "rendered", "audited", "reviewed", "exported", "posted", "measured"] },
			counts: { type: "object" },
			next_actions: { type: "array", items: { type: "string" } },
			linked_campaign: { type: ["string", "null"] },
			created_at: { type: ["string", "null"] },
			updated_at: { type: ["string", "null"] },
		},
	},
	recommendationAccuracyReport: {
		$id: RECOMMENDATION_ACCURACY_REPORT_SCHEMA_ID,
		type: "object",
		required: [
			"schema",
			"campaign",
			"campaignGraphId",
			"reportId",
			"reportGraphId",
			"windowDays",
			"generatedAt",
			"recommendationTrustScore",
			"trustConfidence",
			"overall",
			"calibration",
			"segments",
			"drift",
		],
		properties: {
			schema: { const: RECOMMENDATION_ACCURACY_REPORT_SCHEMA_ID },
			campaign: { type: "string" },
			campaignGraphId: { type: "string", minLength: 1 },
			reportId: { type: "string", minLength: 1 },
			reportGraphId: { type: "string", minLength: 1 },
			account: { type: ["string", "null"] },
			windowDays: { type: "integer" },
			generatedAt: { type: "string" },
			recommendationTrustScore: { type: "integer" },
			trustConfidence: { type: "string", enum: ["insufficient", "directional", "usable", "strong"] },
			overall: { type: "object" },
			calibration: { type: "array" },
			segments: { type: "object" },
			drift: { type: "array" },
			observations: { type: "array" },
			warnings: { type: "array" },
		},
	},
	recommendationNextBatch: {
		$id: RECOMMENDATION_NEXT_BATCH_SCHEMA_ID,
		type: "object",
		required: ["schema", "campaign", "campaignGraphId", "persisted", "scoringVersion", "generatedAt", "count", "requestedCount", "inputHash", "items"],
		properties: {
			schema: { const: RECOMMENDATION_NEXT_BATCH_SCHEMA_ID },
			campaign: { type: "string" },
			campaignGraphId: { type: ["string", "null"] },
			runId: { type: ["string", "null"] },
			persisted: { type: "boolean" },
			scoringVersion: { type: "string" },
			generatedAt: { type: "string" },
			count: { type: "integer" },
			requestedCount: { type: "integer" },
			account: { type: ["string", "null"] },
			inputHash: { type: "string" },
			warnings: { type: "array", items: { type: "string" } },
			items: { type: "array" },
		},
	},
} as const;

const AUDIO_INTENT_STATUSES = new Set([
	"not_required",
	"recommended",
	"needs_operator_selection",
	"selected",
	"attached",
	"verified",
	"skipped",
	"blocked",
	"needs_review",
	"burned",
]);

const SAFE_NATIVE_AUDIO_STATUSES = new Set([
	"attached",
	"verified",
	"skipped",
	"not_required",
]);

const ASSIGNED_NATIVE_AUDIO_STATUSES = new Set([
	"selected",
	"attached",
	"verified",
	"skipped",
	"not_required",
]);

const EXPORTABLE_ASSET_STATE_SET = new Set<string>(EXPORTABLE_ASSET_STATES);
const ajv = new Ajv2020({ allErrors: true, strict: false });
for (const schema of Object.values(generatedPipelineContractSchemas)) {
	ajv.addSchema(schema, schema.$id);
}
for (const entry of generatedPipelineContractSchemaManifest) {
	const schema =
		generatedPipelineContractSchemas[entry.key as keyof typeof generatedPipelineContractSchemas];
	ajv.addSchema(schema, entry.filename);
}
const ajvCache = new WeakMap<object, ValidateFunction>();

function schemaErrors(schema: object, value: unknown, label: string): string[] {
	let validate = ajvCache.get(schema);
	if (!validate) {
		validate = ajv.compile(schema);
		ajvCache.set(schema, validate);
	}
	if (validate(value)) return [];
	return (validate.errors || []).map((error) => formatAjvError(error, label));
}

function formatAjvError(error: ErrorObject, label: string): string {
	const path = ajvPath(error.instancePath, label);
	if (error.keyword === "additionalProperties") {
		const property = String(error.params.additionalProperty || "");
		return `${path}.${property} is not allowed`;
	}
	return `${path} ${error.message || "is invalid"}`;
}

function ajvPath(instancePath: string, label: string): string {
	if (!instancePath) return label;
	return `${label}${instancePath
		.split("/")
		.slice(1)
		.map((part) => {
			const decoded = part.replace(/~1/g, "/").replace(/~0/g, "~");
			return /^\d+$/.test(decoded) ? `[${decoded}]` : `.${decoded}`;
		})
		.join("")}`;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
	return !!value && typeof value === "object" && !Array.isArray(value);
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

function boolValue(...values: unknown[]): boolean | undefined {
	for (const value of values) {
		if (typeof value === "boolean") return value;
	}
	return undefined;
}

function normalizedPass(value: unknown): boolean {
	return String(value || "").trim().toLowerCase() === "pass";
}

function captionOutcomeContextFor(
	campaignFactory: Record<string, unknown>,
): Record<string, unknown> | null {
	const lineage = isRecord(campaignFactory.generated_asset_lineage)
		? campaignFactory.generated_asset_lineage
		: null;
	return (
		(isRecord(campaignFactory.captionOutcomeContext)
			? campaignFactory.captionOutcomeContext
			: null) ||
		(isRecord(campaignFactory.caption_outcome_context)
			? campaignFactory.caption_outcome_context
			: null) ||
		(lineage && isRecord(lineage.captionOutcomeContext)
			? lineage.captionOutcomeContext
			: null)
	);
}

function handoffManifestFor(
	campaignFactory: Record<string, unknown>,
): Record<string, unknown> | null {
	return isRecord(campaignFactory.handoff_manifest)
		? campaignFactory.handoff_manifest
		: isRecord(campaignFactory.handoffManifest)
			? campaignFactory.handoffManifest
			: null;
}

function normalizeContentSurface(value: unknown): string | undefined {
	const raw = String(value || "").trim().toLowerCase().replace(/-/g, "_");
	if (!raw) return undefined;
	if (raw === "reel" || raw === "reels" || raw === "regular_reel") return "reel";
	if (raw === "story" || raw === "stories") return "story";
	if (raw === "feed_single" || raw === "image" || raw === "feed_image") return "feed_single";
	if (raw === "feed_carousel" || raw === "carousel" || raw === "carousel_album") return "feed_carousel";
	return raw;
}

function contentSurfaceForDraft(
	draft: Record<string, unknown>,
	campaignFactory: Record<string, unknown>,
	manifest: Record<string, unknown> | null,
): string | undefined {
	return normalizeContentSurface(
		firstStringValue(
			draft.content_surface,
			draft.contentSurface,
			campaignFactory.content_surface,
			campaignFactory.contentSurface,
			manifest?.content_surface,
			manifest?.contentSurface,
		),
	);
}

function explicitInstagramPostCaptionFor(
	campaignFactory: Record<string, unknown>,
	manifest: Record<string, unknown> | null,
): string | undefined {
	return firstStringValue(
		campaignFactory.instagram_post_caption,
		campaignFactory.instagramPostCaption,
		manifest?.instagram_post_caption,
		manifest?.instagramPostCaption,
	);
}

function statusValue(...values: unknown[]): string | undefined {
	const value = firstStringValue(...values);
	return value ? value.trim().toLowerCase() : undefined;
}

function visualQcStatusFor(
	campaignFactory: Record<string, unknown>,
	manifest: Record<string, unknown> | null,
): string | undefined {
	const quality = qualityFor(campaignFactory);
	const visualQc = isRecord(campaignFactory.visualQc)
		? campaignFactory.visualQc
		: isRecord(campaignFactory.visual_qc)
			? campaignFactory.visual_qc
			: isRecord(manifest?.visualQc)
				? manifest?.visualQc
				: isRecord(manifest?.visual_qc)
					? manifest?.visual_qc
					: {};
	return statusValue(
		campaignFactory.visualQcStatus,
		campaignFactory.visual_qc_status,
		manifest?.visualQcStatus,
		manifest?.visual_qc_status,
		quality.visualQcStatus,
		quality.visual_qc_status,
		visualQc.visualQcStatus,
		visualQc.visual_qc_status,
		visualQc.status,
	);
}

function identityVerificationStatusFor(
	campaignFactory: Record<string, unknown>,
	manifest: Record<string, unknown> | null,
): string | undefined {
	const identity = isRecord(campaignFactory.identityVerification)
		? campaignFactory.identityVerification
		: isRecord(campaignFactory.identity_verification)
			? campaignFactory.identity_verification
			: isRecord(manifest?.identityVerification)
				? manifest?.identityVerification
				: isRecord(manifest?.identity_verification)
					? manifest?.identity_verification
					: {};
	return statusValue(
		campaignFactory.identityVerificationStatus,
		campaignFactory.identity_verification_status,
		manifest?.identityVerificationStatus,
		manifest?.identity_verification_status,
		identity.identityVerificationStatus,
		identity.identity_verification_status,
		identity.status,
	);
}

function qualityFor(campaignFactory: Record<string, unknown>): Record<string, unknown> {
	const lineage = isRecord(campaignFactory.generated_asset_lineage)
		? campaignFactory.generated_asset_lineage
		: {};
	return isRecord(lineage.quality) ? lineage.quality : {};
}

function isQuarantined(campaignFactory: Record<string, unknown>): boolean {
	const quarantine = isRecord(campaignFactory.quarantine)
		? campaignFactory.quarantine
		: {};
	return (
		campaignFactory.quarantined === true ||
		quarantine.active === true ||
		String(campaignFactory.asset_state || "").trim().toLowerCase() ===
			"invalid_retired_draft"
	);
}

function audioIntentHasAssignedAudio(audioIntent: unknown): boolean {
	if (!isRecord(audioIntent)) return false;
	const required = audioIntent.required === true;
	const status = String(audioIntent.status || "").trim().toLowerCase();
	if (!required || status === "not_required" || status === "skipped") return true;
	if (!ASSIGNED_NATIVE_AUDIO_STATUSES.has(status)) return false;
	const selection = isRecord(audioIntent.operator_selection)
		? audioIntent.operator_selection
		: {};
	const decision = isRecord(audioIntent.decision) ? audioIntent.decision : {};
	const primaryAudio = isRecord(decision.primaryAudio)
		? decision.primaryAudio
		: isRecord(decision.primary_audio)
			? decision.primary_audio
			: {};
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

export function campaignFactoryPublishabilityFailureReasons(
	campaignFactory: Record<string, unknown>,
): string[] {
	return explainCampaignFactoryPublishability(campaignFactory).reasons;
}

export function explainCampaignFactoryPublishability(
	campaignFactory: Record<string, unknown>,
): PublishabilityDecision {
	const lineage = isRecord(campaignFactory.generated_asset_lineage)
		? campaignFactory.generated_asset_lineage
		: {};
	const review = isRecord(lineage.review) ? lineage.review : {};
	const quality = qualityFor(campaignFactory);
	const captionContext = captionOutcomeContextFor(campaignFactory);
	const approved =
		boolValue(campaignFactory.approved, review.approved) === true ||
		String(review.status || campaignFactory.review_status || "").trim().toLowerCase() ===
			"approved";
	const captionedRenderPresent =
		boolValue(
			campaignFactory.captioned_render_present,
			campaignFactory.captionedRenderPresent,
			quality.captioned_render_present,
			quality.captionedRenderPresent,
		) === true;
	const visibleCaptionVerification = firstStringValue(
		campaignFactory.visible_caption_verification,
		campaignFactory.visibleCaptionVerification,
		quality.visible_caption_verification,
		quality.visibleCaptionVerification,
	);
	const expectedVisualVerification = firstStringValue(
		campaignFactory.expected_visual_verification,
		campaignFactory.expectedVisualVerification,
		quality.expected_visual_verification,
		quality.expectedVisualVerification,
	);
	const captionHash = firstStringValue(
		campaignFactory.caption_hash,
		campaignFactory.captionHash,
		captionContext?.caption_hash,
		captionContext?.captionHash,
	);
	const contentFingerprint = firstStringValue(
		campaignFactory.content_fingerprint,
		campaignFactory.contentFingerprint,
		quality.content_fingerprint,
		quality.contentFingerprint,
	);
	const readinessChecksPass =
		boolValue(
			campaignFactory.readiness_checks_pass,
			campaignFactory.readinessChecksPass,
			quality.readiness_checks_pass,
			quality.readinessChecksPass,
		) === true;
	const checks = {
		creative_approved: approved,
		captioned_render_present: captionedRenderPresent,
		visible_caption_verification: normalizedPass(visibleCaptionVerification),
		expected_visual_verification: normalizedPass(expectedVisualVerification),
		content_fingerprint_present: Boolean(contentFingerprint),
		caption_hash_present: Boolean(captionHash),
		captionOutcomeContext_present: Boolean(captionContext),
		audio_assigned: audioIntentHasAssignedAudio(campaignFactory.audio_intent),
		readiness_checks_pass: readinessChecksPass,
		quarantine_clear: !isQuarantined(campaignFactory),
	};
	const failures: string[] = [];
	if (!checks.creative_approved) failures.push("not_approved");
	if (!checks.captioned_render_present || !checks.visible_caption_verification) {
		failures.push("missing_burned_captions");
	}
	if (!checks.expected_visual_verification) failures.push("wrong_visual");
	if (!checks.caption_hash_present) failures.push("missing_caption_hash");
	if (!checks.captionOutcomeContext_present) failures.push("missing_caption_outcome_context");
	if (!checks.content_fingerprint_present) failures.push("missing_content_fingerprint");
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

export function campaignFactoryAssetStateAllowsExport(state: unknown): boolean {
	return EXPORTABLE_ASSET_STATE_SET.has(String(state || "").trim().toLowerCase());
}

export function validateHandoffManifestContract(
	campaignFactory: Record<string, unknown>,
): string[] {
	const errors: string[] = [];
	const manifest = handoffManifestFor(campaignFactory);
	if (!manifest) return ["handoff_manifest is required"];
	if (manifest.manifest_version !== 1 && manifest.manifest_version !== 2) {
		errors.push("handoff_manifest.manifest_version must be 1 or 2");
	}
	if (manifest.exported_by_system !== "campaign_factory") {
		errors.push("handoff_manifest.exported_by_system must be campaign_factory");
	}
	for (const field of [
		"asset_id",
		"render_file_id",
		"content_fingerprint",
		"caption_hash",
		"visual_verification_id",
		"caption_verification_id",
		"audio_id",
		"distribution_plan_id",
		"exported_at",
	] as const) {
		if (!stringValue(manifest[field])) {
			errors.push(`handoff_manifest.${field} is required`);
		}
	}
	if (!isRecord(manifest.captionOutcomeContext)) {
		errors.push("handoff_manifest.captionOutcomeContext must be an object");
	}
	if (manifest.manifest_version === 2) {
		const contentSurface = firstStringValue(
			manifest.content_surface,
			manifest.contentSurface,
			campaignFactory.content_surface,
			campaignFactory.contentSurface,
		);
		const igMediaType = firstStringValue(
			manifest.ig_media_type,
			manifest.igMediaType,
			campaignFactory.ig_media_type,
			campaignFactory.igMediaType,
		);
		if (!contentSurface) {
			errors.push("handoff_manifest.content_surface is required for v2");
		}
		if (!igMediaType) {
			errors.push("handoff_manifest.ig_media_type is required for v2");
		}
		const mediaItems = manifest.mediaItems || manifest.media_items;
		if (!Array.isArray(mediaItems) || mediaItems.length === 0) {
			errors.push("handoff_manifest.mediaItems is required for v2");
		} else {
			for (const [index, item] of mediaItems.entries()) {
				if (!isRecord(item)) {
					errors.push(`handoff_manifest.mediaItems[${index}] must be an object`);
					continue;
				}
				if (!firstStringValue(item.url, item.mediaUrl, item.media_url)) {
					errors.push(`handoff_manifest.mediaItems[${index}].url is required`);
				}
			}
		}
		if (contentSurface === "feed_single" && igMediaType !== "IMAGE") {
			errors.push("handoff_manifest.feed_single requires ig_media_type IMAGE");
		}
	}
	const captionContext = captionOutcomeContextFor(campaignFactory);
	const quality = qualityFor(campaignFactory);
	const expectedAssetId = firstStringValue(
		campaignFactory.asset_id,
		campaignFactory.rendered_asset_id,
		campaignFactory.source_asset_id,
	);
	if (
		expectedAssetId &&
		stringValue(manifest.asset_id) &&
		manifest.asset_id !== expectedAssetId
	) {
		errors.push("handoff_manifest.asset_id mismatch");
	}
	const expectedFingerprint = firstStringValue(
		campaignFactory.content_fingerprint,
		campaignFactory.contentFingerprint,
		quality.content_fingerprint,
		quality.contentFingerprint,
	);
	if (
		expectedFingerprint &&
		stringValue(manifest.content_fingerprint) &&
		manifest.content_fingerprint !== expectedFingerprint
	) {
		errors.push("handoff_manifest.content_fingerprint mismatch");
	}
	const expectedCaptionHash = firstStringValue(
		campaignFactory.caption_hash,
		campaignFactory.captionHash,
		captionContext?.caption_hash,
		captionContext?.captionHash,
	);
	if (
		expectedCaptionHash &&
		stringValue(manifest.caption_hash) &&
		manifest.caption_hash !== expectedCaptionHash
	) {
		errors.push("handoff_manifest.caption_hash mismatch");
	}
	const expectedInstagramPostCaptionHash = firstStringValue(
		campaignFactory.instagram_post_caption_hash,
		campaignFactory.instagramPostCaptionHash,
	);
	if (
		expectedInstagramPostCaptionHash &&
		stringValue(manifest.instagram_post_caption_hash) &&
		manifest.instagram_post_caption_hash !== expectedInstagramPostCaptionHash
	) {
		errors.push("handoff_manifest.instagram_post_caption_hash mismatch");
	}
	if (
		isRecord(manifest.captionOutcomeContext) &&
		expectedCaptionHash &&
		stringValue(manifest.captionOutcomeContext.caption_hash) &&
		manifest.captionOutcomeContext.caption_hash !== expectedCaptionHash
	) {
		errors.push("handoff_manifest.captionOutcomeContext.caption_hash mismatch");
	}
	for (const [manifestField, ...metadataFields] of [
		["concept_id", "concept_id", "conceptId"],
		["parent_asset_id", "parent_asset_id", "parentAssetId"],
		["parent_reel_id", "parent_reel_id", "parentReelId"],
		["variant_family_id", "variant_family_id", "variantFamilyId"],
		["variant_id", "variant_id", "variantId"],
	] as const) {
		const expected = firstStringValue(...metadataFields.map((field) => campaignFactory[field]));
		const actual = stringValue(manifest[manifestField]);
		if (expected && actual && actual !== expected) {
			errors.push(`handoff_manifest.${manifestField} mismatch`);
		}
	}
	if (isQuarantined(campaignFactory)) {
		errors.push("handoff_manifest asset is quarantined");
	}
	const visualQcStatus = visualQcStatusFor(campaignFactory, manifest);
	if (visualQcStatus !== "passed") {
		errors.push("handoff_manifest.visualQcStatus must be passed");
	}
	const identityVerificationStatus = identityVerificationStatusFor(campaignFactory, manifest);
	if (identityVerificationStatus !== "passed") {
		errors.push("handoff_manifest.identityVerificationStatus must be passed");
	}
	return errors;
}

export function validateAudioIntentContract(value: unknown): string[] {
	const errors = schemaErrors(generatedPipelineContractSchemas.audioIntent, value, "audio_intent");
	if (!isRecord(value)) return ["audio_intent must be an object"];
	if (value.schema !== AUDIO_INTENT_SCHEMA_ID) {
		errors.push("audio_intent.schema must be pipeline.audio_intent.v1");
	}
	if (typeof value.mode !== "string") {
		errors.push("audio_intent.mode must be string");
	}
	if (typeof value.required !== "boolean") {
		errors.push("audio_intent.required must be boolean");
	}
	if (typeof value.status !== "string" || !AUDIO_INTENT_STATUSES.has(value.status)) {
		errors.push("audio_intent.status must be a known status");
	}
	if (typeof value.platform !== "string") {
		errors.push("audio_intent.platform must be string");
	}
	if (!Array.isArray(value.recommendations)) {
		errors.push("audio_intent.recommendations must be an array");
	}
	const gates = value.gates;
	if (!isRecord(gates)) {
		errors.push("audio_intent.gates must be an object");
	} else {
		if (typeof gates.allow_draft_export !== "boolean") {
			errors.push("audio_intent.gates.allow_draft_export must be boolean");
		}
		if (typeof gates.allow_publish !== "boolean") {
			errors.push("audio_intent.gates.allow_publish must be boolean");
		}
	}
	return errors;
}

export function validateCaptionOutcomeContextContract(value: unknown): string[] {
	const errors = schemaErrors(generatedPipelineContractSchemas.captionOutcomeContext, value, "captionOutcomeContext");
	if (!isRecord(value)) return ["captionOutcomeContext must be an object"];
	if (value.schema !== CAPTION_OUTCOME_CONTEXT_SCHEMA_ID) {
		errors.push("captionOutcomeContext.schema must be campaign_factory.caption_outcome_context.v1");
	}
	for (const field of [
		"caption_hash",
		"caption_text",
		"caption_bank",
		"creator_mix",
		"creator_model",
		"frame_type",
		"length_class",
		"format_class",
		"caption_fit_version",
		"suitability_decision",
		"suitability_reason",
		"sceneCompatibilityDecision",
		"sceneCompatibilityReason",
		"captionSceneFitVersion",
		"render_recipe",
		"source_clip",
		"rendered_output",
	] as const) {
		const candidate = value[field];
		if (candidate !== undefined && candidate !== null && typeof candidate !== "string") {
			errors.push(`captionOutcomeContext.${field} must be string or null`);
		}
	}
	if (
		value.caption_banks !== undefined &&
		value.caption_banks !== null &&
		!Array.isArray(value.caption_banks)
	) {
		errors.push("captionOutcomeContext.caption_banks must be array or null");
	}
	for (const field of ["captionSceneTags", "reelSceneTags"] as const) {
		const candidate = value[field];
		if (candidate !== undefined && candidate !== null && !Array.isArray(candidate)) {
			errors.push(`captionOutcomeContext.${field} must be array or null`);
		}
	}
	return errors;
}

const STRICT_GRAPH_FIELDS = [
	"graph_id",
	"campaign_graph_id",
	"source_asset_graph_id",
	"rendered_asset_graph_id",
	"audit_graph_id",
] as const;

export function validateCampaignFactoryDraftPayload(
	value: unknown,
	options: { strictGraphIds?: boolean } = {},
): string[] {
	const errors = schemaErrors(generatedPipelineContractSchemas.campaignDraftPayload, value, "draft payload");
	if (!isRecord(value)) return ["draft payload must be an object"];
	if (value.schema !== CAMPAIGN_DRAFT_PAYLOAD_SCHEMA_ID) {
		errors.push("draft payload schema mismatch");
	}
	if (typeof value.campaign !== "string") {
		errors.push("draft payload campaign must be string");
	}
	const drafts = value.drafts;
	if (!Array.isArray(drafts)) {
		errors.push("draft payload drafts must be an array");
		return errors;
	}
	for (const [index, draft] of drafts.entries()) {
		if (!isRecord(draft)) {
			errors.push(`drafts[${index}] must be an object`);
			continue;
		}
		if (typeof draft.platform !== "string") {
			errors.push(`drafts[${index}].platform must be string`);
		}
		if (typeof draft.status !== "string") {
			errors.push(`drafts[${index}].status must be string`);
		}
		const metadata = isRecord(draft.metadata) ? draft.metadata : null;
		const campaignFactory = metadata && isRecord(metadata.campaign_factory)
			? metadata.campaign_factory
			: null;
		if (!campaignFactory) {
			errors.push(`drafts[${index}].metadata.campaign_factory must be an object`);
			continue;
		}
		if (options.strictGraphIds && campaignFactory.legacy_compat !== true) {
			for (const field of STRICT_GRAPH_FIELDS) {
				if (typeof campaignFactory[field] !== "string" || !campaignFactory[field]) {
					errors.push(`drafts[${index}].metadata.campaign_factory.${field} is required`);
				}
			}
		}
		const audioIntent = campaignFactory?.audio_intent;
		for (const error of validateAudioIntentContract(audioIntent)) {
			errors.push(`drafts[${index}].metadata.campaign_factory.${error}`);
		}
		for (const key of ["captionOutcomeContext", "caption_outcome_context"] as const) {
			if (campaignFactory[key] !== undefined) {
				for (const error of validateCaptionOutcomeContextContract(campaignFactory[key])) {
					errors.push(`drafts[${index}].metadata.campaign_factory.${error}`);
				}
			}
		}
		if (!campaignFactoryAssetStateAllowsExport(campaignFactory.asset_state)) {
			const state = String(campaignFactory.asset_state || "").trim() || "missing";
			errors.push(
				`drafts[${index}].metadata.campaign_factory.asset_state must be publishable_candidate or exportable, got ${state}`,
			);
		}
		const publishabilityFailures =
			campaignFactoryPublishabilityFailureReasons(campaignFactory);
		for (const reason of publishabilityFailures) {
			errors.push(
				`drafts[${index}].metadata.campaign_factory.publishable_candidate missing ${reason}`,
			);
		}
		for (const error of validateHandoffManifestContract(campaignFactory)) {
			errors.push(`drafts[${index}].metadata.campaign_factory.${error}`);
		}
		const manifest = handoffManifestFor(campaignFactory);
		const contentSurface = contentSurfaceForDraft(draft, campaignFactory, manifest);
		if (contentSurface !== "story" && !explicitInstagramPostCaptionFor(campaignFactory, manifest)) {
			errors.push(
				`drafts[${index}].metadata.campaign_factory.instagram_post_caption is required for non-Story Instagram surfaces`,
			);
		}
	}
	return errors;
}

export function validateAudioCatalogExport(value: unknown): string[] {
	const errors = schemaErrors(generatedPipelineContractSchemas.audioCatalogExport, value, "audio catalog export");
	if (!isRecord(value)) return ["audio catalog export must be an object"];
	if (value.schema !== AUDIO_CATALOG_EXPORT_SCHEMA_ID) {
		errors.push("audio catalog export schema mismatch");
	}
	if (!Array.isArray(value.items)) {
		errors.push("audio catalog export items must be an array");
		return errors;
	}
	for (const [index, item] of value.items.entries()) {
		if (!isRecord(item)) {
			errors.push(`items[${index}] must be an object`);
			continue;
		}
		if (typeof item.title !== "string") {
			errors.push(`items[${index}].title must be string`);
		}
		if (typeof item.platform !== "string") {
			errors.push(`items[${index}].platform must be string`);
		}
	}
	return errors;
}

export function validateRepurposingPlan(value: unknown): string[] {
	const errors = schemaErrors(generatedPipelineContractSchemas.repurposingPlan, value, "repurposing plan");
	if (!isRecord(value)) return ["repurposing plan must be an object"];
	if (value.schema !== REPURPOSING_PLAN_SCHEMA_ID) {
		errors.push("repurposing plan schema mismatch");
	}
	if (typeof value.master_asset_id !== "string") {
		errors.push("repurposing plan master_asset_id must be string");
	}
	if (!["tiktok_aggressive", "ig_subtle", "custom"].includes(String(value.preset_name))) {
		errors.push("repurposing plan preset_name must be a known preset");
	}
	if (typeof value.target_count !== "number" || !Number.isInteger(value.target_count)) {
		errors.push("repurposing plan target_count must be integer");
	}
	if (typeof value.platform !== "string") {
		errors.push("repurposing plan platform must be string");
	}
	return errors;
}

export function validateVariantAssignment(value: unknown): string[] {
	const errors = schemaErrors(generatedPipelineContractSchemas.variantAssignment, value, "variant assignment");
	if (!isRecord(value)) return ["variant assignment must be an object"];
	if (value.schema !== VARIANT_ASSIGNMENT_SCHEMA_ID) {
		errors.push("variant assignment schema mismatch");
	}
	if (typeof value.master_asset_id !== "string") {
		errors.push("variant assignment master_asset_id must be string");
	}
	if (!Array.isArray(value.assignments)) {
		errors.push("variant assignment assignments must be an array");
		return errors;
	}
	for (const [index, assignment] of value.assignments.entries()) {
		if (!isRecord(assignment)) {
			errors.push(`assignments[${index}] must be an object`);
			continue;
		}
		for (const field of ["account_id", "variant_asset_id", "variant_path", "parent_master_asset_id", "preset_name"] as const) {
			if (typeof assignment[field] !== "string" || assignment[field].trim() === "") {
				errors.push(`assignments[${index}].${field} must be string`);
			}
		}
		if (!isRecord(assignment.distinctness_scores)) {
			errors.push(`assignments[${index}].distinctness_scores must be an object`);
		}
	}
	return errors;
}

export function validateMotionEditRender(value: unknown): string[] {
	const errors = schemaErrors(generatedPipelineContractSchemas.motionEditRender, value, "motion edit render");
	if (!isRecord(value)) return ["motion edit render must be an object"];
	if (value.schema !== MOTION_EDIT_RENDER_SCHEMA_ID) {
		errors.push("motion edit render schema mismatch");
	}
	if (value.animationMode !== "motion_edit") {
		errors.push("motion edit render animationMode must be motion_edit");
	}
	if (value.paidGeneration !== false) {
		errors.push("motion edit render paidGeneration must be false");
	}
	if (value.estimatedCostUsd !== 0) {
		errors.push("motion edit render estimatedCostUsd must be 0");
	}
	if (!Array.isArray(value.ffmpegCommand)) {
		errors.push("motion edit render ffmpegCommand must be an array");
	}
	return errors;
}

export function validateFrontGenerationPlan(value: unknown): string[] {
	const errors = schemaErrors(generatedPipelineContractSchemas.frontGenerationPlan, value, "front generation plan");
	if (!isRecord(value)) return ["front generation plan must be an object"];
	if (value.schema !== FRONT_GENERATION_PLAN_SCHEMA_ID) {
		errors.push("front generation plan schema mismatch");
	}
	if (value.humanReviewRequired !== true) {
		errors.push("front generation plan humanReviewRequired must be true");
	}
	if (value.publishingAllowed !== false) {
		errors.push("front generation plan publishingAllowed must be false");
	}
	if (!Array.isArray(value.stages) || value.stages.length === 0) {
		errors.push("front generation plan stages must be a non-empty array");
	}
	return errors;
}

export function validateGeneratedAssetLineage(value: unknown): string[] {
	const errors = schemaErrors(generatedPipelineContractSchemas.generatedAssetLineage, value, "generated asset lineage");
	if (!isRecord(value)) return ["generated asset lineage must be an object"];
	if (value.schema !== GENERATED_ASSET_LINEAGE_SCHEMA_ID) {
		errors.push("generated asset lineage schema mismatch");
	}
	if (typeof value.pipelineTraceId !== "string" || value.pipelineTraceId.trim() === "") {
		errors.push("generated asset lineage pipelineTraceId must be string");
	}
	return errors;
}

export function validateRecommendationAccuracyReport(value: unknown): string[] {
	const errors = schemaErrors(generatedPipelineContractSchemas.recommendationAccuracyReport, value, "recommendation accuracy report");
	if (!isRecord(value)) return ["recommendation accuracy report must be an object"];
	if (value.schema !== RECOMMENDATION_ACCURACY_REPORT_SCHEMA_ID) {
		errors.push("recommendation accuracy report schema mismatch");
	}
	for (const field of ["campaignGraphId", "reportId", "reportGraphId"] as const) {
		if (typeof value[field] !== "string" || value[field].trim() === "") {
			errors.push(`recommendation accuracy report ${field} must be string`);
		}
	}
	return errors;
}

export function validatePerformanceSync(value: unknown): string[] {
	const errors = schemaErrors(generatedPipelineContractSchemas.performanceSync, value, "performance sync");
	if (!isRecord(value)) return ["performance sync must be an object"];
	if (value.schema !== PERFORMANCE_SYNC_SCHEMA_ID) {
		errors.push("performance sync schema mismatch");
	}
	for (const field of ["campaign", "userId"] as const) {
		if (typeof value[field] !== "string") {
			errors.push(`performance sync ${field} must be string`);
		}
	}
	if (!isRecord(value.summary)) {
		errors.push("performance sync summary must be an object");
	}
	for (const field of ["pipelineJobId", "pipelineTraceId"] as const) {
		if (typeof value[field] !== "string" || value[field].trim() === "") {
			errors.push(`performance sync ${field} must be string`);
		}
	}
	return errors;
}

export function validatePostMetricHistoryRead(value: unknown): string[] {
	const errors = schemaErrors(
		generatedPipelineContractSchemas.postMetricHistoryRead,
		value,
		"post metric history read",
	);
	if (!isRecord(value)) return ["post metric history read must be an object"];
	if (value.schema !== POST_METRIC_HISTORY_READ_SCHEMA_ID) {
		errors.push("post metric history read schema mismatch");
	}
	if (!Array.isArray(value.rows)) {
		errors.push("post metric history read rows must be an array");
		return errors;
	}
	const requiredFields = [
		"id",
		"post_id",
		"account_id",
		"platform",
		"snapshot_at",
		"hours_since_publish",
		"views_count",
		"likes_count",
		"replies_count",
		"reposts_count",
		"quotes_count",
		"shares_count",
		"saves_count",
		"reach",
		"engagement_rate",
		"created_at",
	] as const;
	for (const [index, row] of value.rows.entries()) {
		if (!isRecord(row)) {
			errors.push(`post metric history read rows[${index}] must be object`);
			continue;
		}
		for (const field of requiredFields) {
			if (!(field in row)) {
				errors.push(`post metric history read rows[${index}].${field} is required`);
			}
		}
	}
	return errors;
}

export function nativeAudioStatusAllowsPublish(status: unknown): boolean {
	return SAFE_NATIVE_AUDIO_STATUSES.has(String(status || "").trim().toLowerCase());
}
