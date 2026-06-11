export type ScalePlatform = "threads" | "instagram";

export interface ScaleGroup {
	id: string;
	name: string;
	color: string;
	account_ids: string[];
}

export interface ScaleAccount {
	id: string;
	user_id: string;
	username: string;
	display_name: string;
	group_id: string;
	is_active: boolean;
	is_retired?: boolean;
	needs_reauth?: boolean;
	status?: string;
	token_expires_at?: string;
	last_synced_at?: string;
	platform: ScalePlatform;
}

export interface ScaleFixture {
	user: {
		id: string;
		email: string;
	};
	groups: ScaleGroup[];
	accounts: ScaleAccount[];
	threadsAccounts: ScaleAccount[];
	instagramAccounts: ScaleAccount[];
	posts: Array<Record<string, unknown>>;
	calendarWeek: Record<string, unknown>;
	operatorSnapshot: Record<string, unknown>;
	approvals: Array<Record<string, unknown>>;
	inboxMessages: Array<Record<string, unknown>>;
	listeningAlerts: Array<Record<string, unknown>>;
	listeningResults: Array<Record<string, unknown>>;
	competitors: Array<Record<string, unknown>>;
	competitorPosts: Array<Record<string, unknown>>;
	trendKeywords: Array<Record<string, unknown>>;
	trendPosts: Array<Record<string, unknown>>;
	reports: Array<Record<string, unknown>>;
	reportSendLogs: Array<Record<string, unknown>>;
}

const COLORS = [
	"#A33A3A",
	"#2F6F73",
	"#7A5CBE",
	"#A67C2D",
	"#4E7A47",
	"#B35C2E",
	"#536DAE",
	"#6B6B70",
];

export function createScaleFixture(now = new Date("2026-05-25T12:00:00.000Z")): ScaleFixture {
	const user = { id: "scale-user-200", email: "scale.operator@juno33.test" };
	const isoNow = now.toISOString();
	const groups: ScaleGroup[] = Array.from({ length: 8 }, (_, index) => ({
		id: `scale-group-${index + 1}`,
		name: `Scale Group ${index + 1}`,
		color: COLORS[index] ?? "#6B6B70",
		account_ids: [],
	}));

	const accounts: ScaleAccount[] = Array.from({ length: 200 }, (_, index) => {
		const platform: ScalePlatform = index % 2 === 0 ? "threads" : "instagram";
		const group = groups[index % groups.length]!;
		const idPrefix = platform === "threads" ? "th" : "ig";
		const id = `${idPrefix}-scale-${String(index + 1).padStart(3, "0")}`;
		const account: ScaleAccount = {
			id,
			user_id: user.id,
			username: `${platform}_scale_${String(index + 1).padStart(3, "0")}`,
			display_name: `${platform === "threads" ? "Threads" : "Instagram"} Scale ${index + 1}`,
			group_id: group.id,
			is_active: index % 19 !== 0,
			...(platform === "threads" ? { is_retired: false } : {}),
			needs_reauth: index % 37 === 0,
			status: index % 37 === 0 ? "needs_reauth" : "active",
			token_expires_at: new Date(now.getTime() + (index % 13) * 86_400_000).toISOString(),
			last_synced_at: new Date(now.getTime() - (index % 9) * 3_600_000).toISOString(),
			platform,
		};
		group.account_ids.push(id);
		return account;
	});

	const weekStart = startOfWeek(now);
	const days = Array.from({ length: 7 }, (_, index) => dateOnly(addDays(weekStart, index)));
	const posts = accounts.slice(0, 70).map((account, index) => {
		const date = days[index % days.length]!;
		const scheduledFor = `${date}T${String(9 + (index % 9)).padStart(2, "0")}:00:00.000Z`;
		const failed = index % 17 === 0;
		const pendingApproval = index % 11 === 0;
		return {
			id: `post-scale-${index + 1}`,
			user_id: user.id,
			content: `Scale fixture post ${index + 1} for @${account.username}`,
			media_urls: [],
			status: failed ? "failed" : "scheduled",
			approval_status: pendingApproval ? "pending" : "approved",
			scheduled_for: scheduledFor,
			published_at: null,
			platform: account.platform,
			account_id: account.platform === "threads" ? account.id : null,
			instagram_account_id: account.platform === "instagram" ? account.id : null,
			username: account.username,
			display_name: account.display_name,
			group_id: account.group_id,
			group_name: groups.find((group) => group.id === account.group_id)?.name ?? "Ungrouped",
			group_color: groups.find((group) => group.id === account.group_id)?.color ?? "#6B6B70",
			threads_post_id: null,
			created_at: isoNow,
			metadata: {},
		};
	});

	const fleetAccounts = accounts.map((account, accountIndex) => {
		const group = groups.find((item) => item.id === account.group_id)!;
		return {
			accountId: account.id,
			handle: `@${account.username}`,
			displayName: account.display_name,
			groupId: group.id,
			groupName: group.name,
			groupColor: group.color,
			platform: account.platform,
			days: days.map((date, dayIndex) => {
				const failed = accountIndex % 31 === 0 && dayIndex === 1;
				const approval = accountIndex % 29 === 0 && dayIndex === 2;
				const gap = accountIndex % 7 === dayIndex;
				const conflict = accountIndex % 43 === 0 && dayIndex === 4;
				return {
					date,
					planned: gap ? 0 : 2,
					scheduled: gap ? 0 : 1 + (accountIndex % 2),
					publishing: 0,
					failed: failed ? 1 : 0,
					pendingQueue: gap ? 0 : 1,
					deadLetter: failed && accountIndex % 2 === 0 ? 1 : 0,
					approvalPending: approval ? 1 : 0,
					hasGap: gap,
					hasConflict: conflict,
					tone: failed ? "critical" : gap || approval || conflict ? "warning" : "healthy",
					recommendedAction: failed
						? "recover_failed"
						: approval
							? "review_approval"
							: conflict
								? "rebalance_conflict"
								: gap
									? "fill_gap"
									: "none",
				};
			}),
		};
	});

	const fleetDays = days.map((date, index) => ({
		date,
		scheduled: 160 + index,
		publishing: 2,
		failed: index === 1 ? 8 : 2,
		pendingQueue: 110 - index,
		deadLetter: index === 1 ? 4 : 1,
		approvalPending: index === 2 ? 12 : 3,
		gapCount: 24 + index,
		accountCount: 200,
		accountIds: accounts.map((account) => account.id),
		tone: index === 1 ? "critical" : "warning",
	}));

	const taskSources = ["failed_publish", "approval", "token_reauth", "inbox_attention", "listening_signal", "report_overdue", "qstash_dlq", "qstash_dispatch_backlog"];
	const tasks = Array.from({ length: 48 }, (_, index) => {
		const account = accounts[index % accounts.length]!;
		const source = taskSources[index % taskSources.length]!;
		return {
			id: `task-scale-${index + 1}`,
			source,
			source_id: `${source}-${index + 1}`,
			title: `${titleForSource(source)} for @${account.username}`,
			priority: index % 5 === 0 ? "critical" : index % 3 === 0 ? "high" : "medium",
			status: "open",
			due_at: new Date(now.getTime() + (index + 1) * 900_000).toISOString(),
			sla_at: new Date(now.getTime() + (index + 2) * 900_000).toISOString(),
			account_id: account.id,
			group_id: account.group_id,
			workspace_id: "scale-workspace",
			recommended_action: {
				type: source,
				route: source === "qstash_dlq" ? "/admin/dead-letters" : source === "qstash_dispatch_backlog" ? "/calendar?status=queued" : undefined,
			},
			linked_entity_type: source,
			linked_entity_id: `${source}-${index + 1}`,
			created_at: isoNow,
		};
	});

	const approvals = Array.from({ length: 18 }, (_, index) => {
		const account = accounts[index]!;
		const intentId = `intent-scale-${index + 1}`;
		return {
			id: `approval-scale-${index + 1}`,
			context: `Approve scheduled post for @${account.username}`,
			urgency: index % 4 === 0 ? "high" : "medium",
			status: index % 6 === 0 || index === 7 ? "approved" : "pending",
			expires_at: new Date(now.getTime() + 86_400_000).toISOString(),
			created_at: isoNow,
			proposed_actions: [
				{
					actionName: account.platform === "instagram" ? "schedule_instagram_post" : "schedule_threads_post",
					intentId,
					riskLevel: index % 4 === 0 ? "high" : "medium",
					payloadHash: `payload-hash-${index + 1}`,
					contentHash: `content-hash-${index + 1}`,
					idempotencyKey: `approval-scale-${index + 1}`,
					...(index === 1
						? {
								previousApprovalId: "approval-scale-original-2",
								previousIntentId: "intent-scale-original-2",
								revisedAt: new Date(now.getTime() - 1_800_000).toISOString(),
							}
						: {}),
					...(index === 6
						? {
								decidedAt: new Date(now.getTime() - 900_000).toISOString(),
								decisionNote: "Approved after copy review.",
								dispatchStatus: "consumed",
								dispatchedAt: new Date(now.getTime() - 600_000).toISOString(),
							}
						: {}),
					...(index === 7
						? {
								decidedAt: new Date(now.getTime() - 1_200_000).toISOString(),
								decisionNote: "Approved but dispatch needs recovery.",
								dispatchStatus: "failed",
								dispatchMessage: "Scale handler rejected the scheduled media URL.",
								recoveryTaskId: "task-scale-dispatch-7",
								dispatchedAt: new Date(now.getTime() - 900_000).toISOString(),
							}
						: {}),
					scope: { accountId: account.id, groupId: account.group_id, workspaceId: "scale-workspace" },
					normalizedPayload: {
						accountId: account.id,
						platform: account.platform,
						content: `Scale approval caption ${index + 1}`,
						mediaUrls: [`https://cdn.juno33.test/media/scale-${index + 1}.jpg`],
						scheduledFor: new Date(now.getTime() + 7_200_000).toISOString(),
					},
				},
			],
		};
	});

	const inboxMessages = Array.from({ length: 80 }, (_, index) => {
		const account = accounts[index % accounts.length]!;
		const source = account.platform === "threads"
			? index % 2 === 0 ? "threads_reply" : "threads_mention"
			: index % 2 === 0 ? "ig_comment" : "ig_dm";
		return {
			id: `inbox-scale-${index + 1}`,
			source,
			accountId: account.id,
			groupId: account.group_id,
			conversationId: `conversation-scale-${index + 1}`,
			replyToId: `reply-target-${index + 1}`,
			replyKind: source === "ig_dm" ? "dm" : account.platform === "instagram" ? "comment" : "reply",
			from: { id: `fan-${index + 1}`, username: `customer_${index + 1}` },
			text: `Scale inbox message ${index + 1} needing operator review.`,
			timestamp: new Date(now.getTime() - index * 300_000).toISOString(),
			sentiment: index % 5 === 0 ? "negative" : index % 3 === 0 ? "positive" : "neutral",
			isRead: index % 4 === 0,
			isReplied: false,
			priority: 100 - index,
		};
	});

	const reports = Array.from({ length: 28 }, (_, index) => ({
		id: `report-scale-${index + 1}`,
		user_id: user.id,
		name: `Scale Report ${index + 1}`,
		type: index % 5 === 0 ? "one-off" : "scheduled",
		cadence: index % 5 === 0 ? "one-off" : index % 2 === 0 ? "weekly" : "monthly",
		status: index % 4 === 0 ? "active" : "generated",
		network: groups[index % groups.length]!.id,
		recipients: [{ email: `client${index + 1}@example.com` }],
		last_run_at: new Date(now.getTime() - index * 86_400_000).toISOString(),
		next_run_at: new Date(now.getTime() + (index + 1) * 86_400_000).toISOString(),
		config: { groupIds: [groups[index % groups.length]!.id], platform: index % 2 === 0 ? "threads" : "instagram" },
		last_sent_at: new Date(now.getTime() - index * 3_600_000).toISOString(),
		created_at: isoNow,
		updated_at: isoNow,
	}));

	const reportSendLogs = reports.map((report, index) => ({
		id: `report-send-scale-${index + 1}`,
		report_id: report.id,
		recipients: report.recipients,
		status: index % 6 === 0 ? "failed" : "sent",
		error: index % 6 === 0 ? "Email provider rejected one recipient" : null,
		sent_at: new Date(now.getTime() - index * 3_600_000).toISOString(),
	}));

	const listeningAlerts = Array.from({ length: 12 }, (_, index) => ({
		id: `listening-alert-scale-${index + 1}`,
		user_id: user.id,
		workspace_id: "scale-workspace",
		keyword: `scale keyword ${index + 1}`,
		alert_type: index % 2 === 0 ? "keyword" : "mention",
		threshold_value: 10 + index,
		is_active: true,
		last_checked_at: new Date(now.getTime() - index * 1_800_000).toISOString(),
	}));

	const listeningResults = listeningAlerts.slice(0, 8).map((alert, index) => ({
		id: `listening-result-scale-${index + 1}`,
		alert_id: alert.id,
		workspace_id: "scale-workspace",
		keyword: alert.keyword,
		result_count: 15 + index,
		source: index % 2 === 0 ? "threads" : "instagram",
		checked_at: new Date(now.getTime() - index * 1_200_000).toISOString(),
		sentiment_breakdown: { positive: 6 + index, neutral: 5, negative: index % 3 },
	}));

	const competitors = Array.from({ length: 16 }, (_, index) => ({
		id: `competitor-scale-${index + 1}`,
		user_id: user.id,
		username: `competitor_scale_${index + 1}`,
		display_name: `Competitor Scale ${index + 1}`,
		avatar_url: null,
		follower_count: 50_000 + index * 1500,
		engagement_rate: 0.03 + index * 0.001,
		platform: index % 2 === 0 ? "threads" : "instagram",
		last_synced_at: new Date(now.getTime() - index * 3_600_000).toISOString(),
		sync_status: "synced",
	}));

	const competitorPosts = competitors.slice(0, 10).map((competitor, index) => ({
		id: `competitor-post-scale-${index + 1}`,
		competitor_id: competitor.id,
		competitor_username: competitor.username,
		content: `Competitor scale post ${index + 1} with an angle worth reviewing.`,
		engagement_score: 900 + index * 41,
		like_count: 500 + index * 30,
		reply_count: 40 + index,
		repost_count: 12 + index,
		view_count: 10_000 + index * 500,
		permalink: `https://threads.net/@${competitor.username}/post/${index + 1}`,
		platform: competitor.platform,
		published_at: new Date(now.getTime() - index * 3_600_000).toISOString(),
		topic_tag: `Scale competitor angle ${index + 1}`,
	}));

	const trendKeywords = Array.from({ length: 12 }, (_, index) => ({
		id: `trend-keyword-scale-${index + 1}`,
		user_id: user.id,
		keyword: `scale trend ${index + 1}`,
		category: "operator",
		is_active: true,
		post_count: 30 + index,
		total_engagement: 20_000 + index * 750,
		last_synced_at: new Date(now.getTime() - index * 2_700_000).toISOString(),
	}));

	const trendPosts = trendKeywords.slice(0, 10).map((keyword, index) => ({
		id: `trend-post-scale-${index + 1}`,
		keyword_id: keyword.id,
		content: `Trend scale post ${index + 1} that should become an idea or reply draft.`,
		username: `trend_source_${index + 1}`,
		engagement_score: 700 + index * 37,
		like_count: 300 + index * 20,
		reply_count: 30 + index,
		repost_count: 10 + index,
		view_count: 8000 + index * 400,
		permalink: `https://threads.net/@trend_source_${index + 1}/post/${index + 1}`,
		posted_at: new Date(now.getTime() - index * 3_600_000).toISOString(),
	}));

	const unhealthyAccounts = accounts
		.filter((account, index) => index % 19 === 0 || account.needs_reauth)
		.slice(0, 40)
		.map((account) => ({
			accountId: account.id,
			handle: `@${account.username}`,
			platform: account.platform,
			group_id: account.group_id,
			status: account.status ?? "active",
			severity: account.needs_reauth ? "critical" : "warning",
			reasons: account.needs_reauth ? ["Needs reauth"] : ["Inactive"],
			needsReauth: account.needs_reauth === true,
			tokenExpiresAt: account.token_expires_at,
			lastSyncedAt: account.last_synced_at,
			isActive: account.is_active,
			route: `/accounts?accountId=${account.id}`,
		}));

	const operatorSnapshot = {
		success: true,
		generatedAt: isoNow,
		tasks,
		pendingApprovals: approvals.filter((approval) => approval.status === "pending"),
		failedPosts: posts.filter((post) => post.status === "failed").map((post) => ({
			id: post.id,
			account_id: post.account_id ?? post.instagram_account_id,
			platform: post.platform,
			content: post.content,
			status: post.status,
			error_message: "Scale fixture publish failure",
			updated_at: isoNow,
		})),
		recentDecisions: [],
		managerBrain: { activeGoals: [], recentDecisions: [] },
		opsHealth: {
			generatedAt: isoNow,
			score: 74,
			tone: "warning",
			summary: {
				critical: 6,
				warning: 18,
				healthy: false,
				impactedAccountCount: unhealthyAccounts.length,
			},
			metrics: [
				{ key: "cron", label: "Cron freshness", value: "4m ago", status: "healthy", route: "/settings?tab=ops" },
				{ key: "webhooks", label: "Webhook backlog", value: 12, status: "warning", route: "/settings?tab=webhooks" },
				{ key: "failed_posts", label: "Failed posts", value: 8, status: "critical", route: "/calendar?status=failed" },
			],
			issues: [
				{ key: "failed-posts", title: "8 failed posts need recovery", severity: "critical", source: "publish", route: "/calendar?status=failed" },
				{ key: "tokens", title: "6 accounts need reauth", severity: "critical", source: "tokens", route: "/accounts?status=flagged" },
			],
			impactedAccountIds: unhealthyAccounts.map((account) => account.accountId),
			unhealthyAccounts,
			unhealthyAccountTotal: unhealthyAccounts.length,
			lastSuccessfulCronAt: new Date(now.getTime() - 240_000).toISOString(),
		},
		reliabilitySlo: {
			generatedAt: isoNow,
			windowHours: 24,
			scheduledTotal: 220,
			publishedTotal: 204,
			failedTotal: 8,
			onTime60s: 194,
			lateOver5m: 6,
			successRate: 92.7,
			onTimeRate: 95.1,
			driftSeconds: { p50: 22, p95: 412, p99: 740, max: 920, avg: 61 },
			qstashFailures: 4,
			dlqCount: 4,
			backlogCount: 34,
			impactedAccountIds: accounts.slice(0, 12).map((account) => account.id),
			tone: "critical",
			issues: [
				{ key: "failed_posts", title: "8 scheduled posts failed", severity: "critical", route: "/calendar?status=failed" },
				{ key: "publish_drift", title: "6 posts drifted over 5 minutes", severity: "warning", route: "/calendar?status=published" },
				{ key: "qstash_dlq", title: "4 queue items are dead-lettered", severity: "critical", route: "/admin/dead-letters" },
			],
			trend: [
				{ windowEnd: days[0], successRate: 99.2, onTimeRate: 98.7, p95DriftSeconds: 88, failedTotal: 1, dlqCount: 0 },
				{ windowEnd: days[1], successRate: 92.7, onTimeRate: 95.1, p95DriftSeconds: 412, failedTotal: 8, dlqCount: 4 },
			],
		},
		metaApiUsage: {
			generatedAt: isoNow,
			tone: "warning",
			latest: [
				{ id: "meta-usage-scale-1", platform: "instagram", endpoint_family: "igPublish", usage_percent: 84, retry_after_seconds: 0, tone: "warning", captured_at: isoNow },
				{ id: "meta-usage-scale-2", platform: "threads", endpoint_family: "postToThreads:publish", usage_percent: 72, retry_after_seconds: 0, tone: "healthy", captured_at: isoNow },
			],
			maxUsagePercent: 84,
			retryAfterActiveCount: 0,
			warningCount: 1,
			criticalCount: 0,
		},
		webhookHealth: {
			generatedAt: isoNow,
			tone: "warning",
			failedDeliveries: 7,
			deadLetterDeliveries: 2,
			threadsDeadLetters: 3,
			instagramDeadLetters: 2,
			nextRetryCount: 4,
			issues: [{ id: "webhook-scale-1", event: "comment", status: "failed", attempts: 2, next_retry_at: isoNow }],
		},
		tokenSlo: {
			generatedAt: isoNow,
			tone: "critical",
			totalIssues: unhealthyAccounts.length,
			needsReauth: unhealthyAccounts.filter((account) => account.needsReauth).length,
			expiringSoon: 18,
			expired: 2,
			accounts: unhealthyAccounts.slice(0, 12).map((account) => ({
				id: account.accountId,
				handle: account.handle,
				platform: account.platform,
				group_id: account.group_id,
				status: account.status,
				needs_reauth: account.needsReauth,
				token_expires_at: account.tokenExpiresAt,
				last_token_refresh_at: new Date(now.getTime() - 7_200_000).toISOString(),
				token_refresh_failures: account.needsReauth ? 2 : 0,
				route: account.route,
			})),
		},
		fleetCapacity: {
			generatedAt: isoNow,
			windowDays: 7,
			activeAccountCount: accounts.filter((account) => account.is_active).length,
			score: 71,
			tone: "warning",
			totals: {
				scheduled: fleetDays.reduce((sum, day) => sum + day.scheduled, 0),
				publishing: 14,
				failed: 22,
				pendingQueue: 750,
				deadLetter: 10,
				approvalPending: 30,
				gapCount: 189,
			},
			days: fleetDays,
			accounts: fleetAccounts,
			groups: groups.map((group) => ({
				id: group.id,
				name: group.name,
				color: group.color,
				accountCount: group.account_ids.length,
			})),
			recommendations: [
				{ type: "recover_failed", route: "/calendar?status=failed", label: "Recover failed posts" },
				{ type: "review_approval", route: "/approval-queue?status=pending", label: "Review pending approvals" },
				{ type: "fill_gap", route: "/composer", label: "Fill schedule gaps" },
			],
		},
		aiEvalSummary: {
			generatedAt: isoNow,
			windowDays: 14,
			total: 86,
			passed: 80,
			failed: 6,
			passRate: 93,
			avgRegressionScore: 0.91,
			tone: "warning",
			latestFailures: [{ id: "eval-scale-1", surface: "trend_pipeline_generator", reason: "needs human review" }],
			coverage: {
				hasGoldenEvals: true,
				hasLiveSnapshots: true,
				directGenerativeSurfaceCount: 5,
				directGenerativeCoveredCount: 5,
				documentedNonGenerativeCount: 4,
				uncoveredDirectSurfaces: [],
			},
		},
		recommendedNextActions: [
			{ type: "recover_failed", label: "Recover failed posts" },
			{ type: "review_approvals", label: "Review pending approvals" },
		],
		warnings: [],
	};

	const calendarWeek = {
		posts,
		groups: groups.map((group) => ({ id: group.id, name: group.name, color: group.color })),
		queueHealthByGroup: Object.fromEntries(
			groups.map((group) => [
				group.id,
				{
					id: group.id,
					name: group.name,
					color: group.color,
					postsCount: 40,
					daysOfContent: 13,
				},
			]),
		),
		gapsCount: 189,
		totalQueue: 750,
	};

	const threadsAccounts = accounts.filter((account) => account.platform === "threads");
	const instagramAccounts = accounts.filter((account) => account.platform === "instagram");

	return {
		user,
		groups,
		accounts,
		threadsAccounts,
		instagramAccounts,
		posts,
		calendarWeek,
		operatorSnapshot,
		approvals,
		inboxMessages,
		listeningAlerts,
		listeningResults,
		competitors,
		competitorPosts,
		trendKeywords,
		trendPosts,
		reports,
		reportSendLogs,
	};
}

function startOfWeek(date: Date): Date {
	const out = new Date(date);
	const day = (out.getUTCDay() + 6) % 7;
	out.setUTCDate(out.getUTCDate() - day);
	out.setUTCHours(0, 0, 0, 0);
	return out;
}

function addDays(date: Date, days: number): Date {
	const out = new Date(date);
	out.setUTCDate(out.getUTCDate() + days);
	return out;
}

function dateOnly(date: Date): string {
	return date.toISOString().slice(0, 10);
}

function titleForSource(source: string): string {
	if (source === "failed_publish") return "Recover failed publish";
	if (source === "approval") return "Review approval";
	if (source === "token_reauth") return "Reconnect account";
	if (source === "inbox_attention") return "Reply to inbox item";
	if (source === "listening_signal") return "Review listening signal";
	if (source === "report_overdue") return "Run overdue report";
	if (source === "qstash_dlq") return "Recover QStash DLQ";
	if (source === "qstash_dispatch_backlog") return "Dispatch queue backlog";
	return "Operator task";
}
