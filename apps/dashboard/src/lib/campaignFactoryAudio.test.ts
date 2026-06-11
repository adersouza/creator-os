import { describe, expect, it } from "vitest";
import {
	applyCampaignFactoryAudioBatchAction,
	buildCampaignFactoryAudioTask,
	campaignFactoryAudioAllowsLive,
	campaignFactoryAudioMissingNativeProof,
	filterCampaignFactoryPosts,
	formatCampaignFactoryAudioStatus,
	getCampaignFactoryAudioQueueLane,
	getCampaignFactoryMetadata,
	summarizeCampaignFactoryAudioQueue,
	updateCampaignFactoryAudioIntent,
} from "./campaignFactory";

const basePost = {
	id: "post_1",
	platform: "instagram",
	status: "draft",
	metadata: {
		campaign_factory: {
			campaign_id: "may",
			rendered_asset_id: "asset_1",
			audio_intent: {
				schema: "pipeline.audio_intent.v1",
				required: true,
				status: "recommended",
				recommendations: [{ audio_title: "Good sound", artist_name: "Artist", platform_audio_id: "ig_audio_1" }],
			},
		},
	},
};

describe("Campaign Factory native audio metadata", () => {
	it("parses audio intent and formats unresolved state", () => {
		const cf = getCampaignFactoryMetadata(basePost);

		expect(cf?.audio_intent?.status).toBe("recommended");
		expect(campaignFactoryAudioAllowsLive(cf)).toBe(false);
		expect(formatCampaignFactoryAudioStatus(cf)).toBe("Audio recommended");
		expect(buildCampaignFactoryAudioTask(cf, "2026-05-22T12:00:00.000Z")).toMatchObject({
			schema: "pipeline.audio_task.v1",
			status: "open",
			proof_required: false,
		});
	});

	it("parses canonical content graph ids without dropping legacy ids", () => {
		const cf = getCampaignFactoryMetadata({
			...basePost,
			metadata: {
				campaign_factory: {
					...basePost.metadata.campaign_factory,
					graph_id: "cg_rendered_asset_abc123def456",
					campaign_graph_id: "cg_campaign_abc123def456",
					source_asset_graph_id: "cg_source_asset_abc123def456",
					rendered_asset_graph_id: "cg_rendered_asset_abc123def456",
					audit_graph_id: "cg_audit_report_abc123def456",
					source_asset_id: "src_1",
				},
			},
		});

		expect(cf?.graph_id).toBe("cg_rendered_asset_abc123def456");
		expect(cf?.campaign_graph_id).toBe("cg_campaign_abc123def456");
		expect(cf?.source_asset_graph_id).toBe("cg_source_asset_abc123def456");
		expect(cf?.rendered_asset_graph_id).toBe("cg_rendered_asset_abc123def456");
		expect(cf?.audit_graph_id).toBe("cg_audit_report_abc123def456");
		expect(cf?.source_asset_id).toBe("src_1");
		expect(cf?.rendered_asset_id).toBe("asset_1");
	});

	it("preserves richer catalog recommendation fields", () => {
		const cf = getCampaignFactoryMetadata({
			...basePost,
			metadata: {
				campaign_factory: {
					...basePost.metadata.campaign_factory,
					audio_intent: {
						schema: "pipeline.audio_intent.v1",
						required: true,
						status: "recommended",
						recommendations: [{
							audio_title: "Good sound",
							artist_name: "Artist",
							platform_audio_id: "ig_123",
							platform_url: "https://instagram.com/reels/audio/ig_123",
							vibe_tags: ["glam", "fit_check"],
							best_content_types: ["reel"],
							freshness: "rising",
							confidence: 0.91,
							safe_usage_notes: "Attach natively only",
						}],
					},
				},
			},
		});

		const recommendation = cf?.audio_intent?.recommendations?.[0];
		expect(recommendation?.platform_audio_id).toBe("ig_123");
		expect(recommendation?.safe_usage_notes).toBe("Attach natively only");
		expect(recommendation?.vibe_tags).toEqual(["glam", "fit_check"]);
	});

	it("allows attached and verified only with native audio proof, and allows skipped/not_required", () => {
		for (const status of ["attached", "verified", "skipped", "not_required"]) {
			const cf = getCampaignFactoryMetadata({
				...basePost,
				metadata: {
					campaign_factory: {
						...(basePost.metadata.campaign_factory as Record<string, unknown>),
						audio_intent: {
							schema: "pipeline.audio_intent.v1",
							required: status !== "not_required",
							status,
							...(status === "attached" || status === "verified"
								? {
										operator_selection: {
											platform_audio_id: "ig_audio_1",
											selected_at: "2026-05-22T12:00:00.000Z",
											...(status === "attached"
												? { attached_at: "2026-05-22T12:05:00.000Z" }
												: { verified_at: "2026-05-22T12:10:00.000Z" }),
										},
									}
								: {}),
						},
					},
				},
			});
			expect(campaignFactoryAudioAllowsLive(cf)).toBe(true);
		}
	});

	it("does not treat attached or verified as live-safe without proof", () => {
		for (const status of ["attached", "verified"] as const) {
			const cf = getCampaignFactoryMetadata({
				...basePost,
				metadata: {
					campaign_factory: {
						...basePost.metadata.campaign_factory,
						audio_intent: { schema: "pipeline.audio_intent.v1", required: true, status },
					},
				},
			});

			expect(campaignFactoryAudioAllowsLive(cf)).toBe(false);
			expect(campaignFactoryAudioMissingNativeProof(cf)).toBe(true);
			expect(formatCampaignFactoryAudioStatus(cf)).toBe(`Audio ${status} - proof missing`);
		}
	});

	it("labels needs_review and burned but does not treat them as live-safe", () => {
		for (const [status, label] of [["needs_review", "Audio needs review"], ["burned", "Audio burned"]] as const) {
			const cf = getCampaignFactoryMetadata({
				...basePost,
				metadata: {
					campaign_factory: {
						...basePost.metadata.campaign_factory,
						audio_intent: { schema: "pipeline.audio_intent.v1", required: true, status },
					},
				},
			});

			expect(formatCampaignFactoryAudioStatus(cf)).toBe(label);
			expect(campaignFactoryAudioAllowsLive(cf)).toBe(false);
		}
	});

	it("filters Campaign Factory posts by audio readiness", () => {
		const ready = {
			...basePost,
			id: "post_2",
			metadata: {
				campaign_factory: {
					...basePost.metadata.campaign_factory,
					rendered_asset_id: "asset_2",
					audio_intent: {
						schema: "pipeline.audio_intent.v1",
						required: true,
						status: "verified",
						operator_selection: {
							platform_audio_id: "ig_audio_1",
							selected_at: "2026-05-22T12:00:00.000Z",
							verified_at: "2026-05-22T12:10:00.000Z",
						},
					},
				},
			},
		};

		expect(filterCampaignFactoryPosts([basePost, ready], { audioState: "needs_audio" }).map((post) => post.id)).toEqual(["post_1"]);
		expect(filterCampaignFactoryPosts([basePost, ready], { audioState: "ready" }).map((post) => post.id)).toEqual(["post_2"]);
	});

	it("classifies audio review queue lanes", () => {
		const selected = {
			...basePost,
			id: "post_selected",
			metadata: applyCampaignFactoryAudioBatchAction(
				basePost,
				"apply_first_recommendation",
				"2026-05-22T12:00:00.000Z",
			),
		};
		const missingProof = {
			...basePost,
			id: "post_missing_proof",
			metadata: {
				campaign_factory: {
					...basePost.metadata.campaign_factory,
					audio_intent: {
						schema: "pipeline.audio_intent.v1",
						required: true,
						status: "attached",
						operator_selection: {
							attached_at: "2026-05-22T12:05:00.000Z",
						},
					},
				},
			},
		};
		const blocked = {
			...basePost,
			id: "post_blocked",
			metadata: applyCampaignFactoryAudioBatchAction(
				basePost,
				"blocked",
				"2026-05-22T12:00:00.000Z",
			),
		};
		const ready = {
			...basePost,
			id: "post_ready",
			metadata: {
				campaign_factory: {
					...basePost.metadata.campaign_factory,
					audio_intent: {
						schema: "pipeline.audio_intent.v1",
						required: true,
						status: "verified",
						operator_selection: {
							platform_audio_id: "ig_audio_1",
							selected_at: "2026-05-22T12:00:00.000Z",
							verified_at: "2026-05-22T12:10:00.000Z",
						},
					},
				},
			},
		};
		const handoff = { ...ready, id: "post_handoff", status: "scheduled" };

		expect(getCampaignFactoryAudioQueueLane(basePost)).toBe("needs_audio");
		expect(getCampaignFactoryAudioQueueLane(selected)).toBe("selected_not_attached");
		expect(getCampaignFactoryAudioQueueLane(missingProof)).toBe("missing_proof");
		expect(getCampaignFactoryAudioQueueLane(blocked)).toBe("blocked");
		expect(getCampaignFactoryAudioQueueLane(ready)).toBe("ready");
		expect(getCampaignFactoryAudioQueueLane(handoff)).toBe("needs_handoff");
		expect(summarizeCampaignFactoryAudioQueue([basePost, selected, missingProof, blocked, ready, handoff])).toMatchObject({
			needs_audio: 1,
			selected_not_attached: 1,
			missing_proof: 1,
			blocked: 1,
			ready: 1,
			needs_handoff: 1,
		});
		expect(filterCampaignFactoryPosts([basePost, selected, handoff], { audioState: "selected_not_attached" }).map((post) => post.id)).toEqual(["post_selected"]);
		expect(filterCampaignFactoryPosts([basePost, selected, handoff], { audioState: "needs_handoff" }).map((post) => post.id)).toEqual(["post_handoff"]);
	});

	it("filters attached/verified posts with incomplete proof", () => {
		const missingProof = {
			...basePost,
			id: "post_3",
			metadata: {
				campaign_factory: {
					...basePost.metadata.campaign_factory,
					rendered_asset_id: "asset_3",
					audio_intent: {
						schema: "pipeline.audio_intent.v1",
						required: true,
						status: "attached",
						operator_selection: {
							audio_title: "Good sound",
							attached_at: "2026-05-22T12:10:00.000Z",
						},
					},
				},
			},
		};

		expect(filterCampaignFactoryPosts([basePost, missingProof], { audioState: "missing_proof" }).map((post) => post.id)).toEqual(["post_3"]);
	});

	it("updates the nested audio intent without dropping Campaign Factory metadata", () => {
		const metadata = updateCampaignFactoryAudioIntent(basePost, {
			status: "attached",
			operator_selection: { audio_title: "Good sound" },
		});

		const cf = getCampaignFactoryMetadata({ ...basePost, metadata });
		expect(cf?.rendered_asset_id).toBe("asset_1");
		expect(cf?.audio_intent?.status).toBe("attached");
		expect(cf?.audio_intent?.operator_selection?.audio_title).toBe("Good sound");
		expect(cf?.audio_intent?.task?.status).toBe("proof_missing");
	});

	it("uses audio decision primary before falling back to first recommendation", () => {
		const post = {
			id: "post_primary",
			metadata: {
				campaign_factory: {
					audio_intent: {
						schema: "pipeline.audio_intent.v1",
						status: "recommended",
						decision: {
							primaryAudio: {
								audio_title: "Primary Sound",
								artist_name: "Primary Artist",
								platform_audio_id: "ig_primary",
								platform_url: "https://instagram.com/reels/audio/ig_primary",
								catalogAudioId: "aud_primary",
								audioMemoryGraphId: "cg_audio_memory_primary",
								selectionRank: 2,
							},
						},
						recommendations: [
							{
								audio_title: "First Sound",
								artist_name: "First Artist",
								platform_audio_id: "ig_first",
								catalogAudioId: "aud_first",
							},
						],
					},
				},
			},
		};

		const metadata = applyCampaignFactoryAudioBatchAction(post, "apply_primary_audio", "2026-05-22T12:00:00.000Z");
		const cf = metadata?.campaign_factory as {
			audio_intent: {
				operator_selection: {
					audio_title?: string;
					platform_audio_id?: string;
					catalog_audio_id?: string;
					audio_memory_graph_id?: string;
					selection_rank?: number;
					selection_source?: string;
				};
			};
		};

		expect(cf.audio_intent.operator_selection.audio_title).toBe("Primary Sound");
		expect(cf.audio_intent.operator_selection.platform_audio_id).toBe("ig_primary");
		expect(cf.audio_intent.operator_selection.catalog_audio_id).toBe("aud_primary");
		expect(cf.audio_intent.operator_selection.audio_memory_graph_id).toBe("cg_audio_memory_primary");
		expect(cf.audio_intent.operator_selection.selection_rank).toBe(2);
		expect(cf.audio_intent.operator_selection.selection_source).toBe("batch_primary_audio_decision");
	});

	it("applies first recommendation as a selected operator choice", () => {
		const metadata = applyCampaignFactoryAudioBatchAction(
			basePost,
			"apply_first_recommendation",
			"2026-05-22T12:00:00.000Z",
		);

		const cf = getCampaignFactoryMetadata({ ...basePost, metadata });
		expect(cf?.rendered_asset_id).toBe("asset_1");
		expect(cf?.audio_intent?.status).toBe("selected");
		expect(cf?.audio_intent?.operator_selection?.audio_title).toBe("Good sound");
		expect(cf?.audio_intent?.operator_selection?.artist_name).toBe("Artist");
		expect(cf?.audio_intent?.operator_selection?.selected_at).toBe("2026-05-22T12:00:00.000Z");
		expect(cf?.audio_intent?.task?.status).toBe("selected");
		expect(campaignFactoryAudioAllowsLive(cf)).toBe(false);
	});

	it("marks batch statuses without making selected or blocked live-safe", () => {
		for (const status of ["selected", "blocked"] as const) {
			const metadata = applyCampaignFactoryAudioBatchAction(basePost, status, "2026-05-22T12:00:00.000Z");
			const cf = getCampaignFactoryMetadata({ ...basePost, metadata });
			expect(cf?.audio_intent?.status).toBe(status);
			expect(cf?.audio_intent?.task?.status).toBe(status === "blocked" ? "blocked" : "selected");
			expect(campaignFactoryAudioAllowsLive(cf)).toBe(false);
		}
		for (const status of ["attached", "verified", "skipped"] as const) {
			const selectedPost =
				status === "skipped"
					? basePost
					: {
							...basePost,
							metadata: applyCampaignFactoryAudioBatchAction(
								basePost,
								"apply_first_recommendation",
								"2026-05-22T12:00:00.000Z",
							),
						};
			const metadata = applyCampaignFactoryAudioBatchAction(selectedPost, status, "2026-05-22T12:05:00.000Z");
			const cf = getCampaignFactoryMetadata({ ...basePost, metadata });
			expect(cf?.audio_intent?.status).toBe(status);
			expect(cf?.audio_intent?.task?.status).toBe("completed");
			expect(campaignFactoryAudioAllowsLive(cf)).toBe(true);
		}
	});
});
