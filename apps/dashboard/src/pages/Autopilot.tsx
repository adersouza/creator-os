import type React from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
	Pause,
	RotateCw,
	AlertTriangle,
	AlertCircle,
	Clock,
	CheckCircle2,
	Activity,
	Zap,
	ChevronRight,
	Gauge,
	ShieldAlert,
	ShieldCheck,
	CircleSlash2,
	ListChecks,
	PlayCircle,
	Leaf,
	Repeat2,
	SlidersHorizontal,
	History,
	ServerCog,
	BrainCircuit,
	Trash2,
	Plus,
	Search,
	Wrench,
	ChevronDown,
	Power,
	Fingerprint,
} from "lucide-react";
import { Sparkline as UISparkline } from "@/components/ui/Sparkline";
import { StatusPill } from "@/components/ui/StatusPill";
import { NovaScreen } from "@/components/layout/NovaScreen";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
	NovaDataPanel,
	NovaEmpty,
	NovaHeader,
	NovaMiniStat,
	NovaSection,
	NovaToolbar,
} from "@/components/ui/NovaPrimitives";
import { Input } from "@/components/ui/Input";
import { Kbd, KbdGroup } from "@/components/ui/Kbd";
import { Select } from "@/components/ui/Select";
import { Skeleton } from "@/components/ui/Skeleton";
import { Textarea } from "@/components/ui/Textarea";
import { cn } from "@/lib/utils";
import {
	fetchJobs,
	fetchRateLimits,
	fetchQueueHealth,
	fetchFailures,
	fetchReplayRuns,
	fetchReplaySteps,
	replayAutopilotStep,
	retryFailedPost,
	type AutopilotReplayRun,
	type AutopilotReplayStep,
	type AutopilotRunStatus,
	type AutopilotStepStatus,
	type FailureRow as ServiceFailureRow,
	type JobSummary,
	type QueueHealthRow,
	type RateLimitRow as ServiceRateLimitRow,
} from "@/services/autopilotService";
import {
	getAutoPostConfig,
	getGroupConfigs,
	saveAutoPostConfig,
	toggleAutoPost,
	upsertGroupConfig,
	backfillAccountDna,
	fetchAccountDnaOpsSummary,
	fetchRestartWarmupOpsSummary,
	type AutoPostConfig,
	type AccountDnaBackfillResponse,
	type AccountDnaOpsSummary,
	type RestartWarmupOpsSummary,
	type AccountDnaProfileSummary,
	type AccountDnaReviewItem,
	type GroupConfig,
} from "@/services/autoPost";
import {
	deleteAgentNote,
	fetchAgentLog,
	fetchAgentNotes,
	fetchAgentSettings,
	saveAgentNote,
	setAgentPaused,
	type AgentActionLogRow,
	type AgentNoteRow,
	type AgentSettings,
} from "@/services/agentService";
import { AutopilotSkeleton } from "@/components/skeletons/PageSkeletons";
import { groupColorFromId, groupLabelFromId } from "@/lib/groupPresentation";
import {
	ConditionsModePage,
	QueueModePage,
	SchemaGatedMode,
} from "@/components/autopilot/AutopilotModePages";

/* =========================================================================
   Autopilot — operator surface for the auto-poster backend.
   Single-scroll layout, three focused bands:
     1. Jobs (left) + Failures feed (right) — the diagnostic pair
     2. Queue health — days-of-content bars, link to Calendar for detail
     3. Rate limits — signal-first (sorted by % desc, warn/critical default)
   Hero Pause all / Resume wire auto_post_config.is_enabled workspace-wide.
   Keyboard: J/K navigate failures · R retry focused · Enter opens account.
   ========================================================================= */

type JobStatus = "running" | "idle" | "paused" | "failed";
type HealthTone = "good" | "warn" | "critical";

type Job = JobSummary;

type Failure = ServiceFailureRow & {
	retrying?: boolean | undefined;
	resolved?: boolean | undefined;
	retryError?: string | undefined;
};

type RateLimit = ServiceRateLimitRow;
type AutopilotSection =
	| "agent"
	| "replay"
	| "queue"
	| "evergreen"
	| "recurrent"
	| "conditions"
	| "health"
	| "history";
type FailureWindow = "24h" | "7d" | "30d";
type FailureBucket = {
	key: string;
	label: string;
	startMs: number;
	endMs: number;
	count: number;
	dominantClass: string;
};
type FailureGroup = {
	className: string;
	count: number;
	firstSeenMs: number;
	lastSeenMs: number;
	failures: Failure[];
	accounts: Array<{ key: string; handle: string; avatarUrl: string | null }>;
};
type AccountFailureHealth = {
	key: string;
	accountId: string | null;
	handle: string;
	avatarUrl: string | null;
	count: number;
	lastSeenMs: number;
	mostRecentClass: string;
	status: "failing" | "recovering" | "healthy";
};

const AUTOPILOT_SECTIONS: Array<{
	id: AutopilotSection;
	label: string;
	shortcut: string;
	group: "Agent" | "Modes" | "Engine";
	icon: React.ComponentType<{ className?: string | undefined }>;
}> = [
	{
		id: "agent",
		label: "Agent",
		shortcut: "A",
		group: "Agent",
		icon: BrainCircuit,
	},
	{
		id: "replay",
		label: "Replay",
		shortcut: "P",
		group: "Agent",
		icon: PlayCircle,
	},
	{
		id: "queue",
		label: "Queue",
		shortcut: "Q",
		group: "Modes",
		icon: ListChecks,
	},
	{
		id: "evergreen",
		label: "Evergreen",
		shortcut: "E",
		group: "Modes",
		icon: Leaf,
	},
	{
		id: "recurrent",
		label: "Recurrent",
		shortcut: "R",
		group: "Modes",
		icon: Repeat2,
	},
	{
		id: "conditions",
		label: "Conditions",
		shortcut: "C",
		group: "Engine",
		icon: SlidersHorizontal,
	},
	{
		id: "health",
		label: "Health",
		shortcut: "H",
		group: "Engine",
		icon: ServerCog,
	},
	{
		id: "history",
		label: "History",
		shortcut: "",
		group: "Engine",
		icon: History,
	},
];

const SECTION_TITLES: Record<
	AutopilotSection,
	{ title: string; meta: string }
> = {
	agent: {
		title: "Agent",
		meta: "Explainable autonomous decisions, operator notes, and the kill switch.",
	},
	replay: {
		title: "Replay",
		meta: "Per-step autoposter run playback with safe replay from captured inputs.",
	},
	queue: {
		title: "Queue",
		meta: "Scheduled inventory by account group, with cap progress and condition state.",
	},
	evergreen: {
		title: "Evergreen",
		meta: "High-performing posts eligible to re-enter the queue after storage support is active.",
	},
	recurrent: {
		title: "Recurrent",
		meta: "Republish-as-new cycles, gated until recurrent scheduling fields exist.",
	},
	conditions: {
		title: "Conditions",
		meta: "Read-only rule pills for the engine thresholds Autopilot can enforce today.",
	},
	health: {
		title: "Health",
		meta: "The existing job, failure, queue coverage, and rate-limit diagnostics.",
	},
	history: {
		title: "History",
		meta: "Chronological engine history. Step replay lives in the Replay section.",
	},
};

/* Rate limits have no cached fallback — when the live read fails we render
 * the empty "All buckets healthy" state rather than fabricating accounts. */
const INITIAL_RATE_LIMITS: RateLimit[] = [];
const FAILURE_WINDOWS: Array<{ id: FailureWindow; label: string }> = [
	{ id: "24h", label: "24h" },
	{ id: "7d", label: "7d" },
	{ id: "30d", label: "30d" },
];

/* =========================================================================
   HELPERS
   ========================================================================= */

function formatPercent(n: number): string {
	return `${n.toFixed(1).replace(/\.0$/, "")}%`;
}

function formatDateTime(iso: string): string {
	const date = new Date(iso);
	if (Number.isNaN(date.getTime())) return "—";
	return new Intl.DateTimeFormat(undefined, {
		month: "short",
		day: "numeric",
		hour: "numeric",
		minute: "2-digit",
	}).format(date);
}

function relativeShort(iso: string): string {
	const date = new Date(iso);
	if (Number.isNaN(date.getTime())) return "—";
	const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
	if (seconds < 60) return "now";
	const minutes = Math.floor(seconds / 60);
	if (minutes < 60) return `${minutes}m ago`;
	const hours = Math.floor(minutes / 60);
	if (hours < 24) return `${hours}h ago`;
	return `${Math.floor(hours / 24)}d ago`;
}

function failureWindowStartMs(window: FailureWindow): number {
	const now = Date.now();
	const days = window === "24h" ? 1 : window === "7d" ? 7 : 30;
	return now - days * 24 * 60 * 60 * 1000;
}

function failureTimestampMs(failure: Failure): number | null {
	if (!failure.failedAt) return null;
	const ms = new Date(failure.failedAt).getTime();
	return Number.isNaN(ms) ? null : ms;
}

function formatBucketLabel(date: Date, window: FailureWindow): string {
	if (window === "24h") {
		return new Intl.DateTimeFormat(undefined, { hour: "numeric" }).format(date);
	}
	return new Intl.DateTimeFormat(undefined, {
		month: "short",
		day: "numeric",
	}).format(date);
}

function bucketKey(ms: number, window: FailureWindow): string {
	const date = new Date(ms);
	if (window === "24h") {
		date.setMinutes(0, 0, 0);
		return date.toISOString();
	}
	date.setHours(0, 0, 0, 0);
	return date.toISOString();
}

function buildFailureBuckets(
	failures: Failure[],
	window: FailureWindow,
): FailureBucket[] {
	const bucketMs = window === "24h" ? 60 * 60 * 1000 : 24 * 60 * 60 * 1000;
	const count = window === "24h" ? 24 : window === "7d" ? 7 : 30;
	const now = Date.now();
	const startMs = now - count * bucketMs;
	const buckets: FailureBucket[] = Array.from({ length: count }, (_, index) => {
		const start = startMs + index * bucketMs;
		const normalizedStart =
			window === "24h"
				? new Date(new Date(start).setMinutes(0, 0, 0)).getTime()
				: new Date(new Date(start).setHours(0, 0, 0, 0)).getTime();
		return {
			key: new Date(normalizedStart).toISOString(),
			label: formatBucketLabel(new Date(normalizedStart), window),
			startMs: normalizedStart,
			endMs: normalizedStart + bucketMs,
			count: 0,
			dominantClass: "None",
		};
	});
	const byKey = new Map(buckets.map((bucket) => [bucket.key, bucket]));
	const classesByKey = new Map<string, Map<string, number>>();

	failures.forEach((failure) => {
		const ms = failureTimestampMs(failure);
		if (ms === null || ms < startMs || ms > now) return;
		const key = bucketKey(ms, window);
		const bucket = byKey.get(key);
		if (!bucket) return;
		bucket.count += 1;
		const classCounts = classesByKey.get(key) ?? new Map<string, number>();
		classCounts.set(
			failure.failureClass,
			(classCounts.get(failure.failureClass) ?? 0) + 1,
		);
		classesByKey.set(key, classCounts);
	});

	buckets.forEach((bucket) => {
		const classCounts = classesByKey.get(bucket.key);
		if (!classCounts) return;
		bucket.dominantClass =
			Array.from(classCounts.entries()).sort((a, b) => b[1] - a[1])[0]?.[0] ??
			"Other";
	});

	return buckets;
}

function groupFailures(failures: Failure[]): FailureGroup[] {
	const groups = new Map<string, FailureGroup>();
	failures.forEach((failure) => {
		const ms = failureTimestampMs(failure);
		if (ms === null) return;
		const key = failure.failureClass || "Other";
		const group = groups.get(key) ?? {
			className: key,
			count: 0,
			firstSeenMs: ms,
			lastSeenMs: ms,
			failures: [],
			accounts: [],
		};
		group.count += 1;
		group.firstSeenMs = Math.min(group.firstSeenMs, ms);
		group.lastSeenMs = Math.max(group.lastSeenMs, ms);
		group.failures.push(failure);
		const accountKey = failure.accountId ?? failure.handle;
		if (!group.accounts.some((account) => account.key === accountKey)) {
			group.accounts.push({
				key: accountKey,
				handle: failure.handle,
				avatarUrl: failure.avatarUrl,
			});
		}
		groups.set(key, group);
	});

	return Array.from(groups.values()).sort((a, b) => {
		if (b.count !== a.count) return b.count - a.count;
		return b.lastSeenMs - a.lastSeenMs;
	});
}

function accountFailureHealth(failures: Failure[]): AccountFailureHealth[] {
	const rows = new Map<string, AccountFailureHealth>();
	failures.forEach((failure) => {
		const ms = failureTimestampMs(failure);
		if (ms === null) return;
		const key = failure.accountId ?? failure.handle;
		const existing = rows.get(key);
		if (!existing || ms > existing.lastSeenMs) {
			rows.set(key, {
				key,
				accountId: failure.accountId,
				handle: failure.handle,
				avatarUrl: failure.avatarUrl,
				count: (existing?.count ?? 0) + 1,
				lastSeenMs: ms,
				mostRecentClass: failure.failureClass,
				status:
					ms >= Date.now() - 24 * 60 * 60 * 1000 ? "failing" : "recovering",
			});
		} else {
			existing.count += 1;
		}
	});

	return Array.from(rows.values()).sort((a, b) => {
		if (b.count !== a.count) return b.count - a.count;
		return b.lastSeenMs - a.lastSeenMs;
	});
}

function truncateFailureMessage(value: string): string {
	return value.length > 180 ? `${value.slice(0, 177)}...` : value;
}

function asRecord(value: unknown): Record<string, unknown> {
	return value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: {};
}

function stringParam(
	params: Record<string, unknown>,
	keys: string[],
): string | null {
	for (const key of keys) {
		const value = params[key];
		if (typeof value === "string" && value.trim()) return value.trim();
		if (typeof value === "number") return String(value);
	}
	return null;
}

function humanizeToolName(toolName: string): string {
	return toolName
		.replace(/^get_/, "read_")
		.replace(/_/g, " ")
		.replace(/\b\w/g, (char) => char.toUpperCase());
}

function classifyAgentAction(toolName: string): string {
	if (toolName.includes("publish") || toolName.includes("schedule"))
		return "publishing";
	if (toolName.includes("pause") || toolName.includes("settings"))
		return "control";
	if (toolName.includes("approval")) return "approval";
	if (toolName.includes("note")) return "memory";
	if (
		toolName.includes("anomaly") ||
		toolName.includes("health") ||
		toolName.includes("cap")
	)
		return "health";
	if (toolName.startsWith("get_") || toolName.startsWith("search_"))
		return "read";
	return "tool";
}

function deriveAgentSeverity(row: AgentActionLogRow): AgentSeverity {
	const params = asRecord(row.params_json);
	const explicit = stringParam(params, ["severity", "urgency", "confidence"]);
	if (explicit?.toLowerCase().includes("high")) return "high";
	if (explicit?.toLowerCase().includes("medium")) return "medium";
	if (!row.success) return "high";
	if (
		row.tool_name.includes("pause") ||
		row.tool_name.includes("publish") ||
		row.tool_name.includes("approval")
	) {
		return "medium";
	}
	return "info";
}

function extractAgentTarget(row: AgentActionLogRow): string {
	const params = asRecord(row.params_json);
	const handle = stringParam(params, ["handle", "username", "account_handle"]);
	if (handle) return handle.startsWith("@") ? handle : `@${handle}`;
	const account = stringParam(params, [
		"accountId",
		"account_id",
		"instagram_account_id",
	]);
	if (account) return `Account ${account.slice(0, 8)}`;
	const post = stringParam(params, ["postId", "post_id", "queue_item_id"]);
	if (post) return `Post ${post.slice(0, 8)}`;
	const group = stringParam(params, [
		"accountGroupId",
		"account_group_id",
		"groupId",
	]);
	if (group) return `Group ${group.slice(0, 8)}`;
	return "Workspace";
}

function extractAgentReason(row: AgentActionLogRow): string {
	if (row.reason) return row.reason;
	const params = asRecord(row.params_json);
	const reason = stringParam(params, [
		"reason",
		"context",
		"summary",
		"decision",
		"message",
	]);
	if (reason) return reason;
	if (row.result_summary && row.result_summary !== "ok")
		return row.result_summary;
	const target = extractAgentTarget(row);
	return `${humanizeToolName(row.tool_name)} completed for ${target}; source parameters are available in the expanded tool payload.`;
}

const STATUS_META: Record<
	JobStatus,
	{ label: string; tone: "good" | "idle" | "warn" | "critical"; pulse: boolean }
> = {
	running: { label: "Running", tone: "good", pulse: true },
	idle: { label: "Idle", tone: "idle", pulse: false },
	paused: { label: "Paused", tone: "warn", pulse: false },
	failed: { label: "Failed", tone: "critical", pulse: true },
};

function JobStatusPill({ status }: { status: JobStatus }) {
	const meta = STATUS_META[status];
	return (
		<StatusPill
			tone={meta.tone}
			size="xs"
			dot
			live={meta.pulse}
			className="!rounded-md"
		>
			{meta.label}
		</StatusPill>
	);
}

/* =========================================================================
   COMPONENT
   ========================================================================= */
export function Autopilot() {
	const navigate = useNavigate();
	const { section, runId } = useParams<{
		section?: string | undefined;
		runId?: string | undefined;
	}>();
	const activeSection = isAutopilotSection(section) ? section : "queue";
	const [jobs, setJobs] = useState<Job[]>([]);
	const [jobsLoading, setJobsLoading] = useState(true);
	const [jobsError, setJobsError] = useState<string | null>(null);
	const [queueRows, setQueueRows] = useState<QueueHealthRow[]>([]);
	const [queueLoading, setQueueLoading] = useState(true);
	const [queueError, setQueueError] = useState<string | null>(null);
	const [conditionConfigs, setConditionConfigs] = useState<GroupConfig[]>([]);
	const [conditionLoading, setConditionLoading] = useState(true);
	const [conditionError, setConditionError] = useState<string | null>(null);
	const [conditionSavingKey, setConditionSavingKey] = useState<string | null>(
		null,
	);
	const [workspaceConditionSavingKey, setWorkspaceConditionSavingKey] =
		useState<string | null>(null);
	const [workspaceAutoPostConfig, setWorkspaceAutoPostConfig] =
		useState<AutoPostConfig | null>(null);
	const [failures, setFailures] = useState<Failure[]>([]);
	const [failuresLoading, setFailuresLoading] = useState(true);
	const [failuresError, setFailuresError] = useState<string | null>(null);
	const [rateLimits, setRateLimits] = useState<RateLimit[]>([]);
	const [rateLoading, setRateLoading] = useState(true);
	const [rateError, setRateError] = useState<string | null>(null);
	const [showAllRate, setShowAllRate] = useState(false);
	const [failureWindow, setFailureWindow] = useState<FailureWindow>("24h");
	const [selectedFailureBucketKey, setSelectedFailureBucketKey] = useState<
		string | null
	>(null);
	const [expandedFailureClass, setExpandedFailureClass] = useState<
		string | null
	>(null);

	/* --- workspace pause state (auto_post_config.is_enabled) --- */
	const [workspacePaused, setWorkspacePaused] = useState<boolean | null>(null);
	const [togglingWorkspace, setTogglingWorkspace] = useState(false);
	const [workspaceToggleError, setWorkspaceToggleError] = useState<
		string | null
	>(null);
	const [workspaceToggleWarning, setWorkspaceToggleWarning] = useState<
		string | null
	>(null);
	const [agentLog, setAgentLog] = useState<AgentActionLogRow[]>([]);
	const [agentLogLoading, setAgentLogLoading] = useState(true);
	const [agentLogError, setAgentLogError] = useState<string | null>(null);
	const [agentNotes, setAgentNotes] = useState<AgentNoteRow[]>([]);
	const [agentNotesLoading, setAgentNotesLoading] = useState(true);
	const [agentNotesError, setAgentNotesError] = useState<string | null>(null);
	const [agentSettings, setAgentSettingsState] = useState<AgentSettings | null>(
		null,
	);
	const [agentSettingsLoading, setAgentSettingsLoading] = useState(true);
	const [agentSettingsError, setAgentSettingsError] = useState<string | null>(
		null,
	);
	const [agentPauseConfirm, setAgentPauseConfirm] = useState<boolean | null>(
		null,
	);
	const [agentPauseSaving, setAgentPauseSaving] = useState(false);
	const [agentPauseError, setAgentPauseError] = useState<string | null>(null);
	const [replayRuns, setReplayRuns] = useState<AutopilotReplayRun[]>([]);
	const [replayRunsLoading, setReplayRunsLoading] = useState(true);
	const [replayRunsError, setReplayRunsError] = useState<string | null>(null);
	const [replaySteps, setReplaySteps] = useState<AutopilotReplayStep[]>([]);
	const [replayStepsLoading, setReplayStepsLoading] = useState(false);
	const [replayStepsError, setReplayStepsError] = useState<string | null>(null);
	const [replayRunTypeFilter, setReplayRunTypeFilter] = useState<string>("all");
	const [replayStatusFilter, setReplayStatusFilter] = useState<string>("all");
	const [expandedReplayStepId, setExpandedReplayStepId] = useState<
		string | null
	>(null);
	const [replayingStepId, setReplayingStepId] = useState<string | null>(null);
	const [replayActionError, setReplayActionError] = useState<string | null>(
		null,
	);
	const [accountDna, setAccountDna] = useState<AccountDnaOpsSummary | null>(
		null,
	);
	const [accountDnaLoading, setAccountDnaLoading] = useState(true);
	const [accountDnaError, setAccountDnaError] = useState<string | null>(null);
	const [restartWarmup, setRestartWarmup] =
		useState<RestartWarmupOpsSummary | null>(null);
	const [restartWarmupLoading, setRestartWarmupLoading] = useState(true);
	const [restartWarmupError, setRestartWarmupError] = useState<string | null>(
		null,
	);
	const [dnaBackfillRunning, setDnaBackfillRunning] = useState(false);
	const [dnaBackfillResult, setDnaBackfillResult] =
		useState<AccountDnaBackfillResponse | null>(null);

	/* --- live data: cron_runs, rate_limit_tracking, posts (queue + failures) --- */
	useEffect(() => {
		let cancelled = false;

		setJobsLoading(true);
		fetchJobs()
			.then((rows) => {
				if (cancelled) return;
				setJobs(rows);
				setJobsError(null);
			})
			.catch((e: unknown) => {
				if (cancelled) return;
				setJobs([]);
				setJobsError(
					e instanceof Error ? e.message : "Could not load job runs.",
				);
			})
			.finally(() => {
				if (!cancelled) setJobsLoading(false);
			});

		setRateLoading(true);
		fetchRateLimits()
			.then((rows) => {
				if (cancelled) return;
				setRateLimits(rows);
				setRateError(null);
			})
			.catch((e: unknown) => {
				if (cancelled) return;
				setRateLimits(INITIAL_RATE_LIMITS);
				setRateError(
					e instanceof Error ? e.message : "Could not load rate-limit buckets.",
				);
			})
			.finally(() => {
				if (!cancelled) setRateLoading(false);
			});

		setQueueLoading(true);
		fetchQueueHealth()
			.then((rows) => {
				if (cancelled) return;
				setQueueRows(rows);
				setQueueError(null);
			})
			.catch((e: unknown) => {
				if (cancelled) return;
				setQueueError(
					e instanceof Error ? e.message : "Could not load queue health.",
				);
				setQueueRows([]);
			})
			.finally(() => {
				if (!cancelled) setQueueLoading(false);
			});

		setConditionLoading(true);
		getGroupConfigs()
			.then((configs) => {
				if (cancelled) return;
				setConditionConfigs(configs);
				setConditionError(null);
			})
			.catch((e: unknown) => {
				if (cancelled) return;
				setConditionConfigs([]);
				setConditionError(
					e instanceof Error ? e.message : "Could not load group conditions.",
				);
			})
			.finally(() => {
				if (!cancelled) setConditionLoading(false);
			});

		setFailuresLoading(true);
		fetchFailures()
			.then((rows) => {
				if (cancelled) return;
				setFailures(rows.map((r) => ({ ...r })));
				setFailuresError(null);
			})
			.catch((e: unknown) => {
				if (cancelled) return;
				setFailures([]);
				setFailuresError(
					e instanceof Error ? e.message : "Could not load failures.",
				);
			})
			.finally(() => {
				if (!cancelled) setFailuresLoading(false);
			});

		getAutoPostConfig()
			.then((cfg) => {
				if (cancelled) return;
				setWorkspaceAutoPostConfig(cfg);
				setWorkspacePaused(!cfg.enabled);
			})
			.catch(() => {
				/* getAutoPostConfig already logs; leave paused unknown */
			});

		setAgentLogLoading(true);
		fetchAgentLog(100)
			.then((rows) => {
				if (cancelled) return;
				setAgentLog(rows);
				setAgentLogError(null);
			})
			.catch((e: unknown) => {
				if (cancelled) return;
				setAgentLog([]);
				setAgentLogError(
					e instanceof Error ? e.message : "Could not load agent decisions.",
				);
			})
			.finally(() => {
				if (!cancelled) setAgentLogLoading(false);
			});

		setAgentNotesLoading(true);
		fetchAgentNotes()
			.then((rows) => {
				if (cancelled) return;
				setAgentNotes(rows);
				setAgentNotesError(null);
			})
			.catch((e: unknown) => {
				if (cancelled) return;
				setAgentNotes([]);
				setAgentNotesError(
					e instanceof Error ? e.message : "Could not load agent notes.",
				);
			})
			.finally(() => {
				if (!cancelled) setAgentNotesLoading(false);
			});

		setAgentSettingsLoading(true);
		fetchAgentSettings()
			.then((settings) => {
				if (cancelled) return;
				setAgentSettingsState(settings);
				setAgentSettingsError(null);
			})
			.catch((e: unknown) => {
				if (cancelled) return;
				setAgentSettingsState(null);
				setAgentSettingsError(
					e instanceof Error ? e.message : "Could not load agent settings.",
				);
			})
			.finally(() => {
				if (!cancelled) setAgentSettingsLoading(false);
			});

		return () => {
			cancelled = true;
		};
	}, []);

	const refreshAccountDna = useCallback(async () => {
		setAccountDnaLoading(true);
		setAccountDnaError(null);
		try {
			const summary = await fetchAccountDnaOpsSummary();
			setAccountDna(summary);
		} catch (e) {
			setAccountDna(null);
			setAccountDnaError(
				e instanceof Error ? e.message : "Could not load account DNA.",
			);
		} finally {
			setAccountDnaLoading(false);
		}
	}, []);

	const refreshRestartWarmup = useCallback(async () => {
		setRestartWarmupLoading(true);
		setRestartWarmupError(null);
		try {
			const summary = await fetchRestartWarmupOpsSummary();
			setRestartWarmup(summary);
		} catch (e) {
			setRestartWarmup(null);
			setRestartWarmupError(
				e instanceof Error ? e.message : "Could not load restart warm-up.",
			);
		} finally {
			setRestartWarmupLoading(false);
		}
	}, []);

	useEffect(() => {
		void refreshAccountDna();
		void refreshRestartWarmup();
	}, [refreshAccountDna, refreshRestartWarmup]);

	useEffect(() => {
		let cancelled = false;
		setReplayRunsLoading(true);
		fetchReplayRuns(7)
			.then((rows) => {
				if (cancelled) return;
				setReplayRuns(rows);
				setReplayRunsError(null);
			})
			.catch((e: unknown) => {
				if (cancelled) return;
				setReplayRuns([]);
				setReplayRunsError(
					e instanceof Error ? e.message : "Could not load replay runs.",
				);
			})
			.finally(() => {
				if (!cancelled) setReplayRunsLoading(false);
			});
		return () => {
			cancelled = true;
		};
	}, []);

	const filteredReplayRuns = useMemo(() => {
		return replayRuns.filter((run) => {
			const typeOk =
				replayRunTypeFilter === "all" || run.run_type === replayRunTypeFilter;
			const statusOk =
				replayStatusFilter === "all" || run.status === replayStatusFilter;
			return typeOk && statusOk;
		});
	}, [replayRuns, replayRunTypeFilter, replayStatusFilter]);

	const selectedReplayRunId =
		activeSection === "replay"
			? (runId ?? filteredReplayRuns[0]?.id ?? null)
			: null;
	const selectedReplayRun = selectedReplayRunId
		? (replayRuns.find((run) => run.id === selectedReplayRunId) ?? null)
		: null;

	useEffect(() => {
		if (activeSection !== "replay") return;
		if (!runId && filteredReplayRuns[0]?.id) {
			navigate(`/autopilot/replay/${filteredReplayRuns[0].id}`, {
				replace: true,
			});
		}
	}, [activeSection, filteredReplayRuns, navigate, runId]);

	useEffect(() => {
		if (!selectedReplayRunId) {
			setReplaySteps([]);
			return;
		}
		let cancelled = false;
		setReplayStepsLoading(true);
		fetchReplaySteps(selectedReplayRunId)
			.then((rows) => {
				if (cancelled) return;
				setReplaySteps(rows);
				setReplayStepsError(null);
			})
			.catch((e: unknown) => {
				if (cancelled) return;
				setReplaySteps([]);
				setReplayStepsError(
					e instanceof Error ? e.message : "Could not load run steps.",
				);
			})
			.finally(() => {
				if (!cancelled) setReplayStepsLoading(false);
			});
		return () => {
			cancelled = true;
		};
	}, [selectedReplayRunId]);

	/* --- derived stats --- */
	const stats = useMemo(() => {
		const active = jobs.filter((j) => j.status === "running").length;
		const failedJobs = jobs.filter((j) => j.status === "failed").length;
		const totalRuns = jobs.reduce((sum, j) => sum + j.runs24h, 0);
		const weightedSuccess =
			totalRuns === 0
				? 100
				: jobs.reduce((sum, j) => sum + j.successRate24h * j.runs24h, 0) /
					totalRuns;
		const queued = queueRows.reduce((sum, q) => sum + q.scheduledCount, 0);
		const atRiskQueues = queueRows.filter((q) => q.days < 4).length;
		const dayStartMs = Date.now() - 24 * 60 * 60 * 1000;
		const openFailures = failures.filter((f) => {
			const failedAt = failureTimestampMs(f);
			return !f.resolved && failedAt !== null && failedAt >= dayStartMs;
		}).length;
		const now = Date.now();
		const upcomingMinutes = jobs
			.map((j) =>
				j.status === "running" || j.status === "idle" ? j.nextRunMs : null,
			)
			.filter((ms): ms is number => ms !== null)
			.map((ms) => Math.max(0, Math.round((ms - now) / 60_000)));
		const nextRunMinutes = upcomingMinutes.length
			? Math.min(...upcomingMinutes)
			: null;
		return {
			active,
			failedJobs,
			weightedSuccess,
			queued,
			atRiskQueues,
			openFailures,
			nextRunMinutes,
		};
	}, [jobs, queueRows, failures]);

	const setWorkspaceEnabled = useCallback(async (enabled: boolean) => {
		setTogglingWorkspace(true);
		setWorkspaceToggleError(null);
		setWorkspaceToggleWarning(null);
		try {
			const result = await toggleAutoPost(enabled);
			if (result === false) {
				throw new Error("Could not update auto-poster config");
			}
			if (typeof result === "object" && result.warning) {
				setWorkspaceToggleWarning(result.warning);
			}
			setWorkspacePaused(!enabled);
		} catch (e) {
			setWorkspaceToggleError(
				e instanceof Error ? e.message : "Could not update auto-poster config",
			);
		} finally {
			setTogglingWorkspace(false);
		}
	}, []);

	const runAccountDnaBackfill = useCallback(async () => {
		setDnaBackfillRunning(true);
		setAccountDnaError(null);
		setDnaBackfillResult(null);
		try {
			const result = await backfillAccountDna({ force: false });
			setDnaBackfillResult(result);
			await refreshAccountDna();
		} catch (e) {
			setAccountDnaError(
				e instanceof Error ? e.message : "Could not backfill account DNA.",
			);
		} finally {
			setDnaBackfillRunning(false);
		}
	}, [refreshAccountDna]);

	const refreshAgentNotes = useCallback(async () => {
		setAgentNotesLoading(true);
		setAgentNotesError(null);
		try {
			setAgentNotes(await fetchAgentNotes());
		} catch (e) {
			setAgentNotesError(
				e instanceof Error ? e.message : "Could not load agent notes.",
			);
		} finally {
			setAgentNotesLoading(false);
		}
	}, []);

	const saveOperatorNote = useCallback(
		async (key: string, value: string) => {
			await saveAgentNote(key, value);
			await refreshAgentNotes();
		},
		[refreshAgentNotes],
	);

	const removeOperatorNote = useCallback(
		async (key: string) => {
			await deleteAgentNote(key);
			await refreshAgentNotes();
		},
		[refreshAgentNotes],
	);

	const applyAgentPaused = useCallback(async (paused: boolean) => {
		setAgentPauseSaving(true);
		setAgentPauseError(null);
		try {
			const next = await setAgentPaused(paused);
			setAgentSettingsState(next);
			setAgentPauseConfirm(null);
		} catch (e) {
			setAgentPauseError(
				e instanceof Error ? e.message : "Could not update agent state.",
			);
		} finally {
			setAgentPauseSaving(false);
		}
	}, []);

	const updateGroupCondition = useCallback(
		async (groupId: string, patch: Partial<GroupConfig>) => {
			const current = conditionConfigs.find(
				(config) => config.groupId === groupId,
			);
			if (!current)
				throw new Error("This group does not have an editable config row yet.");

			const next: GroupConfig = {
				...current,
				...patch,
			};

			const savingKey = `${groupId}:${Object.keys(patch).sort().join(",")}`;
			setConditionSavingKey(savingKey);
			try {
				const ok = await upsertGroupConfig(next);
				if (!ok) throw new Error("Could not save condition.");
				setConditionConfigs((prev) =>
					prev.map((config) => (config.groupId === groupId ? next : config)),
				);
				setConditionError(null);
			} finally {
				setConditionSavingKey(null);
			}
		},
		[conditionConfigs],
	);

	const updateWorkspaceCondition = useCallback(
		async (patch: Partial<AutoPostConfig>) => {
			const savingKey = Object.keys(patch).sort()[0] ?? "workspace";
			setWorkspaceConditionSavingKey(savingKey);
			try {
				const ok = await saveAutoPostConfig(patch);
				if (!ok) throw new Error("Could not save workspace condition.");
				setWorkspaceAutoPostConfig((prev) => ({
					...(prev ?? ({} as AutoPostConfig)),
					...patch,
				}));
				setConditionError(null);
			} finally {
				setWorkspaceConditionSavingKey(null);
			}
		},
		[],
	);

	/* --- failure actions — real Supabase UPDATE; the scheduled-post-publish
	 *     cron picks the row up on its next tick (every 5 min). --- */
	const retryFailure = useCallback(async (id: string) => {
		setFailures((prev) =>
			prev.map((f) =>
				f.id === id ? { ...f, retrying: true, retryError: undefined } : f,
			),
		);
		try {
			await retryFailedPost(id);
			setFailures((prev) =>
				prev.map((f) =>
					f.id === id
						? {
								...f,
								retrying: false,
								resolved: true,
								retryCount: f.retryCount + 1,
							}
						: f,
				),
			);
		} catch (e) {
			const msg = e instanceof Error ? e.message : "Retry failed";
			setFailures((prev) =>
				prev.map((f) =>
					f.id === id ? { ...f, retrying: false, retryError: msg } : f,
				),
			);
		}
	}, []);

	const replayStep = useCallback(
		async (step: AutopilotReplayStep) => {
			if (!selectedReplayRunId) return;
			setReplayingStepId(step.id);
			setReplayActionError(null);
			try {
				const result = await replayAutopilotStep(selectedReplayRunId, step.id);
				setReplayRuns(await fetchReplayRuns(7));
				if (result.runId) {
					navigate(`/autopilot/replay/${result.runId}`);
				}
			} catch (e) {
				setReplayActionError(e instanceof Error ? e.message : "Replay failed.");
			} finally {
				setReplayingStepId(null);
			}
		},
		[navigate, selectedReplayRunId],
	);

	/* --- keyboard: section navigation --- */
	useEffect(() => {
		const onKey = (e: KeyboardEvent) => {
			const target = e.target as HTMLElement | null;
			const typing =
				target &&
				(target.tagName === "INPUT" ||
					target.tagName === "TEXTAREA" ||
					target.isContentEditable);
			if (typing) return;

			const key = e.key.toLowerCase();
			const navByKey: Partial<Record<string, AutopilotSection>> = {
				a: "agent",
				q: "queue",
				e: "evergreen",
				p: "replay",
				c: "conditions",
				h: "health",
			};
			if (key === "r") {
				e.preventDefault();
				navigate("/autopilot/recurrent");
				return;
			}
			const targetSection = navByKey[key];
			if (targetSection) {
				e.preventDefault();
				navigate(`/autopilot/${targetSection}`);
				return;
			}
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, [navigate]);

	/* --- rate limits: signal-first ordering --- */
	const sortedRateLimits = useMemo(
		() => [...rateLimits].sort((a, b) => b.used / b.cap - a.used / a.cap),
		[rateLimits],
	);
	const warnRateLimits = useMemo(
		() => sortedRateLimits.filter((r) => r.used / r.cap >= 0.8),
		[sortedRateLimits],
	);
	const rateRows = showAllRate ? sortedRateLimits : warnRateLimits;
	const hiddenRateCount = sortedRateLimits.length - warnRateLimits.length;
	const diagnosticsUnavailable = !!(
		jobsError ||
		queueError ||
		failuresError ||
		rateError
	);
	const windowFailures = useMemo(() => {
		const startMs = failureWindowStartMs(failureWindow);
		return failures.filter((failure) => {
			const failedAt = failureTimestampMs(failure);
			return !failure.resolved && failedAt !== null && failedAt >= startMs;
		});
	}, [failures, failureWindow]);
	const failureBuckets = useMemo(
		() => buildFailureBuckets(windowFailures, failureWindow),
		[windowFailures, failureWindow],
	);
	const selectedFailureBucket = useMemo(
		() =>
			selectedFailureBucketKey
				? (failureBuckets.find(
						(bucket) => bucket.key === selectedFailureBucketKey,
					) ?? null)
				: null,
		[failureBuckets, selectedFailureBucketKey],
	);
	const drilldownFailures = useMemo(() => {
		if (!selectedFailureBucket) return windowFailures;
		return windowFailures.filter((failure) => {
			const failedAt = failureTimestampMs(failure);
			return (
				failedAt !== null &&
				failedAt >= selectedFailureBucket.startMs &&
				failedAt < selectedFailureBucket.endMs
			);
		});
	}, [windowFailures, selectedFailureBucket]);
	const failureGroups = useMemo(
		() => groupFailures(drilldownFailures),
		[drilldownFailures],
	);
	const accountHealthRows = useMemo(
		() => accountFailureHealth(windowFailures),
		[windowFailures],
	);

	const changeFailureWindow = useCallback((nextWindow: FailureWindow) => {
		setFailureWindow(nextWindow);
		setSelectedFailureBucketKey(null);
		setExpandedFailureClass(null);
	}, []);

	const subtitleParts: string[] = [];
	if (workspacePaused === true) {
		subtitleParts.push("workspace paused");
	} else if (diagnosticsUnavailable) {
		subtitleParts.push("live diagnostics unavailable");
	} else {
		subtitleParts.push(
			`${stats.active} job${stats.active === 1 ? "" : "s"} active`,
		);
		if (stats.nextRunMinutes !== null) {
			subtitleParts.push(
				`next run ${stats.nextRunMinutes < 1 ? "any second" : `in ${stats.nextRunMinutes}m`}`,
			);
		}
	}
	subtitleParts.push(
		`${stats.openFailures} failure${stats.openFailures === 1 ? "" : "s"} in last 24h`,
	);

	// First-visit loading — all four data sources empty and loading together.
	const isFirstLoad =
		jobsLoading &&
		queueLoading &&
		rateLoading &&
		failuresLoading &&
		jobs.length === 0 &&
		queueRows.length === 0 &&
		rateLimits.length === 0 &&
		failures.length === 0;
	if (isFirstLoad) return <AutopilotSkeleton />;

	return (
		<NovaScreen width="wide" density="compact">
			<style>{`
        @keyframes autopilot-live-pulse {
          0%, 100% { box-shadow: 0 0 0 0 var(--color-ring-oxblood-strong); }
          70% { box-shadow: 0 0 0 6px transparent; }
        }
        .autopilot-live-dot { animation: autopilot-live-pulse 2s ease-out infinite; }
        @media (prefers-reduced-motion: reduce) {
          .autopilot-live-dot { animation: none; }
        }
      `}</style>

			<NovaSection>
				<NovaHeader
					eyebrow="Autopilot"
					title="Automation control"
					meta="Engine · live"
					description={
						<>
							<strong className="font-semibold text-foreground">
								Control queue automation without losing operator oversight.
							</strong>{" "}
							Pause publishing, inspect replay runs, and jump into the failure
							bucket that needs intervention.
						</>
					}
					filters={subtitleParts.map((part) => (
						<Badge
							key={part}
							tone={
								part.toLowerCase().includes("paused") ? "oxblood" : "outline"
							}
						>
							{part}
						</Badge>
					))}
					actions={
						<div className="flex flex-col items-start gap-1.5 md:items-end">
							<NovaToolbar>
								<Button
									type="button"
									onClick={() => void setWorkspaceEnabled(false)}
									disabled={workspacePaused !== false || togglingWorkspace}
									variant="outline"
									size="sm"
								>
									<Pause data-icon="inline-start" aria-hidden="true" />
									{togglingWorkspace && workspacePaused === false
										? "Pausing…"
										: "Pause all"}
								</Button>
								<Button
									type="button"
									onClick={() => void setWorkspaceEnabled(true)}
									disabled={workspacePaused !== true || togglingWorkspace}
									variant="outline"
									size="sm"
								>
									<Zap
										data-icon="inline-start"
										className="text-[var(--color-oxblood)]"
										aria-hidden="true"
									/>
									{togglingWorkspace && workspacePaused === true
										? "Resuming…"
										: "Resume"}
								</Button>
							</NovaToolbar>
							{workspaceToggleError && (
								<div
									className="text-[0.65625rem] leading-[1.4] max-w-[280px] text-right"
									style={{ color: "var(--color-oxblood)" }}
									role="alert"
								>
									{workspaceToggleError}
								</div>
							)}
							{workspaceToggleWarning && !workspaceToggleError && (
								<div
									className="text-[0.65625rem] leading-[1.4] max-w-[280px] text-right"
									style={{ color: "var(--color-health-warn)" }}
									role="status"
								>
									{workspaceToggleWarning}
								</div>
							)}
						</div>
					}
				/>
			</NovaSection>

			<AutopilotModeShell
				activeSection={activeSection}
				stats={stats}
				queueRows={queueRows}
				jobs={jobs}
				rateLimits={sortedRateLimits}
				agentLog={agentLog}
				replayRuns={replayRuns}
				onNavigate={(next) => navigate(`/autopilot/${next}`)}
			>
				{activeSection === "agent" && (
					<AgentModePage
						logRows={agentLog}
						logLoading={agentLogLoading}
						logError={agentLogError}
						notes={agentNotes}
						notesLoading={agentNotesLoading}
						notesError={agentNotesError}
						settings={agentSettings}
						settingsLoading={agentSettingsLoading}
						settingsError={agentSettingsError}
						pauseConfirm={agentPauseConfirm}
						pauseSaving={agentPauseSaving}
						pauseError={agentPauseError}
						accountScopeCount={queueRows.reduce(
							(sum, row) => sum + row.accountCount,
							0,
						)}
						nextRunMinutes={stats.nextRunMinutes}
						onOpenHealth={() => navigate("/autopilot/health")}
						onSaveNote={saveOperatorNote}
						onDeleteNote={removeOperatorNote}
						onRequestPause={(paused) => {
							setAgentPauseError(null);
							setAgentPauseConfirm(paused);
						}}
						onCancelPause={() => setAgentPauseConfirm(null)}
						onConfirmPause={(paused) => void applyAgentPaused(paused)}
					/>
				)}
				{activeSection === "queue" && (
					<QueueModePage
						rows={queueRows}
						loading={queueLoading}
						error={queueError}
						onOpenCalendar={() => navigate("/calendar")}
					/>
				)}
				{activeSection === "replay" && (
					<ReplayModePage
						runs={filteredReplayRuns}
						allRuns={replayRuns}
						runsLoading={replayRunsLoading}
						runsError={replayRunsError}
						steps={replaySteps}
						stepsLoading={replayStepsLoading}
						stepsError={replayStepsError}
						selectedRun={selectedReplayRun}
						selectedRunId={selectedReplayRunId}
						runTypeFilter={replayRunTypeFilter}
						statusFilter={replayStatusFilter}
						expandedStepId={expandedReplayStepId}
						replayingStepId={replayingStepId}
						replayActionError={replayActionError}
						onRunTypeFilter={setReplayRunTypeFilter}
						onStatusFilter={setReplayStatusFilter}
						onSelectRun={(id) => navigate(`/autopilot/replay/${id}`)}
						onToggleStep={(id) =>
							setExpandedReplayStepId((current) => (current === id ? null : id))
						}
						onReplayStep={(step) => void replayStep(step)}
					/>
				)}
				{activeSection === "evergreen" && (
					<SchemaGatedMode
						icon={Leaf}
						title="Evergreen queue is waiting on storage"
						body="This mode needs an evergreen_posts table or posts.evergreen_status before operators can safely promote high performers back into inventory."
						rows={[
							"Render high-performing candidates with source post, lift, and last published time.",
							"Let operators approve or exclude posts before automated reposting.",
							"Reuse the Queue cap rings once evergreen rows can be scheduled.",
						]}
					/>
				)}
				{activeSection === "recurrent" && (
					<SchemaGatedMode
						icon={Repeat2}
						title="Recurrent cycles need publish cadence fields"
						body="The shell is in place, but recurrent posts need cycle-days and last-published timestamps before the UI can mutate live schedules."
						rows={[
							"Show repeat cadence, next publish, and per-account cap pressure.",
							"Block cycles that would exceed group conditions.",
							"Expose pause, skip next, and edit cadence once schema is live.",
						]}
					/>
				)}
				{activeSection === "conditions" && (
					<ConditionsModePage
						rows={queueRows}
						configs={conditionConfigs}
						workspaceConfig={workspaceAutoPostConfig}
						loading={queueLoading || conditionLoading}
						error={queueError || conditionError}
						savingKey={conditionSavingKey}
						workspaceSavingKey={workspaceConditionSavingKey}
						onUpdateConfig={updateGroupCondition}
						onUpdateWorkspaceConfig={updateWorkspaceCondition}
					/>
				)}
				{activeSection === "history" && (
					<SchemaGatedMode
						icon={History}
						title="Run history will attach to structured logs"
						body="The current backend exposes cron summaries and failed posts. Step replay needs auto_post_run_log and auto_post_run_steps before this page can drill into preserved payloads."
						rows={[
							"Show a 24h run timeline with success bars and failure dots.",
							"Open raw payloads inline for retry and replay decisions.",
							"Add a per-step rail once the publish worker emits step state.",
						]}
					/>
				)}
				{activeSection === "health" && (
					<>
						{/* Stat strip */}
						<NovaSection className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8"
						>
							<AutopilotHealthStat
								label="Jobs active"
								value={jobsError ? "—" : `${stats.active}/${jobs.length}`}
								icon={Activity}
								tone={
									jobsError
										? "neutral"
										: stats.failedJobs > 0
											? "critical"
											: stats.active > 0
												? "good"
												: workspacePaused
													? "warn"
													: "neutral"
								}
							/>
							<AutopilotHealthStat
								label="Success · last 24h"
								value={jobsError ? "—" : formatPercent(stats.weightedSuccess)}
								icon={CheckCircle2}
								tone={
									jobsError
										? "neutral"
										: stats.weightedSuccess >= 98
											? "good"
											: stats.weightedSuccess >= 92
												? "warn"
												: "critical"
								}
							/>
							<AutopilotHealthStat
								label="Posts queued"
								value={queueError ? "—" : `${stats.queued}`}
								icon={Clock}
								tone={queueError ? "critical" : "neutral"}
							/>
							<AutopilotHealthStat
								label="Queues at risk"
								value={queueError ? "—" : `${stats.atRiskQueues}`}
								icon={AlertTriangle}
								tone={
									queueError
										? "critical"
										: stats.atRiskQueues === 0
											? "good"
											: stats.atRiskQueues < 5
												? "warn"
												: "critical"
								}
							/>
						</NovaSection>

						{/* Failure UX — sparkline, grouped drilldown, account strip */}
						<NovaSection className="mb-8 flex flex-col gap-5"
						>
							<FailureSparklinePanel
								window={failureWindow}
								windows={FAILURE_WINDOWS}
								buckets={failureBuckets}
								selectedBucketKey={selectedFailureBucketKey}
								loading={failuresLoading}
								error={failuresError}
								onWindowChange={changeFailureWindow}
								onSelectBucket={(key) =>
									setSelectedFailureBucketKey((current) =>
										current === key ? null : key,
									)
								}
							/>
							<FailureDrilldownPanel
								window={failureWindow}
								selectedBucket={selectedFailureBucket}
								groups={failureGroups}
								loading={failuresLoading}
								error={failuresError}
								expandedClass={expandedFailureClass}
								onToggleClass={(className) =>
									setExpandedFailureClass((current) =>
										current === className ? null : className,
									)
								}
								onRetryFailure={retryFailure}
								onClearBucket={() => setSelectedFailureBucketKey(null)}
								onOpenAccount={(failure) =>
									navigate(
										failure.accountId
											? `/accounts?id=${encodeURIComponent(failure.accountId)}`
											: `/accounts?handle=${encodeURIComponent(failure.handle)}`,
									)
								}
								onOpenReplayForPost={(postId) => {
									const run = replayRuns.find(
										(item) => item.post_id === postId,
									);
									navigate(
										run ? `/autopilot/replay/${run.id}` : "/autopilot/replay",
									);
								}}
							/>
							<AccountHealthStrip
								rows={accountHealthRows}
								window={failureWindow}
								loading={failuresLoading}
								error={failuresError}
								onOpenAccount={(row) =>
									navigate(
										row.accountId
											? `/accounts?id=${encodeURIComponent(row.accountId)}`
											: `/accounts?handle=${encodeURIComponent(row.handle)}`,
									)
								}
							/>
							<RestartWarmupCard
								summary={restartWarmup}
								loading={restartWarmupLoading}
								error={restartWarmupError}
								onRefresh={refreshRestartWarmup}
								onOpenAccount={(row) =>
									navigate(`/accounts?id=${encodeURIComponent(row.account_id)}`)
								}
							/>
							<AccountDnaCard
								summary={accountDna}
								loading={accountDnaLoading}
								error={accountDnaError}
								backfillRunning={dnaBackfillRunning}
								backfillResult={dnaBackfillResult}
								onRefresh={refreshAccountDna}
								onBackfill={runAccountDnaBackfill}
							/>
						</NovaSection>

						{/* Jobs — live cron diagnostics remain below the failure readout */}
						<NovaSection className="mb-8"
						>
							<SectionHeader
								eyebrow="Scheduled jobs"
								meta={
									jobsLoading
										? "loading"
										: jobsError
											? "live read unavailable"
											: `${jobs.length} cron${jobs.length === 1 ? "" : "s"} · live`
								}
							/>
							<div className="grid grid-cols-1 xl:grid-cols-2 gap-2.5 mt-2.5">
								{jobsLoading && jobs.length === 0 ? (
									Array.from({ length: 4 }).map((_, i) => (
										<JobCardSkeleton key={i} />
									))
								) : jobs.length === 0 ? (
									<JobsEmpty error={jobsError} />
								) : (
									jobs.map((job) => <JobCard key={job.id} job={job} />)
								)}
							</div>
						</NovaSection>

						{/* Queue health — compact bars + link to Calendar */}
						<NovaSection className="mb-8"
						>
							<SectionHeader
								eyebrow="Queue health"
								meta={
									queueLoading
										? "loading"
										: queueError
											? "live read unavailable"
											: queueRows.length === 0
												? "no networks with scheduled posts"
												: `Target ≥ 4 days · ${queueRows.length} network${queueRows.length === 1 ? "" : "s"} · live`
								}
								action={
									<Button
										type="button"
										variant="ghost"
										size="sm"
										onClick={() => navigate("/calendar")}
										className="gap-1 text-[0.71875rem] text-[var(--color-oxblood)]"
									>
										Open calendar
										<ChevronRight data-icon="inline-end" aria-hidden="true" />
									</Button>
								}
							/>
							<NovaDataPanel className="mt-2.5" contentClassName="p-5">
								{queueLoading ? (
									<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
										{Array.from({ length: 4 }).map((_, i) => (
											<DaysBarSkeleton key={i} />
										))}
									</div>
								) : queueError ? (
									<NovaEmpty
										className="py-6"
										icon={<AlertTriangle data-icon aria-hidden="true" />}
										title="Queue health unavailable"
										description="Autopilot could not load scheduled-post coverage right now. The queue is not being reported as empty."
									/>
								) : queueRows.length === 0 ? (
									<NovaEmpty
										className="py-6"
										icon={<Clock data-icon aria-hidden="true" />}
										title="No scheduled posts"
										description="Schedule a post from the Composer and Autopilot will start tracking queue health per network."
									/>
								) : (
									<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
										{queueRows.map((q) => (
											<DaysBar key={q.network} row={q} />
										))}
									</div>
								)}
							</NovaDataPanel>
						</NovaSection>

						{/* Rate limits — signal-first */}
						<NovaSection>
							<SectionHeader
								eyebrow="Rate limits · token buckets"
								meta={
									rateLoading
										? "loading"
										: rateError
											? "live read unavailable"
											: "IG 100/24h · Threads 250/24h · live"
								}
								action={
									hiddenRateCount > 0 ? (
										<Button
											type="button"
											variant="ghost"
											size="sm"
											onClick={() => setShowAllRate((v) => !v)}
											className="gap-1 text-[0.71875rem]"
										>
											{showAllRate
												? `Hide ${hiddenRateCount} healthy`
												: `Show all ${sortedRateLimits.length}`}
											<ChevronRight
												data-icon="inline-end"
												className={cn(
													"transition-transform",
													showAllRate && "rotate-90",
												)}
												aria-hidden="true"
											/>
										</Button>
									) : null
								}
							/>

							<NovaDataPanel className="mt-2.5" contentClassName="p-0">
								{warnRateLimits.length > 0 && (
									<div
										className="px-5 py-3 flex items-center gap-2 text-[0.71875rem] font-medium border-b border-border"
										style={{
											color: "var(--color-health-warn)",
											background:
												"color-mix(in srgb, var(--color-health-warn) 7%, transparent)",
										}}
									>
										<ShieldAlert data-icon="inline-start" aria-hidden="true" />
										<span>
											{warnRateLimits.length} account
											{warnRateLimits.length === 1 ? "" : "s"} near cap
										</span>
									</div>
								)}

								{rateError ? (
									<NovaEmpty
										className="px-5 py-10"
										icon={
											<AlertTriangle
												data-icon="inline"
												style={{ color: "var(--color-oxblood)" }}
												aria-hidden="true"
											/>
										}
										title="Rate-limit telemetry unavailable"
										description="Juno33 could not load token-bucket usage right now. Healthy-state messaging is hidden until the live read recovers."
									/>
								) : rateRows.length === 0 ? (
									<div className="px-5 py-4 flex items-center gap-3">
										<div className="size-9 rounded-full bg-muted border border-border inline-flex items-center justify-center shrink-0">
											<ShieldCheck
												data-icon="inline"
												style={{ color: "var(--color-health-good)" }}
												aria-hidden="true"
											/>
										</div>
										<div className="min-w-0">
											<div className="text-[0.8125rem] font-medium text-foreground">
												Token buckets healthy
											</div>
											<p className="mt-0.5 text-[0.71875rem] text-muted-foreground">
												No accounts above 80% of daily cap.
											</p>
										</div>
									</div>
								) : (
									<div className="grid grid-cols-1 md:grid-cols-2 gap-px bg-muted">
										{rateRows.map((r) => (
											<RateLimitRow key={r.id} row={r} />
										))}
									</div>
								)}
							</NovaDataPanel>
						</NovaSection>

						{/* Keyboard hints */}
						{activeSection === "health" && (
							<div className="mt-6 hidden items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-xs text-muted-foreground md:flex">
								<KbdGroup>
									{["A", "P", "Q", "E", "R", "C", "H"].map((key) => (
										<Kbd key={key}>{key}</Kbd>
									))}
								</KbdGroup>
								modes
							</div>
						)}
					</>
				)}
			</AutopilotModeShell>
		</NovaScreen>
	);
}

/* =========================================================================
   SUB-COMPONENTS
   ========================================================================= */
function isAutopilotSection(
	value: string | undefined,
): value is AutopilotSection {
	return AUTOPILOT_SECTIONS.some((item) => item.id === value);
}

function AutopilotModeShell({
	activeSection,
	stats,
	queueRows,
	jobs,
	rateLimits,
	agentLog,
	replayRuns,
	onNavigate,
	children,
}: {
	activeSection: AutopilotSection;
	stats: {
		active: number;
		failedJobs: number;
		weightedSuccess: number;
		queued: number;
		atRiskQueues: number;
		openFailures: number;
		nextRunMinutes: number | null;
	};
	queueRows: QueueHealthRow[];
	jobs: Job[];
	rateLimits: RateLimit[];
	agentLog: AgentActionLogRow[];
	replayRuns: AutopilotReplayRun[];
	onNavigate: (section: AutopilotSection) => void;
	children: React.ReactNode;
}) {
	const activeMeta = SECTION_TITLES[activeSection];
	const groupedSections = AUTOPILOT_SECTIONS.reduce<
		Record<"Agent" | "Modes" | "Engine", typeof AUTOPILOT_SECTIONS>
	>(
		(acc, item) => {
			acc[item.group].push(item);
			return acc;
		},
		{ Agent: [], Modes: [], Engine: [] },
	);

	const counts: Partial<Record<AutopilotSection, string>> = {
		agent: String(agentLog.length),
		replay: String(replayRuns.length),
		queue: String(stats.queued),
		health: stats.openFailures > 0 ? String(stats.openFailures) : "ok",
		conditions: String(queueRows.length),
		history: String(jobs.reduce((sum, job) => sum + job.runs24h, 0)),
	};

	return (
		<div className="grid grid-cols-1 xl:grid-cols-[184px_minmax(0,1fr)] gap-5 items-start">
			<NovaDataPanel contentClassName="p-2" className="xl:sticky xl:top-4">
				<div className="px-2.5 pt-1 pb-2 border-b border-border">
					<div className="text-[0.8125rem] font-semibold text-foreground">
						Autopilot engine
					</div>
				</div>
				{(
					Object.keys(groupedSections) as Array<"Agent" | "Modes" | "Engine">
				).map((group) => (
					<nav
						key={group}
						className="pt-3"
						aria-label={`Autopilot ${group.toLowerCase()}`}
					>
						<div className="px-2.5 pb-1.5 text-[0.59375rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
							{group}
						</div>
						<div className="flex flex-col gap-1">
							{groupedSections[group].map((item) => {
								const Icon = item.icon;
								const active = item.id === activeSection;
								return (
									<Button
										key={item.id}
										type="button"
										variant={active ? "secondary" : "ghost"}
										size="sm"
										onClick={() => onNavigate(item.id)}
										className={cn("w-full h-9 justify-start px-2.5 text-left")}
									>
										<Icon data-icon="inline-start" aria-hidden="true" />
										<span className="min-w-0 flex-1 text-[0.78125rem] font-medium">
											{item.label}
										</span>
										<span className="inline-flex items-center gap-1">
											{item.shortcut && (
												<span className="hidden sm:inline-flex text-[0.59375rem] font-semibold text-muted-foreground">
													{item.shortcut}
												</span>
											)}
											{counts[item.id] && (
												<span className="min-w-5 h-5 px-1.5 rounded-[5px] inline-flex items-center justify-center bg-background border border-border text-[0.625rem] font-semibold tabular-nums text-muted-foreground">
													{counts[item.id]}
												</span>
											)}
										</span>
									</Button>
								);
							})}
						</div>
					</nav>
				))}
			</NovaDataPanel>

			<main className="min-w-0">
				<NovaDataPanel className="mb-5" contentClassName="p-4 md:p-5">
					<div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4">
						<div>
							<div className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
								{activeSection === "health"
									? "Engine diagnostics"
									: "Autopilot mode"}
							</div>
							<h2 className="app-page-title mt-1 text-foreground">
								{activeMeta.title}
							</h2>
							<p className="mt-2 max-w-[72ch] text-[0.78125rem] leading-[1.55] text-muted-foreground">
								{activeMeta.meta}
							</p>
						</div>
						<div className="grid grid-cols-3 gap-2 min-w-[260px]">
							<NovaMiniStat label="Queued" value={String(stats.queued)} />
							<NovaMiniStat
								label="Failures"
								value={String(stats.openFailures)}
								tone={stats.openFailures ? "danger" : "success"}
							/>
							<NovaMiniStat
								label="Caps"
								value={rateLimits.length ? String(rateLimits.length) : "ok"}
								tone={rateLimits.length ? "warning" : "success"}
							/>
						</div>
					</div>
				</NovaDataPanel>
				{children}
			</main>
		</div>
	);
}

const SAFE_REPLAY_STEP_NAMES = new Set([
	"queue_select",
	"generate",
	"validate",
	"media_prep",
]);

function ReplayModePage({
	runs,
	allRuns,
	runsLoading,
	runsError,
	steps,
	stepsLoading,
	stepsError,
	selectedRun,
	selectedRunId,
	runTypeFilter,
	statusFilter,
	expandedStepId,
	replayingStepId,
	replayActionError,
	onRunTypeFilter,
	onStatusFilter,
	onSelectRun,
	onToggleStep,
	onReplayStep,
}: {
	runs: AutopilotReplayRun[];
	allRuns: AutopilotReplayRun[];
	runsLoading: boolean;
	runsError: string | null;
	steps: AutopilotReplayStep[];
	stepsLoading: boolean;
	stepsError: string | null;
	selectedRun: AutopilotReplayRun | null;
	selectedRunId: string | null;
	runTypeFilter: string;
	statusFilter: string;
	expandedStepId: string | null;
	replayingStepId: string | null;
	replayActionError: string | null;
	onRunTypeFilter: (value: string) => void;
	onStatusFilter: (value: string) => void;
	onSelectRun: (id: string) => void;
	onToggleStep: (id: string) => void;
	onReplayStep: (step: AutopilotReplayStep) => void;
}) {
	const runTypes = ["all", "queue_fill", "publish", "auto_unpost"];
	const statuses = ["all", "success", "failed", "partial", "in_progress"];

	return (
		<div className="grid grid-cols-1 2xl:grid-cols-[320px_minmax(0,1fr)] gap-5">
			<NovaDataPanel contentClassName="p-0">
				<div className="p-4 border-b border-border">
					<SectionHeader
						eyebrow="Runs"
						meta={
							runsLoading
								? "loading"
								: runsError
									? "unavailable"
									: `${runs.length} of ${allRuns.length} · last 7d`
						}
					/>
					<div className="mt-3 flex flex-wrap gap-2">
						{runTypes.map((type) => (
							<ReplayFilterButton
								key={type}
								active={runTypeFilter === type}
								onClick={() => onRunTypeFilter(type)}
							>
								{type === "all" ? "All types" : type.replace("_", " ")}
							</ReplayFilterButton>
						))}
					</div>
					<div className="mt-2 flex flex-wrap gap-2">
						{statuses.map((status) => (
							<ReplayFilterButton
								key={status}
								active={statusFilter === status}
								onClick={() => onStatusFilter(status)}
							>
								{status === "all" ? "All states" : status.replace("_", " ")}
							</ReplayFilterButton>
						))}
					</div>
				</div>
				<div className="max-h-[680px] overflow-auto">
					{runsLoading ? (
						Array.from({ length: 5 }).map((_, index) => (
							<div
								key={index}
								className="border-b border-border p-4"
							>
								<Skeleton className="mb-3 h-3 w-28 rounded" />
								<Skeleton className="h-4 w-44 rounded" />
							</div>
						))
					) : runsError ? (
						<ReplayEmpty title="Replay runs unavailable" body={runsError} />
					) : runs.length === 0 ? (
						<ReplayEmpty
							title="No runs in this window"
							body="Trigger a queue fill or publish run and it will appear here."
						/>
					) : (
						runs.map((run) => (
							<Button
								key={run.id}
								type="button"
								variant="ghost"
								size="sm"
								onClick={() => onSelectRun(run.id)}
								className={cn(
									"h-auto w-full rounded-none border-b border-border p-4 text-left",
									selectedRunId === run.id ? "bg-muted" : "hover:bg-muted/60",
								)}
							>
								<div className="w-full">
									<div className="flex items-center justify-between gap-3">
										<div className="text-[0.6875rem] text-muted-foreground tabular-nums">
											{formatRunTime(run.started_at)}
										</div>
										<ReplayStatusPill status={run.status} />
									</div>
									<div className="mt-2 flex items-center gap-2">
										<span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-muted border border-border text-[0.625rem] font-semibold text-muted-foreground">
											{run.run_type === "queue_fill"
												? "QF"
												: run.run_type.slice(0, 2).toUpperCase()}
										</span>
										<div className="min-w-0">
											<div className="text-[0.8125rem] font-semibold text-foreground capitalize">
												{run.run_type.replace("_", " ")}
											</div>
											<div className="text-[0.65625rem] text-muted-foreground tabular-nums">
												{formatDuration(runDurationMs(run))} ·{" "}
												{run.trigger ?? "system"}
											</div>
										</div>
									</div>
								</div>
							</Button>
						))
					)}
				</div>
			</NovaDataPanel>

			<NovaDataPanel className="min-h-[520px]" contentClassName="p-0">
				<div className="p-4 border-b border-border flex flex-col md:flex-row md:items-center md:justify-between gap-3">
					<div>
						<SectionHeader
							eyebrow="Step detail"
							meta={
								selectedRun
									? `${selectedRun.run_type.replace("_", " ")} · ${formatRunTime(selectedRun.started_at)}`
									: "select a run"
							}
						/>
						{selectedRun?.parent_run_id && (
							<div className="mt-1 text-[0.6875rem] text-muted-foreground">
								Replay of {selectedRun.parent_run_id.slice(0, 8)}
							</div>
						)}
					</div>
					{selectedRun && <ReplayStatusPill status={selectedRun.status} />}
				</div>

				{replayActionError && (
					<div
						className="m-4 rounded-md border px-3 py-2 text-[0.71875rem]"
						style={{
							borderColor:
								"color-mix(in srgb, var(--color-oxblood) 28%, transparent)",
							color: "var(--color-oxblood)",
						}}
					>
						{replayActionError}
					</div>
				)}

				{!selectedRun ? (
					<ReplayEmpty
						title="No run selected"
						body="Choose a run from the left rail to inspect its step outputs."
					/>
				) : stepsLoading ? (
					<div className="flex flex-col gap-2 p-4">
						{Array.from({ length: 4 }).map((_, index) => (
							<Skeleton key={index} className="h-14 rounded-md" />
						))}
					</div>
				) : stepsError ? (
					<ReplayEmpty title="Steps unavailable" body={stepsError} />
				) : steps.length === 0 ? (
					<ReplayEmpty
						title="No steps recorded"
						body="This run predates Phase 5 instrumentation or the migration has not been applied yet."
					/>
				) : (
					<div className="divide-y divide-border">
						{steps.map((step) => {
							const expanded = expandedStepId === step.id;
							const safe = SAFE_REPLAY_STEP_NAMES.has(step.step_name);
							const unsafeReason =
								step.step_name === "dispatch" ||
								step.step_name === "response_capture"
									? "Dispatch step replays would re-publish the post."
									: "Replay is not enabled for this step in v1.";
							return (
								<div key={step.id}>
									<Button
										type="button"
										variant="ghost"
										size="sm"
										onClick={() => onToggleStep(step.id)}
										className={cn(
											"h-auto w-full justify-start rounded-none px-4 py-3 text-left",
											step.status === "failed" &&
												"bg-[color-mix(in_srgb,var(--color-oxblood)_7%,transparent)]",
										)}
									>
										<span className="grid w-full grid-cols-[36px_minmax(0,1fr)_auto_auto] items-center gap-3">
											<span className="font-mono text-[0.6875rem] text-muted-foreground tabular-nums">
												{String(step.step_index + 1).padStart(2, "0")}
											</span>
											<span className="min-w-0">
												<span className="block text-[0.8125rem] font-semibold text-foreground">
													{step.step_name.replaceAll("_", " ")}
												</span>
												<span className="block text-[0.65625rem] text-muted-foreground tabular-nums">
													{formatDuration(step.duration_ms)} ·{" "}
													{formatRunTime(step.started_at)}
												</span>
											</span>
											<ReplayStatusPill status={step.status} />
											<ChevronDown
												data-icon="inline-end"
												className={cn(
													"text-muted-foreground transition-transform",
													expanded && "rotate-180",
												)}
											/>
										</span>
									</Button>
									{expanded && (
										<div className="px-4 pb-4 grid grid-cols-1 xl:grid-cols-2 gap-3">
											<JsonPanel title="Inputs" value={step.inputs} />
											<JsonPanel
												title={step.error_message ? "Error" : "Outputs"}
												value={
													step.error_message
														? { error: step.error_message }
														: step.outputs
												}
											/>
											<div className="xl:col-span-2 flex items-center justify-end gap-2">
												<Button
													type="button"
													disabled={!safe || replayingStepId === step.id}
													title={safe ? "Replay from here" : unsafeReason}
													onClick={() => onReplayStep(step)}
													variant="outline"
													size="sm"
													className="h-8 text-[0.71875rem] disabled:opacity-45"
												>
													{replayingStepId === step.id
														? "Replaying…"
														: "Replay from here"}
												</Button>
											</div>
										</div>
									)}
								</div>
							);
						})}
					</div>
				)}
			</NovaDataPanel>
		</div>
	);
}

function ReplayFilterButton({
	active,
	onClick,
	children,
}: {
	active: boolean;
	onClick: () => void;
	children: React.ReactNode;
}) {
	return (
		<Button
			type="button"
			onClick={onClick}
			variant={active ? "secondary" : "outline"}
			size="sm"
			className={cn("h-7 px-2.5 text-[0.6875rem] capitalize")}
		>
			{children}
		</Button>
	);
}

function ReplayStatusPill({
	status,
}: {
	status: AutopilotRunStatus | AutopilotStepStatus;
}) {
	const tone =
		status === "success"
			? "good"
			: status === "failed"
				? "critical"
				: status === "in_progress"
					? "warn"
					: "idle";
	return (
		<StatusPill
			tone={tone}
			size="xs"
			dot
			live={status === "in_progress"}
			className="!rounded-md capitalize"
		>
			{status.replace("_", " ")}
		</StatusPill>
	);
}

function JsonPanel({ title, value }: { title: string; value: unknown }) {
	const json = JSON.stringify(value ?? {}, null, 2);
	return (
		<div className="rounded-md border border-border bg-muted/40 overflow-hidden">
			<div className="h-8 px-3 border-b border-border flex items-center justify-between">
				<span className="text-[0.65625rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
					{title}
				</span>
				<Button
					type="button"
					onClick={() => void navigator.clipboard?.writeText(json)}
					variant="ghost"
					size="sm"
					className="h-7 px-2 text-[0.625rem]"
				>
					Copy
				</Button>
			</div>
			<pre className="max-h-[280px] overflow-auto p-3 text-[0.6875rem] leading-[1.5] font-mono text-muted-foreground whitespace-pre-wrap">
				{json}
			</pre>
		</div>
	);
}

function ReplayEmpty({ title, body }: { title: string; body: string }) {
	return (
		<NovaEmpty
			className="p-8"
			icon={<PlayCircle data-icon="inline" aria-hidden="true" />}
			title={title}
			description={body}
		/>
	);
}

function runDurationMs(run: AutopilotReplayRun): number | null {
	if (!run.finished_at) return null;
	return (
		new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()
	);
}

function formatRunTime(value: string): string {
	const date = new Date(value);
	if (Number.isNaN(date.getTime())) return "unknown";
	return new Intl.DateTimeFormat(undefined, {
		month: "short",
		day: "numeric",
		hour: "numeric",
		minute: "2-digit",
	}).format(date);
}

function formatDuration(value: number | null | undefined): string {
	if (value == null || Number.isNaN(value)) return "—";
	if (value < 1000) return `${value}ms`;
	return `${(value / 1000).toFixed(value < 10_000 ? 1 : 0)}s`;
}

type AgentSeverity = "high" | "medium" | "info";

function AgentModePage({
	logRows,
	logLoading,
	logError,
	notes,
	notesLoading,
	notesError,
	settings,
	settingsLoading,
	settingsError,
	pauseConfirm,
	pauseSaving,
	pauseError,
	accountScopeCount,
	nextRunMinutes,
	onOpenHealth,
	onSaveNote,
	onDeleteNote,
	onRequestPause,
	onCancelPause,
	onConfirmPause,
}: {
	logRows: AgentActionLogRow[];
	logLoading: boolean;
	logError: string | null;
	notes: AgentNoteRow[];
	notesLoading: boolean;
	notesError: string | null;
	settings: AgentSettings | null;
	settingsLoading: boolean;
	settingsError: string | null;
	pauseConfirm: boolean | null;
	pauseSaving: boolean;
	pauseError: string | null;
	accountScopeCount: number;
	nextRunMinutes: number | null;
	onOpenHealth: () => void;
	onSaveNote: (key: string, value: string) => Promise<void>;
	onDeleteNote: (key: string) => Promise<void>;
	onRequestPause: (paused: boolean) => void;
	onCancelPause: () => void;
	onConfirmPause: (paused: boolean) => void;
}) {
	const [actionFilter, setActionFilter] = useState("all");
	const [accountFilter, setAccountFilter] = useState("all");
	const [severityFilter, setSeverityFilter] = useState("all");
	const latestAction = logRows[0] ?? null;
	const lastRun = latestAction?.created_at ?? null;
	const paused = settings?.agent_paused ?? false;

	const actionTypes = useMemo(
		() =>
			Array.from(
				new Set(logRows.map((row) => classifyAgentAction(row.tool_name))),
			).sort(),
		[logRows],
	);
	const accountTargets = useMemo(
		() =>
			Array.from(
				new Set(
					logRows
						.map((row) => extractAgentTarget(row))
						.filter((target) => target !== "Workspace"),
				),
			).sort(),
		[logRows],
	);

	const filteredRows = useMemo(
		() =>
			logRows.filter((row) => {
				if (
					actionFilter !== "all" &&
					classifyAgentAction(row.tool_name) !== actionFilter
				)
					return false;
				if (
					accountFilter !== "all" &&
					extractAgentTarget(row) !== accountFilter
				)
					return false;
				if (
					severityFilter !== "all" &&
					deriveAgentSeverity(row) !== severityFilter
				)
					return false;
				return true;
			}),
		[logRows, actionFilter, accountFilter, severityFilter],
	);

	return (
		<div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_340px] gap-5 items-start">
			<div className="flex min-w-0 flex-col gap-5">
				<AgentStatusHeader
					paused={paused}
					loading={settingsLoading}
					error={settingsError}
					lastRun={lastRun}
					nextRunMinutes={nextRunMinutes}
					accountScopeCount={accountScopeCount}
					toolCount={244}
					pauseConfirm={pauseConfirm}
					pauseSaving={pauseSaving}
					pauseError={pauseError}
					onRequestPause={onRequestPause}
					onCancelPause={onCancelPause}
					onConfirmPause={onConfirmPause}
				/>
				<NovaDataPanel contentClassName="p-0">
					<div className="px-5 py-4 border-b border-border flex flex-col gap-3">
						<div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
							<SectionHeader
								eyebrow="Decision feed"
								meta={
									logLoading
										? "loading"
										: logError
											? "live read unavailable"
											: `${filteredRows.length}/${logRows.length} decisions`
								}
								inline
							/>
							<Button
								type="button"
								variant="secondary"
								size="sm"
								onClick={onOpenHealth}
								className="h-8 gap-1.5 text-[0.71875rem]"
							>
								Engine health
								<ChevronRight data-icon="inline-end" aria-hidden="true" />
							</Button>
						</div>
						<AgentFeedFilters
							actionTypes={actionTypes}
							accountTargets={accountTargets}
							actionFilter={actionFilter}
							accountFilter={accountFilter}
							severityFilter={severityFilter}
							onActionFilter={setActionFilter}
							onAccountFilter={setAccountFilter}
							onSeverityFilter={setSeverityFilter}
						/>
					</div>
					{logLoading ? (
						<AgentFeedSkeleton />
					) : logError ? (
						<InlineModeState
							icon={AlertTriangle}
							title="Decision feed unavailable"
							body={logError}
						/>
					) : logRows.length === 0 ? (
						<InlineModeState
							icon={BrainCircuit}
							title="Agent is idle"
							body={`Last action ${lastRun ? formatDateTime(lastRun) : "has not been recorded yet"}. Decisions appear here after autonomous tool calls are logged.`}
						/>
					) : filteredRows.length === 0 ? (
						<InlineModeState
							icon={Search}
							title="No decisions match these filters"
							body="Clear one of the filters to return to the full decision feed."
						/>
					) : (
						<div className="divide-y divide-border">
							{filteredRows.map((row) => (
								<AgentDecisionRow key={row.id} row={row} />
							))}
						</div>
					)}
				</NovaDataPanel>
			</div>
			<AgentNotesPanel
				notes={notes}
				loading={notesLoading}
				error={notesError}
				latestAgentReadAt={lastRun}
				onSaveNote={onSaveNote}
				onDeleteNote={onDeleteNote}
			/>
		</div>
	);
}

function AgentStatusHeader({
	paused,
	loading,
	error,
	lastRun,
	nextRunMinutes,
	accountScopeCount,
	toolCount,
	pauseConfirm,
	pauseSaving,
	pauseError,
	onRequestPause,
	onCancelPause,
	onConfirmPause,
}: {
	paused: boolean;
	loading: boolean;
	error: string | null;
	lastRun: string | null;
	nextRunMinutes: number | null;
	accountScopeCount: number;
	toolCount: number;
	pauseConfirm: boolean | null;
	pauseSaving: boolean;
	pauseError: string | null;
	onRequestPause: (paused: boolean) => void;
	onCancelPause: () => void;
	onConfirmPause: (paused: boolean) => void;
}) {
	const nextLabel =
		nextRunMinutes === null
			? "cron-derived"
			: nextRunMinutes < 1
				? "any second"
				: `in ${nextRunMinutes}m`;
	const desiredPaused = pauseConfirm ?? false;

	return (
		<NovaDataPanel className="relative" contentClassName="p-5">
			<div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-4">
				<div>
					<div className="flex items-center gap-2">
						<span
							className="w-2 h-2 rounded-full"
							style={{
								background: paused
									? "var(--color-health-warn)"
									: "var(--color-health-good)",
							}}
							aria-hidden="true"
						/>
						<span className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
							Agent status
						</span>
					</div>
					<h3 className="app-page-title mt-2 text-foreground">
						{loading ? "Loading" : paused ? "Paused" : "Active"}
					</h3>
					<p className="mt-2 text-[0.8125rem] leading-[1.5] text-muted-foreground max-w-[72ch]">
						{error
							? error
							: paused
								? `Paused since ${lastRun ? formatDateTime(lastRun) : "before the latest visible run"}. Agent writes are blocked until resumed.`
								: "Agent writes are enabled. Decisions remain explainable and traceable through the log below."}
					</p>
				</div>
				<div className="flex flex-col items-start lg:items-end gap-2">
					<Button
						type="button"
						variant={paused ? "outline" : "secondary"}
						size="sm"
						onClick={() => onRequestPause(!paused)}
						disabled={loading || pauseSaving}
						className={cn(
							"h-9 gap-1.5 text-[0.8125rem] disabled:opacity-50",
							!paused && "text-[var(--color-oxblood)]",
						)}
					>
						<Power data-icon="inline-start" aria-hidden="true" />
						{paused ? "Resume agent" : "Pause agent"}
					</Button>
					{pauseError && (
						<div
							className="text-[0.6875rem] text-[var(--color-oxblood)] max-w-[280px] lg:text-right"
							role="alert"
						>
							{pauseError}
						</div>
					)}
				</div>
			</div>
			<div className="mt-5 grid grid-cols-2 md:grid-cols-4 gap-2">
				<NovaMiniStat
					label="Last run"
					value={lastRun ? relativeShort(lastRun) : "none"}
				/>
				<NovaMiniStat label="Next run" value={nextLabel} />
				<NovaMiniStat label="Accounts" value={String(accountScopeCount)} />
				<NovaMiniStat label="Tools" value={String(toolCount)} />
			</div>

			{pauseConfirm !== null && (
				<div className="absolute inset-0 z-10 bg-background/72 backdrop-blur-[10px] grid place-items-center p-4">
					<div className="w-full max-w-[420px] rounded-lg border border-border bg-popover p-4 text-popover-foreground shadow-[var(--shadow-modal)]">
						<div className="text-[0.9375rem] font-medium text-foreground">
							{desiredPaused ? "Pause agent writes?" : "Resume agent writes?"}
						</div>
						<p className="mt-2 text-[0.75rem] leading-[1.5] text-muted-foreground">
							{desiredPaused
								? "This kill switch blocks autonomous write operations. Read-only diagnostics and notes remain visible."
								: "This re-enables autonomous write operations and resets circuit-breaker counters when the backend accepts the change."}
						</p>
						<div className="mt-4 flex justify-end gap-2">
							<Button
								type="button"
								onClick={onCancelPause}
								disabled={pauseSaving}
								variant="secondary"
								size="sm"
								className="h-8 text-[0.75rem]"
							>
								Cancel
							</Button>
							<Button
								type="button"
								onClick={() => onConfirmPause(desiredPaused)}
								disabled={pauseSaving}
								variant="outline"
								size="sm"
								className="h-8 text-[0.75rem]"
							>
								{pauseSaving
									? "Saving..."
									: desiredPaused
										? "Pause agent"
										: "Resume agent"}
							</Button>
						</div>
					</div>
				</div>
			)}
		</NovaDataPanel>
	);
}

function AgentFeedFilters({
	actionTypes,
	accountTargets,
	actionFilter,
	accountFilter,
	severityFilter,
	onActionFilter,
	onAccountFilter,
	onSeverityFilter,
}: {
	actionTypes: string[];
	accountTargets: string[];
	actionFilter: string;
	accountFilter: string;
	severityFilter: string;
	onActionFilter: (value: string) => void;
	onAccountFilter: (value: string) => void;
	onSeverityFilter: (value: string) => void;
}) {
	return (
		<div className="flex flex-wrap gap-2">
			<AgentFilterSelect
				label="Action"
				value={actionFilter}
				values={["all", ...actionTypes]}
				onChange={onActionFilter}
			/>
			<AgentFilterSelect
				label="Account"
				value={accountFilter}
				values={["all", ...accountTargets]}
				onChange={onAccountFilter}
			/>
			<AgentFilterSelect
				label="Severity"
				value={severityFilter}
				values={["all", "high", "medium", "info"]}
				onChange={onSeverityFilter}
			/>
		</div>
	);
}

function AgentFilterSelect({
	label,
	value,
	values,
	onChange,
}: {
	label: string;
	value: string;
	values: string[];
	onChange: (value: string) => void;
}) {
	const selectId = `autopilot-filter-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
	return (
		<label
			htmlFor={selectId}
			className="inline-flex items-center gap-2 rounded-md bg-muted/60 border border-border px-2.5 py-1.5 text-[0.6875rem] text-muted-foreground"
		>
			<span className="font-semibold text-muted-foreground uppercase tracking-[0.08em]">
				{label}
			</span>
			<Select
				id={selectId}
				value={value}
				onChange={(e) => onChange(e.target.value)}
				sizeVariant="sm"
				className="h-7 max-w-[180px] border-0 bg-transparent px-1 shadow-none"
			>
				{values.map((item) => (
					<option key={item} value={item}>
						{item === "all" ? "All" : item}
					</option>
				))}
			</Select>
		</label>
	);
}

function AgentDecisionRow({ row }: { row: AgentActionLogRow }) {
	const [open, setOpen] = useState(false);
	const severity = deriveAgentSeverity(row);
	const reason = extractAgentReason(row);
	const target = extractAgentTarget(row);
	const actionType = classifyAgentAction(row.tool_name);

	return (
		<article className="px-5 py-3.5 hover:bg-muted/35 transition-colors">
			<Button
				type="button"
				variant="ghost"
				size="sm"
				onClick={() => setOpen((v) => !v)}
				className="h-auto w-full justify-start p-0 text-left"
			>
				<span className="grid w-full grid-cols-1 items-start gap-2 xl:grid-cols-[132px_150px_minmax(160px,0.8fr)_minmax(280px,1.4fr)_auto] xl:gap-4">
					<span className="pt-0.5 text-[0.6875rem] tabular-nums text-muted-foreground">
						{formatDateTime(row.created_at)}
					</span>
					<span className="min-w-0">
						<span className="block truncate text-[0.8125rem] font-semibold text-foreground">
							{humanizeToolName(row.tool_name)}
						</span>
						<span className="mt-0.5 block text-[0.625rem] uppercase tracking-[0.08em] text-muted-foreground">
							{actionType}
						</span>
					</span>
					<span className="truncate pt-0.5 text-[0.78125rem] text-muted-foreground">
						{target}
					</span>
					<span className="text-[0.8125rem] leading-[1.45] text-foreground">
						{reason}
					</span>
					<span className="flex items-center gap-2 justify-start xl:justify-end">
						<SeverityTag severity={severity} />
						<ChevronDown
							className={cn(
								"w-3.5 h-3.5 text-muted-foreground transition-transform",
								open && "rotate-180",
							)}
							aria-hidden="true"
						/>
					</span>
				</span>
			</Button>
			{open && (
				<div className="mt-3 ml-0 xl:ml-[132px] rounded-md bg-muted/45 border border-border p-3">
					<div className="grid grid-cols-1 lg:grid-cols-[1fr_1fr] gap-3">
						<div>
							<div className="text-[0.625rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
								Full reason
							</div>
							<p className="mt-1 text-[0.75rem] leading-[1.5] text-muted-foreground">
								{reason}
							</p>
						</div>
						<div>
							<div className="text-[0.625rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
								Tools used
							</div>
							<div className="mt-1 flex items-center gap-2 text-[0.75rem] text-muted-foreground">
								<Wrench className="w-3.5 h-3.5" aria-hidden="true" />
								<span className="font-medium text-foreground">
									{row.tool_name}
								</span>
								<span className="tabular-nums">{row.duration_ms ?? 0}ms</span>
								<span>{row.success ? "ok" : "failed"}</span>
							</div>
						</div>
					</div>
					<pre className="mt-3 max-h-44 overflow-auto rounded-md bg-background/70 border border-border p-3 text-[0.6875rem] leading-[1.45] text-muted-foreground">
						{JSON.stringify(row.params_json ?? {}, null, 2)}
					</pre>
				</div>
			)}
		</article>
	);
}

function SeverityTag({ severity }: { severity: AgentSeverity }) {
	const color =
		severity === "high"
			? "var(--color-oxblood)"
			: severity === "medium"
				? "var(--color-meridian, var(--color-warning))"
				: "var(--color-muted-foreground)";
	return (
		<span
			className="rounded-md px-2 py-1 text-[0.625rem] font-semibold uppercase tracking-[0.08em]"
			style={{
				color,
				background: "color-mix(in srgb, currentColor 10%, transparent)",
			}}
		>
			{severity}
		</span>
	);
}

function AgentNotesPanel({
	notes,
	loading,
	error,
	latestAgentReadAt,
	onSaveNote,
	onDeleteNote,
}: {
	notes: AgentNoteRow[];
	loading: boolean;
	error: string | null;
	latestAgentReadAt: string | null;
	onSaveNote: (key: string, value: string) => Promise<void>;
	onDeleteNote: (key: string) => Promise<void>;
}) {
	const [draftKey, setDraftKey] = useState("");
	const [draftValue, setDraftValue] = useState("");
	const [saving, setSaving] = useState(false);
	const [localError, setLocalError] = useState<string | null>(null);

	const submit = async () => {
		const key = draftKey.trim();
		const value = draftValue.trim();
		if (!key || !value) {
			setLocalError("Add both a note key and instruction.");
			return;
		}
		setSaving(true);
		setLocalError(null);
		try {
			await onSaveNote(key, value);
			setDraftKey("");
			setDraftValue("");
		} catch (e) {
			setLocalError(e instanceof Error ? e.message : "Could not save note.");
		} finally {
			setSaving(false);
		}
	};

	return (
		<NovaDataPanel contentClassName="p-4" className="xl:sticky xl:top-4">
			<SectionHeader
				eyebrow="Operator notes"
				meta={loading ? "loading" : `${notes.length} pinned`}
			/>
			<p className="mt-2 text-[0.71875rem] leading-[1.45] text-muted-foreground">
				Notes are read by the agent at the start of its next run and stay pinned
				until deleted.
			</p>
			<div className="mt-4 flex flex-col gap-2">
				<Input
					value={draftKey}
					onChange={(e) => setDraftKey(e.target.value)}
					placeholder="note key"
				/>
				<Textarea
					value={draftValue}
					onChange={(e) => setDraftValue(e.target.value)}
					placeholder="instruction for the agent"
					rows={3}
					className="resize-none"
				/>
				<Button
					type="button"
					onClick={() => void submit()}
					disabled={saving}
					variant="outline"
					className="w-full gap-1.5 disabled:opacity-50"
				>
					<Plus data-icon="inline-start" aria-hidden="true" />
					{saving ? "Saving..." : "Save note"}
				</Button>
				{(localError || error) && (
					<div
						className="text-[0.6875rem] leading-[1.4] text-[var(--color-oxblood)]"
						role="alert"
					>
						{localError || error}
					</div>
				)}
			</div>
			<div className="mt-4 flex flex-col gap-2">
				{loading ? (
					Array.from({ length: 3 }).map((_, i) => (
						<div
							key={i}
							className="h-20 rounded-md bg-muted"
							aria-hidden="true"
						/>
					))
				) : notes.length === 0 ? (
					<div className="rounded-md bg-muted/50 border border-border p-3 text-[0.71875rem] leading-[1.45] text-muted-foreground">
						No pinned operator notes yet.
					</div>
				) : (
					notes.map((note) => (
						<AgentNoteCard
							key={note.id}
							note={note}
							latestAgentReadAt={latestAgentReadAt}
							onDelete={() => onDeleteNote(note.key)}
						/>
					))
				)}
			</div>
		</NovaDataPanel>
	);
}

function AgentNoteCard({
	note,
	latestAgentReadAt,
	onDelete,
}: {
	note: AgentNoteRow;
	latestAgentReadAt: string | null;
	onDelete: () => Promise<void>;
}) {
	const [deleting, setDeleting] = useState(false);
	const readLabel =
		latestAgentReadAt &&
		new Date(latestAgentReadAt).getTime() >= new Date(note.updated_at).getTime()
			? formatDateTime(latestAgentReadAt)
			: "next run not scheduled";
	return (
		<article className="rounded-md bg-muted/45 border border-border p-3">
			<div className="flex items-start justify-between gap-2">
				<div className="min-w-0">
					<div className="text-[0.78125rem] font-semibold text-foreground truncate">
						{note.key}
					</div>
					<p className="mt-1 text-[0.71875rem] leading-[1.45] text-muted-foreground">
						{note.value}
					</p>
				</div>
				<Button
					type="button"
					variant="ghost"
					size="icon"
					onClick={async () => {
						setDeleting(true);
						try {
							await onDelete();
						} finally {
							setDeleting(false);
						}
					}}
					disabled={deleting}
					className="h-7 w-7 text-muted-foreground hover:text-[var(--color-oxblood)] disabled:opacity-40"
					aria-label={`Delete ${note.key}`}
				>
					<Trash2 aria-hidden="true" />
				</Button>
			</div>
			<div className="mt-2 text-[0.625rem] text-muted-foreground tabular-nums">
				Updated {relativeShort(note.updated_at)} · Last read {readLabel}
			</div>
		</article>
	);
}

function AgentFeedSkeleton() {
	return (
		<div className="divide-y divide-border" aria-hidden="true">
			{Array.from({ length: 5 }).map((_, i) => (
				<div key={i} className="px-5 py-4 grid grid-cols-[132px_1fr] gap-4">
					<div className="h-3 w-24 rounded-md bg-muted" />
					<div className="flex flex-col gap-2">
						<Skeleton className="h-4 w-52 rounded-md" />
						<Skeleton className="h-3 w-[80%] rounded-md" />
					</div>
				</div>
			))}
		</div>
	);
}

function InlineModeState({
	icon: Icon,
	title,
	body,
}: {
	icon: React.ComponentType<{ className?: string | undefined }>;
	title: string;
	body: string;
}) {
	return (
		<NovaEmpty
			className="px-5 py-12"
			icon={<Icon data-icon="inline" className="text-muted-foreground" aria-hidden="true" />}
			title={title}
			description={body}
		/>
	);
}

function SectionHeader({
	eyebrow,
	meta,
	action,
	inline,
}: {
	eyebrow: string;
	meta?: string | undefined;
	action?: React.ReactNode | undefined;
	inline?: boolean | undefined;
}) {
	return (
		<div
			className={cn(
				"flex items-baseline gap-3",
				inline ? "flex-1" : "justify-between",
			)}
		>
			<div className="flex items-baseline gap-2 min-w-0">
				<span className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
					{eyebrow}
				</span>
				{meta && (
					<span className="text-[0.65625rem] text-muted-foreground tabular-nums truncate">
						{meta}
					</span>
				)}
			</div>
			{action}
		</div>
	);
}

function AutopilotHealthStat({
	label,
	value,
	icon: Icon,
	tone,
}: {
	label: string;
	value: string;
	icon: React.ComponentType<{ className?: string | undefined }>;
	tone: "good" | "warn" | "critical" | "neutral";
}) {
	const accent =
		tone === "good"
			? "var(--color-health-good)"
			: tone === "warn"
				? "var(--color-health-warn)"
				: tone === "critical"
					? "var(--color-oxblood)"
					: "var(--color-muted-foreground)";

	return (
		<NovaDataPanel contentClassName="p-4">
			<div className="flex items-center justify-between mb-2">
				<span className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
					{label}
				</span>
				<Icon className="w-3.5 h-3.5 text-muted-foreground" aria-hidden="true" />
			</div>
			<div className="flex items-baseline gap-2">
				<span className="text-[1.5rem] font-medium tabular-nums tracking-[-0.02em] text-foreground leading-none">
					{value}
				</span>
				<span
					className="w-[3px] h-3.5 rounded-full"
					style={{ background: accent }}
					aria-hidden="true"
				/>
			</div>
		</NovaDataPanel>
	);
}

/* ------------------------- Job card ------------------------- */
function JobCard({ job }: { job: Job }) {
	const successColor =
		job.successRate24h >= 98
			? "var(--color-health-good)"
			: job.successRate24h >= 92
				? "var(--color-health-warn)"
				: "var(--color-oxblood)";

	const isPaused = job.status === "paused";
	const accentColor = isPaused ? "var(--color-health-warn)" : successColor;

	return (
		<NovaDataPanel
			className="relative"
			contentClassName="flex flex-col gap-3 p-4"
		>
			{/* Left accent bar */}
			<span
				className="absolute left-0 top-3 bottom-3 w-[2px] rounded-full"
				style={{ background: accentColor, opacity: isPaused ? 0.45 : 1 }}
				aria-hidden="true"
			/>

			<div className="pl-1 min-w-0">
				<div className="flex items-center gap-2 flex-wrap">
					<span
						className="text-[0.84375rem] font-medium text-foreground tracking-[-0.005em] truncate"
						style={{ fontFamily: "'JetBrains Mono', ui-monospace, monospace" }}
					>
						{job.name}
					</span>
					<JobStatusPill status={job.status} />
				</div>
				<p className="mt-1 text-[0.71875rem] text-muted-foreground leading-[1.45] line-clamp-2">
					{job.description}
				</p>
			</div>

			{/* Schedule + times + success */}
			<div className="grid grid-cols-1 sm:grid-cols-3 gap-2 sm:gap-4 pl-1">
				<Meta label="Schedule">
					<span className="inline-flex items-center gap-1 text-muted-foreground">
						<Clock className="w-2.5 h-2.5" aria-hidden="true" />
						{job.schedule}
					</span>
				</Meta>
				<Meta label="Last / Next">
					<span className="text-muted-foreground tabular-nums">
						{job.lastRunRelative}{" "}
						<span className="text-muted-foreground mx-0.5">·</span>{" "}
						<span className="text-foreground font-medium">
							{job.nextRunRelative}
						</span>
					</span>
				</Meta>
				<Meta label="24h success" align="right">
					<span
						className="tabular-nums font-medium"
						style={{ color: successColor }}
					>
						{formatPercent(job.successRate24h)}{" "}
						<span className="text-muted-foreground font-normal">
							· {job.runs24h.toLocaleString()} runs
						</span>
					</span>
				</Meta>
			</div>

			{/* Sparkline */}
			<Sparkline values={job.spark} color={successColor} dim={isPaused} />
		</NovaDataPanel>
	);
}

function JobCardSkeleton() {
	return (
		<NovaDataPanel className="relative" contentClassName="p-4">
			<span
				className="absolute left-0 top-3 bottom-3 w-[2px] rounded-full bg-muted"
				aria-hidden="true"
			/>
			<div className="pl-1 flex flex-col gap-3">
				<div className="flex items-center gap-2">
					<div className="h-4 w-40 rounded-md bg-muted" />
					<div className="h-5 w-14 rounded-md bg-muted" />
				</div>
				<div className="h-3 w-[80%] rounded-md bg-muted" />
				<div className="h-3 w-[60%] rounded-md bg-muted" />
				<div className="h-4 w-full rounded-md bg-[color-mix(in_srgb,var(--color-foreground)_3%,transparent)] dark:bg-[color-mix(in_srgb,var(--color-card)_3%,transparent)]" />
			</div>
		</NovaDataPanel>
	);
}

function JobsEmpty({ error }: { error?: string | null | undefined }) {
	return (
		<NovaDataPanel contentClassName="p-10">
			<NovaEmpty
				icon={
					error ? (
						<AlertTriangle data-icon aria-hidden="true" />
					) : (
						<CircleSlash2 data-icon aria-hidden="true" />
					)
				}
				title={error ? "Job runs unavailable" : "No job runs yet"}
				description={
					error
						? "Autopilot could not load cron-run diagnostics right now. No fallback data is shown."
						: "Cron-run diagnostics will appear here once Autopilot starts executing scheduled work."
				}
			/>
		</NovaDataPanel>
	);
}

function Meta({
	label,
	children,
	align,
}: {
	label: string;
	children: React.ReactNode;
	align?: "right" | undefined;
}) {
	return (
		<div
			className={cn(
				"flex flex-col gap-0.5",
				align === "right" && "items-end text-right",
			)}
		>
			<span className="text-[0.59375rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
				{label}
			</span>
			<span className="text-[0.71875rem] tabular-nums">{children}</span>
		</div>
	);
}

function Sparkline({
	values,
	color,
	dim,
}: {
	values: number[];
	color: string;
	dim?: boolean | undefined;
}) {
	return (
		<div
			className="w-full h-4 ml-1"
			style={{ opacity: dim ? 0.4 : 1 }}
			aria-hidden="true"
		>
			<UISparkline
				points={values}
				color={color}
				height={18}
				strokeWidth={1.25}
				animate={false}
			/>
		</div>
	);
}

/* ------------------------- Failures ------------------------- */
function FailureSparklinePanel({
	window,
	windows,
	buckets,
	selectedBucketKey,
	loading,
	error,
	onWindowChange,
	onSelectBucket,
}: {
	window: FailureWindow;
	windows: Array<{ id: FailureWindow; label: string }>;
	buckets: FailureBucket[];
	selectedBucketKey: string | null;
	loading: boolean;
	error: string | null;
	onWindowChange: (window: FailureWindow) => void;
	onSelectBucket: (key: string) => void;
}) {
	const max = Math.max(1, ...buckets.map((bucket) => bucket.count));
	const total = buckets.reduce((sum, bucket) => sum + bucket.count, 0);

	return (
		<NovaDataPanel contentClassName="p-5">
			<div className="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
				<SectionHeader
					eyebrow="Failure density"
					meta={
						loading
							? "loading"
							: error
								? "live read unavailable"
								: `${total} failure${total === 1 ? "" : "s"} · ${window} window`
					}
					inline
				/>
				<div className="inline-flex self-start rounded-md bg-muted/70 border border-border p-0.5">
					{windows.map((item) => (
						<Button
							key={item.id}
							type="button"
							variant={item.id === window ? "secondary" : "ghost"}
							size="sm"
							onClick={() => onWindowChange(item.id)}
							className="h-7 rounded-[5px] px-2.5 text-[0.6875rem] tabular-nums"
						>
							{item.label}
						</Button>
					))}
				</div>
			</div>

			<div className="mt-4">
				{loading && buckets.every((bucket) => bucket.count === 0) ? (
					<Skeleton className="h-24 rounded-md border border-border" />
				) : error ? (
					<FailurePanelMessage
						title="Failure density unavailable"
						body="The failed-post read could not be loaded."
					/>
				) : (
					<div
						className="flex items-end gap-px h-24"
						role="list"
						aria-label={`Failures by ${window} bucket`}
					>
						{buckets.map((bucket) => {
							const active = selectedBucketKey === bucket.key;
							const height =
								bucket.count === 0
									? 7
									: Math.max(12, Math.round((bucket.count / max) * 88));
							return (
								<Button
									key={bucket.key}
									type="button"
									variant="ghost"
									size="sm"
									title={`${bucket.label}: ${bucket.count} failures · ${bucket.dominantClass}`}
									aria-label={`${bucket.label}, ${bucket.count} failures, dominant class ${bucket.dominantClass}`}
									onClick={() => onSelectBucket(bucket.key)}
									className={cn(
										"h-auto min-w-[3px] flex-1 rounded-t-[2px] p-0 transition-[height,opacity,background-color]",
										active &&
											"ring-2 ring-[var(--color-ring-oxblood)] ring-offset-2 ring-offset-card",
									)}
									style={{
										height,
										background:
											bucket.count > 0
												? "var(--color-oxblood)"
												: "color-mix(in srgb, var(--color-muted-foreground) 20%, transparent)",
										opacity: bucket.count > 0 ? 0.9 : 0.45,
									}}
								/>
							);
						})}
					</div>
				)}
				{!error && (
					<div className="mt-2 flex items-center justify-between text-[0.625rem] text-muted-foreground tabular-nums">
						<span>{buckets[0]?.label ?? "—"}</span>
						<span>{buckets[buckets.length - 1]?.label ?? "—"}</span>
					</div>
				)}
			</div>
		</NovaDataPanel>
	);
}

function FailureDrilldownPanel({
	window,
	selectedBucket,
	groups,
	loading,
	error,
	expandedClass,
	onToggleClass,
	onRetryFailure,
	onClearBucket,
	onOpenAccount,
	onOpenReplayForPost,
}: {
	window: FailureWindow;
	selectedBucket: FailureBucket | null;
	groups: FailureGroup[];
	loading: boolean;
	error: string | null;
	expandedClass: string | null;
	onToggleClass: (className: string) => void;
	onRetryFailure: (id: string) => void;
	onClearBucket: () => void;
	onOpenAccount: (failure: Failure) => void;
	onOpenReplayForPost: (postId: string) => void;
}) {
	return (
		<NovaDataPanel contentClassName="p-0">
			<div className="px-5 py-4 border-b border-border flex flex-col md:flex-row md:items-center md:justify-between gap-2">
				<SectionHeader
					eyebrow="Failure drilldown"
					meta={
						selectedBucket
							? `${selectedBucket.label} bucket selected`
							: `${window} grouped by error class`
					}
					inline
				/>
				{selectedBucket && (
					<Button
						type="button"
						variant="secondary"
						size="sm"
						onClick={onClearBucket}
						className="h-7 self-start px-2.5 text-[0.6875rem]"
					>
						Clear bucket
					</Button>
				)}
			</div>

			{loading && groups.length === 0 ? (
				<FailureGroupsSkeleton />
			) : error ? (
				<FailurePanelMessage
					title="Failure drilldown unavailable"
					body="Grouped error rows could not be loaded."
				/>
			) : groups.length === 0 ? (
				<FailurePanelMessage
					title={`No failures in ${window}`}
					body="The publish pipeline has no open failed posts in this window."
				/>
			) : (
				<div className="divide-y divide-border">
					{groups.map((group) => {
						const expanded = expandedClass === group.className;
						const latest = [...group.failures].sort(
							(a, b) =>
								(failureTimestampMs(b) ?? 0) - (failureTimestampMs(a) ?? 0),
						)[0];
						const samples = [...group.failures]
							.sort(
								(a, b) =>
									(failureTimestampMs(b) ?? 0) - (failureTimestampMs(a) ?? 0),
							)
							.slice(0, 3);
						return (
							<div key={group.className} className="bg-background">
								<Button
									type="button"
									variant="ghost"
									size="sm"
									onClick={() => onToggleClass(group.className)}
									className="h-auto w-full justify-start rounded-none px-5 py-4 text-left hover:bg-muted/40"
								>
									<span className="grid w-full grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_auto_auto_auto] lg:items-center">
										<span className="min-w-0">
											<span className="block text-[1rem] font-medium leading-tight text-foreground">
												{group.className}
											</span>
											<span className="mt-1 block text-[0.71875rem] text-muted-foreground">
												First seen{" "}
												{formatDateTime(
													new Date(group.firstSeenMs).toISOString(),
												)}{" "}
												· last seen{" "}
												{relativeShort(
													new Date(group.lastSeenMs).toISOString(),
												)}
											</span>
										</span>
										<span className="inline-flex items-center gap-2">
											<AvatarStack accounts={group.accounts} />
											<span className="text-[0.6875rem] text-muted-foreground">
												{group.accounts.length} account
												{group.accounts.length === 1 ? "" : "s"}
											</span>
										</span>
										<span
											className="text-[1rem] font-semibold tabular-nums"
											style={{
												color:
													group.count > 0
														? "var(--color-oxblood)"
														: "var(--color-muted-foreground)",
											}}
										>
											{group.count}
										</span>
										<ChevronDown
											data-icon="inline-end"
											className={cn(
												"text-muted-foreground transition-transform",
												expanded && "rotate-180",
											)}
											aria-hidden="true"
										/>
									</span>
								</Button>
								{expanded && (
									<div className="px-5 pb-5 pt-1 bg-muted/20">
										<div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_280px] gap-4">
											<div className="flex flex-col gap-2">
												{samples.map((failure) => (
													<div
														key={failure.id}
														className="rounded-md border border-border bg-background p-3"
													>
														<div className="flex flex-wrap items-center gap-2 text-[0.6875rem] text-muted-foreground">
															<Button
																type="button"
																variant="ghost"
																size="sm"
																onClick={() => onOpenAccount(failure)}
																className="h-auto p-0 font-semibold text-foreground hover:underline"
															>
																{failure.handle}
															</Button>
															<span>{failure.whenRelative}</span>
															<span>
																{failure.platform === "instagram"
																	? "IG"
																	: "Threads"}
															</span>
														</div>
														<div className="mt-1 text-[0.78125rem] leading-[1.45] text-muted-foreground">
															{truncateFailureMessage(failure.detail)}
														</div>
														{failure.retryError && (
															<div
																className="mt-1 text-[0.65625rem]"
																style={{ color: "var(--color-oxblood)" }}
															>
																Retry failed — {failure.retryError}
															</div>
														)}
													</div>
												))}
											</div>
											<div className="rounded-md border border-border bg-background p-3">
												<div className="text-[0.65625rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
													Affected accounts
												</div>
												<div className="mt-2 flex flex-wrap gap-1.5">
													{group.accounts.map((account) => (
														<span
															key={account.key}
															className="px-2 py-1 rounded-md bg-muted text-[0.6875rem] font-medium text-muted-foreground"
														>
															{account.handle}
														</span>
													))}
												</div>
												<div className="mt-4 flex flex-wrap gap-2">
													<Button
														type="button"
														disabled={
															!latest || latest.retrying || latest.resolved
														}
														onClick={() => latest && onRetryFailure(latest.id)}
														variant="outline"
														size="sm"
														className="h-8 gap-1.5 text-[0.71875rem] text-[var(--color-oxblood)] disabled:opacity-40"
													>
														<RotateCw
															data-icon="inline-start"
															className={cn(latest?.retrying && "animate-spin")}
															aria-hidden="true"
														/>
														Retry latest
													</Button>
													<Button
														type="button"
														disabled={!latest}
														onClick={() =>
															latest && onOpenReplayForPost(latest.id)
														}
														variant="secondary"
														size="sm"
														className="h-8 text-[0.71875rem] disabled:opacity-40"
													>
														Open replay
													</Button>
												</div>
											</div>
										</div>
									</div>
								)}
							</div>
						);
					})}
				</div>
			)}
		</NovaDataPanel>
	);
}

function AccountHealthStrip({
	rows,
	window,
	loading,
	error,
	onOpenAccount,
}: {
	rows: AccountFailureHealth[];
	window: FailureWindow;
	loading: boolean;
	error: string | null;
	onOpenAccount: (row: AccountFailureHealth) => void;
}) {
	return (
		<NovaDataPanel contentClassName="p-0">
			<div className="px-5 py-4 border-b border-border">
				<SectionHeader
					eyebrow="Account health"
					meta={
						loading
							? "loading"
							: error
								? "live read unavailable"
								: `${rows.length} affected · ${window}`
					}
					inline
				/>
			</div>
			{loading && rows.length === 0 ? (
				<div
					className="grid grid-cols-1 md:grid-cols-3 gap-px bg-border"
					aria-hidden="true"
				>
					{Array.from({ length: 3 }).map((_, index) => (
						<div key={index} className="h-24 bg-background p-4">
							<Skeleton className="h-8 w-8 rounded-full" />
							<Skeleton className="mt-3 h-3 w-28 rounded-md" />
						</div>
					))}
				</div>
			) : error ? (
				<FailurePanelMessage
					title="Account health unavailable"
					body="Recent account failure counts could not be loaded."
				/>
			) : rows.length === 0 ? (
				<FailurePanelMessage
					title={`No affected accounts in ${window}`}
					body="Every account is healthy for this failure window."
				/>
			) : (
				<div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-px bg-border">
					{rows.map((row) => (
						<Button
							key={row.key}
							type="button"
							variant="ghost"
							size="sm"
							onClick={() => onOpenAccount(row)}
							className="h-auto rounded-none bg-background px-5 py-4 text-left hover:bg-muted/40"
						>
							<span className="grid w-full grid-cols-[auto_1fr_auto] items-center gap-3">
								<AccountAvatar
									handle={row.handle}
									avatarUrl={row.avatarUrl}
									size="md"
								/>
								<span className="min-w-0">
									<span className="block truncate text-[0.8125rem] font-medium text-foreground">
										{row.handle}
									</span>
									<span className="mt-1 block truncate text-[0.6875rem] text-muted-foreground">
										{row.mostRecentClass} ·{" "}
										{relativeShort(new Date(row.lastSeenMs).toISOString())}
									</span>
								</span>
								<span className="text-right">
									<span
										className="block font-mono text-[1rem] font-semibold tabular-nums"
										style={{
											color:
												row.count > 0
													? "var(--color-oxblood)"
													: "var(--color-muted-foreground)",
										}}
									>
										{row.count}
									</span>
									<StatusPill
										tone={row.status === "failing" ? "critical" : "warn"}
										size="xs"
										className="!rounded-md"
									>
										{row.status}
									</StatusPill>
								</span>
							</span>
						</Button>
					))}
				</div>
			)}
		</NovaDataPanel>
	);
}

function RestartWarmupCard({
	summary,
	loading,
	error,
	onRefresh,
	onOpenAccount,
}: {
	summary: RestartWarmupOpsSummary | null;
	loading: boolean;
	error: string | null;
	onRefresh: () => Promise<void>;
	onOpenAccount: (row: RestartWarmupOpsSummary["rows"][number]) => void;
}) {
	const rows = summary?.rows.slice(0, 9) ?? [];
	const meta = loading
		? "loading"
		: error
			? "unavailable"
			: summary
				? `${summary.activeCount} warming · ${summary.heldCount} held · ${summary.suppressedCount} suppressed`
				: "no restart ramp";
	return (
		<NovaDataPanel contentClassName="p-0">
			<div className="px-5 py-4 border-b border-border">
				<SectionHeader
					eyebrow="Restart warm-up"
					meta={meta}
					inline
					action={
						<Button
							type="button"
							variant="ghost"
							size="sm"
							onClick={() => void onRefresh()}
							disabled={loading}
						>
							Refresh
						</Button>
					}
				/>
			</div>
			{loading && rows.length === 0 ? (
				<div className="grid grid-cols-1 md:grid-cols-3 gap-px bg-border">
					{Array.from({ length: 3 }).map((_, index) => (
						<div key={index} className="h-28 bg-background p-4">
							<Skeleton className="h-4 w-24 rounded-md" />
							<Skeleton className="mt-3 h-3 w-36 rounded-md" />
							<Skeleton className="mt-2 h-3 w-28 rounded-md" />
						</div>
					))}
				</div>
			) : error ? (
				<FailurePanelMessage
					title="Restart warm-up unavailable"
					body="The ops dashboard did not return warm-up state."
				/>
			) : rows.length === 0 ? (
				<FailurePanelMessage
					title="No accounts in restart warm-up"
					body="Accounts are either not restarting, completed, or suppressed elsewhere."
				/>
			) : (
				<div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-px bg-border">
					{rows.map((row) => (
						<Button
							key={row.account_id}
							type="button"
							variant="ghost"
							size="sm"
							onClick={() => onOpenAccount(row)}
							className="h-auto rounded-none bg-background px-5 py-4 text-left hover:bg-muted/40"
						>
							<span className="block w-full min-w-0">
								<span className="flex items-center justify-between gap-3">
									<span className="truncate text-[0.8125rem] font-medium text-foreground">
										{row.username}
									</span>
									<StatusPill
										tone={
											row.restart_warmup_status === "suppressed"
												? "critical"
												: row.restart_warmup_status === "held"
													? "warn"
													: "good"
										}
										size="xs"
										className="!rounded-md"
									>
										{row.restart_warmup_status}
									</StatusPill>
								</span>
								<span className="mt-2 block text-[0.6875rem] text-muted-foreground">
									day {row.restart_warmup_day ?? "-"} · cap{" "}
									{row.restart_warmup_allowed_posts_per_day ?? "normal"}/day ·
									health {row.score ?? "-"}
								</span>
								<span className="mt-1 block truncate text-[0.6875rem] text-muted-foreground">
									last views {row.restart_warmup_last_post_views ?? "-"} ·{" "}
									{row.restart_warmup_next_ramp_at
										? `next ${relativeShort(row.restart_warmup_next_ramp_at)}`
										: "no next ramp"}
								</span>
								<span className="mt-1 block truncate text-[0.6875rem] text-muted-foreground">
									{row.restart_warmup_reason ?? row.reason ?? "no reason"}
								</span>
							</span>
						</Button>
					))}
				</div>
			)}
		</NovaDataPanel>
	);
}

function AccountDnaCard({
	summary,
	loading,
	error,
	backfillRunning,
	backfillResult,
	onRefresh,
	onBackfill,
}: {
	summary: AccountDnaOpsSummary | null;
	loading: boolean;
	error: string | null;
	backfillRunning: boolean;
	backfillResult: AccountDnaBackfillResponse | null;
	onRefresh: () => Promise<void>;
	onBackfill: () => Promise<void>;
}) {
	const coverage =
		summary && summary.totalAutoposterAccounts > 0
			? Math.round(
					(summary.activeProfiles / summary.totalAutoposterAccounts) * 100,
				)
			: 0;
	const profiles = summary?.profiles.slice(0, 6) ?? [];
	const reviewItems = summary?.reviewItems.slice(0, 3) ?? [];
	return (
		<NovaDataPanel contentClassName="p-5">
			<SectionHeader
				eyebrow="Account DNA"
				meta={
					loading
						? "loading"
						: error
							? "unavailable"
							: summary
								? `${summary.activeProfiles}/${summary.totalAutoposterAccounts} active`
								: "not configured"
				}
				action={
					<div className="flex items-center gap-2">
						<Button
							type="button"
							variant="ghost"
							size="icon"
							onClick={() => void onRefresh()}
							disabled={loading || backfillRunning}
							className="h-7 w-7 text-muted-foreground disabled:opacity-40"
							aria-label="Refresh account DNA"
						>
							<RotateCw aria-hidden="true" />
						</Button>
						<Button
							type="button"
							size="sm"
							variant="outline"
							onClick={() => void onBackfill()}
							disabled={loading || backfillRunning}
						>
							<Fingerprint data-icon="inline-start" aria-hidden="true" />
							{backfillRunning ? "Backfilling" : "Backfill DNA"}
						</Button>
					</div>
				}
			/>
			{error ? (
				<div className="mt-3 rounded-md border border-border bg-muted/45 px-3 py-2 text-[0.71875rem] leading-[1.45] text-[var(--color-oxblood)]">
					{error}
				</div>
			) : loading ? (
				<div
					className="mt-4 grid grid-cols-1 md:grid-cols-4 gap-3"
					aria-hidden="true"
				>
					{Array.from({ length: 4 }).map((_, i) => (
						<div key={i} className="h-20 rounded-md bg-muted" />
					))}
				</div>
			) : !summary ? (
				<div className="mt-3 rounded-md border border-border bg-muted/45 px-3 py-2 text-[0.71875rem] leading-[1.45] text-muted-foreground">
					Account DNA has not returned a live summary yet.
				</div>
			) : (
				<>
					<div className="mt-4 grid grid-cols-2 md:grid-cols-5 gap-2.5">
						<DnaMetric label="Coverage" value={`${coverage}%`} />
						<DnaMetric label="Drafts" value={String(summary.draftProfiles)} />
						<DnaMetric
							label="Missing"
							value={String(summary.missingProfiles)}
						/>
						<DnaMetric
							label="Uniqueness"
							value={formatNullableScore(summary.avgUniquenessScore)}
						/>
						<DnaMetric
							label="Review"
							value={String(summary.reviewQueueCount)}
							tone={summary.reviewQueueCount > 0 ? "warn" : "good"}
						/>
					</div>
					{backfillResult && (
						<div className="mt-3 rounded-md border border-border bg-muted/45 px-3 py-2 text-[0.71875rem] leading-[1.45] text-muted-foreground">
							Created {backfillResult.created}, skipped {backfillResult.skipped}
							, failed {backfillResult.failed}; examples{" "}
							{backfillResult.examplesCreated}, rules{" "}
							{backfillResult.rulesCreated}.
						</div>
					)}
					<div className="mt-4 grid grid-cols-1 xl:grid-cols-[1.2fr_0.8fr] gap-3">
						<div className="flex flex-col gap-2">
							{profiles.length === 0 ? (
								<div className="rounded-md border border-border bg-muted/45 px-3 py-4 text-[0.71875rem] text-muted-foreground">
									No DNA profiles found for active autoposter accounts.
								</div>
							) : (
								profiles.map((profile) => (
									<DnaProfileRow key={profile.id} profile={profile} />
								))
							)}
						</div>
						<div className="flex flex-col gap-2">
							{reviewItems.length === 0 ? (
								<div className="rounded-md border border-border bg-muted/45 px-3 py-4 text-[0.71875rem] text-muted-foreground">
									No DNA review candidates.
								</div>
							) : (
								reviewItems.map((item) => (
									<DnaReviewRow key={item.id} item={item} />
								))
							)}
						</div>
					</div>
				</>
			)}
		</NovaDataPanel>
	);
}

function DnaMetric({
	label,
	value,
	tone = "neutral",
}: {
	label: string;
	value: string;
	tone?: "good" | "warn" | "neutral";
}) {
	const color =
		tone === "good"
			? "var(--color-health-good)"
			: tone === "warn"
				? "var(--color-health-warn)"
				: "var(--color-foreground)";
	return (
		<div className="rounded-md border border-border bg-muted/35 px-3 py-2">
			<div className="text-[0.625rem] uppercase tracking-[0.12em] text-muted-foreground">
				{label}
			</div>
			<div
				className="mt-1 text-[1rem] font-semibold tabular-nums"
				style={{ color }}
			>
				{value}
			</div>
		</div>
	);
}

function DnaProfileRow({ profile }: { profile: AccountDnaProfileSummary }) {
	return (
		<article className="rounded-md border border-border bg-muted/30 px-3 py-2.5">
			<div className="flex items-start justify-between gap-3">
				<div className="min-w-0">
					<div className="flex items-center gap-2 min-w-0">
						<span className="text-[0.8125rem] font-semibold text-foreground truncate">
							{profile.archetype}
						</span>
						<StatusPill
							tone={profile.status === "active" ? "good" : "warn"}
							size="xs"
							className="!rounded-md"
						>
							{profile.status}
						</StatusPill>
					</div>
					<p className="mt-1 text-[0.71875rem] leading-[1.4] text-muted-foreground line-clamp-2">
						{profile.follower_promise}
					</p>
				</div>
				<div className="text-right shrink-0">
					<div className="text-[0.75rem] font-semibold tabular-nums text-foreground">
						{Math.round(Number(profile.confidence ?? 0) * 100)}%
					</div>
					<div className="text-[0.625rem] text-muted-foreground">confidence</div>
				</div>
			</div>
			<div className="mt-2 flex flex-wrap gap-1.5">
				{profile.primary_topics.slice(0, 3).map((topic) => (
					<Badge key={topic} variant="secondary" className="text-[0.625rem]">
						{topic}
					</Badge>
				))}
				{profile.signature_phrases.slice(0, 2).map((phrase) => (
					<Badge key={phrase} variant="outline" className="text-[0.625rem]">
						{phrase}
					</Badge>
				))}
			</div>
			<div className="mt-2 grid grid-cols-3 gap-2 text-[0.6875rem] text-muted-foreground tabular-nums">
				<span>unique {formatNullableScore(profile.uniqueness_score)}</span>
				<span>
					collision {formatNullableScore(profile.sibling_collision_score)}
				</span>
				<span>generic {formatNullableScore(profile.genericness_score)}</span>
			</div>
		</article>
	);
}

function DnaReviewRow({ item }: { item: AccountDnaReviewItem }) {
	const reasons = Array.isArray(item.dna_reasons) ? item.dna_reasons : [];
	return (
		<article className="rounded-md border border-border bg-muted/30 px-3 py-2.5">
			<div className="flex items-center justify-between gap-2">
				<span className="text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
					{item.dna_decision ?? "needs_review"}
				</span>
				<span className="text-[0.6875rem] tabular-nums text-muted-foreground">
					fit {formatNullableScore(item.dna_fit_score)}
				</span>
			</div>
			<p className="mt-1 text-[0.75rem] leading-[1.35] text-foreground line-clamp-2">
				{item.content}
			</p>
			<div className="mt-2 flex flex-wrap gap-1.5">
				{reasons.slice(0, 3).map((reason) => (
					<Badge key={reason} variant="secondary" className="text-[0.625rem]">
						{reason.replaceAll("_", " ")}
					</Badge>
				))}
			</div>
		</article>
	);
}

function formatNullableScore(value: number | null | undefined): string {
	return Number.isFinite(Number(value))
		? String(Math.round(Number(value)))
		: "—";
}

function AvatarStack({
	accounts,
}: {
	accounts: Array<{ key: string; handle: string; avatarUrl: string | null }>;
}) {
	const visible = accounts.slice(0, 5);
	const extra = accounts.length - visible.length;
	return (
		<div className="flex items-center">
			{visible.map((account, index) => (
				<div key={account.key} className={index > 0 ? "-ml-2" : undefined}>
					<AccountAvatar
						handle={account.handle}
						avatarUrl={account.avatarUrl}
						size="sm"
						stacked
					/>
				</div>
			))}
			{extra > 0 && (
				<span className="-ml-2 inline-flex h-6 w-6 items-center justify-center rounded-full border-2 border-card bg-muted text-[0.59375rem] font-semibold text-muted-foreground">
					+{extra}
				</span>
			)}
		</div>
	);
}

function AccountAvatar({
	handle,
	avatarUrl,
	size,
	stacked,
}: {
	handle: string;
	avatarUrl: string | null;
	size: "sm" | "md";
	stacked?: boolean | undefined;
}) {
	const dimensions =
		size === "sm" ? "w-6 h-6 text-[0.625rem]" : "w-9 h-9 text-[0.75rem]";
	const initial = handle.replace(/^@/, "").slice(0, 1).toUpperCase() || "?";
	if (avatarUrl) {
		return (
			<img
				src={avatarUrl}
				alt=""
				loading="lazy"
				decoding="async"
				className={cn(
					dimensions,
					"rounded-full object-cover bg-muted",
					stacked && "border-2 border-card",
				)}
			/>
		);
	}
	return (
		<span
			className={cn(
				dimensions,
				"rounded-full inline-flex items-center justify-center bg-muted text-muted-foreground font-semibold",
				stacked && "border-2 border-card",
			)}
			aria-hidden="true"
		>
			{initial}
		</span>
	);
}

function FailureGroupsSkeleton() {
	return (
		<div className="divide-y divide-border" aria-hidden="true">
			{Array.from({ length: 3 }).map((_, index) => (
				<div key={index} className="px-5 py-4">
					<Skeleton className="h-4 w-40 rounded-md" />
					<Skeleton className="mt-2 h-3 w-72 max-w-full rounded-md" />
				</div>
			))}
		</div>
	);
}

function FailurePanelMessage({ title, body }: { title: string; body: string }) {
	return (
		<NovaEmpty
			className="py-2"
			icon={<AlertCircle data-icon aria-hidden="true" />}
			title={title}
			description={body}
		/>
	);
}

/* ------------------------- Queue + Rate limit rows ------------------------- */
function networkLabelOf(network: string, fallback?: string): string {
	return groupLabelFromId(network, fallback);
}

function DaysBar({ row }: { row: QueueHealthRow }) {
	const pct = Math.min(100, (row.days / 7) * 100);
	const tone: HealthTone =
		row.days < 2 ? "critical" : row.days < 4 ? "warn" : "good";
	const color =
		tone === "good"
			? "var(--color-health-good)"
			: tone === "warn"
				? "var(--color-health-warn)"
				: "var(--color-oxblood)";
	const label = networkLabelOf(row.network, row.networkLabel);

	return (
		<div className="flex flex-col gap-1.5">
			<div className="flex items-center justify-between">
				<div className="inline-flex items-center gap-1.5 min-w-0">
					<span
						className="w-1.5 h-1.5 rounded-full shrink-0"
						style={{ background: networkColorOf(row.network) }}
						aria-hidden="true"
					/>
					<span className="text-[0.78125rem] font-medium text-foreground truncate">
						{label}
					</span>
				</div>
				<span
					className="text-[0.75rem] tabular-nums shrink-0"
					style={{ color }}
				>
					{row.days.toFixed(1)}d
				</span>
			</div>
			<div className="h-1.5 rounded-full overflow-hidden bg-muted">
				<div
					className="h-full w-full rounded-full origin-left"
					style={{ background: color, transform: `scaleX(${pct / 100})` }}
				/>
			</div>
			<div className="text-[0.65625rem] text-muted-foreground tabular-nums">
				{row.scheduledCount} scheduled · {row.accountCount} account
				{row.accountCount === 1 ? "" : "s"}
			</div>
		</div>
	);
}

function DaysBarSkeleton() {
	return (
		<div className="flex flex-col gap-1.5" aria-hidden="true">
			<div className="flex items-center justify-between">
				<div className="h-3 w-20 rounded-md bg-muted" />
				<div className="h-3 w-8 rounded-md bg-muted" />
			</div>
			<div className="h-1.5 rounded-full bg-muted" />
			<div className="h-2.5 w-28 rounded-md bg-muted" />
		</div>
	);
}

function networkColorOf(network: string): string {
	return groupColorFromId(network);
}

function RateLimitRow({ row }: { row: RateLimit }) {
	const pct = Math.min(100, (row.used / row.cap) * 100);
	const tone: HealthTone = pct >= 95 ? "critical" : pct >= 80 ? "warn" : "good";
	const color =
		tone === "good"
			? "var(--color-health-good)"
			: tone === "warn"
				? "var(--color-health-warn)"
				: "var(--color-oxblood)";

	return (
		<div className="px-5 py-3.5 bg-background">
			<div className="flex items-center justify-between gap-3 mb-2">
				<div className="flex items-center gap-2 min-w-0">
					<span
						className="w-1.5 h-1.5 rounded-full shrink-0"
						style={{ background: networkColorOf(row.network) }}
						aria-hidden="true"
					/>
					<span className="text-[0.8125rem] font-medium text-foreground truncate">
						{row.handle}
					</span>
					<span className="text-[0.65625rem] uppercase tracking-[0.08em] text-muted-foreground">
						{row.platform === "instagram" ? "IG" : "Threads"}
					</span>
				</div>
				<div className="text-[0.75rem] tabular-nums inline-flex items-center gap-1.5 shrink-0">
					<Gauge className="w-3 h-3 text-muted-foreground" aria-hidden="true" />
					<span style={{ color }}>
						{row.used}/{row.cap}
					</span>
				</div>
			</div>
			<div className="h-1.5 rounded-full overflow-hidden bg-muted">
				<div
					className="h-full w-full rounded-full origin-left"
					style={{ background: color, transform: `scaleX(${pct / 100})` }}
				/>
			</div>
			<div className="mt-1.5 text-[0.65625rem] text-muted-foreground tabular-nums inline-flex items-center gap-1">
				<Clock className="w-2.5 h-2.5" aria-hidden="true" />
				resets in {row.resetRelative}
			</div>
		</div>
	);
}
