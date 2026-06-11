import type React from "react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
	Activity,
	ArrowUpRight,
	Bell,
	CheckCircle2,
	Eye,
	Lightbulb,
	MessageSquareText,
	NotebookPen,
	Plus,
	Radio,
	Radar,
	Search,
	Target,
	TrendingUp,
} from "lucide-react";
import { NovaScreen } from "@/components/layout/NovaScreen";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import {
	NovaDataPanel,
	NovaEmpty,
	NovaHeader,
	NovaSection,
	NovaStat,
	NovaToolbar,
} from "@/components/ui/NovaPrimitives";
import { Select } from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import { useAuthUser } from "@/hooks/useAuthUser";
import { useAccountGroups, type AccountGroup } from "@/hooks/useAccountGroups";
import { useCompetitorSurprises } from "@/hooks/useCompetitorSurprises";
import { useUnifiedInbox } from "@/hooks/useUnifiedInbox";
import { getApiAuthHeaders } from "@/lib/apiAuth";
import { apiUrl } from "@/lib/apiUrl";
import { queryClient } from "@/lib/queryClient";
import { queryKeys } from "@/lib/queryKeys";
import { appToast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { randomUUID } from "@/lib/uuid";
import { supabase } from "@/services/supabase";
import {
	getUserSetting,
	upsertUserSetting,
} from "@/services/userSettingsService";
import { useWorkspaceStore } from "@/stores/useWorkspaceStore";
import type { Conversation } from "@/components/inbox/types";

interface ListeningAlert {
	id: string;
	keyword: string;
	alert_type: string;
	threshold_value: number | null;
	is_active: boolean | null;
	last_checked_at: string | null;
	last_triggered_at: string | null;
	created_at: string | null;
}

interface ListeningResult {
	id: string;
	keyword: string;
	result_count: number;
	source: string;
	checked_at: string | null;
	sentiment_breakdown: unknown;
}

interface CompetitorRow {
	id: string;
	username: string;
	display_name: string | null;
	avatar_url: string | null;
	follower_count: number | null;
	engagement_rate: number | null;
	platform: string | null;
	last_synced_at: string | null;
	sync_status: string | null;
}

interface CompetitorPostRow {
	id: string;
	competitor_id: string;
	competitor_username: string | null;
	content: string | null;
	engagement_score: number | null;
	like_count: number | null;
	reply_count: number | null;
	repost_count: number | null;
	view_count: number | null;
	permalink: string | null;
	platform: string | null;
	published_at: string | null;
	topic_tag: string | null;
}

interface TrendKeywordRow {
	id: string;
	keyword: string;
	category: string | null;
	is_active: boolean | null;
	post_count: number | null;
	total_engagement: number | null;
	last_synced_at: string | null;
}

interface TrendPostRow {
	id: string;
	keyword_id: string;
	content: string | null;
	username: string;
	engagement_score: number | null;
	like_count: number | null;
	reply_count: number | null;
	repost_count: number | null;
	view_count: number | null;
	permalink: string | null;
	posted_at: string | null;
}

interface ListeningSnapshot {
	alerts: ListeningAlert[];
	results: ListeningResult[];
	competitors: CompetitorRow[];
	competitorPosts: CompetitorPostRow[];
	trendKeywords: TrendKeywordRow[];
	trendPosts: TrendPostRow[];
}

type ListeningWorkflowSource =
	| "competitor_signal"
	| "trend_signal"
	| "listening_signal";
type WorkflowStatus = "resolved" | "ignored" | "snoozed";

const IDEAS_BOARD_PREFIX = "juno33:ideas-board";
const LISTENING_WORKFLOW_PREFIX = "juno33:listening-workflows";
const IDEAS_REMOTE_SETTING_KEY = "ideas_board_v1";
const LISTENING_REMOTE_SETTING_KEY = "listening_workflow_v1";
const INBOX_REPLY_DRAFT_KEY = "juno33:inbox-reply-draft";

function ideasBoardKey(userId: string | null): string {
	return `${IDEAS_BOARD_PREFIX}:${userId ?? "anon"}`;
}

function listeningWorkflowKey(userId: string | null): string {
	return `${LISTENING_WORKFLOW_PREFIX}:${userId ?? "anon"}`;
}

function normalizeHandledIds(value: unknown): Set<string> {
	if (!value || typeof value !== "object") return new Set();
	const handledIds = (value as { handledIds?: unknown }).handledIds;
	return new Set(
		Array.isArray(handledIds)
			? handledIds.filter((item): item is string => typeof item === "string")
			: [],
	);
}

function normalizeIdeasSetting(value: unknown): unknown[] {
	if (!value || typeof value !== "object") return [];
	const ideas = (value as { ideas?: unknown }).ideas;
	return Array.isArray(ideas) ? ideas : [];
}

function formatNumber(value: number | null | undefined): string {
	const n = value ?? 0;
	if (n >= 1_000_000)
		return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
	if (n >= 1_000) return `${(n / 1_000).toFixed(1).replace(/\.0$/, "")}K`;
	return String(n);
}

function formatDate(value: string | null | undefined): string {
	if (!value) return "Not yet";
	const time = new Date(value).getTime();
	if (!Number.isFinite(time)) return "Recently";
	const diff = Date.now() - time;
	const minutes = Math.max(1, Math.round(diff / 60_000));
	if (minutes < 60) return `${minutes}m ago`;
	const hours = Math.round(minutes / 60);
	if (hours < 24) return `${hours}h ago`;
	return `${Math.round(hours / 24)}d ago`;
}

function sentimentLabel(value: unknown): string {
	if (!value || typeof value !== "object") return "No sentiment";
	const record = value as Record<string, unknown>;
	const entries = Object.entries(record)
		.map(
			([key, count]) =>
				[key, typeof count === "number" ? count : Number(count)] as const,
		)
		.filter(([, count]) => Number.isFinite(count) && count > 0)
		.sort((a, b) => b[1] - a[1]);
	if (entries.length === 0) return "No sentiment";
	return entries
		.slice(0, 2)
		.map(([key, count]) => `${key} ${count}`)
		.join(" · ");
}

async function fetchAlerts(
	workspaceId: string | null,
): Promise<ListeningAlert[]> {
	const params = new URLSearchParams({ action: "alerts" });
	if (workspaceId) params.set("workspace_id", workspaceId);
	const response = await fetch(apiUrl(`/api/listening?${params}`), {
		headers: await getApiAuthHeaders(),
	});
	if (!response.ok) throw new Error("Failed to load listening alerts");
	const data = (await response.json()) as { alerts?: ListeningAlert[] };
	return data.alerts ?? [];
}

async function fetchSnapshot(
	workspaceId: string | null,
): Promise<ListeningSnapshot> {
	const user = (await supabase.auth.getUser()).data.user;
	if (!user) {
		return {
			alerts: [],
			results: [],
			competitors: [],
			competitorPosts: [],
			trendKeywords: [],
			trendPosts: [],
		};
	}

	const alerts = await fetchAlerts(workspaceId);
	const keywordIdsPromise = supabase
		.from("trend_keywords")
		.select(
			"id, keyword, category, is_active, post_count, total_engagement, last_synced_at",
		)
		.eq("user_id", user.id)
		.order("total_engagement", { ascending: false })
		.limit(50);

	const [resultsRes, competitorsRes, competitorPostsRes, keywordsRes] =
		await Promise.all([
			supabase
				.from("listening_results")
				.select(
					"id, keyword, result_count, source, checked_at, sentiment_breakdown",
				)
				.eq("workspace_id", workspaceId ?? "")
				.order("checked_at", { ascending: false })
				.limit(20),
			supabase
				.from("competitors")
				.select(
					"id, username, display_name, avatar_url, follower_count, engagement_rate, platform, last_synced_at, sync_status",
				)
				.eq("user_id", user.id)
				.order("last_synced_at", { ascending: false })
				.limit(80),
			supabase
				.from("competitor_top_posts")
				.select(
					"id, competitor_id, competitor_username, content, engagement_score, like_count, reply_count, repost_count, view_count, permalink, platform, published_at, topic_tag",
				)
				.eq("user_id", user.id)
				.order("engagement_score", { ascending: false })
				.limit(18),
			keywordIdsPromise,
		]);

	const trendKeywordIds = (keywordsRes.data ?? []).map((keyword) => keyword.id);
	const trendPostsRes =
		trendKeywordIds.length > 0
			? await supabase
					.from("trend_posts")
					.select(
						"id, keyword_id, content, username, engagement_score, like_count, reply_count, repost_count, view_count, permalink, posted_at",
					)
					.eq("user_id", user.id)
					.in("keyword_id", trendKeywordIds)
					.order("engagement_score", { ascending: false })
					.limit(18)
			: { data: [], error: null };

	if (resultsRes.error) throw resultsRes.error;
	if (competitorsRes.error) throw competitorsRes.error;
	if (competitorPostsRes.error) throw competitorPostsRes.error;
	if (keywordsRes.error) throw keywordsRes.error;
	if (trendPostsRes.error) throw trendPostsRes.error;

	return {
		alerts,
		results: (resultsRes.data ?? []) as ListeningResult[],
		competitors: (competitorsRes.data ?? []) as CompetitorRow[],
		competitorPosts: (competitorPostsRes.data ?? []) as CompetitorPostRow[],
		trendKeywords: (keywordsRes.data ?? []) as TrendKeywordRow[],
		trendPosts: (trendPostsRes.data ?? []) as TrendPostRow[],
	};
}

async function createWatchTerm(input: {
	keyword: string;
	workspaceId: string | null;
	threshold: number;
}) {
	const keyword = input.keyword.trim();
	if (!keyword) throw new Error("Keyword required");

	const headers = await getApiAuthHeaders();
	const response = await fetch(apiUrl("/api/listening?action=alerts"), {
		method: "POST",
		headers: { ...headers, "Content-Type": "application/json" },
		body: JSON.stringify({
			keyword,
			alert_type: "spike",
			threshold_value: input.threshold,
			workspace_id: input.workspaceId ?? undefined,
		}),
	});
	if (!response.ok) {
		const body = (await response.json().catch(() => null)) as {
			error?: string;
		} | null;
		throw new Error(body?.error || "Failed to create listening alert");
	}

	const user = (await supabase.auth.getUser()).data.user;
	if (user) {
		const { error } = await supabase.from("trend_keywords").insert({
			user_id: user.id,
			keyword: keyword.toLowerCase(),
			category: "listening",
			is_active: true,
		});
		if (error && error.code !== "23505") throw error;
	}
}

async function runListeningScan(workspaceId: string | null): Promise<number> {
	const headers = await getApiAuthHeaders();
	const response = await fetch(apiUrl("/api/listening?action=monitor"), {
		method: "POST",
		headers: { ...headers, "Content-Type": "application/json" },
		body: JSON.stringify({
			workspace_id: workspaceId ?? undefined,
		}),
	});
	if (!response.ok) {
		const body = (await response.json().catch(() => null)) as {
			error?: string;
		} | null;
		throw new Error(body?.error || "Failed to run listening scan");
	}
	const data = (await response.json()) as { processed?: number };
	return data.processed ?? 0;
}

async function addSignalToIdeas({
	userId,
	title,
	body,
	linkUrl,
	accountId,
	groupId,
}: {
	userId: string | null;
	title: string;
	body: string;
	linkUrl?: string | null | undefined;
	accountId?: string | null | undefined;
	groupId?: string | null | undefined;
}) {
	const now = new Date().toISOString();
	const idea = {
		id: randomUUID(),
		title: title.slice(0, 72),
		body,
		linkUrl: linkUrl ?? null,
		imageUrl: null,
		audioUrl: null,
		transcript: null,
		status: "inbox",
		accountId: accountId ?? null,
		groupId: groupId ?? null,
		source: "rough",
		variants: [],
		createdAt: now,
		updatedAt: now,
	};
	const key = ideasBoardKey(userId);
	const raw = window.localStorage.getItem(key);
	const existing = raw ? JSON.parse(raw) : [];
	const next = Array.isArray(existing) ? [idea, ...existing] : [idea];
	window.localStorage.setItem(key, JSON.stringify(next));
	if (userId) {
		try {
			const remote = await getUserSetting(userId, IDEAS_REMOTE_SETTING_KEY);
			const remoteIdeas = normalizeIdeasSetting(remote);
			await upsertUserSetting(userId, IDEAS_REMOTE_SETTING_KEY, {
				ideas: [
					idea,
					...remoteIdeas.filter((item) => {
						if (!item || typeof item !== "object") return true;
						const id = (item as { id?: unknown }).id;
						return id !== idea.id;
					}),
				],
				updatedAt: now,
			});
		} catch {
			/* local ideas board remains the offline source until sync recovers */
		}
	}
	appToast.success("Added to Ideas", {
		description: "Listening signal captured.",
	});
}

function readHandledSignals(key: string): Set<string> {
	try {
		const raw = window.localStorage.getItem(key);
		const parsed = raw ? JSON.parse(raw) : null;
		return new Set(
			Array.isArray(parsed?.handledIds)
				? parsed.handledIds.filter(
						(value: unknown): value is string => typeof value === "string",
					)
				: [],
		);
	} catch {
		return new Set();
	}
}

function writeHandledSignals(key: string, handledIds: Set<string>) {
	window.localStorage.setItem(
		key,
		JSON.stringify({ handledIds: [...handledIds].slice(-500) }),
	);
}

function localIdForWorkflowTask(
	source: string | null | undefined,
	sourceId: string | null | undefined,
): string | null {
	if (!source || !sourceId) return null;
	if (source === "competitor_signal") return `competitor:${sourceId}`;
	if (source === "trend_signal") return `trend:${sourceId}`;
	if (source === "listening_signal") return `listening:${sourceId}`;
	return null;
}

async function fetchDurableListeningWorkflowIds(): Promise<Set<string>> {
	const response = await fetch(
		apiUrl("/api/operator?action=tasks&status=all&limit=100"),
		{
			headers: await getApiAuthHeaders(),
		},
	);
	if (!response.ok) return new Set();
	const body = (await response.json().catch(() => null)) as {
		tasks?: Array<{
			source?: string | null;
			source_id?: string | null;
			status?: string | null;
			snoozed_until?: string | null;
		}>;
	} | null;
	const hidden = new Set<string>();
	const now = Date.now();
	for (const task of body?.tasks ?? []) {
		const localId = localIdForWorkflowTask(task.source, task.source_id);
		if (!localId) continue;
		if (task.status === "resolved" || task.status === "ignored") {
			hidden.add(localId);
			continue;
		}
		if (task.status === "snoozed") {
			const snoozedUntil = task.snoozed_until
				? Date.parse(task.snoozed_until)
				: Number.NaN;
			if (Number.isFinite(snoozedUntil) && snoozedUntil > now)
				hidden.add(localId);
		}
	}
	return hidden;
}

async function updateDurableListeningWorkflow(input: {
	source: ListeningWorkflowSource;
	sourceId: string;
	status: WorkflowStatus;
	title: string;
	groupId?: string | null | undefined;
	snoozedUntil?: string | null;
	resolutionReason?: string | null;
	payload?: unknown;
}) {
	const response = await fetch(apiUrl("/api/operator?action=source-workflow"), {
		method: "PATCH",
		headers: {
			...(await getApiAuthHeaders()),
			"Content-Type": "application/json",
		},
		body: JSON.stringify({
			source: input.source,
			source_id: input.sourceId,
			status: input.status,
			title: input.title,
			group_id: input.groupId ?? null,
			snoozed_until: input.snoozedUntil ?? null,
			resolution_reason: input.resolutionReason ?? null,
			payload: input.payload ?? {},
		}),
	});
	if (!response.ok) {
		const body = (await response.json().catch(() => null)) as {
			error?: string;
		} | null;
		throw new Error(body?.error || "Failed to update workflow state");
	}
}

function inboxMessageIdFromConversation(conversationId: string): string {
	if (conversationId.startsWith("tm-"))
		return `threads_mention_${conversationId.slice(3)}`;
	if (conversationId.startsWith("tr-"))
		return `threads_reply_${conversationId.slice(3)}`;
	if (conversationId.startsWith("igc-"))
		return `ig_comment_${conversationId.slice(4)}`;
	if (conversationId.startsWith("dm-"))
		return `ig_dm_${conversationId.slice(3)}`;
	return conversationId;
}

async function markInboxSignalHandled(conversationId: string) {
	const response = await fetch(apiUrl("/api/inbox?action=mark-read"), {
		method: "POST",
		headers: {
			...(await getApiAuthHeaders()),
			"Content-Type": "application/json",
		},
		body: JSON.stringify({
			messageId: inboxMessageIdFromConversation(conversationId),
			read: true,
		}),
	});
	if (!response.ok) throw new Error("Failed to mark mention handled");
}

async function saveCompetitorNote(input: {
	userId: string;
	post: CompetitorPostRow;
	note: string;
}) {
	const note = input.note.trim();
	if (!note) throw new Error("Note required");
	const { error } = await supabase.from("saved_competitor_posts").insert({
		user_id: input.userId,
		content: input.post.content ?? null,
		username: input.post.competitor_username ?? "competitor",
		notes: note,
	});
	if (error) throw error;
}

export function Listening() {
	const authUser = useAuthUser();
	const [searchParams, setSearchParams] = useSearchParams();
	const workspaceId = useWorkspaceStore((s) => s.currentWorkspace?.id ?? null);
	const { groups } = useAccountGroups();
	const { conversations } = useUnifiedInbox();
	const competitorSurprises = useCompetitorSurprises();
	const [keyword, setKeyword] = useState("");
	const [threshold, setThreshold] = useState(10);
	const [query, setQuery] = useState("");
	const workflowKey = listeningWorkflowKey(authUser?.id ?? null);
	const [handledIds, setHandledIds] = useState<Set<string>>(() =>
		typeof window === "undefined" ? new Set() : readHandledSignals(workflowKey),
	);
	const [handledRemoteReady, setHandledRemoteReady] = useState(false);

	useEffect(() => {
		const nextQuery = searchParams.get("q");
		const nextKeyword = searchParams.get("keyword");
		if (nextQuery) setQuery(nextQuery);
		if (nextKeyword) setKeyword(nextKeyword);
		if (nextQuery || nextKeyword) {
			const cleaned = new URLSearchParams(searchParams);
			cleaned.delete("q");
			cleaned.delete("keyword");
			cleaned.delete("accountId");
			cleaned.delete("account");
			cleaned.delete("platform");
			cleaned.delete("group");
			cleaned.delete("accounts");
			setSearchParams(cleaned, { replace: true });
		}
	}, [searchParams, setSearchParams]);

	useEffect(() => {
		let cancelled = false;
		setHandledRemoteReady(false);
		const local =
			typeof window === "undefined"
				? new Set<string>()
				: readHandledSignals(workflowKey);
		setHandledIds(local);
		if (!authUser) {
			setHandledRemoteReady(true);
			return () => {
				cancelled = true;
			};
		}
		void getUserSetting(authUser.id, LISTENING_REMOTE_SETTING_KEY)
			.then(async (setting) => {
				if (cancelled) return;
				const remote = normalizeHandledIds(setting);
				const durable = await fetchDurableListeningWorkflowIds();
				if (cancelled) return;
				const merged = new Set([...remote, ...local, ...durable]);
				setHandledIds(merged);
				writeHandledSignals(workflowKey, merged);
			})
			.catch(() => {
				/* local workflow state stays usable while offline */
			})
			.finally(() => {
				if (!cancelled) setHandledRemoteReady(true);
			});
		return () => {
			cancelled = true;
		};
	}, [workflowKey, authUser]);

	useEffect(() => {
		if (!authUser || !handledRemoteReady) return;
		const timer = window.setTimeout(() => {
			const handled = [...handledIds].slice(-500);
			void upsertUserSetting(authUser.id, LISTENING_REMOTE_SETTING_KEY, {
				handledIds: handled,
				updatedAt: new Date().toISOString(),
			}).catch(() => {
				/* local workflow state remains authoritative until sync recovers */
			});
		}, 600);
		return () => window.clearTimeout(timer);
	}, [authUser, handledIds, handledRemoteReady]);

	const snapshot = useQuery({
		queryKey: queryKeys.listening.snapshot(authUser?.id ?? null, workspaceId),
		enabled: !!authUser,
		staleTime: 60_000,
		queryFn: () => fetchSnapshot(workspaceId),
	});

	const createTerm = useMutation({
		mutationFn: () => createWatchTerm({ keyword, workspaceId, threshold }),
		onSuccess: () => {
			setKeyword("");
			void queryClient.invalidateQueries({ queryKey: queryKeys.listening.snapshotAll });
			appToast.success("Watch term added");
		},
		onError: (error) => {
			appToast.error("Could not add watch term", {
				description: error instanceof Error ? error.message : undefined,
			});
		},
	});

	const runScan = useMutation({
		mutationFn: () => runListeningScan(workspaceId),
		onSuccess: (processed) => {
			void queryClient.invalidateQueries({ queryKey: queryKeys.listening.snapshotAll });
			appToast.success("Scan complete", {
				description: `${processed} monitor${processed === 1 ? "" : "s"} checked.`,
			});
		},
		onError: (error) => {
			appToast.error("Could not run scan", {
				description: error instanceof Error ? error.message : undefined,
			});
		},
	});

	const data = snapshot.data ?? {
		alerts: [],
		results: [],
		competitors: [],
		competitorPosts: [],
		trendKeywords: [],
		trendPosts: [],
	};

	const markHandled = (id: string, label = "Signal") => {
		setHandledIds((prev) => {
			const next = new Set(prev);
			next.add(id);
			try {
				writeHandledSignals(workflowKey, next);
			} catch {
				/* local workflow state is best effort */
			}
			return next;
		});
		appToast.success(`${label} marked handled`);
	};

	const markSignalWorkflow = async (input: {
		localId: string;
		label: string;
		source: ListeningWorkflowSource;
		sourceId: string;
		title: string;
		status: WorkflowStatus;
		groupId?: string | null;
		payload?: unknown;
	}) => {
		const snoozedUntil =
			input.status === "snoozed"
				? new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString()
				: null;
		await updateDurableListeningWorkflow({
			source: input.source,
			sourceId: input.sourceId,
			status: input.status,
			title: input.title,
			groupId: input.groupId,
			snoozedUntil,
			resolutionReason:
				input.status === "ignored"
					? "Ignored from Listening"
					: input.status === "snoozed"
						? "Snoozed from Listening"
						: "Marked handled from Listening",
			payload: input.payload,
		});
		markHandled(input.localId, input.label);
		void queryClient.invalidateQueries({ queryKey: queryKeys.operator.snapshotAll });
	};

	const createReplyDraft = (conversation: Conversation) => {
		const draft = {
			conversationId: conversation.id,
			text: `Thanks for flagging this. ${conversation.snippet}`,
			createdAt: new Date().toISOString(),
		};
		window.sessionStorage.setItem(INBOX_REPLY_DRAFT_KEY, JSON.stringify(draft));
		appToast.success("Reply draft prepared", {
			description: "Open Inbox to review and send it.",
			action: {
				label: "Open",
				onClick: () => {
					window.location.href = "/inbox";
				},
			},
		});
	};

	const createSignalReplyDraft = (input: {
		source: ListeningWorkflowSource;
		sourceId: string;
		title: string;
		body: string;
		permalink?: string | null;
	}) => {
		const draft = {
			conversationId: input.sourceId,
			source: input.source,
			text: `Thanks for the context here. Draft a human-reviewed response based on: ${input.body}`.slice(
				0,
				900,
			),
			context: {
				title: input.title,
				permalink: input.permalink ?? null,
			},
			createdAt: new Date().toISOString(),
		};
		window.sessionStorage.setItem(INBOX_REPLY_DRAFT_KEY, JSON.stringify(draft));
		appToast.success("Reply draft prepared", {
			description: "Open Inbox to review before sending.",
			action: {
				label: "Open",
				onClick: () => {
					window.location.href = "/inbox";
				},
			},
		});
	};

	const mentionSignals = useMemo(() => {
		const q = query.trim().toLowerCase();
		return conversations
			.filter((conversation) => {
				if (handledIds.has(`mention:${conversation.id}`)) return false;
				const isSignal =
					conversation.type === "mention" ||
					conversation.sentiment === "negative" ||
					conversation.snippet.includes("@");
				if (!isSignal) return false;
				if (!q) return true;
				return `${conversation.user.name} ${conversation.user.handle} ${conversation.snippet} ${conversation.toAccount}`
					.toLowerCase()
					.includes(q);
			})
			.slice(0, 12);
	}, [conversations, handledIds, query]);

	const topCompetitorPosts = useMemo(() => {
		const surpriseIds = new Set(
			competitorSurprises.surprises.map((item) => item.id),
		);
		return [
			...competitorSurprises.surprises.map((item) => ({
				id: item.id,
				competitor_username: item.competitorUsername,
				content: item.content,
				engagement_score: item.engagementScore,
				like_count: item.likes,
				reply_count: item.replies,
				repost_count: item.reposts,
				view_count: item.views,
				permalink: item.permalink,
				platform: null,
				published_at: item.publishedAt,
				topic_tag: `x${item.multiplier.toFixed(1)} baseline`,
			})),
			...data.competitorPosts.filter((post) => !surpriseIds.has(post.id)),
		]
			.filter((post) => !handledIds.has(`competitor:${post.id}`))
			.slice(0, 12);
	}, [competitorSurprises.surprises, data.competitorPosts, handledIds]);

	const visibleTrendPosts = useMemo(
		() =>
			data.trendPosts
				.filter((post) => !handledIds.has(`trend:${post.id}`))
				.slice(0, 10),
		[data.trendPosts, handledIds],
	);

	const keywordById = useMemo(
		() => new Map(data.trendKeywords.map((item) => [item.id, item.keyword])),
		[data.trendKeywords],
	);

	const listeningScore =
		data.alerts.filter((alert) => alert.is_active !== false).length +
		data.trendKeywords.filter((keywordRow) => keywordRow.is_active !== false)
			.length +
		data.competitors.length;
	const activeWatchTerms = data.alerts.filter(
		(a) => a.is_active !== false,
	).length;
	const listeningKpis = [
		{
			label: "Watch terms",
			value: data.alerts.length,
			caption: `${activeWatchTerms} active`,
			trend: activeWatchTerms > 0 ? "good" : "neutral",
			active: true,
			empty: data.alerts.length === 0,
		},
		{
			label: "Competitors",
			value: data.competitors.length,
			caption: `${topCompetitorPosts.length} hot posts`,
			trend: topCompetitorPosts.length > 0 ? "warn" : "neutral",
			active: false,
			empty: data.competitors.length === 0,
		},
		{
			label: "Trend topics",
			value: data.trendKeywords.length,
			caption: `${data.trendPosts.length} sampled posts`,
			trend: data.trendPosts.length > 0 ? "good" : "neutral",
			active: false,
			empty: data.trendKeywords.length === 0,
		},
		{
			label: "Signals",
			value: listeningScore,
			caption: "active monitors",
			trend: listeningScore > 0 ? "good" : "neutral",
			active: false,
			empty: listeningScore === 0,
		},
	] as const;

	return (
		<NovaScreen width="wide" density="compact">
			<NovaSection>
				<NovaHeader
					eyebrow="Listening"
					title="Social listening"
					meta="Monitor · live"
					description="Monitor mentions, competitor spikes, and tracked topics before they become content decisions."
					actions={
						<NovaToolbar>
							<Button
								type="button"
								onClick={() => runScan.mutate()}
								disabled={runScan.isPending || data.alerts.length === 0}
								size="sm"
							>
								<Radar data-icon="inline-start" aria-hidden="true" />
								{runScan.isPending ? "Scanning" : "Run scan now"}
							</Button>
							<Button
								type="button"
								onClick={() => snapshot.refetch()}
								variant="outline"
								size="sm"
							>
								<Radio data-icon="inline-start" aria-hidden="true" />
								Refresh
							</Button>
						</NovaToolbar>
					}
				/>
			</NovaSection>

			<NovaSection className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
				{listeningKpis.map((kpi) => (
					<NovaStat
						key={kpi.label}
						label={kpi.label}
						value={kpi.value}
						description={kpi.caption}
						status={kpi.active ? <Badge tone="oxblood">Live</Badge> : undefined}
					/>
				))}
			</NovaSection>

			<NovaSection>
				<NovaDataPanel contentClassName="p-4">
					<div className="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_auto] lg:items-end">
						<div className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_160px]">
							<label htmlFor="listening-watch-term" className="block">
								<span className="mb-1.5 block text-[0.75rem] font-medium text-muted-foreground">
									Watch term
								</span>
								<div className="relative">
									<Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
									<Input
										id="listening-watch-term"
										value={keyword}
										onChange={(event) => setKeyword(event.target.value)}
										placeholder="@brand, keyword, hashtag"
										className="pl-8"
									/>
								</div>
							</label>
							<label htmlFor="listening-threshold" className="block">
								<span className="mb-1.5 block text-[0.75rem] font-medium text-muted-foreground">
									Threshold
								</span>
								<Input
									id="listening-threshold"
									type="number"
									min={1}
									max={10000}
									value={threshold}
									onChange={(event) => setThreshold(Number(event.target.value))}
								/>
							</label>
						</div>
						<Button
							type="button"
							onClick={() => createTerm.mutate()}
							disabled={!keyword.trim() || createTerm.isPending}
							size="sm"
						>
							<Plus data-icon="inline-start" aria-hidden="true" />
							Add monitor
						</Button>
					</div>
				</NovaDataPanel>
			</NovaSection>

			<div className="grid grid-cols-1 gap-5 2xl:grid-cols-[minmax(0,1fr)_360px]">
				<main className="flex min-w-0 flex-col gap-5">
					<SignalSection
						title="Mentions and customer signals"
						icon={Bell}
						count={mentionSignals.length}
					>
						<div className="mb-3">
							<label
								htmlFor="listening-signal-filter"
								className="relative block max-w-sm"
							>
								<Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
								<Input
									id="listening-signal-filter"
									value={query}
									onChange={(event) => setQuery(event.target.value)}
									placeholder="Filter signals"
									className="pl-8"
								/>
							</label>
						</div>
						{mentionSignals.length === 0 ? (
							<InlineEmpty
								icon={Bell}
								title="No mention signals for this filter"
							/>
						) : (
							<div className="flex flex-col gap-2">
								{mentionSignals.map((conversation) => (
									<MentionSignal
										key={conversation.id}
										conversation={conversation}
										groups={groups}
										onIdea={(groupId) =>
											void addSignalToIdeas({
												userId: authUser?.id ?? null,
												title: `Listening follow-up: ${conversation.user.name}`,
												body: `Turn this ${conversation.platform} ${conversation.type} into a post or reply angle.\n\n${conversation.user.handle}: ${conversation.snippet}`,
												accountId: conversation.reply.accountId,
												groupId,
											})
										}
										onDraftReply={() => createReplyDraft(conversation)}
										onHandled={() => {
											void markInboxSignalHandled(conversation.id)
												.then(() =>
													markHandled(`mention:${conversation.id}`, "Mention"),
												)
												.catch((error) => {
													appToast.error("Could not mark mention handled", {
														description:
															error instanceof Error
																? error.message
																: undefined,
													});
												});
										}}
									/>
								))}
							</div>
						)}
					</SignalSection>

					<SignalSection
						title="Competitor monitoring"
						icon={Target}
						count={topCompetitorPosts.length}
					>
						{topCompetitorPosts.length === 0 ? (
							<NovaEmpty
								className="py-4"
								icon={<Target data-icon aria-hidden="true" />}
								title="No competitor posts yet"
								description="Tracked competitor posts appear here after the sync pipeline has enough data."
							/>
						) : (
							<div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
								{topCompetitorPosts.map((post) => (
									<PostSignalCard
										key={post.id}
										source={`@${post.competitor_username ?? "competitor"}`}
										title={post.topic_tag ?? "Competitor post"}
										body={post.content ?? "No caption captured"}
										metric={`${formatNumber(post.engagement_score)} score`}
										permalink={post.permalink}
										groups={groups}
										onIdea={(groupId) =>
											void addSignalToIdeas({
												userId: authUser?.id ?? null,
												title: `Competitor angle: @${post.competitor_username ?? "competitor"}`,
												body: `Adapt this competitor signal into our own angle.\n\nSource: @${post.competitor_username ?? "competitor"}\nEngagement score: ${formatNumber(post.engagement_score)}\n\n${post.content ?? ""}`,
												linkUrl: post.permalink,
												groupId,
											})
										}
										onNote={
											authUser
												? async (note) => {
														await saveCompetitorNote({
															userId: authUser.id,
															post: post as CompetitorPostRow,
															note,
														});
														appToast.success("Competitor note saved");
													}
												: undefined
										}
										onDraftReply={() =>
											createSignalReplyDraft({
												source: "competitor_signal",
												sourceId: post.id,
												title: `Competitor signal: @${post.competitor_username ?? "competitor"}`,
												body: post.content ?? "Competitor post needs review.",
												permalink: post.permalink,
											})
										}
										onHandled={() => {
											void markSignalWorkflow({
												localId: `competitor:${post.id}`,
												label: "Competitor signal",
												source: "competitor_signal",
												sourceId: post.id,
												title: `Competitor signal: @${post.competitor_username ?? "competitor"}`,
												status: "resolved",
												payload: {
													competitor_username: post.competitor_username,
													content: post.content,
													permalink: post.permalink,
													engagement_score: post.engagement_score,
												},
											}).catch((error) => {
												appToast.error(
													"Could not mark competitor signal handled",
													{
														description:
															error instanceof Error
																? error.message
																: undefined,
													},
												);
											});
										}}
										onIgnore={(groupId) => {
											void markSignalWorkflow({
												localId: `competitor:${post.id}`,
												label: "Competitor signal",
												source: "competitor_signal",
												sourceId: post.id,
												title: `Competitor signal: @${post.competitor_username ?? "competitor"}`,
												status: "ignored",
												groupId,
												payload: {
													competitor_username: post.competitor_username,
													permalink: post.permalink,
												},
											}).catch((error) => {
												appToast.error("Could not ignore competitor signal", {
													description:
														error instanceof Error ? error.message : undefined,
												});
											});
										}}
										onSnooze={(groupId) => {
											void markSignalWorkflow({
												localId: `competitor:${post.id}`,
												label: "Competitor signal",
												source: "competitor_signal",
												sourceId: post.id,
												title: `Competitor signal: @${post.competitor_username ?? "competitor"}`,
												status: "snoozed",
												groupId,
												payload: {
													competitor_username: post.competitor_username,
													permalink: post.permalink,
												},
											}).catch((error) => {
												appToast.error("Could not snooze competitor signal", {
													description:
														error instanceof Error ? error.message : undefined,
												});
											});
										}}
									/>
								))}
							</div>
						)}
					</SignalSection>

					<SignalSection
						title="Trend monitoring"
						icon={TrendingUp}
						count={data.trendPosts.length}
					>
						{visibleTrendPosts.length === 0 ? (
							<InlineEmpty
								icon={TrendingUp}
								title="No trend posts sampled yet"
							/>
						) : (
							<div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
								{visibleTrendPosts.map((post) => (
									<PostSignalCard
										key={post.id}
										source={`@${post.username}`}
										title={keywordById.get(post.keyword_id) ?? "Tracked topic"}
										body={post.content ?? "No text captured"}
										metric={`${formatNumber(post.engagement_score)} score`}
										permalink={post.permalink}
										groups={groups}
										onIdea={(groupId) =>
											void addSignalToIdeas({
												userId: authUser?.id ?? null,
												title: `Trend angle: ${keywordById.get(post.keyword_id) ?? "Tracked topic"}`,
												body: `Build a post from this trend signal.\n\nTopic: ${keywordById.get(post.keyword_id) ?? "Tracked topic"}\nSource: @${post.username}\n\n${post.content ?? ""}`,
												linkUrl: post.permalink,
												groupId,
											})
										}
										onDraftReply={() =>
											createSignalReplyDraft({
												source: "trend_signal",
												sourceId: post.id,
												title: `Trend signal: ${keywordById.get(post.keyword_id) ?? "Tracked topic"}`,
												body: post.content ?? "Trend post needs review.",
												permalink: post.permalink,
											})
										}
										onHandled={() => {
											void markSignalWorkflow({
												localId: `trend:${post.id}`,
												label: "Trend signal",
												source: "trend_signal",
												sourceId: post.id,
												title: `Trend signal: ${keywordById.get(post.keyword_id) ?? "Tracked topic"}`,
												status: "resolved",
												payload: {
													keyword: keywordById.get(post.keyword_id),
													username: post.username,
													content: post.content,
													permalink: post.permalink,
													engagement_score: post.engagement_score,
												},
											}).catch((error) => {
												appToast.error("Could not mark trend signal handled", {
													description:
														error instanceof Error ? error.message : undefined,
												});
											});
										}}
										onIgnore={(groupId) => {
											void markSignalWorkflow({
												localId: `trend:${post.id}`,
												label: "Trend signal",
												source: "trend_signal",
												sourceId: post.id,
												title: `Trend signal: ${keywordById.get(post.keyword_id) ?? "Tracked topic"}`,
												status: "ignored",
												groupId,
												payload: {
													keyword: keywordById.get(post.keyword_id),
													username: post.username,
													permalink: post.permalink,
												},
											}).catch((error) => {
												appToast.error("Could not ignore trend signal", {
													description:
														error instanceof Error ? error.message : undefined,
												});
											});
										}}
										onSnooze={(groupId) => {
											void markSignalWorkflow({
												localId: `trend:${post.id}`,
												label: "Trend signal",
												source: "trend_signal",
												sourceId: post.id,
												title: `Trend signal: ${keywordById.get(post.keyword_id) ?? "Tracked topic"}`,
												status: "snoozed",
												groupId,
												payload: {
													keyword: keywordById.get(post.keyword_id),
													username: post.username,
													permalink: post.permalink,
												},
											}).catch((error) => {
												appToast.error("Could not snooze trend signal", {
													description:
														error instanceof Error ? error.message : undefined,
												});
											});
										}}
									/>
								))}
							</div>
						)}
					</SignalSection>
				</main>

				<aside className="flex min-w-0 flex-col gap-5">
					<SidePanel title="Active monitors" icon={Activity}>
						{data.alerts.length === 0 && data.trendKeywords.length === 0 ? (
							<InlineEmpty icon={Radio} title="Add a watch term to begin" />
						) : (
							<div className="flex flex-col gap-2">
								{data.alerts.slice(0, 8).map((alert) => (
									<MonitorRow
										key={alert.id}
										label={alert.keyword}
										meta={`${alert.alert_type} · threshold ${alert.threshold_value ?? 0}`}
										active={alert.is_active !== false}
										age={formatDate(alert.last_checked_at)}
										onIdea={() =>
											void addSignalToIdeas({
												userId: authUser?.id ?? null,
												title: `Keyword idea: ${alert.keyword}`,
												body: `Use the listening monitor "${alert.keyword}" as a content prompt. Threshold: ${alert.threshold_value ?? 0}.`,
												groupId: null,
											})
										}
									/>
								))}
								{data.trendKeywords.slice(0, 8).map((trend) => (
									<MonitorRow
										key={trend.id}
										label={trend.keyword}
										meta={`${formatNumber(trend.total_engagement)} engagement · ${trend.post_count ?? 0} posts`}
										active={trend.is_active !== false}
										age={formatDate(trend.last_synced_at)}
										onIdea={() =>
											void addSignalToIdeas({
												userId: authUser?.id ?? null,
												title: `Trend idea: ${trend.keyword}`,
												body: `Build a post around "${trend.keyword}". Current sampled engagement: ${formatNumber(trend.total_engagement)} across ${trend.post_count ?? 0} posts.`,
												groupId: null,
											})
										}
									/>
								))}
							</div>
						)}
					</SidePanel>

					<SidePanel title="Tracked competitors" icon={Eye}>
						{data.competitors.length === 0 ? (
							<InlineEmpty icon={Target} title="No competitors tracked" />
						) : (
							<div className="flex flex-col gap-2">
								{data.competitors.slice(0, 12).map((competitor) => (
									<CompetitorRowView
										key={competitor.id}
										competitor={competitor}
										onIdea={() =>
											void addSignalToIdeas({
												userId: authUser?.id ?? null,
												title: `Competitor watch: @${competitor.username}`,
												body: `Track content angles and response opportunities from @${competitor.username}.`,
												groupId: null,
											})
										}
									/>
								))}
							</div>
						)}
					</SidePanel>

					<SidePanel title="Recent scans" icon={CheckCircle2}>
						{data.results.length === 0 ? (
							<InlineEmpty icon={CheckCircle2} title="No completed scans yet" />
						) : (
							<div className="flex flex-col gap-2">
								{data.results.slice(0, 8).map((result) => (
									<div
										key={result.id}
										className="rounded-md border border-border bg-background px-3 py-2"
									>
										<div className="flex items-center justify-between gap-2">
											<span className="text-[0.8125rem] font-medium text-foreground truncate">
												{result.keyword}
											</span>
											<span className="text-[0.6875rem] tabular-nums text-muted-foreground">
												{result.result_count}
											</span>
										</div>
										<div className="mt-1 text-[0.6875rem] text-muted-foreground">
											{result.source} · {formatDate(result.checked_at)} ·{" "}
											{sentimentLabel(result.sentiment_breakdown)}
										</div>
										<div className="mt-2 flex flex-wrap gap-1.5">
											<WorkflowButton
												icon={Lightbulb}
												label="Idea"
												onClick={() =>
													void addSignalToIdeas({
														userId: authUser?.id ?? null,
														title: `Listening result: ${result.keyword}`,
														body: `Turn this scan into an action.\n\n${result.result_count} hits from ${result.source}.\nSentiment: ${sentimentLabel(result.sentiment_breakdown)}`,
														groupId: null,
													})
												}
											/>
											<WorkflowButton
												icon={Bell}
												label="Snooze"
												onClick={() => {
													void markSignalWorkflow({
														localId: `listening:${result.id}`,
														label: "Listening result",
														source: "listening_signal",
														sourceId: result.id,
														title: `Listening result: ${result.keyword}`,
														status: "snoozed",
														payload: result,
													}).catch((error) => {
														appToast.error(
															"Could not snooze listening result",
															{
																description:
																	error instanceof Error
																		? error.message
																		: undefined,
															},
														);
													});
												}}
											/>
											<WorkflowButton
												icon={Eye}
												label="Ignore"
												onClick={() => {
													void markSignalWorkflow({
														localId: `listening:${result.id}`,
														label: "Listening result",
														source: "listening_signal",
														sourceId: result.id,
														title: `Listening result: ${result.keyword}`,
														status: "ignored",
														payload: result,
													}).catch((error) => {
														appToast.error(
															"Could not ignore listening result",
															{
																description:
																	error instanceof Error
																		? error.message
																		: undefined,
															},
														);
													});
												}}
											/>
											<WorkflowButton
												icon={CheckCircle2}
												label="Handled"
												onClick={() => {
													void markSignalWorkflow({
														localId: `listening:${result.id}`,
														label: "Listening result",
														source: "listening_signal",
														sourceId: result.id,
														title: `Listening result: ${result.keyword}`,
														status: "resolved",
														payload: result,
													}).catch((error) => {
														appToast.error(
															"Could not mark listening result handled",
															{
																description:
																	error instanceof Error
																		? error.message
																		: undefined,
															},
														);
													});
												}}
											/>
										</div>
									</div>
								))}
							</div>
						)}
					</SidePanel>
				</aside>
			</div>
		</NovaScreen>
	);
}

function SignalSection({
	title,
	icon: Icon,
	count,
	children,
}: {
	title: string;
	icon: typeof Bell;
	count: number;
	children: React.ReactNode;
}) {
	return (
		<NovaDataPanel contentClassName="p-4">
			<div className="mb-4 flex items-center justify-between gap-3">
				<div className="flex items-center gap-2">
					<div className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-muted">
						<Icon className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
					</div>
					<h2 className="text-[0.9375rem] font-semibold text-foreground">
						{title}
					</h2>
				</div>
				<Badge tone="outline">{count}</Badge>
			</div>
			{children}
		</NovaDataPanel>
	);
}

function SidePanel({
	title,
	icon: Icon,
	children,
}: {
	title: string;
	icon: typeof Bell;
	children: React.ReactNode;
}) {
	return (
		<NovaDataPanel contentClassName="p-4">
			<div className="mb-3 flex items-center gap-2">
				<Icon className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
				<h2 className="text-[0.875rem] font-semibold text-foreground">
					{title}
				</h2>
			</div>
			{children}
		</NovaDataPanel>
	);
}

function InlineEmpty({
	icon: Icon,
	title,
}: {
	icon: typeof Bell;
	title: string;
}) {
	return (
		<NovaEmpty
			className="border border-dashed border-border bg-background/50 px-4 py-6"
			icon={<Icon data-icon aria-hidden="true" />}
			title={title}
		/>
	);
}

function MentionSignal({
	conversation,
	groups,
	onIdea,
	onDraftReply,
	onHandled,
}: {
	conversation: Conversation;
	groups: AccountGroup[];
	onIdea: (groupId: string | null) => void;
	onDraftReply: () => void;
	onHandled: () => void;
}) {
	const [groupId, setGroupId] = useState<string>("");
	return (
		<div className="rounded-md border border-border bg-background px-3 py-3">
			<div className="flex items-start justify-between gap-3">
				<div className="min-w-0">
					<div className="flex flex-wrap items-center gap-1.5 text-[0.6875rem] text-muted-foreground">
						<Badge tone="outline">{conversation.platform}</Badge>
						<span>{conversation.user.handle}</span>
						<span>to {conversation.toAccount}</span>
						<span>{conversation.ago}</span>
					</div>
					<p className="mt-2 text-[0.8125rem] leading-5 text-muted-foreground">
						{conversation.snippet}
					</p>
				</div>
			</div>
			<SignalWorkflowBar
				groups={groups}
				groupId={groupId}
				onGroupChange={setGroupId}
				onIdea={() => onIdea(groupId || null)}
				onDraftReply={onDraftReply}
				onHandled={onHandled}
			/>
		</div>
	);
}

function PostSignalCard({
	source,
	title,
	body,
	metric,
	permalink,
	groups,
	onIdea,
	onNote,
	onDraftReply,
	onHandled,
	onIgnore,
	onSnooze,
}: {
	source: string;
	title: string;
	body: string;
	metric: string;
	permalink?: string | null | undefined;
	groups: AccountGroup[];
	onIdea: (groupId: string | null) => void;
	onNote?: ((note: string) => Promise<void>) | undefined;
	onDraftReply?: (() => void) | undefined;
	onHandled: () => void;
	onIgnore?: ((groupId: string | null) => void) | undefined;
	onSnooze?: ((groupId: string | null) => void) | undefined;
}) {
	const [groupId, setGroupId] = useState<string>("");
	const [note, setNote] = useState("");
	const [noteOpen, setNoteOpen] = useState(false);
	const [savingNote, setSavingNote] = useState(false);
	const saveNote = async () => {
		if (!onNote || !note.trim()) return;
		setSavingNote(true);
		try {
			await onNote(note);
			setNote("");
			setNoteOpen(false);
		} catch (error) {
			appToast.error("Could not save note", {
				description: error instanceof Error ? error.message : undefined,
			});
		} finally {
			setSavingNote(false);
		}
	};
	return (
		<article className="rounded-md border border-border bg-background p-3">
			<div className="flex items-start justify-between gap-3">
				<div className="min-w-0">
					<div className="flex flex-wrap items-center gap-1.5">
						<Badge tone="outline">{source}</Badge>
						<Badge tone="oxblood">{metric}</Badge>
					</div>
					<h3 className="mt-2 text-[0.875rem] font-semibold text-foreground">
						{title}
					</h3>
				</div>
			</div>
			<p className="mt-2 line-clamp-4 text-[0.8125rem] leading-5 text-muted-foreground">
				{body}
			</p>
			<SignalWorkflowBar
				groups={groups}
				groupId={groupId}
				onGroupChange={setGroupId}
				onIdea={() => onIdea(groupId || null)}
				{...(onDraftReply ? { onDraftReply } : {})}
				onHandled={onHandled}
				{...(onIgnore ? { onIgnore: () => onIgnore(groupId || null) } : {})}
				{...(onSnooze ? { onSnooze: () => onSnooze(groupId || null) } : {})}
				{...(onNote
					? { onOpenNote: () => setNoteOpen((value) => !value) }
					: {})}
			/>
			{noteOpen ? (
				<div className="mt-2 rounded-md border border-border bg-background p-2">
					<Textarea
						value={note}
						onChange={(event) => setNote(event.target.value)}
						rows={3}
						placeholder="What should we remember about this competitor signal?"
						className="resize-none"
					/>
					<div className="mt-2 flex justify-end">
						<Button
							type="button"
							onClick={() => void saveNote()}
							disabled={!note.trim() || savingNote}
							size="sm"
						>
							{savingNote ? "Saving" : "Save note"}
						</Button>
					</div>
				</div>
			) : null}
			{permalink ? (
				<a
					href={permalink}
					target="_blank"
					rel="noreferrer"
					className="mt-3 inline-flex items-center gap-1 text-[0.75rem] text-muted-foreground hover:text-foreground"
				>
					Open source
					<ArrowUpRight className="w-3.5 h-3.5" aria-hidden="true" />
				</a>
			) : null}
		</article>
	);
}

function SignalWorkflowBar({
	groups,
	groupId,
	onGroupChange,
	onIdea,
	onDraftReply,
	onOpenNote,
	onHandled,
	onIgnore,
	onSnooze,
}: {
	groups: AccountGroup[];
	groupId: string;
	onGroupChange: (groupId: string) => void;
	onIdea: () => void;
	onDraftReply?: (() => void) | undefined;
	onOpenNote?: (() => void) | undefined;
	onHandled: () => void;
	onIgnore?: (() => void) | undefined;
	onSnooze?: (() => void) | undefined;
}) {
	return (
		<div className="mt-3 flex flex-wrap items-center gap-1.5">
			<Select
				value={groupId}
				onChange={(event) => onGroupChange(event.target.value)}
				aria-label="Assign signal to group"
				sizeVariant="sm"
				className="max-w-[180px] text-[0.75rem]"
			>
				<option value="">No group</option>
				{groups.map((group) => (
					<option key={group.id} value={group.id}>
						{group.name}
					</option>
				))}
			</Select>
			<WorkflowButton icon={Lightbulb} label="Idea" onClick={onIdea} />
			{onDraftReply ? (
				<WorkflowButton
					icon={MessageSquareText}
					label="Reply draft"
					onClick={onDraftReply}
				/>
			) : null}
			{onOpenNote ? (
				<WorkflowButton icon={NotebookPen} label="Note" onClick={onOpenNote} />
			) : null}
			{onSnooze ? (
				<WorkflowButton icon={Bell} label="Snooze" onClick={onSnooze} />
			) : null}
			{onIgnore ? (
				<WorkflowButton icon={Eye} label="Ignore" onClick={onIgnore} />
			) : null}
			<WorkflowButton icon={CheckCircle2} label="Handled" onClick={onHandled} />
		</div>
	);
}

function WorkflowButton({
	icon: Icon,
	label,
	onClick,
}: {
	icon: typeof Bell;
	label: string;
	onClick: () => void;
}) {
	return (
		<Button
			type="button"
			onClick={onClick}
			variant="outline"
			size="sm"
			className="gap-1.5 text-[0.75rem]"
		>
			<Icon data-icon="inline-start" aria-hidden="true" />
			{label}
		</Button>
	);
}

function MonitorRow({
	label,
	meta,
	active,
	age,
	onIdea,
}: {
	label: string;
	meta: string;
	active: boolean;
	age: string;
	onIdea?: (() => void) | undefined;
}) {
	return (
		<div className="rounded-md border border-border bg-background px-3 py-2">
			<div className="flex items-center justify-between gap-2">
				<span className="truncate text-[0.8125rem] font-medium text-foreground">
					{label}
				</span>
				<span
					className={cn(
						"w-1.5 h-1.5 rounded-full shrink-0",
						active
							? "bg-[color:var(--color-health-good)]"
							: "bg-muted-foreground",
					)}
				/>
			</div>
			<div className="mt-1 text-[0.6875rem] leading-4 text-muted-foreground">
				{meta} · {age}
			</div>
			{onIdea ? (
				<div className="mt-2">
					<WorkflowButton icon={Lightbulb} label="Idea" onClick={onIdea} />
				</div>
			) : null}
		</div>
	);
}

function CompetitorRowView({
	competitor,
	onIdea,
}: {
	competitor: CompetitorRow;
	onIdea?: (() => void) | undefined;
}) {
	return (
		<div className="rounded-md border border-border bg-background px-3 py-2">
			<div className="flex items-center justify-between gap-2">
				<span className="truncate text-[0.8125rem] font-medium text-foreground">
					@{competitor.username}
				</span>
				<span className="text-[0.6875rem] text-muted-foreground">
					{competitor.platform ?? "threads"}
				</span>
			</div>
			<div className="mt-1 flex flex-wrap items-center gap-2 text-[0.6875rem] text-muted-foreground">
				<span>{formatNumber(competitor.follower_count)} followers</span>
				<span>{((competitor.engagement_rate ?? 0) * 100).toFixed(2)}% ER</span>
				<span>{formatDate(competitor.last_synced_at)}</span>
			</div>
			{onIdea ? (
				<div className="mt-2">
					<WorkflowButton icon={Lightbulb} label="Idea" onClick={onIdea} />
				</div>
			) : null}
		</div>
	);
}
