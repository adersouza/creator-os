import { describe, expect, it } from "vitest";
import {
	accountPerformanceStrategies,
	buildPerformanceValidationReport,
	buildPerformanceValidationWindows,
	buildAutoposterPerformanceFacts,
	buildPerformanceFirstRecommendations,
	classifyProfileCuriosityFrame,
	classifyWinnerCloneFamily,
	classifyWinnerCloneFamilyFromContent,
	extractWinnerPatterns,
	isProfileCuriosityDeadEndContent,
	isLowCuriosityAiFormulaContent,
	scoreCorrelation,
	summarizePerformanceFacts,
	type AutoposterPerformanceFact,
	winnerCloneFrameAlignmentScore,
} from "../../api/_lib/handlers/auto-post/performanceFirst";
import { buildPerformanceAttributionArtifacts } from "../../api/_lib/handlers/auto-post/performanceAttributionRefresh";

describe("autoposter performance-first attribution", () => {
	it("classifies clone families by framing instead of broad keywords", () => {
		expect(
			classifyWinnerCloneFamily({
				content:
					"if you think a girl who loves her gym gains is basic, we can't be friends",
				topic_label: "gym",
				content_archetype: "observation",
				shape_id: null,
				question_subtype: null,
			}),
		).toBe("gym_crop_top_identity");
		expect(
			classifyWinnerCloneFamily({
				content: "drop your top 3 songs for a gym playlist",
				topic_label: "music",
				content_archetype: "recommendation_request",
				shape_id: "DROP_YOUR_TOP_3_X",
				question_subtype: null,
			}),
		).toBe("music_gatekeeping_question");
		expect(
			classifyWinnerCloneFamily({
				content: "took off my gaming headset. am i still cute?",
				topic_label: "gaming",
				content_archetype: "question",
				shape_id: null,
				question_subtype: "specific_topical_question",
			}),
		).toBe("headset_cute_validation");
		expect(
			classifyWinnerCloneFamily({
				content: "this song is cute but i refuse to gatekeep it",
				topic_label: "music",
				content_archetype: "observation",
				shape_id: null,
				question_subtype: null,
			}),
		).not.toBe("headset_cute_validation");
		expect(
			classifyWinnerCloneFamily({
				content: "would you date a girl who's obsessed with anime lore?",
				topic_label: "anime",
				content_archetype: "question",
				shape_id: null,
				question_subtype: "specific_topical_question",
			}),
		).toBe("anime_dateability_question");
		expect(
			classifyWinnerCloneFamily({
				content: "what's the one anime everyone needs to watch right now?",
				topic_label: "anime",
				content_archetype: "question",
				shape_id: null,
				question_subtype: "specific_topical_question",
			}),
		).toBe("anime_must_watch_question");
	});

	it("scores winner clones by preserving the source curiosity frame", () => {
		const source = "would you date a girl who watches anime every night?";
		expect(classifyProfileCuriosityFrame(source)).toMatchObject({
			profileCuriosityFrame: "dating_curiosity",
			curiosityMechanism: "dateability_test",
			datingAngle: true,
		});
		expect(
			winnerCloneFrameAlignmentScore({
				sourceContent: source,
				candidateContent:
					"would you date a girl who knows too much anime lore?",
			}),
		).toBeGreaterThan(0);
		expect(
			winnerCloneFrameAlignmentScore({
				sourceContent: source,
				candidateContent: "what anime do you watch after a long day?",
			}),
		).toBeLessThan(0);
	});

	it("treats direct profile invitations as profile-curiosity frames", () => {
		const source = "need someone to talk to rn. check my profile if you're actually free rn";
		expect(classifyProfileCuriosityFrame(source)).toMatchObject({
			profileCuriosityFrame: "direct_profile_curiosity",
			curiosityMechanism: "direct_profile_invitation",
		});
		expect(
			winnerCloneFrameAlignmentScore({
				sourceContent: source,
				candidateContent: "check my profile if you can handle my late night texts",
			}),
		).toBeGreaterThan(0);
		expect(
			winnerCloneFrameAlignmentScore({
				sourceContent: source,
				candidateContent: "my love language is making you a playlist. what's yours?",
			}),
		).toBeLessThan(-25);
	});

	it("treats low-effort secret/profile bait as dead-end despite profile words", async () => {
		const { isProfileCuriosityDeadEndContent } = await import(
			"../../api/_lib/handlers/auto-post/performanceFirst"
		);

		expect(
			isProfileCuriosityDeadEndContent("wanna know a secret? check my profile. 🤫"),
		).toBe(true);
		expect(
			isProfileCuriosityDeadEndContent(
				"check my profile if you can handle my late night texts",
			),
		).toBe(false);
	});

	it("treats flirty attraction as profile-curiosity instead of generic topic content", () => {
		expect(
			classifyProfileCuriosityFrame(
				"would you date a clingy girl who sends good morning texts?",
			),
		).toMatchObject({
			profileCuriosityFrame: "dating_curiosity",
			curiosityMechanism: "dateability_test",
			datingAngle: true,
			flirtAttractionAngle: true,
		});
		expect(
			classifyProfileCuriosityFrame(
				"girls who get jealous over gym crushes are kind of cute",
			),
		).toMatchObject({
			profileCuriosityFrame: "validation_attraction",
			curiosityMechanism: "validation_prompt",
			flirtAttractionAngle: true,
		});
		expect(
			classifyWinnerCloneFamily({
				content: "i'm clingy but i'll send you good morning texts",
				topic_label: "dating",
				content_archetype: "identity_statement",
				shape_id: null,
				question_subtype: null,
			}),
		).toBe("flirty_profile_curiosity");
	});

	it("penalizes clones that drop body-confidence or validation framing", () => {
		expect(
			winnerCloneFrameAlignmentScore({
				sourceContent: "wearing a crop top to the gym is not a crime. stop acting like it is",
				candidateContent: "would you date a girl who's 5'1 but can quote every rom-com line?",
			}),
		).toBeLessThan(-25);
		expect(
			winnerCloneFrameAlignmentScore({
				sourceContent: "am i pretty?",
				candidateContent: "if you think a girl who loves her late-night spotify is basic, we can't be friends",
			}),
		).toBeLessThan(-25);
	});

	it("joins published posts to queue provenance through metadata.autoPostQueueId", () => {
		const facts = buildAutoposterPerformanceFacts({
			posts: [
				{
					id: "post-1",
					user_id: "user-1",
					account_id: "acct-1",
					cross_post_group_id: "group-1",
					content: "r u up?",
					platform: "threads",
					media_type: null,
					media_urls: null,
					published_at: "2026-06-05T12:00:00Z",
					views_count: 120,
					replies_count: 2,
					likes_count: 5,
					hook_type: null,
					topic_label: null,
					format_type: null,
					emotional_frame: null,
					reply_mechanism: null,
					content_length_bucket: null,
					media_style: null,
					posting_hour: 12,
					prompt_version: null,
					template_id: null,
					model_provider: null,
					source_pattern_id: null,
					strategy_recommendation_id: null,
					strategy_bucket: "none",
					metadata: { autoPostQueueId: "queue-1" },
				},
			],
			queueRows: [
					{
						id: "queue-1",
						source_type: "competitor_direct_microcopy",
						source_id: "competitor-post-1",
						source_competitor_id: "competitor-1",
						source_competitor_username: "market_ref",
						strategy_recommendation_id: "rec-1",
						strategy_bucket: "proven",
						source_pattern_id: "winner-post-1",
						metadata: {
							microcopy_confidence: 0.91,
							winner_clone: { clone_family: "music_gatekeeping_question" },
							quality_gate_lane: "performance_backed_clone",
							quality_gate_reason: "winner_clone_performance_evidence",
						},
					},
				],
			historyRows: [
				{
					post_id: "post-1",
					hours_since_publish: 24,
					views_count: 150,
					replies_count: 3,
					likes_count: 8,
				},
			],
			smartLinkAttribution: [],
		});

		expect(facts[0]).toMatchObject({
			source_type: "competitor_direct_microcopy",
			source_id: "competitor-post-1",
			views_24h: 150,
				replies_24h: 3,
				microcopy_confidence: 0.91,
				strategy_recommendation_id: "rec-1",
				strategy_bucket: "proven",
				source_pattern_id: "winner-post-1",
				clone_family: "music_gatekeeping_question",
				quality_gate_lane: "performance_backed_clone",
				metrics_quality: "conversion_unavailable",
			});
	});

	it("summarizes views without treating missing conversion data as zero-quality truth", () => {
		const summary = summarizePerformanceFacts([
			{
				post_id: "post-1",
				user_id: "user-1",
				workspace_id: "workspace-1",
				group_id: "group-1",
				group_name: "Lola",
				account_id: "acct-1",
				account_username: "lola",
				creator_key: "Lola",
				content: "what anime should i watch tonight?",
				published_at: "2026-06-05T12:00:00Z",
				posting_hour: 12,
				platform: "threads",
				views_1h: 10,
				views_24h: 120,
				current_views: 120,
				replies_1h: 2,
				replies_24h: 3,
				current_replies: 3,
				likes_24h: 5,
				current_likes: 5,
				reposts_count: 0,
				quotes_count: 0,
				media_type: null,
				media_style: "text",
				has_media: false,
				source_type: "ai_generated",
				source_id: null,
				source_competitor_id: null,
				source_competitor_username: null,
				direct_copy_reason: null,
				microcopy_confidence: null,
				content_archetype: "recommendation_request",
				shape_id: null,
				hook_type: "question",
				topic_label: "anime",
				format_type: "short_text",
				emotional_frame: "playful",
				reply_mechanism: "recommendation",
				content_length_bucket: "short",
			strategy_recommendation_id: null,
			strategy_bucket: "none",
			clone_family: null,
			prompt_version: null,
			template_id: null,
			model_provider: null,
			source_pattern_id: null,
			quality_gate_lane: null,
			quality_gate_reason: null,
				dna_fit_score: null,
				creator_fit_score: null,
				account_flavor_score: null,
				genericness_score: null,
				smart_link_clicks: 0,
				smart_link_conversions: 0,
				smart_link_revenue: 0,
				profile_clicks_proxy: null,
				profile_clicks_proxy_scope: null,
				metrics_quality: "conversion_unavailable",
				metric_notes: {},
			},
		]);

		expect(summary.averageViewsPerPost).toBe(120);
		expect(summary.postsAbove100ViewsRate).toBe(100);
		expect(summary.totalConversions).toBe(0);
		expect(summary.metricsQuality[0]).toMatchObject({
			key: "conversion_unavailable",
			count: 1,
		});
	});

	it("extracts winner clone patterns from 100+ view posts", () => {
		const [fact] = buildAutoposterPerformanceFacts({
			posts: [
				{
					id: "post-1",
					user_id: "user-1",
					workspace_id: "workspace-1",
					account_id: "acct-1",
					cross_post_group_id: "group-1",
					content: "drop your top 3 songs for a gym playlist",
					platform: "threads",
					media_type: null,
					media_urls: null,
					published_at: "2026-06-05T12:00:00Z",
					views_count: 140,
					replies_count: 10,
					likes_count: 4,
					hook_type: null,
					topic_label: "gym",
					format_type: null,
					emotional_frame: null,
					reply_mechanism: null,
					content_length_bucket: null,
					media_style: null,
					posting_hour: 12,
					prompt_version: null,
					template_id: null,
					model_provider: null,
					source_pattern_id: null,
					strategy_recommendation_id: null,
					strategy_bucket: "none",
					metadata: {},
				},
			],
		});
		const winners = extractWinnerPatterns([fact!]);

		expect(winners).toHaveLength(1);
		expect(winners[0]).toMatchObject({
			source_post_id: "post-1",
			performance_basis: "views_above_100",
			content_archetype: "recommendation_request",
		});
		expect(winners[0]?.clone_prompt).toContain("Clone the performance pattern");
		expect(winners[0]?.clone_prompt).toContain("Profile curiosity frame=");
		expect(winners[0]?.clone_prompt).toContain(
			"Do not preserve only the topic",
		);
	});

	it("promotes fresh performance facts into winner-clone recommendations", () => {
		const [fact] = buildAutoposterPerformanceFacts({
			posts: [
				{
					id: "fresh-post-1",
					user_id: "user-1",
					workspace_id: "workspace-1",
					account_id: "acct-1",
					cross_post_group_id: "group-1",
					content: "would you date a girl who watches anime every night?",
					platform: "threads",
					media_type: null,
					media_urls: null,
					published_at: "2026-06-08T12:00:00Z",
					views_count: 220,
					replies_count: 4,
					likes_count: 12,
					hook_type: null,
					topic_label: "anime",
					format_type: null,
					emotional_frame: null,
					reply_mechanism: null,
					content_length_bucket: null,
					media_style: null,
					posting_hour: 12,
					prompt_version: null,
					template_id: null,
					model_provider: null,
					source_pattern_id: null,
					strategy_recommendation_id: null,
					strategy_bucket: "none",
					metadata: {},
				},
			],
			historyRows: [
				{
					post_id: "fresh-post-1",
					hours_since_publish: 24,
					views_count: 220,
					replies_count: 4,
					likes_count: 12,
				},
			],
		});

		const artifacts = buildPerformanceAttributionArtifacts({
			workspaceId: "workspace-1",
			facts: [fact!],
			days: 30,
			now: new Date("2026-06-08T12:00:00Z"),
		});

		expect(artifacts.winnerPatterns).toHaveLength(1);
		expect(artifacts.strategyRecommendations).toEqual(
			expect.arrayContaining([
				expect.objectContaining({
					pattern_type: "winner_clone",
					pattern_value: "fresh-post-1",
					metric_basis: expect.objectContaining({
						sourcePostId: "fresh-post-1",
						cloneFamily: "anime_dateability_question",
						views24h: 220,
					}),
				}),
			]),
		);
	});

	it("returns insufficient data for creator-fit correlation when score coverage is low", () => {
		const result = scoreCorrelation(
			[
				{
					post_id: "post-1",
					user_id: "user-1",
					workspace_id: "workspace-1",
					group_id: null,
					group_name: null,
					account_id: "acct-1",
					account_username: "acct",
					creator_key: null,
					content: "test",
					published_at: null,
					posting_hour: null,
					platform: "threads",
					views_1h: 0,
					views_24h: 10,
					current_views: 10,
					replies_1h: 0,
					replies_24h: 0,
					current_replies: 0,
					likes_24h: 0,
					current_likes: 0,
					reposts_count: 0,
					quotes_count: 0,
					media_type: null,
					media_style: null,
					has_media: false,
					source_type: "ai_generated",
					source_id: null,
					source_competitor_id: null,
					source_competitor_username: null,
					direct_copy_reason: null,
					microcopy_confidence: null,
					content_archetype: "observation",
					shape_id: null,
					hook_type: "observation",
					topic_label: "unknown",
					format_type: "short_text",
					emotional_frame: "neutral",
					reply_mechanism: "none",
					content_length_bucket: "short",
					strategy_recommendation_id: null,
					strategy_bucket: "none",
					prompt_version: null,
					template_id: null,
					model_provider: null,
					source_pattern_id: null,
					dna_fit_score: null,
					creator_fit_score: 90,
					account_flavor_score: null,
					genericness_score: null,
					smart_link_clicks: 0,
					smart_link_conversions: 0,
					smart_link_revenue: 0,
					profile_clicks_proxy: null,
					profile_clicks_proxy_scope: null,
					metrics_quality: "views_only",
					metric_notes: {},
				},
			],
			"creator_fit_score",
		);

		expect(result.status).toBe("insufficient_data");
	});

	it("creates performance-first recommendations and account strategy modes", () => {
		const facts = buildAutoposterPerformanceFacts({
			posts: Array.from({ length: 10 }, (_, index) => ({
				id: `post-${index}`,
				user_id: "user-1",
				workspace_id: "workspace-1",
				account_id: "acct-dead",
				cross_post_group_id: "group-1",
				content:
					index === 0
						? "would you date a girl who lifts heavy and still wears pink?"
						: `hello ${index}`,
				platform: "threads",
				media_type: null,
				media_urls: null,
				published_at: "2026-06-05T12:00:00Z",
				views_count: index === 0 ? 150 : 1,
				replies_count: 0,
				likes_count: 0,
				hook_type: null,
				topic_label: null,
				format_type: null,
				emotional_frame: null,
				reply_mechanism: null,
				content_length_bucket: null,
				media_style: null,
				posting_hour: 12,
				prompt_version: null,
				template_id: null,
				model_provider: null,
				source_pattern_id: null,
				strategy_recommendation_id: null,
				strategy_bucket: "none",
				metadata: {},
			})),
		});
		const accountStrategies = accountPerformanceStrategies(facts);
		const winnerPatterns = extractWinnerPatterns(facts);
		const recommendations = buildPerformanceFirstRecommendations({
			workspaceId: "workspace-1",
			groupId: "group-1",
			days: 30,
			best: {},
			winnerPatterns,
			accountStrategies,
		});

		expect(winnerPatterns.length).toBeGreaterThan(0);
		expect(recommendations).toContainEqual(
			expect.objectContaining({
				pattern_type: "winner_clone",
				recommendation: "increase",
				metric_basis: expect.objectContaining({
					sourcePostId: expect.any(String),
					sourcePatternId: expect.any(String),
					performanceBasis: expect.any(String),
					profileCuriosityFrame: expect.any(String),
					curiosityMechanism: expect.any(String),
				}),
			}),
		);
		expect(accountStrategies[0]?.recommendedStrategyMode).toBe("reduce");
	});

	it("recomputes recommendation clone family from source framing instead of stale labels", () => {
		expect(
			classifyWinnerCloneFamilyFromContent({
				content: "would you date a girl who's obsessed with anime lore?",
				contentArchetype: "question",
				questionSubtype: "specific_topical_question",
			}),
		).toBe("anime_dateability_question");

		const facts = buildAutoposterPerformanceFacts({
			posts: [
				{
					id: "post-anime-date",
					user_id: "user-1",
					workspace_id: "workspace-1",
					account_id: "acct-1",
					cross_post_group_id: "group-1",
					content: "would you date a girl who's obsessed with anime lore?",
					platform: "threads",
					media_type: null,
					media_urls: null,
					published_at: "2026-06-05T12:00:00Z",
					views_count: 180,
					replies_count: 2,
					likes_count: 3,
					hook_type: null,
					topic_label: "anime",
					format_type: null,
					emotional_frame: null,
					reply_mechanism: null,
					content_length_bucket: null,
					media_style: null,
					posting_hour: 12,
					prompt_version: null,
					template_id: null,
					model_provider: null,
					source_pattern_id: null,
					strategy_recommendation_id: null,
					strategy_bucket: "none",
					metadata: {},
				},
			],
		});
		const winnerPatterns = extractWinnerPatterns(facts);
		winnerPatterns[0]!.clone_family = "single_cook_clean_identity";
		const recommendations = buildPerformanceFirstRecommendations({
			workspaceId: "workspace-1",
			groupId: "group-1",
			days: 30,
			best: {},
			winnerPatterns,
		});

		expect(recommendations[0]?.metric_basis).toMatchObject({
			cloneFamily: "anime_dateability_question",
			profileCuriosityFrame: "dating_curiosity",
			curiosityMechanism: "dateability_test",
		});
	});

	it("does not promote winner patterns that contain internal taxonomy labels", () => {
		const facts = buildAutoposterPerformanceFacts({
			posts: [
				{
					id: "post-taxonomy-leak",
					user_id: "user-1",
					workspace_id: "workspace-1",
					account_id: "acct-1",
					cross_post_group_id: "group-1",
					content:
						"specific topical question: what's your go-to sad girl anthem??",
					platform: "threads",
					media_type: null,
					media_urls: null,
					published_at: "2026-06-05T12:00:00Z",
					views_count: 305,
					replies_count: 2,
					likes_count: 3,
					hook_type: null,
					topic_label: "music",
					format_type: null,
					emotional_frame: null,
					reply_mechanism: null,
					content_length_bucket: null,
					media_style: null,
					posting_hour: 12,
					prompt_version: null,
					template_id: null,
					model_provider: null,
					source_pattern_id: null,
					strategy_recommendation_id: null,
					strategy_bucket: "none",
					metadata: {},
				},
			],
		});
		const recommendations = buildPerformanceFirstRecommendations({
			workspaceId: "workspace-1",
			groupId: "group-1",
			days: 30,
			best: {},
			winnerPatterns: extractWinnerPatterns(facts),
		});

		expect(
			recommendations.some((rec) => rec.pattern_type === "winner_clone"),
		).toBe(false);
	});

	it("does not promote generic-topic winners as profile-curiosity clones", () => {
		const facts = buildAutoposterPerformanceFacts({
			posts: [
				{
					id: "post-generic-topic",
					user_id: "user-1",
					workspace_id: "workspace-1",
					account_id: "acct-1",
					cross_post_group_id: "group-1",
					content: "what's your favorite snack after studying?",
					platform: "threads",
					media_type: null,
					media_urls: null,
					published_at: "2026-06-05T12:00:00Z",
					views_count: 305,
					replies_count: 2,
					likes_count: 3,
					hook_type: null,
					topic_label: "food",
					format_type: null,
					emotional_frame: null,
					reply_mechanism: null,
					content_length_bucket: null,
					media_style: null,
					posting_hour: 12,
					prompt_version: null,
					template_id: null,
					model_provider: null,
					source_pattern_id: null,
					strategy_recommendation_id: null,
					strategy_bucket: "none",
					metadata: {},
				},
				{
					id: "post-profile-curiosity",
					user_id: "user-1",
					workspace_id: "workspace-1",
					account_id: "acct-1",
					cross_post_group_id: "group-1",
					content: "would you date a girl who's obsessed with anime lore?",
					platform: "threads",
					media_type: null,
					media_urls: null,
					published_at: "2026-06-05T13:00:00Z",
					views_count: 280,
					replies_count: 2,
					likes_count: 3,
					hook_type: null,
					topic_label: "anime",
					format_type: null,
					emotional_frame: null,
					reply_mechanism: null,
					content_length_bucket: null,
					media_style: null,
					posting_hour: 13,
					prompt_version: null,
					template_id: null,
					model_provider: null,
					source_pattern_id: null,
					strategy_recommendation_id: null,
					strategy_bucket: "none",
					metadata: {},
				},
			],
		});
		const recommendations = buildPerformanceFirstRecommendations({
			workspaceId: "workspace-1",
			groupId: "group-1",
			days: 30,
			best: {},
			winnerPatterns: extractWinnerPatterns(facts),
		});

		const winnerClones = recommendations.filter(
			(rec) => rec.pattern_type === "winner_clone",
		);
		expect(winnerClones).toHaveLength(1);
		expect(winnerClones[0]?.metric_basis).toMatchObject({
			sourceText: "would you date a girl who's obsessed with anime lore?",
			profileCuriosityFrame: "dating_curiosity",
			curiosityMechanism: "dateability_test",
		});
	});

	it("detects low-curiosity AI formula winners before recommendation promotion", () => {
		expect(
			isLowCuriosityAiFormulaContent(
				"hot take: the best pre-workout is just black coffee. on god",
				"ai",
			),
		).toBe(true);
		expect(
			isLowCuriosityAiFormulaContent(
				"would you date a girl who only listens to metal at the gym?",
				"ai",
			),
		).toBe(false);
		expect(
			isLowCuriosityAiFormulaContent(
				"hot take: protein powder should taste like dessert. trust",
				"competitor_copy",
			),
		).toBe(false);
	});

	it("treats safe aesthetic filler as profile-curiosity dead-end content", () => {
		expect(
			isProfileCuriosityDeadEndContent(
				"girls who love cozy blankets and hot tea > sorry not sorry",
			),
		).toBe(true);
		expect(
			isProfileCuriosityDeadEndContent(
				"is it just me or does coffee taste better in a cute mug?",
			),
		).toBe(true);
		expect(
			isProfileCuriosityDeadEndContent(
				"best sad girl anthem for a heartbreak playlist? help me",
			),
		).toBe(true);
		expect(
			isProfileCuriosityDeadEndContent(
				"would you date a girl who drinks coffee in a crop top after leg day?",
			),
		).toBe(false);
	});
});

function validationFact(
	overrides: Partial<AutoposterPerformanceFact>,
): AutoposterPerformanceFact {
	return {
		post_id: "post",
		user_id: "user-1",
		workspace_id: "workspace-1",
		group_id: "group-1",
		group_name: "Lola",
		account_id: "acct-1",
		account_username: "lola_one",
		creator_key: "Lola",
		content: "test post",
		published_at: "2026-06-06T12:00:00Z",
		posting_hour: 12,
		platform: "threads",
		views_1h: 0,
		views_24h: 10,
		current_views: 10,
		replies_1h: 0,
		replies_24h: 0,
		current_replies: 0,
		likes_24h: 0,
		current_likes: 0,
		reposts_count: 0,
		quotes_count: 0,
		media_type: null,
		media_style: "text",
		has_media: false,
		source_type: "ai_generated",
		source_id: null,
		source_competitor_id: null,
		source_competitor_username: null,
		direct_copy_reason: null,
		microcopy_confidence: null,
		content_archetype: "observation",
		question_subtype: null,
		shape_id: null,
		hook_type: "observation",
		topic_label: "unknown",
		format_type: "short_text",
		emotional_frame: "neutral",
		reply_mechanism: "none",
		content_length_bucket: "short",
		strategy_recommendation_id: null,
		strategy_bucket: "none",
		prompt_version: null,
		template_id: null,
		model_provider: null,
		source_pattern_id: null,
		dna_fit_score: null,
		creator_fit_score: null,
		account_flavor_score: null,
		genericness_score: null,
		smart_link_clicks: 0,
		smart_link_conversions: 0,
		smart_link_revenue: 0,
		profile_clicks_proxy: null,
		profile_clicks_proxy_scope: null,
		metrics_quality: "conversion_unavailable",
		metric_notes: {},
		...overrides,
	};
}

describe("autoposter performance validation report", () => {
	it("builds pre/post windows and detects average/above-100 improvement", () => {
		const windows = buildPerformanceValidationWindows({
			patchAppliedAt: "2026-06-06T00:00:00-04:00",
			preDays: 1,
			postDays: 10,
			now: new Date("2026-06-07T00:00:00Z"),
		});
		const facts = [
			validationFact({
				post_id: "pre-1",
				published_at: "2026-06-05T14:00:00Z",
				views_24h: 10,
			}),
			validationFact({
				post_id: "pre-2",
				published_at: "2026-06-05T15:00:00Z",
				views_24h: 20,
			}),
			validationFact({
				post_id: "post-1",
				published_at: "2026-06-06T14:00:00Z",
				views_24h: 120,
			}),
			validationFact({
				post_id: "post-2",
				published_at: "2026-06-06T15:00:00Z",
				views_24h: 80,
			}),
		];

		const report = buildPerformanceValidationReport({
			facts,
			windows,
			minSamples: 2,
		});

		expect(report.windows.post.end).toBe("2026-06-07T00:00:00.000Z");
		expect(report.summary.status).toBe("ready");
		expect(report.summary.pre.averageViewsPerPost).toBe(15);
		expect(report.summary.post.averageViewsPerPost).toBe(100);
		expect(report.answers.averageViewsImproved.value).toBe(true);
		expect(report.answers.above100RateImproved.value).toBe(true);
	});

	it("separates text/image, question subtypes, and winner clones", () => {
		const windows = buildPerformanceValidationWindows({
			patchAppliedAt: "2026-06-06T00:00:00-04:00",
			preDays: 1,
			postDays: 1,
			now: new Date("2026-06-07T12:00:00Z"),
		});
		const facts = [
			validationFact({
				post_id: "pre-generic",
				published_at: "2026-06-05T14:00:00Z",
				content_archetype: "question",
				question_subtype: "generic_question_bait",
				views_24h: 5,
			}),
			validationFact({
				post_id: "post-topical",
				published_at: "2026-06-06T14:00:00Z",
				content: "what anime should everyone watch right now?",
				content_archetype: "question",
				question_subtype: "specific_topical_question",
				strategy_recommendation_id: "rec-1",
				strategy_bucket: "proven",
				views_24h: 140,
			}),
			validationFact({
				post_id: "post-image",
				published_at: "2026-06-06T15:00:00Z",
				has_media: true,
				media_type: "IMAGE",
				media_style: "image",
				views_24h: 20,
			}),
		];

		const report = buildPerformanceValidationReport({
			facts,
			windows,
			minSamples: 1,
			recommendationsById: new Map([
				[
					"rec-1",
					{
						id: "rec-1",
						pattern_type: "winner_clone",
						metric_basis: { cloneFamily: "anime_must_watch_question" },
					},
				],
			]),
		});

		expect(report.breakdowns.media.map((row) => row.key)).toContain("text");
		expect(report.breakdowns.media.map((row) => row.key)).toContain("image");
		expect(report.breakdowns.questionSubtype.map((row) => row.key)).toContain(
			"specific_topical_question",
		);
		expect(report.breakdowns.cloneVsNonClone.map((row) => row.key)).toContain(
			"winner_clone",
		);
		expect(report.winnerBoard[0]).toMatchObject({
			postId: "post-topical",
			cloneFamily: "anime_must_watch_question",
			questionSubtype: "specific_topical_question",
			views24h: 140,
		});
	});

	it("returns insufficient data and retire candidates only with enough weak post volume", () => {
		const windows = buildPerformanceValidationWindows({
			patchAppliedAt: "2026-06-06T00:00:00-04:00",
			preDays: 1,
			postDays: 1,
			now: new Date("2026-06-07T12:00:00Z"),
		});
		const facts = Array.from({ length: 10 }, (_, index) =>
			validationFact({
				post_id: `weak-${index}`,
				account_id: "acct-weak",
				account_username: "dead_weight",
				published_at: "2026-06-06T14:00:00Z",
				views_24h: 1,
			}),
		);

		const report = buildPerformanceValidationReport({
			facts,
			windows,
			minSamples: 10,
			accountStatesById: new Map([
				[
					"acct-weak",
					{
						account_id: "acct-weak",
						recommended_strategy_mode: "suppress",
						recommended_posts_per_day: 0,
					},
				],
			]),
		});

		expect(report.summary.status).toBe("insufficient_data");
		expect(report.answers.retireCandidates[0]).toMatchObject({
			key: "dead_weight",
			post: expect.objectContaining({
				postCount: 10,
				averageViewsPerPost: 1,
			}),
		});
		expect(report.breakdowns.accountRecovery[0]).toMatchObject({
			recommendedStrategyMode: "suppress",
			recoveryResult: "not_recovering",
		});
	});
});
