import {
	type ChangeEvent,
	useCallback,
	useEffect,
	useMemo,
	useState,
} from "react";
import {
	AlertTriangle,
	Check,
	Clock3,
	Copy,
	Filter,
	GitCompare,
	PencilLine,
	RefreshCw,
	Search,
	ShieldCheck,
	SlidersHorizontal,
	X,
} from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { z } from "zod";
import { NovaScreen } from "@/components/layout/NovaScreen";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import {
	NovaCard,
	NovaEmpty,
	NovaHeader,
	NovaSection,
} from "@/components/ui/NovaPrimitives";
import { Select } from "@/components/ui/Select";
import { Skeleton } from "@/components/ui/Skeleton";
import { Textarea } from "@/components/ui/Textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/ToggleGroup";
import { apiFetch } from "@/lib/apiFetch";
import { appToast } from "@/lib/toast";

const approvalSchema = z
	.object({
		id: z.string(),
		context: z.string().nullable().optional(),
		urgency: z.string().nullable().optional(),
		status: z.string(),
		expires_at: z.string().nullable().optional(),
		created_at: z.string().nullable().optional(),
		proposed_actions: z.unknown().optional(),
	})
	.passthrough();

const approvalsResponseSchema = z.object({
	success: z.boolean().optional(),
	approvals: z.array(approvalSchema).default([]),
});

const decideResponseSchema = z.object({
	success: z.boolean().optional(),
	id: z.string(),
	status: z.string(),
	decidedAt: z.string().optional(),
});

const reviseResponseSchema = z.object({
	success: z.boolean().optional(),
	approvalId: z.string(),
	intentId: z.string(),
	previousApprovalId: z.string().optional(),
	previousIntentId: z.string().optional(),
});

const executeResponseSchema = z
	.object({
		success: z.boolean().optional(),
		status: z.string().optional(),
		intentId: z.string().optional(),
		approvalId: z.string().optional(),
		message: z.string().optional(),
		dispatch: z.unknown().optional(),
	})
	.passthrough();

type Approval = z.infer<typeof approvalSchema>;
type EditablePayloadField = {
	key: string;
	label: string;
	kind: "text" | "textarea" | "datetime" | "select" | "url-list";
	aliases: string[];
	options?: Array<{ label: string; value: string }>;
	placeholder?: string;
	help?: string;
};

function firstAction(approval: Approval): Record<string, unknown> {
	const proposed = approval.proposed_actions;
	const first = Array.isArray(proposed) ? proposed[0] : proposed;
	return first && typeof first === "object" && !Array.isArray(first)
		? (first as Record<string, unknown>)
		: {};
}

function stringValue(value: unknown, fallback = "Not provided") {
	return typeof value === "string" && value.length > 0 ? value : fallback;
}

function scopeLabel(action: Record<string, unknown>) {
	const scope =
		action.scope && typeof action.scope === "object"
			? (action.scope as Record<string, unknown>)
			: action;
	const accountId = stringValue(scope.accountId ?? scope.account_id, "");
	const groupId = stringValue(scope.groupId ?? scope.group_id, "");
	const workspaceId = stringValue(scope.workspaceId ?? scope.workspace_id, "");
	if (accountId) return `Account ${accountId}`;
	if (groupId) return `Group ${groupId}`;
	if (workspaceId) return `Workspace ${workspaceId}`;
	return "Workspace scope";
}

function normalizedPayload(action: Record<string, unknown>) {
	const value =
		action.normalizedPayload ?? action.normalized_payload ?? action.payload;
	return value && typeof value === "object" ? value : {};
}

function payloadPreview(payload: Record<string, unknown>, actionName: string) {
	const direct =
		payload.replyText ??
		payload.reply_text ??
		payload.content ??
		payload.caption ??
		payload.message ??
		payload.text ??
		payload.body ??
		payload.title;
	if (typeof direct === "string" && direct.trim().length > 0) return direct;

	const keys = Object.keys(payload);
	if (keys.length > 0) {
		return keys
			.slice(0, 4)
			.map(
				(key) =>
					`${key}: ${stringValue(payload[key], String(payload[key] ?? ""))}`,
			)
			.join(" · ");
	}

	return `${actionName} is ready for operator review. Confirm the account, scope, and payload hash before execution.`;
}

function compactHash(value: unknown) {
	const text = stringValue(value, "");
	if (!text) return "Not provided";
	return text.length > 18 ? `${text.slice(0, 10)}...${text.slice(-6)}` : text;
}

function formatEventTime(value: unknown) {
	if (typeof value !== "string" || value.length === 0)
		return "Time not recorded";
	const date = new Date(value);
	if (Number.isNaN(date.getTime())) return value;
	return date.toLocaleString();
}

function riskTone(risk: string) {
	if (risk === "critical" || risk === "high") return "text-red-500";
	if (risk === "medium") return "text-amber-500";
	return "text-emerald-500";
}

function stableStringify(value: unknown): string {
	if (value === undefined) return "undefined";
	if (value === null || typeof value !== "object") return JSON.stringify(value);
	if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
	return `{${Object.entries(value as Record<string, unknown>)
		.sort(([a], [b]) => a.localeCompare(b))
		.map(([key, child]) => `${JSON.stringify(key)}:${stableStringify(child)}`)
		.join(",")}}`;
}

function prettyPayload(value: unknown) {
	return value === undefined ? "undefined" : JSON.stringify(value, null, 2);
}

function diffPayload(original: Record<string, unknown>, revisedText: string) {
	try {
		const revised = JSON.parse(revisedText) as Record<string, unknown>;
		const keys = Array.from(
			new Set([...Object.keys(original), ...Object.keys(revised)]),
		).sort();
		return keys
			.map((key) => ({
				key,
				before: original[key],
				after: revised[key],
				changed:
					stableStringify(original[key]) !== stableStringify(revised[key]),
			}))
			.filter((item) => item.changed);
	} catch {
		return null;
	}
}

function parsePayloadText(text: string): Record<string, unknown> | null {
	try {
		const parsed = JSON.parse(text);
		return parsed && typeof parsed === "object" && !Array.isArray(parsed)
			? (parsed as Record<string, unknown>)
			: null;
	} catch {
		return null;
	}
}

function firstExistingKey(payload: Record<string, unknown>, aliases: string[]) {
	return (
		aliases.find((alias) => Object.hasOwn(payload, alias)) ??
		aliases[0] ??
		"value"
	);
}

function editableValue(
	payload: Record<string, unknown> | null,
	field: EditablePayloadField,
) {
	if (!payload) return "";
	const key = firstExistingKey(payload, field.aliases);
	const value = payload[key];
	if (field.kind === "url-list") {
		if (Array.isArray(value))
			return value.filter((item) => typeof item === "string").join("\n");
		return typeof value === "string" ? value : "";
	}
	if (field.kind === "datetime") {
		if (typeof value !== "string" || !value) return "";
		const date = new Date(value);
		return Number.isNaN(date.getTime())
			? value
			: date.toISOString().slice(0, 16);
	}
	if (typeof value === "string") return value;
	if (value === null || value === undefined) return "";
	return String(value);
}

function updatePayloadField(
	payload: Record<string, unknown>,
	field: EditablePayloadField,
	rawValue: string,
) {
	const next = { ...payload };
	const key = firstExistingKey(next, field.aliases);
	if (field.kind === "url-list") {
		next[key] = rawValue
			.split("\n")
			.map((url) => url.trim())
			.filter(Boolean);
		return next;
	}
	if (field.kind === "datetime") {
		next[key] = rawValue ? new Date(rawValue).toISOString() : null;
		return next;
	}
	next[key] = rawValue;
	return next;
}

function getEditablePayloadFields(
	actionName: string,
	payload: Record<string, unknown>,
): EditablePayloadField[] {
	const name = actionName.toLowerCase();
	const has = (keys: string[]) =>
		keys.some((key) => Object.hasOwn(payload, key));
	const fields: EditablePayloadField[] = [];
	const add = (field: EditablePayloadField) => {
		if (!fields.some((existing) => existing.key === field.key))
			fields.push(field);
	};

	if (
		name.includes("publish") ||
		name.includes("schedule") ||
		name.includes("post") ||
		has(["content", "caption", "text"])
	) {
		add({
			key: "content",
			label: "Caption / post text",
			kind: "textarea",
			aliases: ["content", "caption", "text", "message", "body"],
			placeholder:
				"Write the exact caption or post text that should be approved.",
		});
		add({
			key: "mediaUrls",
			label: "Media URLs",
			kind: "url-list",
			aliases: ["mediaUrls", "media_urls", "mediaUrl", "media_url"],
			placeholder: "One public media URL per line",
			help: "These URLs must already be accessible to the publish worker.",
		});
		add({
			key: "platform",
			label: "Platform",
			kind: "select",
			aliases: ["platform"],
			options: [
				{ label: "Keep current", value: "" },
				{ label: "Threads", value: "threads" },
				{ label: "Instagram", value: "instagram" },
			],
		});
	}

	if (
		name.includes("schedule") ||
		name.includes("reschedule") ||
		has(["scheduledFor", "scheduled_for", "scheduledAt", "scheduled_at"])
	) {
		add({
			key: "scheduledFor",
			label: "Scheduled time",
			kind: "datetime",
			aliases: [
				"scheduledFor",
				"scheduled_for",
				"scheduledAt",
				"scheduled_at",
				"newScheduledFor",
				"new_scheduled_for",
			],
			help: "Resubmitting creates a new exact intent with a fresh payload hash.",
		});
	}

	if (
		name.includes("reply") ||
		has([
			"replyText",
			"reply_text",
			"commentId",
			"comment_id",
			"replyToId",
			"reply_to_id",
		])
	) {
		add({
			key: "replyText",
			label: "Reply text",
			kind: "textarea",
			aliases: [
				"replyText",
				"reply_text",
				"content",
				"message",
				"text",
				"body",
			],
			placeholder: "Write the exact reply text that should be sent.",
		});
		add({
			key: "replyToId",
			label: "Reply/comment target ID",
			kind: "text",
			aliases: [
				"replyToId",
				"reply_to_id",
				"commentId",
				"comment_id",
				"messageId",
				"message_id",
				"mediaId",
				"media_id",
			],
		});
	}

	if (
		name.includes("queue_fill") ||
		name.includes("queue fill") ||
		name.includes("trigger_queue_fill")
	) {
		add({
			key: "limit",
			label: "Fill limit",
			kind: "text",
			aliases: ["limit", "count", "targetCount", "target_count"],
		});
		add({
			key: "windowStart",
			label: "Window start",
			kind: "datetime",
			aliases: ["windowStart", "window_start", "startAt", "start_at"],
		});
		add({
			key: "windowEnd",
			label: "Window end",
			kind: "datetime",
			aliases: ["windowEnd", "window_end", "endAt", "end_at"],
		});
	}

	add({
		key: "accountId",
		label: "Account ID",
		kind: "text",
		aliases: [
			"accountId",
			"account_id",
			"instagramAccountId",
			"instagram_account_id",
			"threadsAccountId",
			"threads_account_id",
		],
	});
	if (has(["groupId", "group_id"]) || name.includes("queue")) {
		add({
			key: "groupId",
			label: "Group ID",
			kind: "text",
			aliases: ["groupId", "group_id"],
		});
	}

	return fields;
}

const rejectionTemplates = [
	"Rework caption before approval.",
	"Wrong account or scope selected.",
	"Needs compliance check before posting.",
	"Timing is not right for this account group.",
];

function buildApprovalTimeline(
	approval: Approval,
	action: Record<string, unknown>,
) {
	const timeline = [
		{
			key: "requested",
			title: "Approval requested",
			detail:
				approval.context || "Agent submitted this exact action for review.",
			time: approval.created_at,
			tone: "neutral",
		},
		{
			key: "bound-intent",
			title: "Exact intent bound",
			detail: `Intent ${compactHash(action.intentId ?? action.intent_id)} · payload ${compactHash(action.payloadHash ?? action.actionHash ?? action.payload_hash)}`,
			time:
				action.intentCreatedAt ??
				action.intent_created_at ??
				approval.created_at,
			tone: "neutral",
		},
	];

	const previousApprovalId =
		action.previousApprovalId ?? action.previous_approval_id;
	const previousIntentId = action.previousIntentId ?? action.previous_intent_id;
	if (previousApprovalId || previousIntentId) {
		timeline.push({
			key: "revision",
			title: "Revised from earlier approval",
			detail: `Previous approval ${compactHash(previousApprovalId)} · previous intent ${compactHash(previousIntentId)}`,
			time: action.revisedAt ?? action.revised_at ?? approval.created_at,
			tone: "warning",
		});
	}

	const supersededBy =
		action.supersededByApprovalId ?? action.superseded_by_approval_id;
	if (supersededBy) {
		timeline.push({
			key: "superseded",
			title: "Superseded by revised request",
			detail: `Replacement approval ${compactHash(supersededBy)} now carries the editable payload.`,
			time: action.supersededAt ?? action.superseded_at,
			tone: "warning",
		});
	}

	if (approval.status !== "pending") {
		const decidedAt = action.decidedAt ?? action.decided_at;
		const note = stringValue(action.decisionNote ?? action.decision_note, "");
		timeline.push({
			key: "decision",
			title:
				approval.status === "approved"
					? "Approved"
					: approval.status === "rejected"
						? "Rejected"
						: approval.status,
			detail: note || "Reviewer decision recorded.",
			time: decidedAt,
			tone:
				approval.status === "approved"
					? "success"
					: approval.status === "rejected"
						? "danger"
						: "neutral",
		});
	}

	const dispatchStatus = stringValue(
		action.dispatchStatus ?? action.dispatch_status,
		"",
	);
	if (dispatchStatus) {
		timeline.push({
			key: "dispatch",
			title: `Dispatch ${dispatchStatus}`,
			detail: stringValue(
				action.dispatchMessage ??
					action.dispatch_message ??
					action.recoveryTaskId ??
					action.recovery_task_id,
				"Execution status recorded by the operator dispatcher.",
			),
			time: action.dispatchedAt ?? action.dispatched_at,
			tone:
				dispatchStatus === "failed"
					? "danger"
					: dispatchStatus === "consumed"
						? "success"
						: "warning",
		});
	}

	return timeline;
}

function timelineToneClass(tone: string) {
	if (tone === "danger") return "border-red-500/40 bg-red-500/5";
	if (tone === "success") return "border-emerald-500/40 bg-emerald-500/5";
	if (tone === "warning") return "border-amber-500/40 bg-amber-500/5";
	return "border-border/70 bg-background/40";
}

function ApprovalMetaRow({
	label,
	value,
	toneClass,
	mono,
}: {
	label: string;
	value: string;
	toneClass?: string | undefined;
	mono?: boolean | undefined;
}) {
	return (
		<div className="flex items-start justify-between gap-3 border-b border-border/60 pb-2 text-[0.703125rem] last:border-b-0 last:pb-0">
			<span className="text-muted-foreground">{label}</span>
			<span
				className={`text-right font-medium text-foreground ${toneClass ?? ""} ${mono ? "font-mono text-[0.6875rem]" : ""}`}
			>
				{value}
			</span>
		</div>
	);
}

export function ApprovalQueue() {
	const [searchParams, setSearchParams] = useSearchParams();
	const [approvals, setApprovals] = useState<Approval[]>([]);
	const [loading, setLoading] = useState(true);
	const [decidingId, setDecidingId] = useState<string | null>(null);
	const [statusFilter, setStatusFilter] = useState<
		"all" | "pending" | "approved" | "rejected" | "expired"
	>(
		(searchParams.get("status") as
			| "all"
			| "pending"
			| "approved"
			| "rejected"
			| "expired"
			| null) ?? "all",
	);
	const [riskFilter, setRiskFilter] = useState<
		"all" | "low" | "medium" | "high" | "critical"
	>("all");
	const [query, setQuery] = useState("");
	const [selectedId, setSelectedId] = useState<string | null>(() =>
		searchParams.get("approvalId"),
	);
	const [decisionNotes, setDecisionNotes] = useState<Record<string, string>>(
		{},
	);
	const [editingId, setEditingId] = useState<string | null>(null);
	const [revisionPayloads, setRevisionPayloads] = useState<
		Record<string, string>
	>({});
	const [revisingId, setRevisingId] = useState<string | null>(null);
	const [executingId, setExecutingId] = useState<string | null>(null);

	const pendingCount = useMemo(
		() => approvals.filter((approval) => approval.status === "pending").length,
		[approvals],
	);
	const statusCounts = useMemo(
		() => ({
			all: approvals.length,
			pending: approvals.filter((approval) => approval.status === "pending")
				.length,
			approved: approvals.filter((approval) => approval.status === "approved")
				.length,
			rejected: approvals.filter((approval) => approval.status === "rejected")
				.length,
			expired: approvals.filter((approval) => approval.status === "expired")
				.length,
		}),
		[approvals],
	);

	const filteredApprovals = useMemo(
		() =>
			approvals.filter((approval) => {
				const action = firstAction(approval);
				const riskLevel = stringValue(
					action.riskLevel ?? action.risk_level,
					approval.urgency || "medium",
				).toLowerCase();
				const haystack = [
					approval.id,
					approval.context,
					approval.status,
					action.actionName,
					action.toolName,
					action.intentId,
					action.intent_id,
					action.payloadHash,
					action.actionHash,
				]
					.join(" ")
					.toLowerCase();
				if (statusFilter !== "all" && approval.status !== statusFilter)
					return false;
				if (riskFilter !== "all" && riskLevel !== riskFilter) return false;
				if (query.trim() && !haystack.includes(query.trim().toLowerCase()))
					return false;
				return true;
			}),
		[approvals, query, riskFilter, statusFilter],
	);

	const loadApprovals = useCallback(async () => {
		setLoading(true);
		try {
			const data = await apiFetch(
				"/api/agent?action=approvals&status=all&limit=100",
				approvalsResponseSchema,
			);
			setApprovals(data.approvals);
		} catch {
			appToast.error("Could not load approval queue.");
		} finally {
			setLoading(false);
		}
	}, []);

	useEffect(() => {
		void loadApprovals();
	}, [loadApprovals]);

	function updateStatusFilter(next: typeof statusFilter) {
		setStatusFilter(next);
		const cleaned = new URLSearchParams(searchParams);
		if (next === "all") cleaned.delete("status");
		else cleaned.set("status", next);
		setSearchParams(cleaned, { replace: true });
	}

	function selectApproval(id: string) {
		setSelectedId(id);
		const cleaned = new URLSearchParams(searchParams);
		cleaned.set("approvalId", id);
		setSearchParams(cleaned, { replace: true });
	}

	async function copyActionSummary(approval: Approval) {
		const action = firstAction(approval);
		const summary = {
			approvalId: approval.id,
			intentId: action.intentId ?? action.intent_id,
			actionName: action.actionName ?? action.toolName ?? action.tool_name,
			riskLevel: action.riskLevel ?? action.risk_level ?? approval.urgency,
			payloadHash:
				action.payloadHash ?? action.actionHash ?? action.payload_hash,
			contentHash: action.contentHash ?? action.content_hash,
			idempotencyKey: action.idempotencyKey ?? action.idempotency_key,
			scope: action.scope ?? {
				workspaceId: action.workspaceId ?? action.workspace_id,
				groupId: action.groupId ?? action.group_id,
				accountId: action.accountId ?? action.account_id,
			},
		};
		await navigator.clipboard.writeText(JSON.stringify(summary, null, 2));
		appToast.success("Approval summary copied.");
	}

	async function decide(id: string, decision: "approved" | "rejected") {
		setDecidingId(id);
		try {
			await apiFetch("/api/agent?action=approvals", decideResponseSchema, {
				method: "PATCH",
				json: { id, decision, note: decisionNotes[id] || null },
			});
			appToast.success(
				decision === "approved" ? "Approval accepted." : "Approval rejected.",
			);
			await loadApprovals();
		} catch {
			appToast.error("Could not record decision.");
		} finally {
			setDecidingId(null);
		}
	}

	function startEditing(approval: Approval) {
		const action = firstAction(approval);
		const payload = normalizedPayload(action);
		setEditingId(approval.id);
		setRevisionPayloads((prev) => ({
			...prev,
			[approval.id]: prev[approval.id] ?? prettyPayload(payload),
		}));
		selectApproval(approval.id);
	}

	async function reviseApproval(approval: Approval) {
		const action = firstAction(approval);
		const intentId = stringValue(action.intentId ?? action.intent_id, "");
		const text =
			revisionPayloads[approval.id] || prettyPayload(normalizedPayload(action));
		let payload: unknown;
		try {
			payload = JSON.parse(text);
		} catch {
			appToast.error("Revision payload must be valid JSON.");
			return;
		}
		if (!intentId) {
			appToast.error("This approval is missing its bound intent.");
			return;
		}
		setRevisingId(approval.id);
		try {
			const data = await apiFetch(
				"/api/operator?action=revise-approval",
				reviseResponseSchema,
				{
					method: "POST",
					json: {
						approval_id: approval.id,
						intent_id: intentId,
						payload,
						note: decisionNotes[approval.id] || null,
					},
				},
			);
			setEditingId(null);
			setSelectedId(data.approvalId);
			const cleaned = new URLSearchParams(searchParams);
			cleaned.set("approvalId", data.approvalId);
			setSearchParams(cleaned, { replace: true });
			appToast.success("Revised approval created.");
			await loadApprovals();
		} catch {
			appToast.error("Could not create revised approval.");
		} finally {
			setRevisingId(null);
		}
	}

	async function executeApproval(approval: Approval) {
		const action = firstAction(approval);
		const intentId = stringValue(action.intentId ?? action.intent_id, "");
		if (!intentId) {
			appToast.error("This approval is missing its bound intent.");
			return;
		}
		setExecutingId(approval.id);
		try {
			const data = await apiFetch(
				"/api/operator?action=execute",
				executeResponseSchema,
				{
					method: "POST",
					json: {
						approval_id: approval.id,
						intent_id: intentId,
					},
				},
			);
			appToast.success(data.message || "Approved action executed.");
			await loadApprovals();
		} catch (error) {
			appToast.error("Could not execute approved action.", {
				description: error instanceof Error ? error.message : undefined,
			});
			await loadApprovals();
		} finally {
			setExecutingId(null);
		}
	}

	function updateStructuredField(
		approvalId: string,
		field: EditablePayloadField,
		value: string,
	) {
		setRevisionPayloads((prev) => {
			const currentText = prev[approvalId] ?? "{}";
			const currentPayload = parsePayloadText(currentText);
			if (!currentPayload) return prev;
			return {
				...prev,
				[approvalId]: prettyPayload(
					updatePayloadField(currentPayload, field, value),
				),
			};
		});
	}

	return (
		<NovaScreen width="wide" density="compact">
			<NovaHeader
				eyebrow="Agent control"
				title="Approval Queue"
				meta={`${pendingCount} pending`}
				description="Review and approve AI-generated requests before they become live actions."
				filters={
					<span className="inline-flex items-center gap-1.5">
						<span className="h-1.5 w-1.5 rounded-full bg-[color:var(--color-oxblood)]" />
						{filteredApprovals.length} visible
					</span>
				}
				actions={
					<Button
						type="button"
						variant="outline"
						size="sm"
						onClick={() => void loadApprovals()}
						disabled={loading}
					>
						<RefreshCw
							className={loading ? "h-4 w-4 animate-spin" : "h-4 w-4"}
						/>
						Refresh
					</Button>
				}
			/>

			<NovaCard className="mb-3" contentClassName="p-3 md:p-4">
				<div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
					<ToggleGroup
						type="single"
						aria-label="Approval status"
						value={statusFilter}
						onValueChange={(value) => {
							if (value) updateStatusFilter(value as typeof statusFilter);
						}}
						className="scrollbar-hide"
					>
						{(
							[
								["all", "Queue"],
								["pending", "Pending"],
								["approved", "Approved"],
								["rejected", "Rejected"],
								["expired", "Expired"],
							] as const
						).map(([value, label]) => {
							const active = statusFilter === value;
							return (
								<ToggleGroupItem key={value} value={value} sizeVariant="md">
									<span className="inline-flex items-center gap-2">
										{label}
										<span
											className={`rounded-full px-1.5 py-0.5 text-[0.65625rem] tabular-nums ${active ? "bg-background/15" : "bg-muted text-muted-foreground"}`}
										>
											{statusCounts[value]}
										</span>
									</span>
								</ToggleGroupItem>
							);
						})}
					</ToggleGroup>
					<div className="flex flex-1 flex-col gap-2 md:flex-row xl:max-w-3xl">
						<label htmlFor="approval-queue-search" className="flex-1">
							<span className="sr-only">Search approval requests</span>
							<Input
								id="approval-queue-search"
								value={query}
								onChange={(event) => setQuery(event.target.value)}
								placeholder="Search action, intent, hash, or approval context"
								sizeVariant="lg"
								leadingIcon={<Search className="h-4 w-4" />}
							/>
						</label>
						<div className="flex items-center gap-2">
							<span className="hidden h-10 items-center rounded-md border border-border bg-background px-3 text-muted-foreground md:inline-flex">
								<Filter className="h-4 w-4" />
							</span>
							<Select
								value={riskFilter}
								onChange={(event) =>
									setRiskFilter(event.target.value as typeof riskFilter)
								}
								sizeVariant="lg"
								options={[
									{ value: "all", label: "All risk" },
									{ value: "critical", label: "Critical" },
									{ value: "high", label: "High" },
									{ value: "medium", label: "Medium" },
									{ value: "low", label: "Low" },
								]}
							/>
						</div>
					</div>
				</div>
			</NovaCard>

			<NovaSection className="grid gap-3">
				{loading ? (
					<NovaCard role="status" aria-label="Loading approval requests">
						<div className="flex flex-col gap-3">
							<Skeleton className="h-4 w-48 rounded-full" />
							<Skeleton className="h-16 w-full rounded-lg" />
							<Skeleton className="h-9 w-36 rounded-md" />
						</div>
					</NovaCard>
				) : approvals.length === 0 ? (
					<NovaEmpty
						icon={<Check data-icon aria-hidden="true" />}
						title="No approval requests"
						description="When Codex or autopilot asks to do something risky, it will appear here first."
					/>
				) : filteredApprovals.length === 0 ? (
					<NovaEmpty
						icon={<Filter data-icon aria-hidden="true" />}
						title="No matching approvals"
						description="No approval requests match the current filters."
					/>
				) : (
					filteredApprovals.map((approval) => {
						const action = firstAction(approval);
						const actionName = stringValue(
							action.actionName ?? action.toolName ?? action.tool_name,
							"Agent action",
						);
						const riskLevel = stringValue(
							action.riskLevel ?? action.risk_level,
							approval.urgency || "medium",
						);
						const selected = selectedId === approval.id;
						const payload = normalizedPayload(action);
						const editing = editingId === approval.id;
						const revisionText =
							revisionPayloads[approval.id] ?? prettyPayload(payload);
						const parsedRevisionPayload = parsePayloadText(revisionText);
						const payloadDiff = diffPayload(
							payload as Record<string, unknown>,
							revisionText,
						);
						const editableFields = getEditablePayloadFields(
							actionName,
							payload as Record<string, unknown>,
						);
						const timeline = buildApprovalTimeline(approval, action);
						const dispatchStatus = stringValue(
							action.dispatchStatus ?? action.dispatch_status,
							"",
						);
						const dispatchMessage = stringValue(
							action.dispatchMessage ?? action.dispatch_message,
							dispatchStatus === "failed"
								? "The approved action failed during dispatch."
								: "",
						);
						const recoveryTaskId = stringValue(
							action.recoveryTaskId ?? action.recovery_task_id,
							"",
						);
						const actorLabel = stringValue(
							action.requestedBy ??
								action.requested_by ??
								action.createdBy ??
								action.created_by,
							"AI Agent",
						);
						const modelLabel = stringValue(
							action.model ?? action.modelName ?? action.model_name,
							"Operator agent",
						);
						const requestPreview = payloadPreview(
							payload as Record<string, unknown>,
							actionName,
						);
						return (
							<NovaCard
								key={approval.id}
								className={selected ? "ring-2 ring-primary/45" : undefined}
								contentClassName="p-0"
								onClick={() => selectApproval(approval.id)}
							>
								<div className="grid gap-0 lg:grid-cols-[minmax(0,1fr)_230px] xl:grid-cols-[minmax(0,1fr)_260px]">
									<div className="min-w-0 p-3 md:p-4">
										<div className="flex items-start gap-3">
											<div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[color-mix(in_srgb,var(--color-oxblood)_14%,transparent)] text-[0.75rem] font-semibold text-[color:var(--color-oxblood)]">
												{String(approval.context || actionName)
													.trim()
													.charAt(0)
													.toUpperCase() || "A"}
											</div>
											<div className="min-w-0 flex-1">
												<div className="flex flex-wrap items-center gap-2 text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
													<span className={riskTone(riskLevel)}>
														{riskLevel}
													</span>
													<span className="text-muted-foreground">•</span>
													<span>{approval.status}</span>
													{approval.expires_at ? (
														<>
															<span className="text-muted-foreground">•</span>
															<span className="inline-flex items-center gap-1">
																<Clock3 className="h-3 w-3" />
																{new Date(approval.expires_at).toLocaleString()}
															</span>
														</>
													) : null}
												</div>
												<h2 className="mt-1 line-clamp-2 text-[0.9375rem] font-semibold leading-[1.35] text-foreground">
													{approval.context || "Agent approval request"}
												</h2>
												<div className="mt-1.5 flex flex-wrap items-center gap-2 text-[0.6875rem] text-muted-foreground">
													<span className="inline-flex items-center gap-1">
														<ShieldCheck className="h-3.5 w-3.5" />
														Exact action approval
													</span>
													<span>
														Intent{" "}
														{compactHash(action.intentId ?? action.intent_id)}
													</span>
													<span>
														Payload{" "}
														{compactHash(
															action.payloadHash ??
																action.actionHash ??
																action.payload_hash,
														)}
													</span>
												</div>
											</div>
										</div>

										<div className="mt-3 grid gap-3 md:grid-cols-2">
											<section className="rounded-md border border-border/70 bg-background/45 p-3">
												<div className="text-[0.625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
													Original
												</div>
												<p className="mt-2 line-clamp-4 text-[0.78125rem] leading-[1.48] text-muted-foreground">
													{approval.context ||
														"Agent submitted this exact action for review."}
												</p>
												<div className="mt-2 grid gap-1.5 text-[0.71875rem]">
													<ApprovalMetaRow label="Action" value={actionName} />
													<ApprovalMetaRow
														label="Scope"
														value={scopeLabel(action)}
													/>
												</div>
											</section>
											<section className="rounded-md border border-[color-mix(in_srgb,var(--color-health-good)_32%,transparent)] bg-[color-mix(in_srgb,var(--color-health-good)_11%,transparent)] p-3">
												<div className="text-[0.625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
													Exact action preview
												</div>
												<p className="mt-2 line-clamp-4 text-[0.78125rem] leading-[1.48] text-muted-foreground">
													{requestPreview}
												</p>
												<div className="mt-2 grid gap-1.5 text-[0.71875rem]">
													<ApprovalMetaRow label="Action" value={actionName} />
													<ApprovalMetaRow
														label="Content hash"
														value={compactHash(
															action.contentHash ?? action.content_hash,
														)}
														mono
													/>
												</div>
											</section>
										</div>

										<div className="mt-2.5 flex flex-wrap items-center justify-between gap-2 text-[0.6875rem] text-muted-foreground">
											<span>Changes highlighted</span>
											<span>
												Confidence{" "}
												{riskLevel.toLowerCase() === "low"
													? "92%"
													: riskLevel.toLowerCase() === "medium"
														? "84%"
														: "71%"}
											</span>
										</div>

										{dispatchStatus === "failed" ? (
											<div className="mt-3 rounded-md border border-red-500/35 bg-red-500/5 p-3">
												<div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
													<div>
														<div className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-red-500">
															<AlertTriangle className="h-3.5 w-3.5" />
															Dispatch failed
														</div>
														<p className="mt-1 text-sm text-muted-foreground">
															{dispatchMessage}
														</p>
														{recoveryTaskId ? (
															<p className="mt-1 font-mono text-xs text-muted-foreground">
																Recovery task {recoveryTaskId}
															</p>
														) : null}
													</div>
													<div className="flex flex-wrap gap-2">
														<Button asChild variant="outline" size="sm">
															<a
																href={
																	recoveryTaskId
																		? `/dashboard?task=${encodeURIComponent(recoveryTaskId)}`
																		: "/dashboard"
																}
																onClick={(event) => event.stopPropagation()}
															>
																Open recovery
															</a>
														</Button>
														<Button asChild variant="outline" size="sm">
															<a
																href={`/approval-queue?status=pending&approvalId=${encodeURIComponent(approval.id)}`}
																onClick={(event) => event.stopPropagation()}
															>
																Review intent
															</a>
														</Button>
													</div>
												</div>
											</div>
										) : null}

										<details
											className="mt-2.5 rounded-md border border-border/70 bg-background/35 p-3"
											onClick={(event) => event.stopPropagation()}
										>
											<summary className="cursor-pointer text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
												Approval history, payload, and revision tools
											</summary>
											<pre className="mt-3 max-h-36 overflow-auto rounded border border-border/60 bg-background/40 p-2 text-[0.6875rem] text-muted-foreground">
												{JSON.stringify(payload, null, 2)}
											</pre>
											<div className="mt-3 grid gap-2">
												{timeline.map((event) => (
													<div
														key={event.key}
														className={`grid gap-2 rounded-md border p-3 text-xs md:grid-cols-[160px_1fr] ${timelineToneClass(event.tone)}`}
													>
														<div>
															<div className="font-semibold text-foreground">
																{event.title}
															</div>
															<div className="mt-1 text-muted-foreground">
																{formatEventTime(event.time)}
															</div>
														</div>
														<div className="text-muted-foreground">
															{event.detail}
														</div>
													</div>
												))}
											</div>
											{approval.status === "pending" ? (
												<div className="mt-3 flex flex-col gap-3">
													<div className="flex flex-wrap gap-2">
														{rejectionTemplates.map((template) => (
															<Button
																key={template}
																type="button"
																variant="outline"
																size="sm"
																className="h-7 text-xs"
																onClick={() =>
																	setDecisionNotes((prev) => ({
																		...prev,
																		[approval.id]: template,
																	}))
																}
															>
																{template}
															</Button>
														))}
													</div>
													<Textarea
														value={decisionNotes[approval.id] || ""}
														onChange={(event) =>
															setDecisionNotes((prev) => ({
																...prev,
																[approval.id]: event.target.value,
															}))
														}
														placeholder="Optional approval/rejection/revision note"
														className="min-h-20"
													/>
													{editing ? (
														<div className="rounded-md border border-border/70 bg-background/40 p-3">
															<div className="mb-2 flex items-center justify-between gap-3">
																<div className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
																	<GitCompare className="h-3.5 w-3.5" />
																	Edit and resubmit
																</div>
																<span
																	className={
																		payloadDiff === null
																			? "text-xs text-red-500"
																			: "text-xs text-muted-foreground"
																	}
																>
																	{payloadDiff === null
																		? "Invalid JSON"
																		: `${payloadDiff.length} field${payloadDiff.length === 1 ? "" : "s"} changed`}
																</span>
															</div>
															{editableFields.length > 0 ? (
																<div className="mb-3 rounded-md border border-border/70 bg-background/50 p-3">
																	<div className="mb-3 inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
																		<SlidersHorizontal className="h-3.5 w-3.5" />
																		Structured editor
																	</div>
																	<div className="grid gap-3 md:grid-cols-2">
																		{editableFields.map((field) => {
																			const fieldValue = editableValue(
																				parsedRevisionPayload,
																				field,
																			);
																			const inputId = `${approval.id}-${field.key}-field`;
																			const commonProps = {
																				id: inputId,
																				value: fieldValue,
																				onChange: (
																					event: ChangeEvent<
																						| HTMLInputElement
																						| HTMLTextAreaElement
																						| HTMLSelectElement
																					>,
																				) =>
																					updateStructuredField(
																						approval.id,
																						field,
																						event.target.value,
																					),
																				disabled: !parsedRevisionPayload,
																			};
																			return (
																				<label
																					key={field.key}
																					htmlFor={inputId}
																					className={
																						field.kind === "textarea" ||
																						field.kind === "url-list"
																							? "grid gap-1 md:col-span-2"
																							: "grid gap-1"
																					}
																				>
																					<span className="text-xs font-medium text-muted-foreground">
																						{field.label}
																					</span>
																					{field.kind === "textarea" ||
																					field.kind === "url-list" ? (
																						<Textarea
																							{...commonProps}
																							placeholder={field.placeholder}
																							className="min-h-20"
																						/>
																					) : field.kind === "select" ? (
																						<Select {...commonProps}>
																							{field.options?.map((option) => (
																								<option
																									key={option.value}
																									value={option.value}
																								>
																									{option.label}
																								</option>
																							))}
																						</Select>
																					) : (
																						<Input
																							{...commonProps}
																							type={
																								field.kind === "datetime"
																									? "datetime-local"
																									: "text"
																							}
																							placeholder={field.placeholder}
																						/>
																					)}
																					{field.help ? (
																						<span className="text-[11px] text-muted-foreground">
																							{field.help}
																						</span>
																					) : null}
																				</label>
																			);
																		})}
																	</div>
																</div>
															) : null}
															<Textarea
																value={revisionText}
																onChange={(event) =>
																	setRevisionPayloads((prev) => ({
																		...prev,
																		[approval.id]: event.target.value,
																	}))
																}
																className="min-h-52 font-mono text-xs"
																spellCheck={false}
															/>
															<div className="mt-3 flex flex-wrap justify-end gap-2">
																<Button
																	type="button"
																	variant="outline"
																	size="sm"
																	onClick={() => setEditingId(null)}
																>
																	Cancel edit
																</Button>
																<Button
																	type="button"
																	size="sm"
																	onClick={() => void reviseApproval(approval)}
																	disabled={
																		revisingId === approval.id ||
																		payloadDiff === null
																	}
																>
																	<PencilLine className="h-4 w-4" />
																	Resubmit revised
																</Button>
															</div>
														</div>
													) : null}
												</div>
											) : null}
										</details>
									</div>
									{approval.status === "pending" ? (
										<aside className="flex shrink-0 flex-col gap-3 border-t border-border bg-[color-mix(in_srgb,var(--color-card)_82%,transparent)] p-3 md:p-4 lg:border-l lg:border-t-0">
											<div className="text-[0.59375rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
												Metadata
											</div>
											<ApprovalMetaRow
												label="Account"
												value={scopeLabel(action)}
											/>
											<ApprovalMetaRow label="Model" value={modelLabel} />
											<ApprovalMetaRow
												label="Created"
												value={formatEventTime(approval.created_at)}
											/>
											<ApprovalMetaRow label="By" value={actorLabel} />
											<div className="mt-1 grid gap-2">
												<Button
													type="button"
													variant="outline"
													size="sm"
													onClick={(event) => {
														event.stopPropagation();
														startEditing(approval);
													}}
												>
													<PencilLine className="h-4 w-4" />
													Edit
												</Button>
												<Button
													type="button"
													variant="outline"
													size="sm"
													onClick={(event) => {
														event.stopPropagation();
														void copyActionSummary(approval);
													}}
												>
													<Copy className="h-4 w-4" />
													Copy
												</Button>
												<Button
													type="button"
													variant="outline"
													size="sm"
													className="border-red-500/30 text-red-500 hover:bg-red-500/10"
													onClick={(event) => {
														event.stopPropagation();
														void decide(approval.id, "rejected");
													}}
													disabled={decidingId === approval.id}
												>
													<X className="h-4 w-4" />
													Reject
												</Button>
												<Button
													type="button"
													size="sm"
													onClick={(event) => {
														event.stopPropagation();
														void decide(approval.id, "approved");
													}}
													disabled={decidingId === approval.id}
												>
													<Check className="h-4 w-4" />
													Approve
												</Button>
											</div>
										</aside>
									) : approval.status === "approved" ? (
										<aside className="flex shrink-0 flex-col gap-3 border-t border-border bg-[color-mix(in_srgb,var(--color-card)_82%,transparent)] p-3 md:p-4 lg:border-l lg:border-t-0">
											<div className="text-[0.59375rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
												Metadata
											</div>
											<ApprovalMetaRow
												label="Account"
												value={scopeLabel(action)}
											/>
											<ApprovalMetaRow label="Model" value={modelLabel} />
											<ApprovalMetaRow
												label="Created"
												value={formatEventTime(approval.created_at)}
											/>
											<ApprovalMetaRow label="By" value={actorLabel} />
											<div className="mt-1 grid gap-2">
												<Button
													type="button"
													variant="outline"
													size="sm"
													onClick={(event) => {
														event.stopPropagation();
														void copyActionSummary(approval);
													}}
												>
													<Copy className="h-4 w-4" />
													Copy
												</Button>
												<Button
													type="button"
													size="sm"
													onClick={(event) => {
														event.stopPropagation();
														void executeApproval(approval);
													}}
													disabled={
														executingId === approval.id ||
														dispatchStatus === "consumed"
													}
												>
													<ShieldCheck className="h-4 w-4" />
													{dispatchStatus === "consumed"
														? "Executed"
														: "Execute"}
												</Button>
											</div>
										</aside>
									) : (
										<aside className="flex shrink-0 flex-col gap-3 border-t border-border bg-[color-mix(in_srgb,var(--color-card)_82%,transparent)] p-3 md:p-4 lg:border-l lg:border-t-0">
											<div className="text-[0.59375rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
												Metadata
											</div>
											<ApprovalMetaRow
												label="Account"
												value={scopeLabel(action)}
											/>
											<ApprovalMetaRow label="Model" value={modelLabel} />
											<ApprovalMetaRow
												label="Created"
												value={formatEventTime(approval.created_at)}
											/>
											<ApprovalMetaRow label="By" value={actorLabel} />
											<div className="mt-1 inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 text-sm text-muted-foreground">
												<AlertTriangle className="h-4 w-4" />
												Already decided
											</div>
										</aside>
									)}
								</div>
							</NovaCard>
						);
					})
				)}
			</NovaSection>
		</NovaScreen>
	);
}
