import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { z } from 'zod';
import { useAuthUser } from '@/hooks/useAuthUser';
import { ApiHttpError, apiFetch } from '@/lib/apiFetch';
import { queryKeys } from '@/lib/queryKeys';

const jsonRecordSchema = z.record(z.string(), z.unknown());

const operatorTaskSchema = z.object({
	id: z.string(),
	source: z.string().nullable().optional(),
	source_id: z.string().nullable().optional(),
	title: z.string().nullable().optional(),
	priority: z.string().nullable().optional(),
	status: z.string().nullable().optional(),
	due_at: z.string().nullable().optional(),
	sla_at: z.string().nullable().optional(),
	account_id: z.string().nullable().optional(),
	group_id: z.string().nullable().optional(),
	workspace_id: z.string().nullable().optional(),
	recommended_action: z.unknown().optional(),
	linked_entity_type: z.string().nullable().optional(),
	linked_entity_id: z.string().nullable().optional(),
	created_at: z.string().nullable().optional(),
}).passthrough();

const approvalSchema = z.object({
	id: z.string(),
	context: z.string().nullable().optional(),
	urgency: z.string().nullable().optional(),
	status: z.string().nullable().optional(),
	expires_at: z.string().nullable().optional(),
	created_at: z.string().nullable().optional(),
}).passthrough();

const failedPostSchema = z.object({
	id: z.string(),
	account_id: z.string().nullable().optional(),
	platform: z.string().nullable().optional(),
	content: z.string().nullable().optional(),
	status: z.string().nullable().optional(),
	error_message: z.string().nullable().optional(),
	updated_at: z.string().nullable().optional(),
}).passthrough();

const opsHealthMetricSchema = z.object({
	key: z.string(),
	label: z.string(),
	value: z.union([z.string(), z.number(), z.null()]).optional(),
	status: z.enum(['healthy', 'warning', 'critical']),
	route: z.string(),
}).passthrough();

const opsHealthIssueSchema = z.object({
	key: z.string(),
	title: z.string(),
	severity: z.enum(['warning', 'critical']),
	source: z.string(),
	route: z.string(),
	account_id: z.string().nullable().optional(),
	group_id: z.string().nullable().optional(),
	workspace_id: z.string().nullable().optional(),
}).passthrough();

const opsHealthAccountSchema = z.object({
	accountId: z.string(),
	handle: z.string(),
	platform: z.enum(['threads', 'instagram']).default('threads'),
	group_id: z.string().nullable().optional(),
	status: z.string().nullable().optional(),
	severity: z.enum(['warning', 'critical']).default('warning'),
	reasons: z.array(z.string()).default([]),
	needsReauth: z.boolean().default(false),
	tokenExpiresAt: z.string().nullable().optional(),
	lastSyncedAt: z.string().nullable().optional(),
	isActive: z.boolean().default(true),
	route: z.string().default('/accounts?status=flagged'),
}).passthrough();

const opsHealthSchema = z.object({
	generatedAt: z.string().optional(),
	score: z.number().default(100),
	tone: z.enum(['healthy', 'warning', 'critical']).default('healthy'),
	summary: z.object({
		critical: z.number().default(0),
		warning: z.number().default(0),
		healthy: z.boolean().default(true),
		impactedAccountCount: z.number().default(0),
	}).default({ critical: 0, warning: 0, healthy: true, impactedAccountCount: 0 }),
	metrics: z.array(opsHealthMetricSchema).default([]),
	issues: z.array(opsHealthIssueSchema).default([]),
	impactedAccountIds: z.array(z.string()).default([]),
	unhealthyAccounts: z.array(opsHealthAccountSchema).default([]),
	unhealthyAccountTotal: z.number().default(0),
	lastSuccessfulCronAt: z.string().nullable().optional(),
}).default({
	score: 100,
	tone: 'healthy',
	summary: { critical: 0, warning: 0, healthy: true, impactedAccountCount: 0 },
	metrics: [],
	issues: [],
	impactedAccountIds: [],
	unhealthyAccounts: [],
	unhealthyAccountTotal: 0,
});

const fleetCapacityDaySchema = z.object({
	date: z.string(),
	scheduled: z.number().default(0),
	publishing: z.number().default(0),
	failed: z.number().default(0),
	pendingQueue: z.number().default(0),
	deadLetter: z.number().default(0),
	approvalPending: z.number().default(0),
	gapCount: z.number().default(0),
	accountCount: z.number().default(0),
	accountIds: z.array(z.string()).default([]),
	tone: z.enum(['healthy', 'warning', 'critical']).default('healthy'),
}).passthrough();

const fleetCapacityAccountDaySchema = z.object({
	date: z.string(),
	planned: z.number().default(0),
	scheduled: z.number().default(0),
	publishing: z.number().default(0),
	failed: z.number().default(0),
	pendingQueue: z.number().default(0),
	deadLetter: z.number().default(0),
	approvalPending: z.number().default(0),
	hasGap: z.boolean().default(false),
	hasConflict: z.boolean().default(false),
	tone: z.enum(['healthy', 'warning', 'critical']).default('healthy'),
	recommendedAction: z.string().default('none'),
}).passthrough();

const fleetCapacityAccountSchema = z.object({
	accountId: z.string(),
	handle: z.string(),
	displayName: z.string(),
	groupId: z.string().nullable().optional(),
	groupName: z.string().default('Ungrouped'),
	groupColor: z.string().nullable().optional(),
	platform: z.enum(['threads', 'instagram']).default('threads'),
	days: z.array(fleetCapacityAccountDaySchema).default([]),
}).passthrough();

const fleetCapacityGroupSchema = z.object({
	id: z.string(),
	name: z.string(),
	color: z.string().nullable().optional(),
	accountCount: z.number().default(0),
}).passthrough();

const fleetCapacitySchema = z.object({
	generatedAt: z.string().optional(),
	windowDays: z.number().default(7),
	activeAccountCount: z.number().default(0),
	score: z.number().default(100),
	tone: z.enum(['healthy', 'warning', 'critical']).default('healthy'),
	totals: z.object({
		scheduled: z.number().default(0),
		publishing: z.number().default(0),
		failed: z.number().default(0),
		pendingQueue: z.number().default(0),
		deadLetter: z.number().default(0),
		approvalPending: z.number().default(0),
		gapCount: z.number().default(0),
	}).default({
		scheduled: 0,
		publishing: 0,
		failed: 0,
		pendingQueue: 0,
		deadLetter: 0,
		approvalPending: 0,
		gapCount: 0,
	}),
	days: z.array(fleetCapacityDaySchema).default([]),
	accounts: z.array(fleetCapacityAccountSchema).default([]),
	groups: z.array(fleetCapacityGroupSchema).default([]),
	recommendations: z.array(jsonRecordSchema).default([]),
}).default({
	windowDays: 7,
	activeAccountCount: 0,
	score: 100,
	tone: 'healthy',
	totals: {
		scheduled: 0,
		publishing: 0,
		failed: 0,
		pendingQueue: 0,
		deadLetter: 0,
		approvalPending: 0,
		gapCount: 0,
	},
	days: [],
	accounts: [],
	groups: [],
	recommendations: [],
});

const aiEvalLatestFailureSchema = z.object({
	id: z.unknown().optional(),
	suiteName: z.unknown().optional(),
	caseId: z.unknown().optional(),
	category: z.unknown().optional(),
	model: z.unknown().optional(),
	failures: z.array(z.unknown()).default([]),
	capturedAt: z.unknown().optional(),
}).passthrough();

const aiEvalTrendPointSchema = z.object({
	day: z.string(),
	suiteName: z.string(),
	surface: z.string(),
	total: z.number().default(0),
	passed: z.number().default(0),
	failed: z.number().default(0),
	passRate: z.number().default(100),
	avgRegressionScore: z.number().nullable().optional(),
}).passthrough();

const aiEvalSuiteRowSchema = z.object({
	suiteName: z.string(),
	surface: z.string(),
	total: z.number().default(0),
	passed: z.number().default(0),
	failed: z.number().default(0),
	passRate: z.number().default(100),
	avgRegressionScore: z.number().nullable().optional(),
	lastCapturedAt: z.string().nullable().optional(),
}).passthrough();

const aiEvalSummarySchema = z.object({
	generatedAt: z.string().optional(),
	windowDays: z.number().default(14),
	total: z.number().default(0),
	passed: z.number().default(0),
	failed: z.number().default(0),
	passRate: z.number().default(100),
	avgRegressionScore: z.number().nullable().optional(),
	tone: z.enum(['healthy', 'warning', 'critical']).default('healthy'),
	latestFailures: z.array(aiEvalLatestFailureSchema).default([]),
	trend: z.array(aiEvalTrendPointSchema).default([]),
	suites: z.array(aiEvalSuiteRowSchema).default([]),
	thresholds: z.object({
		passed: z.boolean().default(true),
		failures: z.array(z.string()).default([]),
	}).default({ passed: true, failures: [] }),
	coverage: z.object({
		hasGoldenEvals: z.boolean().default(false),
		hasLiveSnapshots: z.boolean().default(false),
		directGenerativeSurfaceCount: z.number().default(0),
		directGenerativeCoveredCount: z.number().default(0),
		documentedNonGenerativeCount: z.number().default(0),
		uncoveredDirectSurfaces: z.array(z.string()).default([]),
	}).default({
		hasGoldenEvals: false,
		hasLiveSnapshots: false,
		directGenerativeSurfaceCount: 0,
		directGenerativeCoveredCount: 0,
		documentedNonGenerativeCount: 0,
		uncoveredDirectSurfaces: [],
	}),
}).default({
	windowDays: 14,
	total: 0,
	passed: 0,
	failed: 0,
	passRate: 100,
	tone: 'healthy',
	latestFailures: [],
	trend: [],
	suites: [],
	thresholds: { passed: true, failures: [] },
	coverage: {
		hasGoldenEvals: false,
		hasLiveSnapshots: false,
		directGenerativeSurfaceCount: 0,
		directGenerativeCoveredCount: 0,
		documentedNonGenerativeCount: 0,
		uncoveredDirectSurfaces: [],
	},
});

const reliabilitySloSchema = z.object({
	generatedAt: z.string().optional(),
	windowHours: z.number().default(24),
	scheduledTotal: z.number().default(0),
	publishedTotal: z.number().default(0),
	failedTotal: z.number().default(0),
	onTime60s: z.number().default(0),
	lateOver5m: z.number().default(0),
	successRate: z.number().default(100),
	onTimeRate: z.number().default(100),
	driftSeconds: z.object({
		p50: z.number().default(0),
		p95: z.number().default(0),
		p99: z.number().default(0),
		max: z.number().default(0),
		avg: z.number().default(0),
	}).default({ p50: 0, p95: 0, p99: 0, max: 0, avg: 0 }),
	qstashFailures: z.number().default(0),
	dlqCount: z.number().default(0),
	backlogCount: z.number().default(0),
	impactedAccountIds: z.array(z.string()).default([]),
	tone: z.enum(['healthy', 'warning', 'critical']).default('healthy'),
	issues: z.array(jsonRecordSchema).default([]),
	trend: z.array(jsonRecordSchema).default([]),
}).default({
	windowHours: 24,
	scheduledTotal: 0,
	publishedTotal: 0,
	failedTotal: 0,
	onTime60s: 0,
	lateOver5m: 0,
	successRate: 100,
	onTimeRate: 100,
	driftSeconds: { p50: 0, p95: 0, p99: 0, max: 0, avg: 0 },
	qstashFailures: 0,
	dlqCount: 0,
	backlogCount: 0,
	impactedAccountIds: [],
	tone: 'healthy',
	issues: [],
	trend: [],
});

const metaApiUsageSchema = z.object({
	generatedAt: z.string().optional(),
	tone: z.enum(['healthy', 'warning', 'critical']).default('healthy'),
	latest: z.array(jsonRecordSchema).default([]),
	maxUsagePercent: z.number().default(0),
	retryAfterActiveCount: z.number().default(0),
	warningCount: z.number().default(0),
	criticalCount: z.number().default(0),
}).default({
	tone: 'healthy',
	latest: [],
	maxUsagePercent: 0,
	retryAfterActiveCount: 0,
	warningCount: 0,
	criticalCount: 0,
});

const webhookHealthSchema = z.object({
	generatedAt: z.string().optional(),
	tone: z.enum(['healthy', 'warning', 'critical']).default('healthy'),
	failedDeliveries: z.number().default(0),
	deadLetterDeliveries: z.number().default(0),
	threadsDeadLetters: z.number().default(0),
	instagramDeadLetters: z.number().default(0),
	nextRetryCount: z.number().default(0),
	issues: z.array(jsonRecordSchema).default([]),
}).default({
	tone: 'healthy',
	failedDeliveries: 0,
	deadLetterDeliveries: 0,
	threadsDeadLetters: 0,
	instagramDeadLetters: 0,
	nextRetryCount: 0,
	issues: [],
});

const tokenSloSchema = z.object({
	generatedAt: z.string().optional(),
	tone: z.enum(['healthy', 'warning', 'critical']).default('healthy'),
	totalIssues: z.number().default(0),
	needsReauth: z.number().default(0),
	expiringSoon: z.number().default(0),
	expired: z.number().default(0),
	accounts: z.array(jsonRecordSchema).default([]),
}).default({
	tone: 'healthy',
	totalIssues: 0,
	needsReauth: 0,
	expiringSoon: 0,
	expired: 0,
	accounts: [],
});

const operatorSnapshotSchema = z.object({
	success: z.boolean().optional(),
	generatedAt: z.string().optional(),
	tasks: z.array(operatorTaskSchema).default([]),
	pendingApprovals: z.array(approvalSchema).default([]),
	failedPosts: z.array(failedPostSchema).default([]),
	recentDecisions: z.array(z.unknown()).default([]),
	managerBrain: z.unknown().optional(),
	opsHealth: opsHealthSchema,
	fleetCapacity: fleetCapacitySchema,
	aiEvalSummary: aiEvalSummarySchema,
	reliabilitySlo: reliabilitySloSchema,
	metaApiUsage: metaApiUsageSchema,
	webhookHealth: webhookHealthSchema,
	tokenSlo: tokenSloSchema,
	recommendedNextActions: z.array(jsonRecordSchema).default([]),
	warnings: z.array(z.string()).default([]),
});

const taskUpdateSchema = z.object({
	success: z.boolean().optional(),
	task: operatorTaskSchema,
});

export type OperatorTask = z.infer<typeof operatorTaskSchema>;
export type OperatorSnapshot = z.infer<typeof operatorSnapshotSchema>;

const EMPTY_SNAPSHOT: OperatorSnapshot = {
	success: true,
	tasks: [],
	pendingApprovals: [],
	failedPosts: [],
	recentDecisions: [],
	opsHealth: {
		score: 100,
		tone: 'healthy',
		summary: { critical: 0, warning: 0, healthy: true, impactedAccountCount: 0 },
		metrics: [],
		issues: [],
		impactedAccountIds: [],
		unhealthyAccounts: [],
		unhealthyAccountTotal: 0,
	},
	fleetCapacity: {
		windowDays: 7,
		activeAccountCount: 0,
		score: 100,
		tone: 'healthy',
		totals: {
			scheduled: 0,
			publishing: 0,
			failed: 0,
			pendingQueue: 0,
			deadLetter: 0,
			approvalPending: 0,
			gapCount: 0,
		},
		days: [],
		accounts: [],
		groups: [],
		recommendations: [],
	},
	aiEvalSummary: {
		windowDays: 14,
		total: 0,
		passed: 0,
		failed: 0,
		passRate: 100,
		tone: 'healthy',
		latestFailures: [],
		trend: [],
		suites: [],
		thresholds: { passed: true, failures: [] },
		coverage: {
			hasGoldenEvals: false,
			hasLiveSnapshots: false,
			directGenerativeSurfaceCount: 0,
			directGenerativeCoveredCount: 0,
			documentedNonGenerativeCount: 0,
			uncoveredDirectSurfaces: [],
		},
	},
	reliabilitySlo: {
		windowHours: 24,
		scheduledTotal: 0,
		publishedTotal: 0,
		failedTotal: 0,
		onTime60s: 0,
		lateOver5m: 0,
		successRate: 100,
		onTimeRate: 100,
		driftSeconds: { p50: 0, p95: 0, p99: 0, max: 0, avg: 0 },
		qstashFailures: 0,
		dlqCount: 0,
		backlogCount: 0,
		impactedAccountIds: [],
		tone: 'healthy',
		issues: [],
		trend: [],
	},
	metaApiUsage: {
		tone: 'healthy',
		latest: [],
		maxUsagePercent: 0,
		retryAfterActiveCount: 0,
		warningCount: 0,
		criticalCount: 0,
	},
	webhookHealth: {
		tone: 'healthy',
		failedDeliveries: 0,
		deadLetterDeliveries: 0,
		threadsDeadLetters: 0,
		instagramDeadLetters: 0,
		nextRetryCount: 0,
		issues: [],
	},
	tokenSlo: {
		tone: 'healthy',
		totalIssues: 0,
		needsReauth: 0,
		expiringSoon: 0,
		expired: 0,
		accounts: [],
	},
	recommendedNextActions: [],
	warnings: [],
};

export function useOperatorSnapshot(options: { capacityStart?: string | null } = {}) {
	const authUser = useAuthUser();
	const queryClient = useQueryClient();
	const userKey = authUser?.id ?? null;
	const capacityStart = options.capacityStart ?? null;
	const queryKey = queryKeys.operator.snapshot(userKey, capacityStart);

	const query = useQuery({
		queryKey,
		enabled: !!userKey,
		staleTime: 60_000,
		queryFn: async () => {
			try {
				const params = new URLSearchParams({ action: 'snapshot' });
				if (capacityStart) params.set('capacityStart', capacityStart);
				return await apiFetch(`/api/operator?${params.toString()}`, operatorSnapshotSchema);
			} catch (error) {
				if (import.meta.env.DEV && error instanceof ApiHttpError && error.status === 404) {
					return {
						...EMPTY_SNAPSHOT,
						warnings: ['Operator API is not available from the current dev proxy yet.'],
					};
				}
				throw error;
			}
		},
	});

	const updateTask = useMutation({
		mutationFn: (input: {
			id?: string | undefined;
			source?: string | undefined;
			sourceId?: string | undefined;
			status: 'open' | 'assigned' | 'in_progress' | 'snoozed' | 'resolved' | 'ignored';
			resolutionReason?: string | null;
			snoozedUntil?: string | null;
		}) => apiFetch('/api/operator?action=tasks', taskUpdateSchema, {
			method: 'PATCH',
			json: {
				id: input.id,
				source: input.source,
				source_id: input.sourceId,
				status: input.status,
				resolution_reason: input.resolutionReason ?? null,
				snoozed_until: input.snoozedUntil ?? null,
			},
		}),
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey });
		},
	});

	return {
		snapshot: query.data ?? EMPTY_SNAPSHOT,
		isLoading: !!userKey && query.isPending,
		hasError: !!userKey && query.isError,
		refetch: query.refetch,
		updateTask,
	};
}
