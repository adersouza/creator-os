import { beforeEach, describe, expect, it, vi } from "vitest";

const mockDispatchPostPublish = vi.fn().mockResolvedValue("msg-campaign-1");
const mockRunPublishPreflight = vi.fn().mockResolvedValue({
	ok: true,
	issues: [],
	summary: { errors: 0, warnings: 0, infos: 0 },
});

vi.mock("@/api/_lib/qstashSchedule.js", () => ({
	dispatchPostPublish: (...args: unknown[]) => mockDispatchPostPublish(...args),
}));

vi.mock("@/api/_lib/publishPreflight.js", () => ({
	runPublishPreflight: (...args: unknown[]) => mockRunPublishPreflight(...args),
}));

vi.mock("@/api/_lib/logger.js", () => ({
	logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

vi.mock("@/api/_lib/apiResponse.js", () => ({
	apiError: (res: any, status: number, message: string, extra?: any) =>
		res.status(status).json({ error: message, ...extra }),
	apiSuccess: (res: any, data: unknown) => res.status(200).json({ data }),
}));

type Row = Record<string, any>;

const state: {
	posts: Row[];
	accounts: Row[];
	groups: Row[];
	batches: Row[];
	items: Row[];
	restrictions: Row[];
	updates: Array<{ table: string; values: Row; filters: Row }>;
} = {
	posts: [],
	accounts: [],
	groups: [],
	batches: [],
	items: [],
	restrictions: [],
	updates: [],
};

class Query {
	private filters: Row = {};
	private notNullField: string | null = null;
	private ltFilters: Row = {};
	private gteFilters: Row = {};
	private selected = "";
	private updateValues: Row | null = null;
	private insertValues: Row | Row[] | null = null;
	private limitCount: number | null = null;

	constructor(private table: string) {}

	select(columns?: string) {
		this.selected = columns || "";
		return this;
	}
	eq(field: string, value: unknown) {
		this.filters[field] = value;
		return this;
	}
	neq(field: string, value: unknown) {
		this.filters[`neq:${field}`] = value;
		return this;
	}
	in(field: string, values: unknown[]) {
		this.filters[`in:${field}`] = values;
		return this;
	}
	not(field: string, op: string, value: unknown) {
		if (op === "is" && value === null) this.notNullField = field;
		return this;
	}
	or() {
		return this;
	}
	gte(field: string, value: unknown) {
		this.gteFilters[field] = value;
		return this;
	}
	lt(field: string, value: unknown) {
		this.ltFilters[field] = value;
		return this;
	}
	order() {
		return this;
	}
	limit(value: number) {
		this.limitCount = value;
		return this;
	}
	insert(values: Row | Row[]) {
		this.insertValues = values;
		const rows = Array.isArray(values) ? values : [values];
		if (this.table === "campaign_schedule_batches") {
			for (const row of rows) state.batches.push({ id: "batch-1", ...row });
		}
		if (this.table === "campaign_schedule_batch_items") {
			for (const row of rows) state.items.push({ id: `item-${state.items.length + 1}`, ...row });
		}
		if (this.table === "instagram_account_restriction_events") {
			for (const row of rows) state.restrictions.push({ id: `restriction-${state.restrictions.length + 1}`, ...row });
		}
		return this;
	}
	update(values: Row) {
		this.updateValues = values;
		return this;
	}
	async maybeSingle() {
		if (this.insertValues && this.table === "campaign_schedule_batches") {
			return { data: { id: "batch-1" }, error: null };
		}
		const rows = this.applyFilters(this.rows());
		return { data: rows[0] ?? null, error: null };
	}
	async then(resolve: (value: { data: Row[]; error: null }) => unknown) {
		if (this.updateValues) {
			const rows = this.applyFilters(this.rows());
			for (const row of rows) Object.assign(row, this.updateValues);
			state.updates.push({ table: this.table, values: this.updateValues, filters: this.filters });
			return resolve({ data: rows, error: null });
		}
		if (this.insertValues) return resolve({ data: [], error: null });
		let rows = this.applyFilters(this.rows());
		if (this.limitCount != null) rows = rows.slice(0, this.limitCount);
		return resolve({ data: rows, error: null });
	}
	private rows(): Row[] {
		if (this.table === "posts") return state.posts;
		if (this.table === "instagram_accounts") return state.accounts;
		if (this.table === "account_groups") return state.groups;
		if (this.table === "campaign_schedule_batches") return state.batches;
		if (this.table === "campaign_schedule_batch_items") return state.items;
		if (this.table === "instagram_account_restriction_events") return state.restrictions;
		return [];
	}
	private applyFilters(rows: Row[]): Row[] {
		let result = rows.filter((row) => {
			for (const [key, value] of Object.entries(this.filters)) {
				if (key.startsWith("neq:")) {
					if (row[key.slice(4)] === value) return false;
					continue;
				}
				if (key.startsWith("in:")) {
					if (!(value as unknown[]).includes(row[key.slice(3)])) return false;
					continue;
				}
				if (row[key] !== value) return false;
			}
			for (const [key, value] of Object.entries(this.ltFilters)) {
				if (!(String(row[key]) < String(value))) return false;
			}
			for (const [key, value] of Object.entries(this.gteFilters)) {
				if (!(String(row[key]) >= String(value))) return false;
			}
			return true;
		});
		if (this.notNullField) result = result.filter((row) => row[this.notNullField!] != null);
		if (this.updateValues) {
			for (const row of result) Object.assign(row, this.updateValues);
			state.updates.push({ table: this.table, values: this.updateValues, filters: this.filters });
		}
		return result;
	}
}

vi.mock("@/api/_lib/supabase.js", () => ({
	getSupabaseAny: () => ({ from: (table: string) => new Query(table) }),
}));

function mockRes() {
	const res: Record<string, any> = {};
	res.status = vi.fn().mockReturnValue(res);
	res.json = vi.fn().mockReturnValue(res);
	return res;
}

function futureIso(minutes = 30) {
	return new Date(Date.now() + minutes * 60 * 1000).toISOString();
}

function validCampaignMeta(overrides: Row = {}) {
	return {
		asset_id: "asset-1",
		rendered_asset_id: "asset-1",
		distribution_plan_id: "dist-1",
		post_key: "post-key-1",
		content_fingerprint: "content-hash-1",
		caption_hash: "caption-hash-1",
		asset_state: "exportable",
		content_surface: "reel",
		ig_media_type: "REELS",
		publishability_failure_reasons: [],
		handoff_manifest: {
			manifest_version: 1,
			asset_id: "asset-1",
			content_fingerprint: "content-hash-1",
			caption_hash: "caption-hash-1",
			exported_by_system: "campaign_factory",
		},
		...overrides,
	};
}

function seedDraft(meta = validCampaignMeta()) {
	state.posts = [{
		id: "post-1",
		user_id: "user-1",
		status: "draft",
		platform: "instagram",
		content: "caption",
		media_urls: ["https://cdn.example.com/reel.mp4"],
		media_type: "reel",
		ig_media_type: "REELS",
		instagram_account_id: "ig-1",
		metadata: { campaign_factory: meta },
		campaign_factory_asset_id: "asset-1",
		campaign_factory_distribution_plan_id: "dist-1",
		campaign_factory_post_key: "post-key-1",
		campaign_factory_content_fingerprint: "content-hash-1",
		campaign_factory_caption_hash: "caption-hash-1",
		platform_draft_validated: true,
	}];
	state.accounts = [{
		id: "ig-1",
		user_id: "user-1",
		username: "bennett.lovee",
		group_id: "group-stacey",
		is_active: true,
		needs_reauth: false,
		status: "active",
		token_expires_at: futureIso(60 * 24),
		instagram_user_id: "1789",
		instagram_access_token_encrypted: "enc",
		login_type: "facebook",
	}];
	state.groups = [{
		id: "group-stacey",
		user_id: "user-1",
		name: "Stacey - Mains",
		account_ids: [],
	}];
}

describe("Campaign schedule manager", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		state.posts = [];
		state.accounts = [];
		state.groups = [];
		state.batches = [];
		state.items = [];
		state.restrictions = [];
		state.updates = [];
		mockDispatchPostPublish.mockResolvedValue("msg-campaign-1");
		mockRunPublishPreflight.mockResolvedValue({ ok: true, issues: [], summary: { errors: 0, warnings: 0, infos: 0 } });
	});

	it("validates campaign drafts in dry-run without scheduling or dispatching", async () => {
		seedDraft();
		const { handleCampaignSchedule } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");
		const res = mockRes();
		await handleCampaignSchedule({ body: { dryRun: true, items: [{ postId: "post-1", scheduledFor: futureIso() }] } } as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(200);
		expect(mockDispatchPostPublish).not.toHaveBeenCalled();
		expect(state.posts[0].status).toBe("draft");
		expect(state.batches).toHaveLength(0);
		expect(res.json.mock.calls[0][0].data.items[0].status).toBe("validated");
	});

	it("blocks drafts with invalid handoff manifest", async () => {
		seedDraft(validCampaignMeta({ handoff_manifest: undefined }));
		const { handleCampaignSchedule } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");
		const res = mockRes();
		await handleCampaignSchedule({ body: { dryRun: true, items: [{ postId: "post-1", scheduledFor: futureIso() }] } } as any, res as any, "user-1");

		const item = res.json.mock.calls[0][0].data.items[0];
		expect(item.ok).toBe(false);
		expect(item.reason).toBe("campaign_factory_manifest_blocked");
	});

	it("blocks Campaign drafts with missing ig_media_type instead of defaulting to Reels", async () => {
		seedDraft(validCampaignMeta({ ig_media_type: undefined, content_surface: undefined }));
		state.posts[0].ig_media_type = null;
		state.posts[0].media_type = null;
		state.posts[0].content_surface = null;
		const { handleCampaignSchedule } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");
		const res = mockRes();
		await handleCampaignSchedule({ body: { dryRun: true, items: [{ postId: "post-1", scheduledFor: futureIso() }] } } as any, res as any, "user-1");

		const item = res.json.mock.calls[0][0].data.items[0];
		expect(item.ok).toBe(false);
		expect(item.reason).toBe("campaign_factory_manifest_blocked");
		expect(item.blockingReasons).toContain("ig_media_type_missing");
	});

	it("commits feed_single Campaign drafts through the Campaign scheduler", async () => {
		seedDraft({
			asset_id: "asset-image-1",
			rendered_asset_id: "asset-image-1",
			distribution_plan_id: "dist-image-1",
			post_key: "post-key-image-1",
			content_fingerprint: "content-image-1",
			caption_hash: "caption-image-1",
			asset_state: "exportable",
			content_surface: "feed_single",
			ig_media_type: "IMAGE",
			instagram_post_caption: "feed caption",
			publishability_failure_reasons: [],
			handoff_manifest: {
				manifest_version: 2,
				exported_by_system: "campaign_factory",
				content_surface: "feed_single",
				ig_media_type: "IMAGE",
				asset_id: "asset-image-1",
				content_fingerprint: "content-image-1",
				caption_hash: "caption-image-1",
				instagram_post_caption: "feed caption",
			},
		});
		Object.assign(state.posts[0], {
			content: "feed caption",
			media_urls: ["https://cdn.example.com/feed.jpg"],
			media_type: "image",
			ig_media_type: "IMAGE",
			content_surface: "feed_single",
			campaign_factory_asset_id: "asset-image-1",
			campaign_factory_distribution_plan_id: "dist-image-1",
			campaign_factory_post_key: "post-key-image-1",
			campaign_factory_content_fingerprint: "content-image-1",
			campaign_factory_caption_hash: "caption-image-1",
		});
		const { handleCampaignSchedule } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");
		const res = mockRes();
		const scheduledFor = futureIso();
		await handleCampaignSchedule({ body: { dryRun: false, items: [{ postId: "post-1", scheduledFor }] } } as any, res as any, "user-1");

		const item = res.json.mock.calls[0][0].data.items[0];
		expect(item.ok).toBe(true);
		expect(item.status).toBe("scheduled");
		expect(item.contentSurface).toBe("feed_single");
		expect(state.posts[0].status).toBe("scheduled");
		expect(state.posts[0].content_surface).toBe("feed_single");
		expect(state.posts[0].scheduled_for).toBe(scheduledFor);
		expect(mockDispatchPostPublish).toHaveBeenCalledWith("post-1", expect.any(Date));
	});

	it("still blocks story Campaign drafts until story scheduling is explicitly enabled", async () => {
		seedDraft({
			asset_id: "asset-story-1",
			rendered_asset_id: "asset-story-1",
			distribution_plan_id: "dist-story-1",
			post_key: "post-key-story-1",
			content_fingerprint: "content-story-1",
			caption_hash: "caption-story-1",
			asset_state: "exportable",
			content_surface: "story",
			ig_media_type: "STORIES",
			publishability_failure_reasons: [],
			handoff_manifest: {
				manifest_version: 2,
				exported_by_system: "campaign_factory",
				content_surface: "story",
				ig_media_type: "STORIES",
				asset_id: "asset-story-1",
					content_fingerprint: "content-story-1",
					caption_hash: "caption-story-1",
					mediaItems: [{ url: "https://cdn.example.com/story.jpg", type: "image" }],
					storyQualityGatePassed: true,
					storySourceNative: true,
					storyNoTextRequired: false,
					storyNoTextPassed: true,
					storyStyleApproved: true,
					sourceLineageBlockers: [],
					visualQualityStatus: "passed",
					surfaceReadiness: { canHandoff: true, blockingReasons: [] },
				},
			});
		Object.assign(state.posts[0], {
			content: "",
			media_urls: ["https://cdn.example.com/story.jpg"],
			media_type: "story",
			ig_media_type: "STORIES",
			content_surface: "story",
			campaign_factory_asset_id: "asset-story-1",
			campaign_factory_distribution_plan_id: "dist-story-1",
			campaign_factory_post_key: "post-key-story-1",
			campaign_factory_content_fingerprint: "content-story-1",
			campaign_factory_caption_hash: "caption-story-1",
		});
		const { handleCampaignSchedule } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");
		const res = mockRes();
		await handleCampaignSchedule({ body: { dryRun: false, items: [{ postId: "post-1", scheduledFor: futureIso() }] } } as any, res as any, "user-1");

		const item = res.json.mock.calls[0][0].data.items[0];
		expect(item.ok).toBe(false);
		expect(item.reason).toBe("surface_scheduling_not_enabled");
		expect(state.posts[0].status).toBe("draft");
	});

	it("commits by updating the existing draft and recording qstash dispatch", async () => {
		seedDraft();
		const { handleCampaignSchedule } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");
		const res = mockRes();
		const scheduledFor = futureIso();
		await handleCampaignSchedule({ body: { dryRun: false, items: [{ postId: "post-1", scheduledFor }] } } as any, res as any, "user-1");

		expect(mockDispatchPostPublish).toHaveBeenCalledWith("post-1", expect.any(Date));
		expect(state.posts[0].status).toBe("scheduled");
		expect(state.posts[0].scheduled_for).toBe(scheduledFor);
		expect(state.posts[0].qstash_dispatch_status).toBe("pending");
		expect(state.items[0].qstash_message_id).toBe("msg-campaign-1");
	});

	it("preserves Campaign variant lineage in first-class columns when scheduling", async () => {
		seedDraft(validCampaignMeta({
			concept_id: "concept-1",
			parent_asset_id: "asset-parent",
			variant_family_id: "vfam-1",
			variant_id: "variant-1",
			handoff_manifest: {
				manifest_version: 1,
				asset_id: "asset-1",
				content_fingerprint: "content-hash-1",
				caption_hash: "caption-hash-1",
				exported_by_system: "campaign_factory",
				concept_id: "concept-1",
				parent_asset_id: "asset-parent",
				variant_family_id: "vfam-1",
				variant_id: "variant-1",
			},
		}));
		const { handleCampaignSchedule } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");
		const res = mockRes();
		await handleCampaignSchedule({ body: { dryRun: false, items: [{ postId: "post-1", scheduledFor: futureIso() }] } } as any, res as any, "user-1");

		expect(state.posts[0]).toEqual(expect.objectContaining({
			campaign_factory_concept_id: "concept-1",
			campaign_factory_parent_asset_id: "asset-parent",
			campaign_factory_variant_family_id: "vfam-1",
			campaign_factory_variant_id: "variant-1",
		}));
		expect(state.items[0].metadata).toEqual(expect.objectContaining({
			conceptId: "concept-1",
			variantFamilyId: "vfam-1",
			variantId: "variant-1",
		}));
	});

	it("preserves Campaign audio segment and cover frame metadata when scheduling", async () => {
		const audioSegment = {
			start_seconds: 18.5,
			duration_seconds: 6,
			label: "hook section",
			reason: "different part of the same song",
		};
		const coverFrame = {
			seconds: 1.4,
			image_path: "/tmp/stacey-cover.jpg",
			image_hash: "cover_hash_1",
			reason: "best face and outfit framing",
		};
		seedDraft(validCampaignMeta({
			audio_segment: audioSegment,
			cover_frame: coverFrame,
			handoff_manifest: {
				manifest_version: 1,
				asset_id: "asset-1",
				content_fingerprint: "content-hash-1",
				caption_hash: "caption-hash-1",
				exported_by_system: "campaign_factory",
				audio_segment: audioSegment,
				cover_frame: coverFrame,
			},
		}));
		const { handleCampaignSchedule } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");
		const res = mockRes();
		await handleCampaignSchedule({ body: { dryRun: false, items: [{ postId: "post-1", scheduledFor: futureIso() }] } } as any, res as any, "user-1");

		const campaignMeta = state.posts[0].metadata.campaign_factory;
		expect(campaignMeta.audio_segment).toEqual(audioSegment);
		expect(campaignMeta.cover_frame).toEqual(coverFrame);
		expect(campaignMeta.handoff_manifest.audio_segment).toEqual(audioSegment);
		expect(campaignMeta.handoff_manifest.cover_frame).toEqual(coverFrame);
	});

	it("blocks the same Campaign variant on the same account forever", async () => {
		seedDraft(validCampaignMeta({
			variant_family_id: "vfam-1",
			variant_id: "variant-1",
		}));
		state.posts.push({
			id: "old-post",
			user_id: "user-1",
			status: "published",
			platform: "instagram",
			instagram_account_id: "ig-1",
			campaign_factory_variant_family_id: "vfam-1",
			campaign_factory_variant_id: "variant-1",
			metadata: { campaign_factory: { variant_family_id: "vfam-1", variant_id: "variant-1" } },
		});
		const { handleCampaignSchedule } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");
		const res = mockRes();

		await handleCampaignSchedule({ body: { dryRun: true, items: [{ postId: "post-1", scheduledFor: futureIso() }] } } as any, res as any, "user-1");

		const item = res.json.mock.calls[0][0].data.items[0];
		expect(item.ok).toBe(false);
		expect(item.reason).toBe("duplicate_variant_account");
	});

	it("blocks sibling variants from the same family on the same account inside cooldown", async () => {
		seedDraft(validCampaignMeta({
			variant_family_id: "vfam-1",
			variant_id: "variant-2",
		}));
		state.posts.push({
			id: "old-post",
			user_id: "user-1",
			status: "published",
			platform: "instagram",
			instagram_account_id: "ig-1",
			published_at: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString(),
			campaign_factory_variant_family_id: "vfam-1",
			campaign_factory_variant_id: "variant-1",
			metadata: { campaign_factory: { variant_family_id: "vfam-1", variant_id: "variant-1" } },
		});
		const { handleCampaignSchedule } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");
		const res = mockRes();

		await handleCampaignSchedule({ body: { dryRun: true, items: [{ postId: "post-1", scheduledFor: futureIso() }] } } as any, res as any, "user-1");

		const item = res.json.mock.calls[0][0].data.items[0];
		expect(item.ok).toBe(false);
		expect(item.reason).toBe("sibling_variant_cooldown");
	});

	it("blocks same account and same content hash on the same day even with different asset ids", async () => {
		seedDraft(validCampaignMeta({
			asset_id: "asset-new",
			rendered_asset_id: "asset-new",
			distribution_plan_id: "dist-new",
			content_fingerprint: "same-content-hash",
			handoff_manifest: {
				manifest_version: 1,
				asset_id: "asset-new",
				content_fingerprint: "same-content-hash",
				caption_hash: "caption-hash-1",
				exported_by_system: "campaign_factory",
			},
		}));
		state.posts[0].campaign_factory_asset_id = "asset-new";
		state.posts[0].campaign_factory_distribution_plan_id = "dist-new";
		state.posts[0].campaign_factory_content_fingerprint = "same-content-hash";
		state.posts.push({
			id: "published-same-content",
			user_id: "user-1",
			status: "published",
			platform: "instagram",
			instagram_account_id: "ig-1",
			published_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
			campaign_factory_asset_id: "asset-old",
			campaign_factory_content_fingerprint: "same-content-hash",
			metadata: { campaign_factory: { asset_id: "asset-old", content_fingerprint: "same-content-hash" } },
		});
		const { handleCampaignSchedule } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");
		const res = mockRes();

		await handleCampaignSchedule({ body: { dryRun: true, items: [{ postId: "post-1", scheduledFor: futureIso() }] } } as any, res as any, "user-1");

		const item = res.json.mock.calls[0][0].data.items[0];
		expect(item.ok).toBe(false);
		expect(item.reason).toBe("same_content_fingerprint_account");
	});

	it("blocks same account and same parent reel within cooldown when variants have different ids", async () => {
		seedDraft(validCampaignMeta({
			asset_id: "asset-new",
			rendered_asset_id: "asset-new",
			distribution_plan_id: "dist-new",
			content_fingerprint: "content-new",
			parent_reel_id: "parent-reel-1",
			variant_family_id: "vfam-new",
			variant_id: "variant-new",
			handoff_manifest: {
				manifest_version: 1,
				asset_id: "asset-new",
				content_fingerprint: "content-new",
				caption_hash: "caption-hash-1",
				exported_by_system: "campaign_factory",
				parent_reel_id: "parent-reel-1",
				variant_family_id: "vfam-new",
				variant_id: "variant-new",
			},
		}));
		state.posts[0].campaign_factory_asset_id = "asset-new";
		state.posts[0].campaign_factory_distribution_plan_id = "dist-new";
		state.posts[0].campaign_factory_content_fingerprint = "content-new";
		state.posts[0].campaign_factory_variant_family_id = "vfam-new";
		state.posts[0].campaign_factory_variant_id = "variant-new";
		state.posts.push({
			id: "published-same-parent",
			user_id: "user-1",
			status: "published",
			platform: "instagram",
			instagram_account_id: "ig-1",
			published_at: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
			campaign_factory_asset_id: "asset-old",
			campaign_factory_content_fingerprint: "content-old",
			campaign_factory_variant_family_id: "vfam-old",
			campaign_factory_variant_id: "variant-old",
			metadata: { campaign_factory: { parent_reel_id: "parent-reel-1", variant_family_id: "vfam-old", variant_id: "variant-old" } },
		});
		const { handleCampaignSchedule } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");
		const res = mockRes();

		await handleCampaignSchedule({ body: { dryRun: true, items: [{ postId: "post-1", scheduledFor: futureIso() }] } } as any, res as any, "user-1");

		const item = res.json.mock.calls[0][0].data.items[0];
		expect(item.ok).toBe(false);
		expect(item.reason).toBe("same_parent_reel_recently_posted");
	});

	it("blocks legacy Campaign rows with missing variant id when content hash matches", async () => {
		seedDraft(validCampaignMeta({
			asset_id: "asset-new",
			rendered_asset_id: "asset-new",
			distribution_plan_id: "dist-new",
			content_fingerprint: "legacy-content-hash",
			handoff_manifest: {
				manifest_version: 1,
				asset_id: "asset-new",
				content_fingerprint: "legacy-content-hash",
				caption_hash: "caption-hash-1",
				exported_by_system: "campaign_factory",
			},
		}));
		state.posts[0].campaign_factory_asset_id = "asset-new";
		state.posts[0].campaign_factory_distribution_plan_id = "dist-new";
		state.posts[0].campaign_factory_content_fingerprint = "legacy-content-hash";
		state.posts.push({
			id: "legacy-manual-post",
			user_id: "user-1",
			status: "published",
			platform: "instagram",
			instagram_account_id: "ig-1",
			published_at: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
			metadata: { campaign_factory: { content_hash: "legacy-content-hash" } },
		});
		const { handleCampaignSchedule } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");
		const res = mockRes();

		await handleCampaignSchedule({ body: { dryRun: true, items: [{ postId: "post-1", scheduledFor: futureIso() }] } } as any, res as any, "user-1");

		const item = res.json.mock.calls[0][0].data.items[0];
		expect(item.ok).toBe(false);
		expect(item.reason).toBe("same_content_fingerprint_account");
	});

	it("rolls back to draft when qstash dispatch fails", async () => {
		seedDraft();
		mockDispatchPostPublish.mockResolvedValue(null);
		const { handleCampaignSchedule } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");
		const res = mockRes();
		await handleCampaignSchedule({ body: { dryRun: false, items: [{ postId: "post-1", scheduledFor: futureIso() }] } } as any, res as any, "user-1");

		expect(state.posts[0].status).toBe("draft");
		expect(state.posts[0].scheduled_for).toBeNull();
		expect(state.posts[0].qstash_dispatch_status).toBe("failed");
		expect(res.json.mock.calls[0][0].data.items[0].reason).toBe("qstash_dispatch_failed");
	});

	it("reports campaign schedule rows with qstash state and duplicate counts", async () => {
		seedDraft();
		state.posts[0].status = "scheduled";
		state.posts[0].scheduled_for = futureIso();
		state.posts[0].qstash_message_id = "msg-campaign-1";
		state.posts[0].qstash_dispatch_status = "dispatched";
		const { handleCampaignScheduleReport } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");
		const res = mockRes();

		await handleCampaignScheduleReport({ body: {} } as any, res as any, "user-1");

		const body = res.json.mock.calls[0][0].data;
		expect(body.scheduledCampaignPosts).toEqual([
			expect.objectContaining({
				postId: "post-1",
				campaignId: null,
				distributionPlanId: "dist-1",
				renderedAssetId: "asset-1",
				accountId: "ig-1",
				qstashMessageId: "msg-campaign-1",
				qstashDispatchStatus: "dispatched",
				platformDraftValidated: true,
			}),
		]);
		expect(body.summary.campaignScheduledCount).toBe(1);
		expect(body.summary.campaignScheduleDuplicateCount).toBe(0);
		expect(body.summary.duplicateVisualRiskCount).toBe(0);
		expect(body.accountBuckets.already_scheduled_today).toHaveLength(1);
	});

	it("surfaces duplicate visual risk in manager reports", async () => {
		seedDraft(validCampaignMeta({
			parent_reel_id: "parent-reel-1",
			variant_family_id: "vfam-1",
			variant_id: "variant-2",
		}));
		state.posts[0].status = "scheduled";
		state.posts[0].scheduled_for = futureIso();
		state.posts[0].campaign_factory_variant_family_id = "vfam-1";
		state.posts[0].campaign_factory_variant_id = "variant-2";
		state.posts.push({
			id: "published-sibling",
			user_id: "user-1",
			status: "published",
			platform: "instagram",
			instagram_account_id: "ig-1",
			published_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
			campaign_factory_asset_id: "asset-old",
			campaign_factory_content_fingerprint: "other-content-hash",
			campaign_factory_variant_family_id: "vfam-1",
			campaign_factory_variant_id: "variant-1",
			metadata: { campaign_factory: { parent_reel_id: "parent-reel-1", variant_family_id: "vfam-1", variant_id: "variant-1" } },
		});
		const { handleCampaignScheduleReport } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");
		const res = mockRes();

		await handleCampaignScheduleReport({ body: {} } as any, res as any, "user-1");

		const body = res.json.mock.calls[0][0].data;
		expect(body.scheduledCampaignPosts[0]).toEqual(expect.objectContaining({
			duplicateVisualRisk: true,
			sameParentRecentlyPosted: true,
			sameVariantFamilyRecentlyPosted: true,
		}));
		expect(body.summary.duplicateVisualRiskCount).toBe(1);
		expect(body.summary.sameParentRecentlyPostedCount).toBe(1);
		expect(body.summary.sameVariantFamilyRecentlyPostedCount).toBe(1);
	});

	it("flags overdue dispatched campaign rows with zero publish attempts as missed", async () => {
		seedDraft();
		state.posts[0].status = "scheduled";
		state.posts[0].scheduled_for = new Date(Date.now() - 60 * 60 * 1000).toISOString();
		state.posts[0].qstash_message_id = "msg-campaign-1";
		state.posts[0].qstash_dispatch_status = "dispatched";
		state.posts[0].ig_publish_attempts = 0;
		const { handleCampaignScheduleReport } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");
		const res = mockRes();

		await handleCampaignScheduleReport({ body: {} } as any, res as any, "user-1");

		const body = res.json.mock.calls[0][0].data;
		expect(body.summary.missedDispatchCount).toBe(1);
		expect(body.missedDispatches).toEqual([
			expect.objectContaining({
				id: "post-1",
				blockingReason: "overdue_dispatch_no_publish_attempt",
				nextOperatorAction: "reschedule_or_recover_same_row",
				qstash_message_id: "msg-campaign-1",
				qstash_dispatch_status: "dispatched",
				ig_publish_attempts: 0,
			}),
		]);
	});

	it("dry-runs instagram account restriction marking without writing rows", async () => {
		seedDraft();
		const { handleInstagramAccountRestrictions } = await import("@/api/_lib/handlers/posts/accountRestrictions.js");
		const res = mockRes();

		await handleInstagramAccountRestrictions({
			method: "POST",
			body: {
				restrictionAction: "dryRun",
				usernames: ["bennett.lovee", "missing.account"],
				restrictionType: "link_sharing_restricted",
				severity: "blocking",
				recommendationEligibilityState: "limited",
				reviewRequired: true,
			},
		} as any, res as any, "user-1");

		const body = res.json.mock.calls[0][0].data;
		expect(body).toEqual(expect.objectContaining({
			wouldWrite: false,
			wouldMark: 1,
			matchedUsernames: 1,
			unmatchedUsernames: ["missing.account"],
			existingActiveEventsUpdated: 0,
			newEventsCreated: 1,
		}));
		expect(state.restrictions).toHaveLength(0);
	});

	it("idempotently marks active instagram account restrictions", async () => {
		seedDraft();
		const { handleInstagramAccountRestrictions } = await import("@/api/_lib/handlers/posts/accountRestrictions.js");
		const first = mockRes();
		const payload = {
			restrictionAction: "mark",
			usernames: ["bennett.lovee"],
			restrictionType: "link_sharing_restricted",
			severity: "blocking",
			recommendationEligibilityState: "limited",
			reviewRequired: true,
			startedAt: "2026-06-07T00:00:00-04:00",
			endsAt: "2026-07-07T00:00:00-04:00",
			source: "manual_instagram_account_status",
			sourceConfidence: "high",
			notes: "Instagram Account Status: You can't share links",
		};

		await handleInstagramAccountRestrictions({ method: "POST", body: payload } as any, first as any, "user-1");
		const second = mockRes();
		await handleInstagramAccountRestrictions({ method: "POST", body: { ...payload, notes: "updated" } } as any, second as any, "user-1");

		expect(state.restrictions).toHaveLength(1);
		expect(state.restrictions[0]).toEqual(expect.objectContaining({
			instagram_account_id: "ig-1",
			restriction_type: "link_sharing_restricted",
			status: "active",
			severity: "blocking",
			recommendation_eligibility_state: "limited",
			review_required: true,
			notes: "updated",
		}));
		expect(second.json.mock.calls[0][0].data).toEqual(expect.objectContaining({
			existingActiveEventsUpdated: 1,
			newEventsCreated: 0,
		}));
	});

	it("projects active link-sharing restrictions into campaign schedule reports", async () => {
		seedDraft();
		state.restrictions.push({
			id: "restriction-1",
			user_id: "user-1",
			instagram_account_id: "ig-1",
			restriction_type: "link_sharing_restricted",
			status: "active",
			severity: "blocking",
			recommendation_eligibility_state: "limited",
			review_required: true,
			started_at: "2026-06-07T04:00:00.000Z",
			ends_at: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString(),
			resolved_at: null,
		});
		const { handleCampaignScheduleReport } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");
		const res = mockRes();

		await handleCampaignScheduleReport({ body: { creator: "Stacey" } } as any, res as any, "user-1");

		const body = res.json.mock.calls[0][0].data;
		const account = body.accounts.find((row: Row) => row.accountId === "ig-1");
		expect(account).toEqual(expect.objectContaining({
			safeToSchedule: false,
			bucket: "blocked_account_health",
			linkSharingRestricted: true,
			activeRestrictionCount: 1,
			restrictionTypes: ["link_sharing_restricted"],
			recommendationEligibilityState: "limited",
			reviewRequired: true,
			accountTrustState: "restricted",
		}));
		expect(account.blockers).toEqual(expect.arrayContaining([
			"account_link_sharing_restricted",
			"recommendation_not_eligible",
			"account_manual_review_required",
		]));
		expect(body.accountBuckets.blocked_account_health.map((row: Row) => row.accountId)).toEqual(["ig-1"]);
		expect(body.summary.restrictedAccountCount).toBe(1);
		expect(body.summary.manualReviewAccountCount).toBe(1);
	});

	it("blocks campaign scheduling when an account has an active restriction", async () => {
		seedDraft();
		state.restrictions.push({
			id: "restriction-1",
			user_id: "user-1",
			instagram_account_id: "ig-1",
			restriction_type: "link_sharing_restricted",
			status: "active",
			severity: "blocking",
			recommendation_eligibility_state: "limited",
			review_required: true,
			started_at: new Date().toISOString(),
			ends_at: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString(),
			resolved_at: null,
		});
		const { handleCampaignSchedule } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");
		const res = mockRes();

		await handleCampaignSchedule({ body: { dryRun: true, items: [{ postId: "post-1", scheduledFor: futureIso() }] } } as any, res as any, "user-1");

		const item = res.json.mock.calls[0][0].data.items[0];
		expect(item.ok).toBe(false);
		expect(item.reason).toBe("account_link_sharing_restricted");
		expect(item.accountHealth.activeRestrictionCount).toBe(1);
	});

	it("requires a reason when resolving account restrictions", async () => {
		seedDraft();
		state.restrictions.push({
			id: "restriction-1",
			user_id: "user-1",
			instagram_account_id: "ig-1",
			restriction_type: "link_sharing_restricted",
			status: "active",
			severity: "blocking",
		});
		const { handleInstagramAccountRestrictions } = await import("@/api/_lib/handlers/posts/accountRestrictions.js");
		const res = mockRes();

		await handleInstagramAccountRestrictions({ method: "POST", body: { restrictionAction: "resolve", eventId: "restriction-1" } } as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(400);
		expect(state.restrictions[0].status).toBe("active");
	});

	it("surfaces post-expiry review without hard-blocking expired restrictions", async () => {
		seedDraft();
		state.restrictions.push({
			id: "restriction-1",
			user_id: "user-1",
			instagram_account_id: "ig-1",
			restriction_type: "link_sharing_restricted",
			status: "active",
			severity: "blocking",
			recommendation_eligibility_state: "eligible",
			review_required: false,
			started_at: new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString(),
			ends_at: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
			resolved_at: null,
		});
		const { handleCampaignScheduleReport } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");
		const res = mockRes();

		await handleCampaignScheduleReport({ body: { creator: "Stacey" } } as any, res as any, "user-1");

		const body = res.json.mock.calls[0][0].data;
		const account = body.accounts.find((row: Row) => row.accountId === "ig-1");
		expect(account.safeToSchedule).toBe(true);
		expect(account.linkSharingRestricted).toBe(false);
		expect(account.activeRestrictionCount).toBe(0);
		expect(account.needsReviewAfterExpiry).toBe(true);
	});

	it("can reset missed campaign rows to draft without creating a duplicate row", async () => {
		seedDraft();
		state.posts[0].status = "scheduled";
		state.posts[0].scheduled_for = new Date(Date.now() - 60 * 60 * 1000).toISOString();
		state.posts[0].qstash_message_id = "msg-campaign-1";
		state.posts[0].qstash_dispatch_status = "dispatched";
		state.posts[0].qstash_dispatched_at = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
		state.posts[0].qstash_failure_reason = null;
		state.posts[0].ig_publish_attempts = 0;
		const { recoverMissedCampaignDispatches } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");

		const result = await recoverMissedCampaignDispatches("user-1", { mode: "reset_to_draft" });

		expect(result).toEqual({ recovered: 1, failed: [] });
		expect(state.posts).toHaveLength(1);
		expect(state.posts[0]).toEqual(expect.objectContaining({
			id: "post-1",
			status: "draft",
			scheduled_for: null,
			qstash_message_id: null,
			qstash_dispatched_at: null,
			qstash_dispatch_status: null,
			qstash_failure_reason: "overdue_dispatch_no_publish_attempt",
			ig_publish_attempts: 0,
			campaign_factory_asset_id: "asset-1",
			campaign_factory_distribution_plan_id: "dist-1",
			platform_draft_validated: true,
		}));
		expect(mockDispatchPostPublish).not.toHaveBeenCalled();
	});

	it("buckets accounts by safe, scheduled, and blocked states without overlap", async () => {
		const now = Date.now();
		state.groups = [
			{ id: "group-stacey", user_id: "user-1", name: "Stacey - Mains" },
			{ id: "group-larissa", user_id: "user-1", name: "Larissa" },
		];
		state.accounts = [
			{
				id: "safe-1",
				user_id: "user-1",
				username: "stacey.safe",
				group_id: "group-stacey",
				is_active: true,
				needs_reauth: false,
				status: "active",
				token_expires_at: new Date(now + 24 * 60 * 60 * 1000).toISOString(),
			},
			{
				id: "scheduled-1",
				user_id: "user-1",
				username: "bennett.scheduled",
				group_id: "group-stacey",
				is_active: true,
				needs_reauth: false,
				status: "active",
				token_expires_at: new Date(now + 24 * 60 * 60 * 1000).toISOString(),
			},
			{
				id: "reauth-1",
				user_id: "user-1",
				username: "stacey.reauth",
				group_id: "group-stacey",
				is_active: true,
				needs_reauth: true,
				status: "active",
				token_expires_at: new Date(now + 24 * 60 * 60 * 1000).toISOString(),
			},
			{
				id: "expired-1",
				user_id: "user-1",
				username: "stacey.expired",
				group_id: "group-stacey",
				is_active: true,
				needs_reauth: false,
				status: "active",
				token_expires_at: new Date(now - 24 * 60 * 60 * 1000).toISOString(),
			},
			{
				id: "disabled-1",
				user_id: "user-1",
				username: "stacey.disabled",
				group_id: "group-stacey",
				is_active: false,
				needs_reauth: false,
				status: "active",
				token_expires_at: new Date(now + 24 * 60 * 60 * 1000).toISOString(),
			},
			{
				id: "larissa-1",
				user_id: "user-1",
				username: "larissa.safe",
				group_id: "group-larissa",
				is_active: true,
				needs_reauth: false,
				status: "active",
				token_expires_at: new Date(now + 24 * 60 * 60 * 1000).toISOString(),
			},
		];
		state.posts = [
			{
				id: "scheduled-post",
				user_id: "user-1",
				status: "scheduled",
				platform: "instagram",
				instagram_account_id: "scheduled-1",
				scheduled_for: futureIso(),
				campaign_factory_asset_id: "asset-1",
				campaign_factory_distribution_plan_id: "dist-1",
				metadata: { campaign_factory: validCampaignMeta() },
			},
		];
		const { handleCampaignScheduleReport } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");
		const res = mockRes();

		await handleCampaignScheduleReport({ body: { creator: "Stacey" } } as any, res as any, "user-1");

		const body = res.json.mock.calls[0][0].data;
		expect(body.filters.creator).toBe("Stacey");
		expect(body.accounts.map((account: Row) => account.accountId).sort()).toEqual([
			"disabled-1",
			"expired-1",
			"reauth-1",
			"safe-1",
			"scheduled-1",
		]);
		expect(body.accountBuckets.safe_to_schedule_today.map((account: Row) => account.accountId)).toEqual(["safe-1"]);
		expect(body.accountBuckets.already_scheduled_today.map((account: Row) => account.accountId)).toEqual(["scheduled-1"]);
		expect(body.accountBuckets.blocked_reauth.map((account: Row) => account.accountId)).toEqual(["reauth-1"]);
		expect(body.accountBuckets.blocked_token_expired.map((account: Row) => account.accountId)).toEqual(["expired-1"]);
		expect(body.accountBuckets.blocked_disabled.map((account: Row) => account.accountId)).toEqual(["disabled-1"]);
		const memberships = Object.values(body.accountBuckets).flat().map((account: Row) => account.accountId);
		expect(new Set(memberships).size).toBe(memberships.length);
		expect(body.summary.safeToScheduleCount).toBe(1);
		expect(body.summary.alreadyScheduledTodayCount).toBe(1);
		expect(body.summary.blockedCount).toBe(3);
	});

	it("blocks the schedule planner when safe accounts exceed validated draft inventory", async () => {
		state.groups = [{ id: "group-stacey", user_id: "user-1", name: "Stacey - Mains" }];
		state.accounts = Array.from({ length: 10 }, (_, index) => ({
			id: `ig-${index + 1}`,
			user_id: "user-1",
			username: `stacey.safe.${index + 1}`,
			group_id: "group-stacey",
			is_active: true,
			needs_reauth: false,
			status: "active",
			token_expires_at: futureIso(60 * 24),
		}));
		state.posts = [{
			id: "draft-1",
			user_id: "user-1",
			status: "draft",
			platform: "instagram",
			instagram_account_id: "ig-1",
			metadata: { campaign_factory: validCampaignMeta({ asset_id: "asset-1", distribution_plan_id: "dist-1" }) },
			campaign_factory_asset_id: "asset-1",
			campaign_factory_distribution_plan_id: "dist-1",
			campaign_factory_content_fingerprint: "content-hash-1",
			campaign_factory_caption_hash: "caption-hash-1",
			platform_draft_validated: true,
		}];
		const { handleCampaignSchedulePlan } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");
		const res = mockRes();

		await handleCampaignSchedulePlan({ body: { creator: "Stacey", requestedCount: 10 } } as any, res as any, "user-1");

		const body = res.json.mock.calls[0][0].data;
		expect(body.status).toBe("blocked");
		expect(body.blockingReason).toBe("insufficient_validated_drafts");
		expect(body.safeAccountsAvailable).toBe(10);
		expect(body.validatedDraftsAvailable).toBe(1);
		expect(body.items).toEqual([]);
		expect(body.wouldWrite).toBe(false);
		expect(state.batches).toHaveLength(0);
		expect(state.items).toHaveLength(0);
		expect(mockDispatchPostPublish).not.toHaveBeenCalled();
	});

	it("returns a read-only jittered plan when enough validated drafts exist", async () => {
		state.groups = [{ id: "group-stacey", user_id: "user-1", name: "Stacey - Mains" }];
		state.accounts = Array.from({ length: 2 }, (_, index) => ({
			id: `ig-${index + 1}`,
			user_id: "user-1",
			username: `stacey.safe.${index + 1}`,
			group_id: "group-stacey",
			is_active: true,
			needs_reauth: false,
			status: "active",
			token_expires_at: futureIso(60 * 24),
		}));
		state.posts = Array.from({ length: 2 }, (_, index) => ({
			id: `draft-${index + 1}`,
			user_id: "user-1",
			status: "draft",
			platform: "instagram",
			instagram_account_id: `ig-${index + 1}`,
			metadata: {
				campaign_factory: validCampaignMeta({
					asset_id: `asset-${index + 1}`,
					rendered_asset_id: `asset-${index + 1}`,
					distribution_plan_id: `dist-${index + 1}`,
					content_fingerprint: `content-hash-${index + 1}`,
					caption_hash: `caption-hash-${index + 1}`,
					handoff_manifest: {
						manifest_version: 1,
						asset_id: `asset-${index + 1}`,
						content_fingerprint: `content-hash-${index + 1}`,
						caption_hash: `caption-hash-${index + 1}`,
						exported_by_system: "campaign_factory",
					},
				}),
			},
			campaign_factory_asset_id: `asset-${index + 1}`,
			campaign_factory_distribution_plan_id: `dist-${index + 1}`,
			campaign_factory_content_fingerprint: `content-hash-${index + 1}`,
			campaign_factory_caption_hash: `caption-hash-${index + 1}`,
			platform_draft_validated: true,
		}));
		const { handleCampaignSchedulePlan } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");
		const res = mockRes();
		const startAt = futureIso(60);

		await handleCampaignSchedulePlan({
			body: { creator: "Stacey", requestedCount: 2, startAt, jitterMinutes: { min: 3, max: 5 } },
		} as any, res as any, "user-1");

		const body = res.json.mock.calls[0][0].data;
		expect(body.status).toBe("ready");
		expect(body.safeAccountsAvailable).toBe(2);
		expect(body.validatedDraftsAvailable).toBe(2);
		expect(body.items).toHaveLength(2);
		expect(body.items[0]).toEqual(expect.objectContaining({
			postId: "draft-1",
			accountId: "ig-1",
			distributionPlanId: "dist-1",
			duplicateCheck: "clear",
			qstashEligible: true,
			wouldWrite: false,
		}));
		expect(body.items[0].scheduledFor).not.toBe(body.items[1].scheduledFor);
		expect(state.batches).toHaveLength(0);
		expect(mockDispatchPostPublish).not.toHaveBeenCalled();
	});

	it("returns a blocked smart time plan when validated draft inventory is short", async () => {
		state.groups = [{ id: "group-stacey", user_id: "user-1", name: "Stacey - Mains" }];
		state.accounts = Array.from({ length: 5 }, (_, index) => ({
			id: `ig-${index + 1}`,
			user_id: "user-1",
			username: `stacey.safe.${index + 1}`,
			group_id: "group-stacey",
			is_active: true,
			needs_reauth: false,
			status: "active",
			token_expires_at: futureIso(60 * 24),
		}));
		state.posts = [{
			id: "draft-1",
			user_id: "user-1",
			status: "draft",
			platform: "instagram",
			instagram_account_id: "ig-1",
			metadata: { campaign_factory: validCampaignMeta({ asset_id: "asset-1", distribution_plan_id: "dist-1" }) },
			campaign_factory_asset_id: "asset-1",
			campaign_factory_distribution_plan_id: "dist-1",
			campaign_factory_content_fingerprint: "content-hash-1",
			campaign_factory_caption_hash: "caption-hash-1",
			platform_draft_validated: true,
		}];
		const { handleCampaignScheduleTimePlan } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");
		const res = mockRes();

		await handleCampaignScheduleTimePlan({ body: { creator: "Stacey", requestedCount: 5 } } as any, res as any, "user-1");

		const body = res.json.mock.calls[0][0].data;
		expect(body.schema).toBe("threadsdashboard.campaign_schedule_time_plan.v1");
		expect(body.status).toBe("blocked");
		expect(body.blockingReason).toBe("insufficient_validated_drafts");
		expect(body.safeAccountsAvailable).toBe(5);
		expect(body.validatedDraftsAvailable).toBe(1);
		expect(body.items).toEqual([]);
		expect(body.wouldWrite).toBe(false);
		expect(state.batches).toHaveLength(0);
		expect(mockDispatchPostPublish).not.toHaveBeenCalled();
	});

	it("returns account-aware spaced smart time plan rows without writing schedules", async () => {
		state.groups = [{ id: "group-stacey", user_id: "user-1", name: "Stacey - Mains" }];
		state.accounts = Array.from({ length: 3 }, (_, index) => ({
			id: `ig-${index + 1}`,
			user_id: "user-1",
			username: `stacey.safe.${index + 1}`,
			group_id: "group-stacey",
			is_active: true,
			needs_reauth: false,
			status: "active",
			token_expires_at: futureIso(60 * 24),
		}));
		state.posts = [
			...Array.from({ length: 3 }, (_, index) => ({
				id: `draft-${index + 1}`,
				user_id: "user-1",
				status: "draft",
				platform: "instagram",
				instagram_account_id: `ig-${index + 1}`,
				metadata: {
					campaign_factory: validCampaignMeta({
						asset_id: `asset-${index + 1}`,
						rendered_asset_id: `asset-${index + 1}`,
						distribution_plan_id: `dist-${index + 1}`,
						content_fingerprint: `content-hash-${index + 1}`,
						caption_hash: `caption-hash-${index + 1}`,
						handoff_manifest: {
							manifest_version: 1,
							asset_id: `asset-${index + 1}`,
							content_fingerprint: `content-hash-${index + 1}`,
							caption_hash: `caption-hash-${index + 1}`,
							exported_by_system: "campaign_factory",
						},
					}),
				},
				campaign_factory_asset_id: `asset-${index + 1}`,
				campaign_factory_distribution_plan_id: `dist-${index + 1}`,
				campaign_factory_content_fingerprint: `content-hash-${index + 1}`,
				campaign_factory_caption_hash: `caption-hash-${index + 1}`,
				platform_draft_validated: true,
			})),
			...Array.from({ length: 6 }, (_, index) => ({
				id: `published-${index + 1}`,
				user_id: "user-1",
				status: "published",
				platform: "instagram",
				instagram_account_id: `ig-${(index % 3) + 1}`,
				published_at: new Date(Date.UTC(2026, 5, 1 + index, 17, 0, 0)).toISOString(),
				metadata: { metrics: { views: 100 + index } },
			})),
		];
		const { handleCampaignScheduleTimePlan } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");
		const res = mockRes();

		await handleCampaignScheduleTimePlan({
			body: {
				creator: "Stacey",
				requestedCount: 3,
				startAt: "2026-06-06T15:00:00.000Z",
				minimumSpacingMinutes: 15,
			},
		} as any, res as any, "user-1");

		const body = res.json.mock.calls[0][0].data;
		expect(body.status).toBe("ready");
		expect(body.items).toHaveLength(3);
		expect(new Set(body.items.map((item: Row) => item.scheduledFor)).size).toBe(3);
		expect(body.items.every((item: Row) => item.wouldWrite === false)).toBe(true);
		expect(body.items.every((item: Row) => item.duplicateCheck === "clear")).toBe(true);
		expect(body.items.every((item: Row) => item.variantCooldownCheck === "clear")).toBe(true);
		expect(body.items.every((item: Row) => item.recommendedWindow.includes("America/New_York"))).toBe(true);
		expect(body.items.every((item: Row) => item.performanceTimingReason.length > 0)).toBe(true);
		expect(body.audit.currentTimingBehavior.legacyConsidersMetricsByHour).toBe(false);
		expect(state.batches).toHaveLength(0);
		expect(mockDispatchPostPublish).not.toHaveBeenCalled();
	});

	it("surfaces variant cooldown conflicts in smart time plan rows", async () => {
		state.groups = [{ id: "group-stacey", user_id: "user-1", name: "Stacey - Mains" }];
		state.accounts = [{
			id: "ig-1",
			user_id: "user-1",
			username: "stacey.safe.1",
			group_id: "group-stacey",
			is_active: true,
			needs_reauth: false,
			status: "active",
			token_expires_at: futureIso(60 * 24),
		}];
		state.posts = [{
			id: "draft-1",
			user_id: "user-1",
			status: "draft",
			platform: "instagram",
			instagram_account_id: "ig-1",
			metadata: { campaign_factory: validCampaignMeta({ asset_id: "asset-1", distribution_plan_id: "dist-1", variant_family_id: "vfam-1", variant_id: "variant-2" }) },
			campaign_factory_asset_id: "asset-1",
			campaign_factory_distribution_plan_id: "dist-1",
			campaign_factory_variant_family_id: "vfam-1",
			campaign_factory_variant_id: "variant-2",
			platform_draft_validated: true,
		}, {
			id: "old-post",
			user_id: "user-1",
			status: "published",
			platform: "instagram",
			instagram_account_id: "ig-1",
			published_at: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString(),
			campaign_factory_variant_family_id: "vfam-1",
			campaign_factory_variant_id: "variant-1",
			metadata: { campaign_factory: { variant_family_id: "vfam-1", variant_id: "variant-1" }, metrics: { views: 50 } },
		}];
		const { handleCampaignScheduleTimePlan } = await import("@/api/_lib/handlers/posts/campaignSchedule.js");
		const res = mockRes();

		await handleCampaignScheduleTimePlan({ body: { creator: "Stacey", requestedCount: 1 } } as any, res as any, "user-1");

		const body = res.json.mock.calls[0][0].data;
		expect(body.status).toBe("ready");
		expect(body.items[0].variantCooldownCheck).toBe("sibling_variant_cooldown");
		expect(body.items[0].qstashEligible).toBe(false);
		expect(body.wouldWrite).toBe(false);
		expect(mockDispatchPostPublish).not.toHaveBeenCalled();
	});
});
