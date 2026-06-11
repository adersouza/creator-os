import { beforeEach, describe, expect, it, vi } from "vitest";

const mockFrom = vi.hoisted(() => vi.fn());

vi.mock("@/api/_lib/supabase.js", () => ({
	getSupabaseAny: () => ({ from: mockFrom }),
}));

import {
	applyCampaignFactoryAudioServerAction,
	handleCampaignFactoryAudioAction,
} from "@/api/_lib/handlers/posts/campaignFactoryAudio";
import {
	formatCampaignFactoryAudioEvent,
	handleCampaignFactoryAudioEvents,
} from "@/api/_lib/handlers/posts/campaignFactoryAudioEvents";

const row = {
	id: "post-1",
	user_id: "user-1",
	platform: "instagram",
	status: "draft",
	metadata: {
		campaign_factory: {
			campaign_id: "campaign-1",
			rendered_asset_id: "asset-1",
			audio_intent: {
				schema: "pipeline.audio_intent.v1",
				required: true,
				status: "recommended",
				recommendations: [
					{
						audio_title: "Runway Pop",
						artist_name: "Reference Artist",
						platform_audio_id: "ig_audio_1",
						platform_url: "https://instagram.com/reels/audio/ig_audio_1",
					},
				],
			},
		},
	},
};

function query(result: any) {
	const q: any = {
		select: vi.fn(() => q),
		eq: vi.fn(() => q),
		order: vi.fn(() => q),
		limit: vi.fn(() => q),
		then: (resolve: (value: any) => unknown) => Promise.resolve(result).then(resolve),
	};
	return q;
}

function response() {
	const res: any = {
		status: vi.fn(() => res),
		json: vi.fn(() => res),
	};
	return res;
}

function inMemoryAudioDb() {
	const state = {
		posts: [JSON.parse(JSON.stringify(row))],
		events: [] as Array<Record<string, unknown>>,
	};
	const makeQuery = (table: string) => {
		const filters: Array<[string, unknown]> = [];
		let updatePatch: Record<string, unknown> | null = null;
		let selectAfterUpdate = false;
		let limitCount = 20;
		const q: any = {
			select: vi.fn(() => {
				selectAfterUpdate = true;
				return q;
			}),
			eq: vi.fn((key: string, value: unknown) => {
				filters.push([key, value]);
				return q;
			}),
			in: vi.fn((key: string, values: unknown[]) => {
				filters.push([key, new Set(values)]);
				return q;
			}),
			order: vi.fn(() => q),
			limit: vi.fn((value: number) => {
				limitCount = value;
				return q;
			}),
			update: vi.fn((patch: Record<string, unknown>) => {
				updatePatch = patch;
				return q;
			}),
			insert: vi.fn((items: Array<Record<string, unknown>>) => {
				state.events.push(...items.map((item, index) => ({ id: `event-${index + 1}`, ...item })));
				return Promise.resolve({ data: null, error: null });
			}),
			maybeSingle: vi.fn(async () => {
				const rows = table === "posts" ? state.posts : state.events;
				const found = rows.find((item) => matches(item, filters));
				if (table === "posts" && found && updatePatch) {
					Object.assign(found, updatePatch);
					return { data: selectAfterUpdate ? found : null, error: null };
				}
				return { data: found || null, error: null };
			}),
			then: (resolve: (value: any) => unknown) => {
				const rows = table === "posts" ? state.posts : state.events;
				const data = rows.filter((item) => matches(item, filters)).slice(0, limitCount);
				return Promise.resolve({ data, error: null }).then(resolve);
			},
		};
		return q;
	};
	return {
		state,
		from: vi.fn((table: string) => makeQuery(table)),
	};
}

function matches(item: Record<string, unknown>, filters: Array<[string, unknown]>): boolean {
	return filters.every(([key, value]) => {
		if (value instanceof Set) return value.has(item[key]);
		return item[key] === value;
	});
}

beforeEach(() => {
	vi.clearAllMocks();
});

describe("Campaign Factory audio server action helper", () => {
	it("applies the first recommendation and preserves Campaign Factory metadata", () => {
		const result = applyCampaignFactoryAudioServerAction(
			row,
			"apply_first_recommendation",
			"2026-05-22T12:00:00.000Z",
		);

		const cf = result.metadata?.campaign_factory as {
			rendered_asset_id: string;
			audio_intent: { operator_selection: Record<string, unknown>; task: Record<string, unknown> };
		};
		expect(result.previousStatus).toBe("recommended");
		expect(result.nextStatus).toBe("selected");
		expect(cf.rendered_asset_id).toBe("asset-1");
		expect(cf.audio_intent.operator_selection.audio_title).toBe("Runway Pop");
		expect(cf.audio_intent.operator_selection.selected_at).toBe("2026-05-22T12:00:00.000Z");
		expect(cf.audio_intent.task).toMatchObject({
			schema: "pipeline.audio_task.v1",
			status: "selected",
			proof_required: false,
		});
		expect(result.proofComplete).toBe(false);
	});

	it("records complete proof only when attached/verified has a native locator and timestamps", () => {
		const selected = applyCampaignFactoryAudioServerAction(
			row,
			"apply_first_recommendation",
			"2026-05-22T12:00:00.000Z",
		);
		const attached = applyCampaignFactoryAudioServerAction(
			{ ...row, metadata: selected.metadata },
			"attached",
			"2026-05-22T12:05:00.000Z",
			undefined,
			{ url: "https://instagram.com/p/proof", type: "native_post_link", note: "checked in app" },
		);

		expect(attached.nextStatus).toBe("attached");
		expect(attached.proofComplete).toBe(true);
		const cf = attached.metadata?.campaign_factory as {
			audio_intent: { operator_selection: Record<string, unknown>; task: Record<string, unknown> };
		};
		expect(cf.audio_intent.operator_selection.attached_at).toBe("2026-05-22T12:05:00.000Z");
		expect(cf.audio_intent.operator_selection.proof_url).toBe("https://instagram.com/p/proof");
		expect(cf.audio_intent.operator_selection.proof_type).toBe("native_post_link");
		expect(attached.eventMetadata.proof).toMatchObject({
			url: "https://instagram.com/p/proof",
			type: "native_post_link",
			note: "checked in app",
		});
		expect(cf.audio_intent.task).toMatchObject({
			status: "completed",
			proof_required: true,
			completed_at: "2026-05-22T12:05:00.000Z",
		});
	});

	it("selects a specific recommended audio choice by audio id", () => {
		const twoChoiceRow = JSON.parse(JSON.stringify(row));
		twoChoiceRow.metadata.campaign_factory.audio_intent.recommendations.push({
			audio_title: "Better Sound",
			artist_name: "Second Artist",
			platform_audio_id: "ig_audio_2",
			audioMemoryGraphId: "cg_audio_memory_222",
			selectionRank: 2,
		});
		const result = applyCampaignFactoryAudioServerAction(
			twoChoiceRow,
			"selected",
			"2026-05-22T12:00:00.000Z",
			undefined,
			undefined,
			"ig_audio_2",
		);
		const cf = result.metadata?.campaign_factory as {
			audio_intent: { operator_selection: Record<string, unknown> };
		};
		expect(result.nextStatus).toBe("selected");
		expect(cf.audio_intent.operator_selection.audio_title).toBe("Better Sound");
		expect(cf.audio_intent.operator_selection.platform_audio_id).toBe("ig_audio_2");
		expect(cf.audio_intent.operator_selection.audio_memory_graph_id).toBe("cg_audio_memory_222");
		expect(cf.audio_intent.operator_selection.selection_rank).toBe(2);
	});

	it("selects the decision primary by audio id even when recommendations are legacy-only", () => {
		const decisionRow = JSON.parse(JSON.stringify(row));
		decisionRow.metadata.campaign_factory.audio_intent.decision = {
			primaryAudio: {
				audio_title: "Primary Decision Sound",
				artist_name: "Decision Artist",
				platform_audio_id: "ig_primary_decision",
				platform_url: "https://instagram.com/reels/audio/ig_primary_decision",
				audioMemoryGraphId: "cg_audio_memory_primary",
				selectionRank: 1,
			},
		};

		const result = applyCampaignFactoryAudioServerAction(
			decisionRow,
			"selected",
			"2026-05-22T12:00:00.000Z",
			undefined,
			undefined,
			"ig_primary_decision",
		);
		const cf = result.metadata?.campaign_factory as {
			audio_intent: { operator_selection: Record<string, unknown> };
		};

		expect(result.nextStatus).toBe("selected");
		expect(cf.audio_intent.operator_selection.audio_title).toBe("Primary Decision Sound");
		expect(cf.audio_intent.operator_selection.platform_audio_id).toBe("ig_primary_decision");
		expect(cf.audio_intent.operator_selection.audio_memory_graph_id).toBe("cg_audio_memory_primary");
		expect(cf.audio_intent.operator_selection.selection_rank).toBe(1);
	});

	it("skips posts that do not have Campaign Factory audio intent", () => {
		const result = applyCampaignFactoryAudioServerAction(
			{ ...row, metadata: {} },
			"selected",
			"2026-05-22T12:00:00.000Z",
		);

		expect(result.metadata).toBeNull();
		expect(result.eventMetadata.skipped_reason).toBe("missing_audio_intent");
	});
});

describe("Campaign Factory audio event history handler", () => {
	it("writes and reads audio event history through a local DB-backed fixture", async () => {
		const db = inMemoryAudioDb();
		mockFrom.mockImplementation(db.from);
		const writeRes = response();

		await handleCampaignFactoryAudioAction(
			{
				method: "POST",
				body: {
					postIds: ["post-1"],
					action: "apply_first_recommendation",
					nowIso: "2026-05-22T12:00:00.000Z",
				},
			} as any,
			writeRes as any,
			"user-1",
		);

		expect(writeRes.status).toHaveBeenCalledWith(200);
		expect(db.state.events).toHaveLength(1);
		expect(db.state.events[0]).toMatchObject({
			post_id: "post-1",
			action: "apply_first_recommendation",
			previous_status: "recommended",
			next_status: "selected",
			proof_complete: false,
			metadata: expect.objectContaining({
				audio_task: expect.objectContaining({ status: "selected" }),
			}),
		});

		const readRes = response();
		await handleCampaignFactoryAudioEvents(
			{ method: "GET", query: { postId: "post-1" } } as any,
			readRes as any,
			"user-1",
		);

		expect(readRes.status).toHaveBeenCalledWith(200);
		expect(readRes.json).toHaveBeenCalledWith({
			success: true,
			limit: 20,
			events: [
				expect.objectContaining({
					action: "apply_first_recommendation",
					previousStatus: "recommended",
					nextStatus: "selected",
					nativeAudioLocator: "https://instagram.com/reels/audio/ig_audio_1",
				}),
			],
		});
	});

	it("applies scoped filters and formats recent event rows", async () => {
		const dbQuery = query({
			data: [
				{
					id: "event-1",
					post_id: "post-1",
					campaign_id: "campaign-1",
					rendered_asset_id: "asset-1",
					action: "attached",
					previous_status: "selected",
					next_status: "attached",
					platform_audio_id: "ig_audio_1",
					platform_url: "https://instagram.com/reels/audio/ig_audio_1",
					proof_complete: true,
					note: "operator found exact audio",
					metadata: { proof_source: "operator_server_action" },
					created_at: "2026-05-22T12:05:00.000Z",
				},
			],
			error: null,
		});
		mockFrom.mockReturnValueOnce(dbQuery);
		const res = response();

		await handleCampaignFactoryAudioEvents(
			{
				method: "GET",
				query: {
					postId: "post-1",
					campaignId: "campaign-1",
					renderedAssetId: "asset-1",
					limit: "3",
				},
			} as any,
			res as any,
			"user-1",
		);

		expect(mockFrom).toHaveBeenCalledWith("campaign_factory_audio_events");
		expect(dbQuery.eq).toHaveBeenCalledWith("user_id", "user-1");
		expect(dbQuery.eq).toHaveBeenCalledWith("post_id", "post-1");
		expect(dbQuery.eq).toHaveBeenCalledWith("campaign_id", "campaign-1");
		expect(dbQuery.eq).toHaveBeenCalledWith("rendered_asset_id", "asset-1");
		expect(dbQuery.order).toHaveBeenCalledWith("created_at", { ascending: false });
		expect(dbQuery.limit).toHaveBeenCalledWith(3);
		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith({
			success: true,
			limit: 3,
			events: [
				expect.objectContaining({
					id: "event-1",
					action: "attached",
					previousStatus: "selected",
					nextStatus: "attached",
					proofComplete: true,
					nativeAudioLocator: "https://instagram.com/reels/audio/ig_audio_1",
					note: "operator found exact audio",
					timestamp: "2026-05-22T12:05:00.000Z",
				}),
			],
		});
	});

	it("formats event reasons from metadata when no note is stored", () => {
		expect(
			formatCampaignFactoryAudioEvent({
				action: "skipped",
				next_status: "skipped",
				metadata: { skipped_reason: "missing_recommendation" },
				created_at: "2026-05-22T12:00:00.000Z",
			}),
		).toMatchObject({
			action: "skipped",
			nextStatus: "skipped",
			reason: "missing_recommendation",
			timestamp: "2026-05-22T12:00:00.000Z",
		});
	});
});
