import { beforeEach, describe, expect, it, vi } from "vitest";
import { createChainMock } from "../helpers/mockFactories";
import type { FilterSurvivor } from "../../api/_lib/handlers/auto-post/pipelineFilters";
import type { InsertionContext } from "../../api/_lib/handlers/auto-post/scheduleAndInsert";

// ---------------------------------------------------------------------------
// Mocks — module-scope, BEFORE importing module under test
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();
const mockRpc = vi.fn();
const mockLoggerInfo = vi.fn();
const mockLoggerWarn = vi.fn();
const mockLoggerError = vi.fn();
const mockLoggerDebug = vi.fn();

vi.mock("../../api/_lib/supabase", () => ({
	getSupabase: () => ({ from: mockFrom, rpc: mockRpc }),
	getSupabaseAny: () => ({ from: mockFrom, rpc: mockRpc }),
}));

vi.mock("../../api/_lib/logger", () => ({
	logger: {
		info: (...args: unknown[]) => mockLoggerInfo(...args),
		warn: (...args: unknown[]) => mockLoggerWarn(...args),
		error: (...args: unknown[]) => mockLoggerError(...args),
		debug: (...args: unknown[]) => mockLoggerDebug(...args),
	},
}));

// Humanize: identity by default so tests can assert exact content
const mockHumanizePost = vi.fn((s: string) => s);
const mockDetectTopicTag = vi.fn().mockReturnValue(null);

vi.mock("../../api/_lib/handlers/auto-post/evergreenManager", () => ({
	humanizePost: (...args: unknown[]) => mockHumanizePost(...(args as [string])),
	detectTopicTag: (...args: unknown[]) =>
		mockDetectTopicTag(...(args as [string])),
}));

// QStash
const mockQstashPublishJSON = vi
	.fn()
	.mockResolvedValue({ messageId: "msg-1" });

vi.mock("../../api/_lib/qstash", () => ({
	getQStashClient: () => ({
		publishJSON: (...args: unknown[]) => mockQstashPublishJSON(...args),
	}),
}));

vi.mock("../../api/_lib/qstashDefaults", () => ({
	RETRIES: { CRITICAL: 3, IMPORTANT: 2, BEST_EFFORT: 1 },
	getRequiredAppBaseUrl: () => "https://test.example.com",
	getFailureCallbackUrl: () =>
		"https://test.example.com/api/qstash-failure",
}));

// Infra telemetry
const mockRecordInfraEvent = vi.fn().mockResolvedValue(undefined);
vi.mock("../../api/_lib/infraTelemetry", () => ({
	recordInfraEvent: (...args: unknown[]) => mockRecordInfraEvent(...args),
}));

// Queue state helpers
const mockEnsureQueueItemScheduleNonce = vi
	.fn()
	.mockResolvedValue("auto-post-q1-1234567890");
const mockRescheduleQueueItemForFutureDispatch = vi
	.fn()
	.mockResolvedValue(undefined);

vi.mock("../../api/_lib/handlers/auto-post/queueState", () => ({
	CLAIMABLE_QUEUE_STATUSES: ["pending", "queued"],
	ensureQueueItemScheduleNonce: (...args: unknown[]) =>
		mockEnsureQueueItemScheduleNonce(...args),
	isClaimableQueueStatus: (status: string | null | undefined) =>
		status === "pending" || status === "queued",
	rescheduleQueueItemForFutureDispatch: (...args: unknown[]) =>
		mockRescheduleQueueItemForFutureDispatch(...args),
}));

// Source policy
vi.mock("../../api/_lib/handlers/auto-post/sourcePolicy", () => ({
	DIRECT_COMPETITOR_SHARE: 0.8,
}));

// Spoiler tricks — disabled by default
const mockDetectNaturalSpoiler = vi.fn().mockReturnValue(null);
const mockDetectNaturalCuriositySpoiler = vi.fn().mockReturnValue(null);
vi.mock("../../api/_lib/handlers/auto-post/spoilerTricks", () => ({
	detectNaturalSpoiler: (...args: unknown[]) =>
		mockDetectNaturalSpoiler(...args),
	detectNaturalCuriositySpoiler: (...args: unknown[]) =>
		mockDetectNaturalCuriositySpoiler(...args),
}));

// Redis (competitor dedup)
const mockRedisIncr = vi.fn().mockResolvedValue(1);
const mockRedisExpire = vi.fn().mockResolvedValue(undefined);
const mockRedisDecr = vi.fn().mockResolvedValue(0);
vi.mock("../../api/_lib/redis", () => ({
	getRedis: () => ({
		incr: (...args: unknown[]) => mockRedisIncr(...args),
		expire: (...args: unknown[]) => mockRedisExpire(...args),
		decr: (...args: unknown[]) => mockRedisDecr(...args),
	}),
}));

// Media generation — disabled by default
const mockGenerateImageForPost = vi.fn().mockResolvedValue(null);
const mockHasImageGenerationCapability = vi.fn().mockResolvedValue(false);
vi.mock("../../api/_lib/handlers/auto-post/mediaGeneration", () => ({
	generateImageForPost: (...args: unknown[]) =>
		mockGenerateImageForPost(...args),
	hasImageGenerationCapability: (...args: unknown[]) =>
		mockHasImageGenerationCapability(...args),
}));

// Account planner
const mockPlanSlots = vi
	.fn()
	.mockResolvedValue({ slots: [], skipped: [], totalAccounts: 0, eligibleCount: 0 });
vi.mock("../../api/_lib/handlers/auto-post/accountPlanner", () => ({
	planAccountSlots: (...args: unknown[]) => mockPlanSlots(...args),
}));

// Types
vi.mock("../../api/_lib/handlers/auto-post/types", () => ({
	RATE_LIMITS: { POSTS_PER_HOUR: 25, POSTS_PER_DAY: 250 },
}));

// ---------------------------------------------------------------------------
// Import module under test AFTER mocks
// ---------------------------------------------------------------------------

import {
	canPerformanceBackedCloneBypassDnaReview,
	insertCandidatesIntoQueue,
	nudgeScheduleForFormat,
	planAccountSlots,
} from "../../api/_lib/handlers/auto-post/scheduleAndInsert";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeCandidate(
	overrides: Partial<FilterSurvivor["idea"]> & {
		scheduledFor?: string;
		judgeResult?: {
			passed: true;
			score: number;
			dimensions: Record<string, number>;
			rationale?: string;
		};
	} = {},
): FilterSurvivor {
	const { scheduledFor, ...ideaOverrides } = overrides;
	return {
		idea: {
			content: "test post content here",
			viralScore: 95,
			sourceContent: null,
			contentType: null,
			sourceCompetitorId: null,
			sourceCompetitorUsername: null,
			qualityGate: {
				decision: "pass",
				reason: "quality_gate_passed",
				confidences: {},
				flags: [],
				score: { overall: 4 },
			},
			judgeResult: {
				passed: true,
				score: 4,
				dimensions: {},
				rationale: "fixture-pass",
			},
			...ideaOverrides,
		} as FilterSurvivor["idea"],
		index: 0,
		scheduledFor:
			scheduledFor || new Date(Date.now() + 3600000).toISOString(),
	};
}

function makeContext(overrides: Partial<InsertionContext> = {}): InsertionContext {
	return {
		workspaceId: "ws-1",
		groupId: "grp-1",
		ownerId: "user-1",
		targetPlatform: "threads",
		config: {
			workspace_id: "ws-1",
			is_enabled: true,
			posting_times: { media_chance: 0, timezone: "America/New_York" },
			pause_on_low_performance: false,
			performance_threshold: 0,
		},
		aiConfig: { provider: "gemini" },
		slotMediaChance: 0,
		resolvedGroupName: "Test Group",
		maxInserts: 10,
		fillStartTime: Date.now(),
		timezone: "America/New_York",
		...overrides,
	};
}

function makeSlot(accountId: string, index = 0, isProbe = false) {
	return { accountId, roundRobinIndex: index, isProbe };
}

function makeWarmupSlot(accountId: string, index = 0) {
	return {
		accountId,
		roundRobinIndex: index,
		timezone: "America/New_York",
		activeHoursStart: 6,
		activeHoursEnd: 13,
		minIntervalMinutes: 180,
		warmupPolicy: {
			status: "warming",
			day: 1,
			allowedPostsPerDay: 1,
			reason: "restart_warmup_day_1",
			textOnly: true,
			mediaChanceCap: 0,
			primaryHoursOnly: true,
			directMicrocopyAllowed: false,
			directMicrocopyCapPercent: 0,
			genericQuestionCap: 0,
			shouldSkipToday: false,
		},
	};
}

/**
 * Set up mockFrom so that:
 * - `auto_post_queue` insert chain returns the given result
 * - `media` select returns the given media rows
 * - `posts` select returns the given top posts
 */
function setupDbMock(opts: {
	insertResult?: { data: { id: string } | null; error: unknown };
	mediaRows?: Array<{ url: string; file_type?: string }>;
	topPost?: { content: string; views_count: number } | null;
} = {}) {
	const insertResult = opts.insertResult ?? { data: { id: "q1" }, error: null };
	const mediaRows = opts.mediaRows ?? [];
	const topPost = opts.topPost ?? null;

	mockFrom.mockImplementation((table: string) => {
		if (table === "user_settings") {
			return createChainMock({
				data: { setting_value: { threshold: 50 } },
				error: null,
			});
		}
		if (table === "auto_post_queue") {
			return {
				insert: vi.fn().mockReturnValue({
					select: vi.fn().mockReturnValue({
						single: vi.fn().mockResolvedValue(insertResult),
					}),
				}),
			};
		}
		if (table === "media") {
			return {
				select: vi.fn().mockReturnValue({
					eq: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							limit: vi.fn().mockResolvedValue({
								data: mediaRows,
								error: null,
							}),
						}),
					}),
				}),
			};
		}
		if (table === "posts") {
			return {
				select: vi.fn().mockReturnValue({
					eq: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							not: vi.fn().mockReturnValue({
								gt: vi.fn().mockReturnValue({
									order: vi.fn().mockReturnValue({
										limit: vi.fn().mockResolvedValue({
											data: topPost ? [topPost] : [],
											error: null,
										}),
									}),
								}),
							}),
						}),
					}),
				}),
			};
		}
		// Fallback
		return createChainMock({ data: null, error: null });
	});
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("performance-backed clone DNA review bypass", () => {
	const baseInput = {
		dnaEvaluation: {
			decision: "regenerate" as const,
			reasons: ["recent_phrase_repetition"],
		},
		qualityGate: {
			decision: "pass" as const,
			lane: "performance_backed_clone" as const,
		},
		winnerCloneFrameMismatch: false,
		winnerCloneSourceTaxonomyLeak: false,
		hasDuplicateMatch: false,
		hasMissingProvenance: false,
	};

	it("allows a safe performance-backed winner clone blocked only by recent phrase repetition", () => {
		expect(canPerformanceBackedCloneBypassDnaReview(baseInput)).toBe(true);
	});

	it("does not bypass exact duplicate protection", () => {
		expect(
			canPerformanceBackedCloneBypassDnaReview({
				...baseInput,
				hasDuplicateMatch: true,
			}),
		).toBe(false);
	});

	it("does not bypass winner clone frame mismatch protection", () => {
		expect(
			canPerformanceBackedCloneBypassDnaReview({
				...baseInput,
				winnerCloneFrameMismatch: true,
			}),
		).toBe(false);
	});

	it("does not bypass non-performance-backed DNA failures", () => {
		expect(
			canPerformanceBackedCloneBypassDnaReview({
				...baseInput,
				qualityGate: { decision: "pass", lane: "standard" },
			}),
		).toBe(false);
		expect(
			canPerformanceBackedCloneBypassDnaReview({
				...baseInput,
				dnaEvaluation: {
					decision: "regenerate",
					reasons: ["low_creator_fit"],
				},
			}),
		).toBe(false);
	});
});

describe("scheduleAndInsert", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockHumanizePost.mockImplementation((s: string) => s);
		mockDetectTopicTag.mockReturnValue(null);
		mockQstashPublishJSON.mockResolvedValue({ messageId: "msg-1" });
		mockEnsureQueueItemScheduleNonce.mockResolvedValue("nonce-1");
		mockRescheduleQueueItemForFutureDispatch.mockResolvedValue(undefined);
		mockRecordInfraEvent.mockResolvedValue(undefined);
		mockDetectNaturalSpoiler.mockReturnValue(null);
		mockDetectNaturalCuriositySpoiler.mockReturnValue(null);
		mockRedisIncr.mockResolvedValue(1);
		mockRedisExpire.mockResolvedValue(undefined);
		mockRedisDecr.mockResolvedValue(0);
		mockHasImageGenerationCapability.mockResolvedValue(false);
		mockGenerateImageForPost.mockResolvedValue(null);
		setupDbMock();
	});

	// =====================================================================
	// 1. Basic insertion — correct fields in auto_post_queue
	// =====================================================================
	describe("queue item insertion", () => {
		it("inserts candidate with correct fields into auto_post_queue", async () => {
			const candidate = makeCandidate({ content: "hello world" });
			const ctx = makeContext();
			const slots = [makeSlot("acc-1")];

			const result = await insertCandidatesIntoQueue([candidate], slots, ctx);

			expect(result.insertedCount).toBe(1);
			expect(result.failedCount).toBe(0);
			expect(result.insertedContents).toContain("hello world");

			// Verify insert was called on auto_post_queue
			const fromCall = mockFrom.mock.calls.find((c) => c[0] === "auto_post_queue");
			expect(fromCall).toBeDefined();
		});

		it("sets source_type to 'ai' for non-competitor content", async () => {
			let capturedInsertData: Record<string, unknown> | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: [], error: null }),
							}),
						}),
					}),
				};
			});

			await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-1")],
				makeContext(),
			);

			expect(capturedInsertData).not.toBeNull();
			expect(capturedInsertData!.source_type).toBe("ai");
			expect(capturedInsertData!.workspace_id).toBe("ws-1");
			expect(capturedInsertData!.status).toBe("pending");
			expect(capturedInsertData!.group_id).toBe("grp-1");
		});

		it("routes brand-new unproven accounts to manual review by default", async () => {
			let capturedInsertData: Record<string, unknown> | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q-new" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				if (table === "user_settings") {
					return createChainMock({ data: null, error: null });
				}
				if (table === "autoposter_post_performance_facts") {
					return {
						select: vi.fn().mockReturnThis(),
						eq: vi.fn().mockReturnThis(),
						not: vi.fn().mockReturnThis(),
						order: vi.fn().mockReturnThis(),
						limit: vi.fn().mockResolvedValue({ data: [], error: null }),
					};
				}
				return createChainMock({ data: null, error: null });
			});

			await insertCandidatesIntoQueue(
				[makeCandidate({ content: "would you date a girl who lifts?" })],
				[makeSlot("brand-new-account")],
				makeContext(),
			);

			expect(capturedInsertData).toMatchObject({
				status: "needs_review",
			});
			expect(capturedInsertData!.metadata).toMatchObject({
				approval: {
					reason: "account_unproven_manual_review_required",
					explicit_threshold: false,
					account_autopublish_proven: false,
				},
			});
			expect(mockQstashPublishJSON).not.toHaveBeenCalled();
		});

		it("stamps canonical timing, warm-up, and planned-account metadata on pool-mode Threads rows", async () => {
			let capturedInsertData: Record<string, unknown> | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						select: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnThis(),
							in: vi.fn().mockReturnThis(),
							gte: vi.fn().mockReturnThis(),
							lt: vi.fn().mockResolvedValue({ data: [], error: null }),
						}),
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: [], error: null }),
							}),
						}),
					}),
				};
			});

			await insertCandidatesIntoQueue(
				[
					{
						...makeCandidate({
							content: "warm-up timing fixture",
							scheduledFor: "2026-06-06T15:17:22.000Z",
						}),
						timing: {
							selectedHour: 11,
							timingReason: "warmup_primary_hour",
							confidence: 0.4,
							fallbackSource: "warmup_primary",
							sampleSize: 3,
						},
					},
				],
				[makeWarmupSlot("acc-1")],
				makeContext({ schedulerVersion: 4 }),
			);

			expect(capturedInsertData).not.toBeNull();
			expect(capturedInsertData!.account_id).toBeUndefined();
			expect(capturedInsertData!.pool_status).toBe("available");
			const metadata = capturedInsertData!.metadata as Record<string, any>;
			expect(metadata.timing).toMatchObject({
				reason: "warmup_primary_hour",
				timingReason: "warmup_primary_hour",
				selectedHour: expect.any(Number),
				selectedMinute: expect.any(Number),
				timezone: "America/New_York",
				warmupApplied: true,
				accountWindow: { start: 6, end: 13 },
			});
			expect(metadata.timing).toHaveProperty("jitterMinutes");
			expect(metadata.restart_warmup).toMatchObject({
				status: "warming",
				day: 1,
				maxPostsToday: 1,
				primaryHoursOnly: true,
				textOnly: true,
				reason: "restart_warmup_day_1",
			});
			expect(metadata.planned_account).toMatchObject({
				accountId: "acc-1",
				candidateAccountIds: ["acc-1"],
				accountWindow: { start: 6, end: 13 },
				minIntervalMinutes: 180,
				timezone: "America/New_York",
				warmupCap: 1,
				timingReason: "warmup_primary_hour",
			});
		});

		it("jitters ready Threads rows away from existing same-minute workspace collisions", async () => {
			let capturedInsertData: Record<string, unknown> | null = null;
			let collisionChecks = 0;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						select: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnThis(),
							in: vi.fn().mockReturnThis(),
							gte: vi.fn().mockReturnThis(),
							lt: vi.fn().mockImplementation(() => {
								collisionChecks++;
								return Promise.resolve({
									data: collisionChecks === 1 ? [{ id: "existing" }] : [],
									error: null,
								});
							}),
						}),
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: [], error: null }),
							}),
						}),
					}),
				};
			});

			await insertCandidatesIntoQueue(
				[
					makeCandidate({
						content: "collision guard fixture",
						scheduledFor: "2026-06-06T15:17:22.000Z",
					}),
				],
				[makeSlot("acc-1")],
				makeContext({ schedulerVersion: 4 }),
			);

			expect(collisionChecks).toBeGreaterThanOrEqual(2);
			expect(capturedInsertData).not.toBeNull();
			expect(capturedInsertData!.scheduled_for).not.toBe(
				"2026-06-06T15:17:22.000Z",
			);
			const metadata = capturedInsertData!.metadata as Record<string, any>;
			expect(metadata.timing.sameMinuteGuardApplied).toBe(true);
			expect(metadata.timing.sameMinuteGuardShiftSeconds).toBeGreaterThanOrEqual(60);
		});

		it("does not insert a ready warm-up row when existing claimable rows already use the account cap", async () => {
			let insertCalled = false;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					const chain: Record<string, any> = {};
					for (const method of ["select", "eq", "in", "or", "gte", "lt"]) {
						chain[method] = vi.fn(() => chain);
					}
					chain.catch = undefined;
					chain.finally = undefined;
					chain.insert = vi.fn(() => {
						insertCalled = true;
						return {
							select: vi.fn().mockReturnValue({
								single: vi.fn().mockResolvedValue({
									data: { id: "q1" },
									error: null,
								}),
							}),
						};
					});
					chain.then = (
						resolve: (value: unknown) => void,
						reject?: (err: unknown) => void,
					) =>
						Promise.resolve({
							data: [
								{
									id: "existing",
									account_id: "acc-1",
									status: "queued",
									scheduled_for: "2026-06-06T15:00:00.000Z",
									metadata: {},
								},
							],
							error: null,
						}).then(resolve, reject);
					return chain;
				}
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: [], error: null }),
							}),
						}),
					}),
				};
			});

			const result = await insertCandidatesIntoQueue(
				[
					makeCandidate({
						content: "warm-up cap fixture",
						scheduledFor: "2026-06-06T16:00:00.000Z",
					}),
				],
				[makeWarmupSlot("acc-1")],
				makeContext({ schedulerVersion: 4 }),
			);

			expect(insertCalled).toBe(false);
			expect(result.insertedCount).toBe(0);
			expect(result.rejectedCount).toBe(1);
			expect(result.rejectionReasons.warmup_cap_exceeded).toBe(1);
		});

		it("attaches account DNA scores and review status to off-DNA candidates", async () => {
			let capturedInsertData: Record<string, unknown> | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "account_dna") {
					return {
						select: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								eq: vi.fn().mockReturnValue({
									eq: vi.fn().mockReturnValue({
										order: vi.fn().mockReturnValue({
											limit: vi.fn().mockReturnValue({
												maybeSingle: vi.fn().mockResolvedValue({
													data: {
														id: "11111111-1111-4111-8111-111111111111",
														workspace_id: "ws-1",
														group_id: "grp-1",
														account_id: "acc-1",
														version: 1,
														status: "active",
														confidence: 0.9,
														archetype: "soft_gfe",
														follower_promise: "late-night comfort",
														identity_summary: "soft lonely late-night texter",
														backstory_facts: [],
														recurring_motifs: ["2am", "playlist"],
														recurring_situations: [],
														signature_beliefs: [],
														primary_topics: ["dating"],
														secondary_topics: ["night"],
														taboo_topics: ["gym"],
														signature_phrases: ["miss you"],
														banned_phrases: ["leg day"],
														vocabulary_fingerprint: {
															signature_words: ["miss", "night"],
															avoid_words: ["protein"],
														},
														emoji_policy: "none",
														punctuation_habits: {},
														casing_style: "lowercase",
														average_length_min: 20,
														average_length_max: 120,
														emotional_baseline: "vulnerable",
														allowed_mood_range: ["vulnerable", "warm"],
														cta_posture: "soft",
														controversy_level: 1,
														humor_level: 1,
														storytelling_tendency: 3,
														vulnerability_level: 5,
														flirt_level: 3,
													},
													error: null,
												}),
											}),
										}),
									}),
								}),
							}),
						}),
					};
				}
				if (table === "account_dna_rules") {
					return {
						select: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								or: vi.fn().mockResolvedValue({ data: [], error: null }),
								neq: vi.fn().mockReturnValue({
									in: vi.fn().mockReturnValue({
										or: vi.fn().mockReturnValue({
											eq: vi.fn().mockResolvedValue({
												data: [
													{
														id: "rule-1",
														account_id: "acc-2",
														rule_type: "owned_phrase",
														rule_value: "gg",
														action: "block",
														severity: "critical",
														weight: 1,
													},
												],
												error: null,
											}),
										}),
									}),
								}),
							}),
						}),
					};
				}
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: [], error: null }),
							}),
						}),
					}),
				};
			});

			await insertCandidatesIntoQueue(
				[
					makeCandidate({
						content: "gg leg day made me feel like a different breed",
						viralScore: 94,
					}),
				],
				[makeSlot("acc-1")],
				makeContext(),
			);

			expect(capturedInsertData).not.toBeNull();
			expect(capturedInsertData!.status).toBe("needs_review");
			expect(capturedInsertData!.dna_id).toBe(
				"11111111-1111-4111-8111-111111111111",
			);
			expect(capturedInsertData!.dna_decision).toBe("needs_review");
			expect(capturedInsertData!.dna_fit_score).toEqual(expect.any(Number));
			expect(capturedInsertData!.sibling_collision_score).toEqual(
				expect.any(Number),
			);
		});

		it("sets source_type to 'competitor_copy' when sourceCompetitorId is present", async () => {
			let capturedInsertData: Record<string, unknown> | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: [], error: null }),
							}),
						}),
					}),
				};
			});

			await insertCandidatesIntoQueue(
				[
					makeCandidate({
						sourceCompetitorId: "comp-1",
						sourceCompetitorUsername: "competitor_user",
					}),
				],
				[makeSlot("acc-1")],
				makeContext(),
			);

			expect(capturedInsertData!.source_type).toBe("competitor_copy");
			expect(capturedInsertData!.source_competitor_id).toBe("comp-1");
			expect(capturedInsertData!.source_competitor_username).toBe(
				"competitor_user",
			);
		});

		it("rejects taxonomy leakage before a row can become queued", async () => {
			let insertCalled = false;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockImplementation(() => {
							insertCalled = true;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: [], error: null }),
							}),
						}),
					}),
				};
			});

			const result = await insertCandidatesIntoQueue(
				[
					makeCandidate({
						content:
							"anime_dateability_question: would you date a girl who loves anime lore",
					}),
				],
				[makeSlot("acc-1")],
				makeContext(),
			);

			expect(insertCalled).toBe(false);
			expect(result.insertedCount).toBe(0);
			expect(result.rejectedCount).toBe(1);
			expect(result.rejectionReasons["structural-taxonomy-label"]).toBe(1);
		});

		it("assigns account_id from planned slot in legacy mode", async () => {
			let capturedInsertData: Record<string, unknown> | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: [], error: null }),
							}),
						}),
					}),
				};
			});

			await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-42")],
				makeContext({ schedulerVersion: 2 }),
			);

			expect(capturedInsertData!.account_id).toBe("acc-42");
			expect(capturedInsertData!.pool_status).toBeUndefined();
		});

		it("sets pool_status='available' without account_id in pool mode (v3+)", async () => {
			let capturedInsertData: Record<string, unknown> | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: [], error: null }),
							}),
						}),
					}),
				};
			});

			await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-42")],
				makeContext({ schedulerVersion: 3 }),
			);

			expect(capturedInsertData!.pool_status).toBe("available");
			expect(capturedInsertData!.account_id).toBeUndefined();
		});

		it("includes ai_provider from context", async () => {
			let capturedInsertData: Record<string, unknown> | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: [], error: null }),
							}),
						}),
					}),
				};
			});

			await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-1")],
				makeContext({ aiConfig: { provider: "xai", model: "grok-4-1-fast" } }),
			);

			expect(capturedInsertData!.ai_provider).toBe("xai");
		});

		it("routes quality-gate uncertainty to needs_review and does not dispatch QStash", async () => {
			let capturedInsertData: Record<string, unknown> | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: [], error: null }),
							}),
						}),
					}),
				};
			});

			await insertCandidatesIntoQueue(
				[
					makeCandidate({
						qualityGate: {
							decision: "needs_review",
							reason: "confidence:uncertain_content",
							confidences: {
								qualityConfidence: 0.34,
								brandConfidence: 0.86,
								noveltyConfidence: 0.84,
								riskConfidence: 0.9,
								expectedOutcomeConfidence: 0.62,
							},
							flags: [],
							score: {
								replyTrigger: 1,
								emotionalWarmth: 3,
								overall: 1.7,
								rejectReason: null,
							},
						},
					}),
				],
				[makeSlot("acc-1")],
				makeContext(),
			);

			expect(capturedInsertData!.status).toBe("needs_review");
			expect(capturedInsertData!.metadata).toMatchObject({
				approval: {
					reason: "confidence:uncertain_content",
					quality_gate_decision: "needs_review",
				},
				quality_gate: {
					decision: "needs_review",
					confidences: {
						qualityConfidence: 0.34,
						expectedOutcomeConfidence: 0.62,
					},
				},
			});
			expect(mockQstashPublishJSON).not.toHaveBeenCalled();
		});

		it("stamps performance-backed quality gate lane metadata for proven winner clones", async () => {
			let capturedInsertData: Record<string, unknown> | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return {
					select: vi.fn().mockReturnThis(),
					eq: vi.fn().mockReturnThis(),
					in: vi.fn().mockReturnThis(),
					gte: vi.fn().mockReturnThis(),
					order: vi.fn().mockReturnThis(),
					limit: vi.fn().mockResolvedValue({ data: [], error: null }),
					maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
				};
			});

			await insertCandidatesIntoQueue(
				[
					makeCandidate({
						content: "would you date a girl who's obsessed with anime lore?",
						sourceCompetitorId: "comp-1",
						sourceContent: "would you date a girl who's obsessed with anime lore?",
						sourcePatternId: "winner-pattern-1",
						qualityGate: {
							decision: "needs_review",
							reason: "policy:competitor_inspired_content",
							confidences: {
								qualityConfidence: 0.48,
								brandConfidence: 0.86,
								noveltyConfidence: 0.68,
								riskConfidence: 0.9,
								expectedOutcomeConfidence: 0.86,
							},
							flags: [],
							score: {
								replyTrigger: 5,
								emotionalWarmth: 3,
								overall: 2.4,
								rejectReason: null,
							},
						},
					}),
				],
				[makeSlot("acc-1")],
				makeContext({
					strategyRecommendations: [
						{
							id: "rec-1",
							workspace_id: "ws-1",
							group_id: "grp-1",
							account_id: null,
							pattern_type: "winner_clone",
							pattern_value: "anime_dateability_question",
							recommendation: "increase",
							confidence: 0.84,
							reason: "winner_clone_views_above_100",
							metric_basis: {
								cloneFamily: "single_cook_clean_identity",
								sourceText:
									"would you date a girl who's obsessed with anime lore?",
								winnerPatternId: "winner-pattern-1",
								performanceBasis: "views_above_100",
							},
							expires_at: new Date(Date.now() + 86_400_000).toISOString(),
						} as any,
					],
				}),
			);

			expect(capturedInsertData).not.toBeNull();
			expect(capturedInsertData!.status).toBe("pending");
			expect(capturedInsertData!.metadata).toMatchObject({
				quality_gate_lane: "performance_backed_clone",
				quality_gate_reason: "winner_clone_performance_evidence",
				quality_gate: {
					decision: "pass",
					reason: "winner_clone_performance_evidence",
					lane: "performance_backed_clone",
				},
				performance_backed_clone: {
					clone_family: "anime_dateability_question",
					source_pattern_id: "winner-pattern-1",
					strategy_recommendation_id: "rec-1",
				},
			});
		});

		it("routes frame-mismatched winner clones to review instead of ready", async () => {
			let capturedInsertData: Record<string, unknown> | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return {
					select: vi.fn().mockReturnThis(),
					eq: vi.fn().mockReturnThis(),
					in: vi.fn().mockReturnThis(),
					gte: vi.fn().mockReturnThis(),
					order: vi.fn().mockReturnThis(),
					limit: vi.fn().mockResolvedValue({ data: [], error: null }),
					maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
				};
			});

			await insertCandidatesIntoQueue(
				[
					makeCandidate({
						content:
							"what's the one manga panel that lives rent free in your head? deadass",
						sourcePatternId: "winner-pattern-1",
						qualityGate: {
							decision: "needs_review",
							reason: "confidence:uncertain_content",
							confidences: {
								qualityConfidence: 0.48,
								brandConfidence: 0.86,
								noveltyConfidence: 0.68,
								riskConfidence: 0.9,
								expectedOutcomeConfidence: 0.86,
							},
							flags: [],
							score: {
								replyTrigger: 5,
								emotionalWarmth: 4,
								overall: 2.4,
								rejectReason: null,
							},
						},
					}),
				],
				[makeSlot("acc-1")],
				makeContext({
					strategyRecommendations: [
						{
							id: "rec-1",
							workspace_id: "ws-1",
							group_id: "grp-1",
							account_id: null,
							pattern_type: "winner_clone",
							pattern_value: "single_cook_clean_identity",
							recommendation: "increase",
							confidence: 0.84,
							reason: "winner_clone_views_above_100",
							metric_basis: {
								cloneFamily: "single_cook_clean_identity",
								sourceText:
									"i'm single. i don't need your money. i don't smoke. i'm not a bad person. i can cook",
								winnerPatternId: "winner-pattern-1",
								performanceBasis: "views_above_100",
							},
							expires_at: new Date(Date.now() + 86_400_000).toISOString(),
						} as any,
					],
				}),
			);

			expect(capturedInsertData).not.toBeNull();
			expect(capturedInsertData!.status).toBe("needs_review");
			expect(capturedInsertData!.metadata).toMatchObject({
				approval: {
					reason: "winner_clone_frame_mismatch",
				},
				winner_clone: {
					clone_family: "single_cook_clean_identity",
					frame_mismatch: true,
					frame_alignment_score: -90,
				},
			});
		});

			it("attributes winner clone variations by clone family when source pattern id is missing", async () => {
			let capturedInsertData: Record<string, unknown> | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return {
					select: vi.fn().mockReturnThis(),
					eq: vi.fn().mockReturnThis(),
					in: vi.fn().mockReturnThis(),
					gte: vi.fn().mockReturnThis(),
					order: vi.fn().mockReturnThis(),
					limit: vi.fn().mockResolvedValue({ data: [], error: null }),
					maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
				};
			});

			await insertCandidatesIntoQueue(
				[
					makeCandidate({
						content: "took off my gaming headset. am i still cute?",
						sourcePatternId: undefined,
						qualityGate: {
							decision: "needs_review",
							reason: "confidence:uncertain_content",
							confidences: {
								qualityConfidence: 0.52,
								brandConfidence: 0.86,
								noveltyConfidence: 0.84,
								riskConfidence: 0.9,
								expectedOutcomeConfidence: 0.86,
							},
							flags: [],
							score: {
								replyTrigger: 3,
								emotionalWarmth: 4,
								overall: 2.6,
								rejectReason: null,
							},
						},
					}),
				],
				[makeSlot("acc-1")],
				makeContext({
					strategyRecommendations: [
						{
							id: "rec-headset",
							workspace_id: "ws-1",
							group_id: "grp-1",
							account_id: null,
							pattern_type: "winner_clone",
							pattern_value: "post-headset-winner",
							recommendation: "increase",
							confidence: 0.82,
							reason: "winner_clone_views_above_100",
							metric_basis: {
								sourcePostId: "post-headset-winner",
								sourcePatternId: "post-headset-winner",
								cloneFamily: "headset_cute_validation",
								performanceBasis: "views_above_100",
							},
							expires_at: new Date(Date.now() + 86_400_000).toISOString(),
						} as any,
					],
				}),
			);

			expect(capturedInsertData).not.toBeNull();
			expect(capturedInsertData!.status).toBe("pending");
			expect(capturedInsertData).toMatchObject({
				source_pattern_id: "post-headset-winner",
				strategy_recommendation_id: "rec-headset",
				strategy_bucket: "proven",
			});
			expect(capturedInsertData!.metadata).toMatchObject({
				quality_gate_lane: "performance_backed_clone",
				performance_backed_clone: {
					clone_family: "headset_cute_validation",
					source_pattern_id: "post-headset-winner",
					strategy_recommendation_id: "rec-headset",
					strategy_bucket: "proven",
				},
				});
			});

			it("honors explicit winner-clone recommendation ids carried by generated ideas", async () => {
				let capturedInsertData: Record<string, unknown> | null = null;
				mockFrom.mockImplementation((table: string) => {
					if (table === "user_settings") {
						return createChainMock({
							data: { setting_value: { threshold: 50 } },
							error: null,
						});
					}
					if (table === "auto_post_queue") {
						return {
							insert: vi.fn().mockImplementation((data: unknown) => {
								capturedInsertData = data as Record<string, unknown>;
								return {
									select: vi.fn().mockReturnValue({
										single: vi.fn().mockResolvedValue({
											data: { id: "q1" },
											error: null,
										}),
									}),
								};
							}),
						};
					}
					return {
						select: vi.fn().mockReturnThis(),
						eq: vi.fn().mockReturnThis(),
						in: vi.fn().mockReturnThis(),
						gte: vi.fn().mockReturnThis(),
						order: vi.fn().mockReturnThis(),
						limit: vi.fn().mockResolvedValue({ data: [], error: null }),
						maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
					};
				});

				await insertCandidatesIntoQueue(
					[
						makeCandidate({
							content: "i'm single. i don't smoke. i can cook",
							strategyRecommendationId: "rec-single",
							winnerClone: true,
							cloneFamily: "single_cook_clean_identity",
							qualityGate: {
								decision: "needs_review",
								reason: "confidence:uncertain_content",
								confidences: {
									qualityConfidence: 0.52,
									brandConfidence: 0.86,
									noveltyConfidence: 0.84,
									riskConfidence: 0.9,
									expectedOutcomeConfidence: 0.86,
								},
								flags: [],
								score: {
									replyTrigger: 2,
									emotionalWarmth: 4,
									overall: 2.7,
									rejectReason: null,
								},
							},
						}),
					],
					[makeSlot("acc-1")],
					makeContext({
						strategyRecommendations: [
							{
								id: "rec-single",
								workspace_id: "ws-1",
								group_id: "grp-1",
								account_id: null,
								pattern_type: "winner_clone",
								pattern_value: "post-single-winner",
								recommendation: "increase",
								confidence: 0.9,
								reason: "winner_clone_views_above_100",
								metric_basis: {
									sourcePostId: "post-single-winner",
									sourcePatternId: "post-single-winner",
									cloneFamily: "single_cook_clean_identity",
									performanceBasis: "views_above_100",
								},
								expires_at: new Date(Date.now() + 86_400_000).toISOString(),
							} as any,
						],
					}),
				);

				expect(capturedInsertData).toMatchObject({
					status: "pending",
					source_pattern_id: "post-single-winner",
					strategy_recommendation_id: "rec-single",
					strategy_bucket: "proven",
				});
				expect(capturedInsertData!.metadata).toMatchObject({
					winner_clone_applied: true,
					winner_clone: {
						clone_family: "single_cook_clean_identity",
						strategy_recommendation_id: "rec-single",
					},
					quality_gate_lane: "performance_backed_clone",
				});
			});

			it("keeps duplicate fingerprint matches in review even with performance-backed lane", async () => {
			let capturedInsertData: Record<string, unknown> | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					const duplicateQuery = {
						eq: vi.fn().mockReturnThis(),
						in: vi.fn().mockReturnThis(),
						gte: vi.fn().mockReturnThis(),
						order: vi.fn().mockReturnThis(),
						limit: vi.fn().mockResolvedValue({
							data: [
								{
									id: "dup-1",
									status: "published",
									account_id: "acc-1",
									threads_post_id: "threads-1",
									posted_at: new Date().toISOString(),
									created_at: new Date().toISOString(),
									publish_fingerprint: "same",
								},
							],
							error: null,
						}),
					};
					return {
						select: vi.fn().mockReturnValue(duplicateQuery),
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return {
					select: vi.fn().mockReturnThis(),
					eq: vi.fn().mockReturnThis(),
					in: vi.fn().mockReturnThis(),
					gte: vi.fn().mockReturnThis(),
					order: vi.fn().mockReturnThis(),
					limit: vi.fn().mockResolvedValue({ data: [], error: null }),
					maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
				};
			});

			await insertCandidatesIntoQueue(
				[
					makeCandidate({
						content: "would you date a girl who's obsessed with anime lore?",
						sourceCompetitorId: "comp-1",
						sourceContent: "would you date a girl who's obsessed with anime lore?",
						sourcePatternId: "winner-pattern-1",
						qualityGate: {
							decision: "needs_review",
							reason: "policy:competitor_inspired_content",
							confidences: {
								qualityConfidence: 0.48,
								brandConfidence: 0.86,
								noveltyConfidence: 0.68,
								riskConfidence: 0.9,
								expectedOutcomeConfidence: 0.86,
							},
							flags: [],
							score: {
								replyTrigger: 5,
								emotionalWarmth: 3,
								overall: 2.4,
								rejectReason: null,
							},
						},
					}),
				],
				[makeSlot("acc-1")],
				makeContext({
					strategyRecommendations: [
						{
							id: "rec-1",
							workspace_id: "ws-1",
							group_id: "grp-1",
							account_id: null,
							pattern_type: "winner_clone",
							pattern_value: "anime_dateability_question",
							recommendation: "increase",
							confidence: 0.84,
							reason: "winner_clone_views_above_100",
							metric_basis: {
								cloneFamily: "anime_dateability_question",
								winnerPatternId: "winner-pattern-1",
							},
							expires_at: new Date(Date.now() + 86_400_000).toISOString(),
						} as any,
					],
				}),
			);

			expect(capturedInsertData).not.toBeNull();
			expect(capturedInsertData!.status).toBe("needs_review");
			expect(capturedInsertData!.metadata).toMatchObject({
				quality_gate_lane: "performance_backed_clone",
				approval: {
					reason: "duplicate_fingerprint_needs_review",
				},
			});
			expect(capturedInsertData!.duplicate_of_queue_item_id).toBe("dup-1");
		});
	});

	// =====================================================================
	// 2. maxInserts cap — never exceed daily limit
	// =====================================================================
	describe("cap checking before insert", () => {
		it("stops inserting when maxInserts is reached", async () => {
			const candidates = Array.from({ length: 5 }, (_, i) =>
				makeCandidate({ content: `post ${i}` }),
			);
			const slots = candidates.map((_, i) => makeSlot(`acc-${i}`, i));
			const ctx = makeContext({ maxInserts: 2 });

			const result = await insertCandidatesIntoQueue(candidates, slots, ctx);

			expect(result.insertedCount).toBe(2);
		});

		it("stops inserting when planned slots are exhausted in legacy mode", async () => {
			const candidates = Array.from({ length: 5 }, (_, i) =>
				makeCandidate({ content: `post ${i}` }),
			);
			const slots = [makeSlot("acc-1", 0), makeSlot("acc-2", 1)];
			const ctx = makeContext({ schedulerVersion: 1 });

			const result = await insertCandidatesIntoQueue(candidates, slots, ctx);

			expect(result.insertedCount).toBe(2);
		});

		it("stops at slot exhaustion in Threads pool mode so rows keep planned constraints", async () => {
			const candidates = Array.from({ length: 4 }, (_, i) =>
				makeCandidate({ content: `pool post ${i}` }),
			);
			const slots = [makeSlot("acc-1", 0)]; // only 1 slot
			const ctx = makeContext({
				schedulerVersion: 3,
				maxInserts: 10,
				targetPlatform: "threads",
			});

			const result = await insertCandidatesIntoQueue(candidates, slots, ctx);

			expect(result.insertedCount).toBe(1);
		});
	});

	// =====================================================================
	// 3. Competitor batch cap — limits competitor content within batch
	// =====================================================================
	describe("competitor batch cap", () => {
		it("rejects competitor posts exceeding batch ratio", async () => {
			// DIRECT_COMPETITOR_SHARE = 0.8, maxInserts=5 => max 4 competitor in batch
			const candidates = Array.from({ length: 6 }, (_, i) =>
				makeCandidate({
					content: `competitor post ${i}`,
					sourceCompetitorId: `comp-${i}`,
					sourceCompetitorUsername: `user-${i}`,
				}),
			);
			const slots = candidates.map((_, i) => makeSlot(`acc-${i}`, i));
			const ctx = makeContext({ maxInserts: 5 });

			const result = await insertCandidatesIntoQueue(candidates, slots, ctx);

			// 0.8 * 5 = 4 competitor posts max; 5th (index 4) is competitor that exceeds cap
			expect(result.insertedCount).toBe(4);
			expect(result.rejectedCount).toBeGreaterThanOrEqual(1);
			expect(result.rejectionReasons["competitor-batch-cap"]).toBeGreaterThanOrEqual(1);
		});
	});

	// =====================================================================
	// 4. Cross-account competitor dedup (Redis)
	// =====================================================================
	describe("cross-account competitor dedup", () => {
		it("rejects competitor post when >15 accounts already adapted it", async () => {
			mockRedisIncr.mockResolvedValue(16);

			const candidates = [
				makeCandidate({
					content: "widely copied post",
					sourceCompetitorId: "comp-popular",
				}),
			];
			const slots = [makeSlot("acc-1")];
			const ctx = makeContext();

			const result = await insertCandidatesIntoQueue(candidates, slots, ctx);

			expect(result.rejectedCount).toBe(1);
			expect(
				result.rejectionReasons["competitor-dedup-15-accounts"],
			).toBe(1);
			// Should decrement after exceeding limit
			expect(mockRedisDecr).toHaveBeenCalled();
		});

		it("sets TTL on first Redis increment", async () => {
			mockRedisIncr.mockResolvedValue(1);

			const candidates = [
				makeCandidate({
					content: "fresh competitor post",
					sourceCompetitorId: "comp-fresh",
				}),
			];
			const slots = [makeSlot("acc-1")];
			const ctx = makeContext();

			await insertCandidatesIntoQueue(candidates, slots, ctx);

			expect(mockRedisExpire).toHaveBeenCalledWith(
				"competitor-adapted:comp-fresh",
				48 * 60 * 60,
			);
		});

		it("does not set TTL on subsequent increments", async () => {
			mockRedisIncr.mockResolvedValue(5);

			const candidates = [
				makeCandidate({
					content: "existing competitor post",
					sourceCompetitorId: "comp-existing",
				}),
			];
			const slots = [makeSlot("acc-1")];
			const ctx = makeContext();

			await insertCandidatesIntoQueue(candidates, slots, ctx);

			expect(mockRedisExpire).not.toHaveBeenCalled();
		});
	});

	// =====================================================================
	// 5. QStash delayed dispatch
	// =====================================================================
	describe("QStash delayed dispatch", () => {
		it("shifts ready Threads rows away from existing planned-account min interval conflicts", async () => {
			let capturedInsertData: Record<string, unknown> | null = null;
			const existingScheduledFor = "2026-06-10T06:02:00.000Z";
			const proposedScheduledFor = "2026-06-10T06:03:00.000Z";
			const autoPostQuery = {
				eq: vi.fn().mockReturnThis(),
				in: vi.fn().mockReturnThis(),
				gte: vi.fn().mockReturnThis(),
				lte: vi.fn().mockResolvedValue({
					data: [
						{
							id: "existing-ready",
							account_id: "acc-1",
							scheduled_for: existingScheduledFor,
							metadata: {
								planned_account: { accountId: "acc-1" },
							},
						},
					],
					error: null,
				}),
				lt: vi.fn().mockResolvedValue({ data: [], error: null }),
			};
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						select: vi.fn().mockReturnValue(autoPostQuery),
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: [], error: null }),
							}),
						}),
					}),
				};
			});

			await insertCandidatesIntoQueue(
				[makeCandidate({ scheduledFor: proposedScheduledFor })],
				[
					{
						...makeSlot("acc-1"),
						timezone: "America/New_York",
						minIntervalMinutes: 180,
					},
				],
				makeContext(),
			);

			expect(capturedInsertData).not.toBeNull();
			const scheduledFor = new Date(
				capturedInsertData?.scheduled_for as string,
			).getTime();
			expect(scheduledFor).toBeGreaterThan(
				new Date(existingScheduledFor).getTime() + 180 * 60_000,
			);
			expect(
				(capturedInsertData?.metadata as Record<string, unknown>)?.timing,
			).toMatchObject({
				accountMinIntervalGuardApplied: true,
				accountMinIntervalGuardConflictCount: 1,
			});
		});

		it("dispatches QStash with notBefore matching scheduled_for", async () => {
			const scheduledFor = new Date(
				Date.now() + 2 * 3600000,
			).toISOString();
			const candidates = [makeCandidate({ scheduledFor })];
			const slots = [makeSlot("acc-1")];
			const ctx = makeContext();

			await insertCandidatesIntoQueue(candidates, slots, ctx);

			expect(mockQstashPublishJSON).toHaveBeenCalledTimes(1);
			const qstashArgs = mockQstashPublishJSON.mock.calls[0][0];
			expect(qstashArgs.url).toBe(
				"https://test.example.com/api/auto-post-publish",
			);
			expect(qstashArgs.retries).toBe(3); // RETRIES.CRITICAL
			expect(qstashArgs.failureCallback).toBe(
				"https://test.example.com/api/qstash-failure",
			);
			expect(qstashArgs.body.queueItemId).toBe("q1");
			expect(qstashArgs.body.workspaceId).toBe("ws-1");
			expect(qstashArgs.body.groupId).toBe("grp-1");
			expect(qstashArgs.body.ownerId).toBe("user-1");
		});

		it("includes accountId in QStash body when planned slot exists", async () => {
			const candidates = [makeCandidate()];
			const slots = [makeSlot("acc-99")];
			const ctx = makeContext();

			await insertCandidatesIntoQueue(candidates, slots, ctx);

			const qstashArgs = mockQstashPublishJSON.mock.calls[0][0];
			expect(qstashArgs.body.accountId).toBe("acc-99");
		});

		it("does not insert Threads pool-mode rows without planned constraints", async () => {
			let capturedInsertData: Record<string, unknown> | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						select: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnThis(),
							in: vi.fn().mockReturnThis(),
							gte: vi.fn().mockReturnThis(),
							lt: vi.fn().mockResolvedValue({ data: [], error: null }),
						}),
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: [], error: null }),
							}),
						}),
					}),
				};
			});
			const candidates = [makeCandidate()];
			const slots: Array<{ accountId: string; roundRobinIndex: number }> = [];
			const ctx = makeContext({ schedulerVersion: 3 }); // pool mode

			const result = await insertCandidatesIntoQueue(candidates, slots, ctx);

			expect(result.insertedCount).toBe(0);
			expect(capturedInsertData).toBeNull();
			expect(mockQstashPublishJSON).not.toHaveBeenCalled();
		});

		it("calls ensureQueueItemScheduleNonce before dispatch", async () => {
			await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-1")],
				makeContext(),
			);

			expect(mockEnsureQueueItemScheduleNonce).toHaveBeenCalledWith(
				"q1",
				expect.stringContaining("auto-post-q1-"),
			);
		});

		it("calls rescheduleQueueItemForFutureDispatch after dispatch", async () => {
			await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-1")],
				makeContext(),
			);

			expect(
				mockRescheduleQueueItemForFutureDispatch,
			).toHaveBeenCalledWith("q1", {
				accountId: "acc-1",
				scheduledFor: expect.any(String),
				scheduleNonce: "nonce-1",
				qstashMessageId: "msg-1",
			});
		});

		it("records infra event after successful dispatch", async () => {
			await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-1")],
				makeContext(),
			);

			expect(mockRecordInfraEvent).toHaveBeenCalledWith(
				"autopost-fill-dispatch",
				expect.objectContaining({
					queueItemId: "q1",
					scheduleNonce: "nonce-1",
					qstashMessageId: "msg-1",
					groupId: "grp-1",
					workspaceId: "ws-1",
				}),
			);
		});

		it("skips QStash dispatch when groupId is undefined", async () => {
			const candidates = [makeCandidate()];
			const slots: Array<{ accountId: string; roundRobinIndex: number }> = [];
			const ctx = makeContext({ groupId: undefined, schedulerVersion: 3 });

			await insertCandidatesIntoQueue(candidates, slots, ctx);

			expect(mockQstashPublishJSON).not.toHaveBeenCalled();
		});
	});

	// =====================================================================
	// 6. QStash failure — best-effort, item still inserted
	// =====================================================================
	describe("QStash failure handling", () => {
		it("still counts insertion as success when QStash dispatch fails", async () => {
			mockQstashPublishJSON.mockRejectedValue(new Error("QStash down"));

			const result = await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-1")],
				makeContext(),
			);

			expect(result.insertedCount).toBe(1);
			expect(result.failedCount).toBe(0);
			expect(mockLoggerWarn).toHaveBeenCalledWith(
				"QStash dispatch failed, cron will pick up",
				expect.objectContaining({
					error: "Error: QStash down",
					queueItemId: "q1",
				}),
			);
		});

		it("records infra failure event when QStash dispatch fails", async () => {
			mockQstashPublishJSON.mockRejectedValue(
				new Error("QStash timeout"),
			);

			await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-1")],
				makeContext(),
			);

			expect(mockRecordInfraEvent).toHaveBeenCalledWith(
				"autopost-fill-dispatch-failed",
				expect.objectContaining({
					queueItemId: "q1",
					error: expect.stringContaining("QStash timeout"),
				}),
			);
		});
	});

	// =====================================================================
	// 7. DB insert failure
	// =====================================================================
	describe("DB insert failure handling", () => {
		it("increments failedCount on DB insert error", async () => {
			setupDbMock({
				insertResult: {
					data: null,
					error: new Error("unique constraint violation"),
				},
			});

			const result = await insertCandidatesIntoQueue(
				[makeCandidate({ content: "duplicate post" })],
				[makeSlot("acc-1")],
				makeContext(),
			);

			expect(result.insertedCount).toBe(0);
			expect(result.failedCount).toBe(1);
			expect(result.errors).toHaveLength(1);
			expect(result.errors[0].error).toContain("unique constraint");
		});

		it("increments failedCount on unexpected exception during insert", async () => {
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockImplementation(() => {
							throw new Error("DB connection lost");
						}),
					};
				}
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: [], error: null }),
							}),
						}),
					}),
				};
			});

			const result = await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-1")],
				makeContext(),
			);

			expect(result.failedCount).toBe(1);
			expect(mockLoggerError).toHaveBeenCalledWith(
				"Unexpected error inserting AI post",
				expect.objectContaining({ error: "DB connection lost" }),
			);
		});
	});

	// =====================================================================
	// 8. Humanization integration
	// =====================================================================
	describe("humanization", () => {
		it("passes content through humanizePost before inserting", async () => {
			mockHumanizePost.mockReturnValue("humanized content yo");

			let capturedInsertData: Record<string, unknown> | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: [], error: null }),
							}),
						}),
					}),
				};
			});

			await insertCandidatesIntoQueue(
				[makeCandidate({ content: "original text" })],
				[makeSlot("acc-1")],
				makeContext(),
			);

			expect(mockHumanizePost).toHaveBeenCalledWith("original text");
			expect(capturedInsertData!.content).toBe("humanized content yo");
		});
	});

	// =====================================================================
	// 9. Topic tag detection
	// =====================================================================
	describe("topic tag detection", () => {
		it("detects topic tag for Threads content and stores it", async () => {
			mockDetectTopicTag.mockReturnValue("Gaming");

			let capturedInsertData: Record<string, unknown> | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: [], error: null }),
							}),
						}),
					}),
				};
			});

			await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-1")],
				makeContext({ targetPlatform: "threads" }),
			);

			expect(mockDetectTopicTag).toHaveBeenCalled();
			expect(capturedInsertData!.topic_tag).toBe("Gaming");
		});

		it("skips topic tag detection for Instagram", async () => {
			// IG needs media to not be rejected, so provide media
			setupDbMock({
				mediaRows: [{ url: "https://cdn.example.com/img.jpg" }],
			});

			await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-1")],
				makeContext({ targetPlatform: "instagram" }),
			);

			expect(mockDetectTopicTag).not.toHaveBeenCalled();
		});
	});

	// =====================================================================
	// 10. Spoiler tricks — Threads only
	// =====================================================================
	describe("spoiler tricks", () => {
		it("includes text_spoilers when curiosity spoiler detected (Threads)", async () => {
			mockDetectNaturalCuriositySpoiler.mockReturnValue("love");

			let capturedInsertData: Record<string, unknown> | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: [], error: null }),
							}),
						}),
					}),
				};
			});

			await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-1")],
				makeContext({ targetPlatform: "threads" }),
			);

			expect(capturedInsertData!.text_spoilers).toEqual({
				word: "love",
				charOffset: 0,
				charLength: 4,
			});
		});

		it("falls back to double-meaning spoiler if curiosity not found", async () => {
			mockDetectNaturalCuriositySpoiler.mockReturnValue(null);
			mockDetectNaturalSpoiler.mockReturnValue({
				word: "date",
				charOffset: 5,
				charLength: 4,
			});

			let capturedInsertData: Record<string, unknown> | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: [], error: null }),
							}),
						}),
					}),
				};
			});

			await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-1")],
				makeContext({ targetPlatform: "threads" }),
			);

			expect(capturedInsertData!.text_spoilers).toEqual({
				word: "date",
				charOffset: 5,
				charLength: 4,
			});
		});

		it("skips spoiler detection for Instagram platform", async () => {
			setupDbMock({
				mediaRows: [{ url: "https://cdn.example.com/img.jpg" }],
			});

			await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-1")],
				makeContext({ targetPlatform: "instagram" }),
			);

			expect(mockDetectNaturalCuriositySpoiler).not.toHaveBeenCalled();
			expect(mockDetectNaturalSpoiler).not.toHaveBeenCalled();
		});
	});

	// =====================================================================
	// 11. Cross-platform scheduling — Instagram vs Threads
	// =====================================================================
	describe("cross-platform scheduling", () => {
		it("rejects IG post when no media is available and AI generation fails", async () => {
			setupDbMock({ mediaRows: [] });
			mockHasImageGenerationCapability.mockResolvedValue(false);

			const result = await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-1")],
				makeContext({ targetPlatform: "instagram" }),
			);

			expect(result.rejectedCount).toBe(1);
			expect(result.rejectionReasons["no-media-for-ig"]).toBe(1);
			expect(result.insertedCount).toBe(0);
		});

		it("uses AI-generated image for IG when library is empty", async () => {
			setupDbMock({ mediaRows: [] });
			mockHasImageGenerationCapability.mockResolvedValue(true);
			mockGenerateImageForPost.mockResolvedValue(
				"https://cdn.example.com/ai-generated.jpg",
			);

			let capturedInsertData: Record<string, unknown> | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				if (table === "media") {
					return {
						select: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								eq: vi.fn().mockReturnValue({
									limit: vi.fn().mockResolvedValue({
										data: [],
										error: null,
									}),
								}),
							}),
						}),
					};
				}
				return {
					select: vi.fn().mockReturnThis(),
					eq: vi.fn().mockReturnThis(),
					single: vi.fn().mockResolvedValue({ data: null, error: null }),
				};
			});

			const result = await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-1")],
				makeContext({ targetPlatform: "instagram" }),
			);

			expect(result.insertedCount).toBe(1);
			expect(capturedInsertData!.media_urls).toEqual([
				"https://cdn.example.com/ai-generated.jpg",
			]);
		});

		it("Threads posts do not require media", async () => {
			const result = await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-1")],
				makeContext({
					targetPlatform: "threads",
					slotMediaChance: 0,
				}),
			);

			expect(result.insertedCount).toBe(1);
			expect(result.rejectedCount).toBe(0);
		});

		it("attaches media to Threads post based on slotMediaChance", async () => {
			// Force Math.random to return 0 (below any threshold)
			const originalRandom = Math.random;
			Math.random = () => 0;

			setupDbMock({
				mediaRows: [
					{ url: "https://cdn.example.com/pic1.jpg", file_type: "image/jpeg" },
				],
			});

			let capturedInsertData: Record<string, unknown> | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				if (table === "media") {
					return {
						select: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								eq: vi.fn().mockReturnValue({
									limit: vi.fn().mockResolvedValue({
										data: [
											{
												url: "https://cdn.example.com/pic1.jpg",
												file_type: "image/jpeg",
											},
										],
										error: null,
									}),
								}),
							}),
						}),
					};
				}
				return {
					select: vi.fn().mockReturnThis(),
					eq: vi.fn().mockReturnThis(),
					single: vi.fn().mockResolvedValue({ data: null, error: null }),
				};
			});

			await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-1")],
				makeContext({
					targetPlatform: "threads",
					slotMediaChance: 50, // 50% chance, Math.random = 0 => always attach
				}),
			);

			expect(capturedInsertData!.media_urls).toEqual([
				"https://cdn.example.com/pic1.jpg",
			]);

			Math.random = originalRandom;
		});

		it("filters out video media on Threads (video kills reach)", async () => {
			const originalRandom = Math.random;
			Math.random = () => 0;

			let capturedInsertData: Record<string, unknown> | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				if (table === "media") {
					return {
						select: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								eq: vi.fn().mockReturnValue({
									limit: vi.fn().mockResolvedValue({
										data: [
											{
												url: "https://cdn.example.com/vid.mp4",
												file_type: "video/mp4",
											},
											{
												url: "https://cdn.example.com/img.jpg",
												file_type: "image/jpeg",
											},
										],
										error: null,
									}),
								}),
							}),
						}),
					};
				}
				return {
					select: vi.fn().mockReturnThis(),
					eq: vi.fn().mockReturnThis(),
					single: vi.fn().mockResolvedValue({ data: null, error: null }),
				};
			});

			await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-1")],
				makeContext({
					targetPlatform: "threads",
					slotMediaChance: 100,
				}),
			);

			// Should pick the image, not the video
			expect(capturedInsertData!.media_urls).toEqual([
				"https://cdn.example.com/img.jpg",
			]);

			Math.random = originalRandom;
		});

		it("does NOT filter video for Instagram (Reels are fine)", async () => {
			const originalRandom = Math.random;
			Math.random = () => 0;

			let capturedInsertData: Record<string, unknown> | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				if (table === "media") {
					return {
						select: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								eq: vi.fn().mockReturnValue({
									limit: vi.fn().mockResolvedValue({
										data: [
											{
												url: "https://cdn.example.com/vid.mp4",
												file_type: "video/mp4",
											},
										],
										error: null,
									}),
								}),
							}),
						}),
					};
				}
				return {
					select: vi.fn().mockReturnThis(),
					eq: vi.fn().mockReturnThis(),
					single: vi.fn().mockResolvedValue({ data: null, error: null }),
				};
			});

			await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-1")],
				makeContext({
					targetPlatform: "instagram",
					slotMediaChance: 100,
				}),
			);

			// Video should be allowed for IG
			expect(capturedInsertData!.media_urls).toEqual([
				"https://cdn.example.com/vid.mp4",
			]);
			// Should set video metadata alongside provenance metadata
			expect(capturedInsertData!.metadata).toMatchObject({
				is_video: true,
				media_format: "REELS",
			});

			Math.random = originalRandom;
		});
	});

	// =====================================================================
	// 12. Probe posts — use top historical content, no media
	// =====================================================================
	describe("probe posts", () => {
		it("replaces content with top historical post for probe slots", async () => {
			setupDbMock({
				topPost: {
					content: "best performing post ever",
					views_count: 50000,
				},
			});

			let capturedInsertData: Record<string, unknown> | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				if (table === "posts") {
					return {
						select: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								eq: vi.fn().mockReturnValue({
									not: vi.fn().mockReturnValue({
										gt: vi.fn().mockReturnValue({
											order: vi.fn().mockReturnValue({
												limit: vi.fn().mockResolvedValue({
													data: [
														{
															content: "best performing post ever",
															views_count: 50000,
														},
													],
													error: null,
												}),
											}),
										}),
									}),
								}),
							}),
						}),
					};
				}
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: [], error: null }),
							}),
						}),
					}),
				};
			});

			await insertCandidatesIntoQueue(
				[makeCandidate({ content: "AI generated content" })],
				[makeSlot("acc-probe", 0, true)],
				makeContext({ targetPlatform: "threads" }),
			);

			// Probe posts use historical content (passed through humanize)
			expect(mockHumanizePost).toHaveBeenCalledWith(
				"best performing post ever",
			);
			expect(capturedInsertData).not.toBeNull();
		});

		it("probe posts do not get media even when slotMediaChance is high", async () => {
			const originalRandom = Math.random;
			Math.random = () => 0;

			let capturedInsertData: Record<string, unknown> | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				if (table === "posts") {
					return {
						select: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								eq: vi.fn().mockReturnValue({
									not: vi.fn().mockReturnValue({
										gt: vi.fn().mockReturnValue({
											order: vi.fn().mockReturnValue({
												limit: vi.fn().mockResolvedValue({
													data: [],
													error: null,
												}),
											}),
										}),
									}),
								}),
							}),
						}),
					};
				}
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: [], error: null }),
							}),
						}),
					}),
				};
			});

			await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-probe", 0, true)],
				makeContext({
					targetPlatform: "threads",
					slotMediaChance: 100,
				}),
			);

			// Probe posts should not have media
			expect(capturedInsertData!.media_urls).toBeNull();

			Math.random = originalRandom;
		});
	});

	// =====================================================================
	// 13. Budget guard — stops if fill takes > 100s
	// =====================================================================
	describe("budget guard", () => {
		it("breaks insertion loop when fill time exceeds 100s", async () => {
			const candidates = Array.from({ length: 5 }, (_, i) =>
				makeCandidate({ content: `budget post ${i}` }),
			);
			const slots = candidates.map((_, i) => makeSlot(`acc-${i}`, i));
			// Set fillStartTime to >100s ago
			const ctx = makeContext({ fillStartTime: Date.now() - 101_000 });

			const result = await insertCandidatesIntoQueue(candidates, slots, ctx);

			expect(result.insertedCount).toBe(0);
			expect(mockLoggerWarn).toHaveBeenCalledWith(
				"Fill budget exceeded 100s during insertion phase",
				expect.objectContaining({ insertedCount: 0 }),
			);
		});
	});

	// =====================================================================
	// 14. Return structure
	// =====================================================================
	describe("return structure", () => {
		it("returns correct shape with all fields populated", async () => {
			// 2 candidates — 1 succeeds, 1 fails
			let insertCallCount = 0;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockImplementation(() => {
							insertCallCount++;
							if (insertCallCount === 1) {
								return {
									select: vi.fn().mockReturnValue({
										single: vi.fn().mockResolvedValue({
											data: { id: "q1" },
											error: null,
										}),
									}),
								};
							}
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: null,
										error: new Error("insert failed"),
									}),
								}),
							};
						}),
					};
				}
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: [], error: null }),
							}),
						}),
					}),
				};
			});

			const result = await insertCandidatesIntoQueue(
				[
					makeCandidate({ content: "success post" }),
					makeCandidate({ content: "fail post" }),
				],
				[makeSlot("acc-1", 0), makeSlot("acc-2", 1)],
				makeContext(),
			);

			expect(result).toEqual(
				expect.objectContaining({
					insertedCount: 1,
					failedCount: 1,
					rejectedCount: 0,
					insertedContents: ["success post"],
					errors: [
						expect.objectContaining({ error: expect.any(String) }),
					],
				}),
			);
		});

		it("returns empty result for empty candidate list", async () => {
			const result = await insertCandidatesIntoQueue(
				[],
				[],
				makeContext(),
			);

			expect(result.insertedCount).toBe(0);
			expect(result.failedCount).toBe(0);
			expect(result.rejectedCount).toBe(0);
			expect(result.insertedContents).toEqual([]);
			expect(result.errors).toEqual([]);
		});
	});

	// =====================================================================
	// 15. Fill cycle traceId propagation
	// =====================================================================
	describe("traceId propagation", () => {
		it("passes fillCycleId as traceId in QStash body", async () => {
			await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-1")],
				makeContext({ fillCycleId: "trace-abc-123" }),
			);

			const qstashArgs = mockQstashPublishJSON.mock.calls[0][0];
			expect(qstashArgs.body.traceId).toBe("trace-abc-123");
		});

		it("generates a traceId when fillCycleId is not provided", async () => {
			await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-1")],
				makeContext({ fillCycleId: undefined }),
			);

			const qstashArgs = mockQstashPublishJSON.mock.calls[0][0];
			expect(qstashArgs.body.traceId).toMatch(/^ap-\d+-/);
		});
	});

	// =====================================================================
	// 16. Video metadata
	// =====================================================================
	describe("video metadata", () => {
		it("sets metadata with is_video and media_format for video media", async () => {
			const originalRandom = Math.random;
			Math.random = () => 0;

			let capturedInsertData: Record<string, unknown> | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				if (table === "media") {
					return {
						select: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								eq: vi.fn().mockReturnValue({
									limit: vi.fn().mockResolvedValue({
										data: [
											{
												url: "https://cdn.example.com/vid.mp4",
												file_type: "video/mp4",
											},
										],
										error: null,
									}),
								}),
							}),
						}),
					};
				}
				return {
					select: vi.fn().mockReturnThis(),
					eq: vi.fn().mockReturnThis(),
					single: vi.fn().mockResolvedValue({ data: null, error: null }),
				};
			});

			await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-1")],
				makeContext({
					targetPlatform: "instagram",
					slotMediaChance: 100,
				}),
			);

			expect(capturedInsertData!.metadata).toMatchObject({
				is_video: true,
				media_format: "REELS",
			});

			Math.random = originalRandom;
		});

		it("does not set metadata for image media", async () => {
			const originalRandom = Math.random;
			Math.random = () => 0;

			let capturedInsertData: Record<string, unknown> | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockImplementation((data: unknown) => {
							capturedInsertData = data as Record<string, unknown>;
							return {
								select: vi.fn().mockReturnValue({
									single: vi.fn().mockResolvedValue({
										data: { id: "q1" },
										error: null,
									}),
								}),
							};
						}),
					};
				}
				if (table === "media") {
					return {
						select: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								eq: vi.fn().mockReturnValue({
									limit: vi.fn().mockResolvedValue({
										data: [
											{
												url: "https://cdn.example.com/img.jpg",
												file_type: "image/jpeg",
											},
										],
										error: null,
									}),
								}),
							}),
						}),
					};
				}
				return {
					select: vi.fn().mockReturnThis(),
					eq: vi.fn().mockReturnThis(),
					single: vi.fn().mockResolvedValue({ data: null, error: null }),
				};
			});

			await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-1")],
				makeContext({
					targetPlatform: "instagram",
					slotMediaChance: 100,
				}),
			);

			expect(capturedInsertData!.metadata).toMatchObject({
				quality_gate: {
					decision: "pass",
				},
				judge: {
					score: 4,
				},
			});
			expect(capturedInsertData!.metadata).not.toMatchObject({
				is_video: true,
			});

			Math.random = originalRandom;
		});
	});

	// =====================================================================
	// 17. Media group override
	// =====================================================================
	describe("media group override", () => {
		it("uses mediaGroupId instead of groupId for media selection", async () => {
			const originalRandom = Math.random;
			Math.random = () => 0;

			let capturedMediaGroupId: string | null = null;
			mockFrom.mockImplementation((table: string) => {
				if (table === "user_settings") {
					return createChainMock({
						data: { setting_value: { threshold: 50 } },
						error: null,
					});
				}
				if (table === "auto_post_queue") {
					return {
						insert: vi.fn().mockReturnValue({
							select: vi.fn().mockReturnValue({
								single: vi.fn().mockResolvedValue({
									data: { id: "q1" },
									error: null,
								}),
							}),
						}),
					};
				}
				if (table === "media") {
					return {
						select: vi.fn().mockReturnValue({
							eq: vi.fn().mockImplementation((_col: string, val: string) => {
								// Second eq is the group_id eq
								if (_col === "group_id") {
									capturedMediaGroupId = val;
								}
								return {
									eq: vi.fn().mockImplementation(
										(_c: string, v: string) => {
											if (_c === "group_id") {
												capturedMediaGroupId = v;
											}
											return {
												limit: vi.fn().mockResolvedValue({
													data: [
														{
															url: "https://cdn.example.com/override.jpg",
															file_type: "image/jpeg",
														},
													],
													error: null,
												}),
											};
										},
									),
									limit: vi.fn().mockResolvedValue({
										data: [
											{
												url: "https://cdn.example.com/override.jpg",
												file_type: "image/jpeg",
											},
										],
										error: null,
									}),
								};
							}),
						}),
					};
				}
				return {
					select: vi.fn().mockReturnThis(),
					eq: vi.fn().mockReturnThis(),
					single: vi.fn().mockResolvedValue({ data: null, error: null }),
				};
			});

			await insertCandidatesIntoQueue(
				[makeCandidate()],
				[makeSlot("acc-1")],
				makeContext({
					targetPlatform: "threads",
					slotMediaChance: 100,
					mediaGroupId: "media-grp-override",
				}),
			);

			// Media should be queried from the override group
			expect(capturedMediaGroupId).toBe("media-grp-override");

			Math.random = originalRandom;
		});
	});
});

// ===========================================================================
// nudgeScheduleForFormat — pure function tests
// ===========================================================================

describe("nudgeScheduleForFormat", () => {
	it("returns unchanged when no timezone provided", () => {
		const input = "2026-04-15T14:00:00Z";
		expect(nudgeScheduleForFormat(input, true)).toBe(input);
		expect(nudgeScheduleForFormat(input, false)).toBe(input);
	});

	it("does not nudge a Reel time already in 19-22 local window", () => {
		// 2026-04-15 at 20:00 UTC = 16:00 ET (not in window)
		// Let's pick a time that IS in 19-22 ET: 23:00 UTC = 19:00 ET
		const input = "2026-04-15T23:00:00Z";
		const result = nudgeScheduleForFormat(
			input,
			true,
			"America/New_York",
		);
		// 23:00 UTC = 19:00 ET, which is in 19-22 window — should not be nudged far
		const resultDate = new Date(result);
		const inputDate = new Date(input);
		// The jitter can add up to 45 min, so check it's within reasonable range
		const diffMs = resultDate.getTime() - inputDate.getTime();
		// Already in window: no shift, only possible jitter (0-45 min)
		expect(diffMs).toBeGreaterThanOrEqual(0);
		expect(diffMs).toBeLessThanOrEqual(45 * 60 * 1000);
	});

	it("nudges a morning Reel time toward evening", () => {
		// 2026-04-15 at 14:00 UTC = 10:00 ET (outside 19-22)
		const input = "2026-04-15T14:00:00Z";
		const result = nudgeScheduleForFormat(
			input,
			true, // video = Reel
			"America/New_York",
		);
		const resultDate = new Date(result);
		const inputDate = new Date(input);
		// Should be shifted later (toward evening)
		expect(resultDate.getTime()).toBeGreaterThan(inputDate.getTime());
	});

	it("nudges a late-night image time toward morning", () => {
		// 2026-04-15 at 06:00 UTC = 02:00 ET (outside 8-11)
		const input = "2026-04-15T06:00:00Z";
		const result = nudgeScheduleForFormat(
			input,
			false, // not video = image
			"America/New_York",
		);
		const resultDate = new Date(result);
		const inputDate = new Date(input);
		// Should be shifted later toward morning window (8 AM ET = 12:00 UTC)
		expect(resultDate.getTime()).toBeGreaterThan(inputDate.getTime());
	});

	it("does not nudge an image time already in 8-11 local window", () => {
		// 2026-04-15 at 13:00 UTC = 09:00 ET (in 8-11 window)
		const input = "2026-04-15T13:00:00Z";
		const result = nudgeScheduleForFormat(
			input,
			false,
			"America/New_York",
		);
		const resultDate = new Date(result);
		const inputDate = new Date(input);
		// Already in window, should stay close (jitter only)
		const diffMs = Math.abs(
			resultDate.getTime() - inputDate.getTime(),
		);
		expect(diffMs).toBeLessThanOrEqual(45 * 60 * 1000);
	});

	it("nudges Stories to nearest wave (11, 17, 20)", () => {
		// 2026-04-15 at 20:00 UTC = 16:00 ET, nearest wave = 17:00 ET
		const input = "2026-04-15T20:00:00Z";
		const result = nudgeScheduleForFormat(
			input,
			false,
			"America/New_York",
			"STORIES",
		);
		const resultDate = new Date(result);
		const inputDate = new Date(input);
		// Should nudge +1h toward 17:00 ET (21:00 UTC) + jitter
		const diffHours =
			(resultDate.getTime() - inputDate.getTime()) / 3600000;
		expect(diffHours).toBeGreaterThanOrEqual(0.5);
		expect(diffHours).toBeLessThanOrEqual(1.6); // 1h shift + up to 30 min jitter
	});

	it("caps the shift at +-6 hours", () => {
		// Force an edge case: midnight local time with image (8 AM target)
		// 2026-04-15 at 04:00 UTC = 00:00 ET, image window is 8-11
		const input = "2026-04-15T04:00:00Z";
		const result = nudgeScheduleForFormat(
			input,
			false,
			"America/New_York",
		);
		const resultDate = new Date(result);
		const inputDate = new Date(input);
		const diffHours =
			(resultDate.getTime() - inputDate.getTime()) / 3600000;
		// Max shift is 6 hours + up to 45 min jitter
		expect(diffHours).toBeLessThanOrEqual(6.75);
	});

	it("handles invalid timezone gracefully (fail-open)", () => {
		const input = "2026-04-15T14:00:00Z";
		// Invalid timezone shouldn't crash
		const result = nudgeScheduleForFormat(
			input,
			true,
			"Invalid/Timezone",
		);
		// Should either return input unchanged or a valid ISO string
		expect(() => new Date(result)).not.toThrow();
	});
});

// ===========================================================================
// planAccountSlots — fail-open wrapper
// ===========================================================================

describe("planAccountSlots", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("delegates to accountPlanner.planAccountSlots", async () => {
		mockPlanSlots.mockResolvedValue({
			slots: [{ accountId: "acc-1", roundRobinIndex: 0 }],
			skipped: [],
			totalAccounts: 1,
			eligibleCount: 1,
		});

		const result = await planAccountSlots(
			"grp-1",
			"ws-1",
			"user-1",
			5,
		);

		expect(result.slots).toHaveLength(1);
		expect(result.slots[0].accountId).toBe("acc-1");
		expect(mockPlanSlots).toHaveBeenCalledWith(
			"grp-1",
			"ws-1",
			"user-1",
			5,
			undefined,
		);
	});

	it("returns empty result and logs warning when planner throws", async () => {
		mockPlanSlots.mockRejectedValue(new Error("planner crashed"));

		const result = await planAccountSlots(
			"grp-1",
			"ws-1",
			"user-1",
			5,
		);

		expect(result.slots).toEqual([]);
		expect(result.skipped).toEqual([]);
		expect(result.totalAccounts).toBe(0);
		expect(result.eligibleCount).toBe(0);
		expect(mockLoggerWarn).toHaveBeenCalledWith(
			"Account planner failed, falling back to publish-time selection",
			expect.objectContaining({
				error: "planner crashed",
				groupId: "grp-1",
			}),
		);
	});

	it("passes resolvedConfig when provided", async () => {
		mockPlanSlots.mockResolvedValue({
			slots: [],
			skipped: [],
			totalAccounts: 0,
			eligibleCount: 0,
		});

		const fakeConfig = { someKey: "someVal" } as any;
		await planAccountSlots("grp-1", "ws-1", "user-1", 3, fakeConfig);

		expect(mockPlanSlots).toHaveBeenCalledWith(
			"grp-1",
			"ws-1",
			"user-1",
			3,
			fakeConfig,
		);
	});
});
