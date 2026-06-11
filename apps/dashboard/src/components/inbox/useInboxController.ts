// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { appToast } from "@/lib/toast";
import type { InboxCommand } from "@/components/inbox/CommandPalette";
import {
	buildIdentityAdvisories,
	conversationKey,
	defaultTabForPlatform,
	inboxAssignmentSource,
	needsAttention,
	supportsTabForPlatform,
	tabsForPlatform,
} from "@/components/inbox/helpers";
import { contradictionWarning } from "@/components/inbox/safety";
import { useConversationPresence } from "@/components/inbox/useConversationPresence";
import type {
	ChatTurn,
	Conversation,
	InboxSuggestion,
	InboxWorkflowFilter,
	PlatformKind,
	TabKey,
} from "@/components/inbox/types";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import { useWorkspaceStore } from "@/stores/useWorkspaceStore";
import { useOnboardingState } from "@/hooks/useOnboardingState";
import { useConnectedAccounts } from "@/hooks/useConnectedAccounts";
import { useTablistKeyboardNav } from "@/hooks/useTablistKeyboardNav";
import { useUnifiedInbox } from "@/hooks/useUnifiedInbox";
import { useInboxAssignments } from "@/hooks/useInboxAssignments";
import { useAuthUser } from "@/hooks/useAuthUser";
import { sendReply } from "@/services/api/posts";
import { instagramService } from "@/services/instagramService";
import { randomUUID } from "@/lib/uuid";
import {
	checkInboxContradiction,
	fetchInboxSuggestionsBatch,
	markInboxRead,
	updateInboxSuggestion,
} from "@/services/api/inbox";
import { supabase } from "@/services/supabase";

const INBOX_WORKFLOW_PREFIX = "juno33:inbox-workflow";
const IDEAS_BOARD_PREFIX = "juno33:ideas-board";
const INBOX_REPLY_DRAFT_KEY = "juno33:inbox-reply-draft";

interface InboxWorkflowState {
	doneKeys: string[];
}

function inboxWorkflowKey(userId: string | null): string {
	return `${INBOX_WORKFLOW_PREFIX}:${userId ?? "anon"}`;
}

function ideasBoardKey(userId: string | null): string {
	return `${IDEAS_BOARD_PREFIX}:${userId ?? "anon"}`;
}

function readDoneKeys(key: string): Set<string> {
	try {
		const raw = window.localStorage.getItem(key);
		if (!raw) return new Set();
		const parsed = JSON.parse(raw) as Partial<InboxWorkflowState>;
		return new Set(
			Array.isArray(parsed.doneKeys)
				? parsed.doneKeys.filter((value): value is string => typeof value === "string")
				: [],
		);
	} catch {
		return new Set();
	}
}

function writeDoneKeys(key: string, doneKeys: Set<string>) {
	window.localStorage.setItem(
		key,
		JSON.stringify({ doneKeys: [...doneKeys].slice(-500) }),
	);
}

function rawInboxId(conversation: Pick<Conversation, "id">): string {
	return conversation.id.replace(/^(tr|tm|igc|dm)-/, "");
}

function inboxMessageId(conversation: Conversation): string {
	return `${inboxAssignmentSource(conversation)}_${rawInboxId(conversation)}`;
}

export function useInboxController() {
	const navigate = useNavigate();
	const onboarding = useOnboardingState();
	const { conversations: liveConversations, isLoading: inboxLoading } =
		useUnifiedInbox();
	const { assign: assignInboxItem } = useInboxAssignments();
	const authUser = useAuthUser();
	const currentWorkspace = useWorkspaceStore((s) => s.currentWorkspace);
	const [searchParams, setSearchParams] = useSearchParams();

	const [localOverlay, setLocalOverlay] = useState<
		Map<string, Partial<Conversation>>
	>(() => new Map());
	const [localTurns, setLocalTurns] = useState<Map<string, ChatTurn[]>>(
		() => new Map(),
	);
	const [suggestionsByKey, setSuggestionsByKey] = useState<
		Map<string, InboxSuggestion>
	>(() => new Map());
	const [safetyWarning, setSafetyWarning] = useState<{
		description: string;
		action: () => void | Promise<void>;
	} | null>(null);
	const [commandOpen, setCommandOpen] = useState(false);
	const [teamMembers, setTeamMembers] = useState<
		Array<{ id: string; name: string }>
	>([]);
	const [likedCommentIds, setLikedCommentIds] = useState<Set<string>>(
		() => new Set(),
	);
	const [likeBusyIds, setLikeBusyIds] = useState<Set<string>>(() => new Set());
	const [workflowFilter, setWorkflowFilter] =
		useState<InboxWorkflowFilter>("open");
	const [doneKeys, setDoneKeys] = useState<Set<string>>(() => new Set());

	const paramTab = searchParams.get("tab");
	const initialTab: TabKey =
		(paramTab === "dm" || paramTab === "mention" || paramTab === "comment") &&
		supportsTabForPlatform("instagram", paramTab)
			? paramTab
			: defaultTabForPlatform("instagram");

	const [tab, setTabState] = useState<TabKey>(initialTab);
	const [platform, setPlatform] = useState<PlatformKind>("instagram");
	const [activeId, setActiveId] = useState<string | null>(null);
	const [mobileActiveId, setMobileActiveId] = useState<string | null>(null);
	const [viewingThread, setViewingThread] = useState(false);
	const [replyText, setReplyText] = useState("");
	const [sendingConversationId, setSendingConversationId] = useState<string | null>(null);
	const [search, setSearch] = useState("");
	const replyRef = useRef<HTMLTextAreaElement>(null);
	const workflowStorageKey = inboxWorkflowKey(authUser?.id ?? null);

	useEffect(() => {
		setDoneKeys(readDoneKeys(workflowStorageKey));
	}, [workflowStorageKey]);

	useEffect(() => {
		try {
			writeDoneKeys(workflowStorageKey, doneKeys);
		} catch {
			/* local workflow state is best effort */
		}
	}, [doneKeys, workflowStorageKey]);

	const conversations = useMemo<Conversation[]>(() => {
		return liveConversations.map((c) => {
			const overlay = localOverlay.get(c.id);
			const extraTurns = localTurns.get(c.id) ?? [];
			const base = c as unknown as Conversation;
			if (!overlay && extraTurns.length === 0) return base;
			return {
				...base,
				...(overlay ?? {}),
				turns: [...base.turns, ...extraTurns],
			};
		});
	}, [liveConversations, localOverlay, localTurns]);

	useEffect(() => {
		if (conversations.length === 0) return;
		const serverKeys = new Set(conversations.map(conversationKey));
		const readKeys = new Set(
			conversations
				.filter((conversation) => conversation.isRead)
				.map(conversationKey),
		);
		setDoneKeys((prev) => {
			const next = new Set(prev);
			for (const key of serverKeys) {
				if (readKeys.has(key)) next.add(key);
				else next.delete(key);
			}
			return next;
		});
	}, [conversations]);

	const setConversations = useCallback(
		(updater: (prev: Conversation[]) => Conversation[]) => {
			const next = updater(conversations);
			setLocalOverlay((prev) => {
				const n = new Map(prev);
				for (const c of next) {
					const orig = liveConversations.find((l) => l.id === c.id);
					if (orig) n.set(c.id, { snippet: c.snippet, ago: c.ago });
				}
				return n;
			});
			setLocalTurns((prev) => {
				const n = new Map(prev);
				for (const c of next) {
					const orig = liveConversations.find((l) => l.id === c.id);
					if (!orig) continue;
					const extras = c.turns.slice(
						(orig as unknown as Conversation).turns.length,
					);
					if (extras.length) n.set(c.id, extras);
				}
				return n;
			});
		},
		[conversations, liveConversations],
	);

	const scopedHandle = useAccountScopeStore((s) => s.scopedAccount);
	const { accounts: connectedAccounts } = useConnectedAccounts();
	const scopedAccount = useMemo(
		() =>
			scopedHandle
				? (connectedAccounts.find((a) => a.id === scopedHandle.id) ?? null)
				: null,
		[scopedHandle, connectedAccounts],
	);
	const activePlatform = scopedAccount?.platform ?? platform;
	useEffect(() => {
		let cancelled = false;
		if (!currentWorkspace?.id) {
			setTeamMembers([]);
			return;
		}
		(async () => {
			const { data } = await supabase
				.from("workspace_members")
				.select("user_id, profiles:user_id(id, display_name, email)")
				.eq("workspace_id", currentWorkspace.id);
			if (cancelled) return;
			const rows = (data ?? []) as Array<{
				user_id: string;
				profiles?:
					| {
							display_name?: string | null | undefined;
							email?: string | null | undefined;
					  }
					| null
					| undefined;
			}>;
			setTeamMembers(
				rows.map((row) => ({
					id: row.user_id,
					name:
						row.profiles?.display_name || row.profiles?.email || row.user_id,
				})),
			);
		})();
		return () => {
			cancelled = true;
		};
	}, [currentWorkspace?.id]);

	const keyForConversation = useCallback(
		(c: Conversation) => conversationKey(c),
		[],
	);
	const conversationKeys = useMemo(
		() => conversations.map(conversationKey),
		[conversations],
	);
	const identityAdvisories = useMemo(
		() => buildIdentityAdvisories(conversations),
		[conversations],
	);

	useEffect(() => {
		let cancelled = false;
		const keys = conversationKeys.slice(0, 80);
		if (keys.length === 0) return;
		fetchInboxSuggestionsBatch(keys)
			.then((suggestions) => {
				if (cancelled) return;
				const next = new Map<string, InboxSuggestion>();
				for (const suggestion of suggestions) {
					if (suggestion.status !== "pending") continue;
					if (!next.has(suggestion.conversation_key)) {
						next.set(suggestion.conversation_key, suggestion);
					}
				}
				setSuggestionsByKey(next);
			})
			.catch(() => {});
		return () => {
			cancelled = true;
		};
	}, [conversationKeys]);

	const filtered = useMemo(() => {
		const q = search.trim().toLowerCase();
		return conversations.filter((c) => {
			const key = conversationKey(c);
			const done = doneKeys.has(key);
			const attention = needsAttention(c, suggestionsByKey.get(key));
			if (
				scopedAccount &&
				(c.toAccount !== scopedAccount.handle ||
					c.platform !== scopedAccount.platform)
			)
				return false;
			if (c.type !== tab) return false;
			if (c.platform !== activePlatform) return false;
			if (workflowFilter === "attention" && (done || !attention)) return false;
			if (workflowFilter === "open" && done) return false;
			if (workflowFilter === "done" && !done) return false;
			if (
				q &&
				!`${c.user.name} ${c.user.handle} ${c.snippet}`
					.toLowerCase()
					.includes(q)
			)
				return false;
			return true;
		});
	}, [
		conversations,
		doneKeys,
		scopedAccount,
		tab,
		activePlatform,
		workflowFilter,
		search,
		suggestionsByKey,
	]);

	const counts = useMemo(() => {
		const q = search.trim().toLowerCase();
		const base = conversations.filter((c) => {
			if (
				scopedAccount &&
				(c.toAccount !== scopedAccount.handle ||
					c.platform !== scopedAccount.platform)
			)
				return false;
			if (c.platform !== activePlatform) return false;
			if (
				q &&
				!`${c.user.name} ${c.user.handle} ${c.snippet}`
					.toLowerCase()
					.includes(q)
			)
				return false;
			return true;
		});
		return {
			dm: base.filter((c) => c.type === "dm").length,
			mention: base.filter((c) => c.type === "mention").length,
			comment: base.filter((c) => c.type === "comment").length,
		};
	}, [conversations, scopedAccount, activePlatform, search]);

	const workflowCounts = useMemo(() => {
		const q = search.trim().toLowerCase();
		const base = conversations.filter((c) => {
			if (
				scopedAccount &&
				(c.toAccount !== scopedAccount.handle ||
					c.platform !== scopedAccount.platform)
			)
				return false;
			if (c.type !== tab) return false;
			if (c.platform !== activePlatform) return false;
			if (
				q &&
				!`${c.user.name} ${c.user.handle} ${c.snippet}`
					.toLowerCase()
					.includes(q)
			)
				return false;
			return true;
		});
		let attention = 0;
		let done = 0;
		for (const c of base) {
			const key = conversationKey(c);
			if (doneKeys.has(key)) {
				done += 1;
			} else if (needsAttention(c, suggestionsByKey.get(key))) {
				attention += 1;
			}
		}
		return { attention, open: base.length - done, done };
	}, [
		conversations,
		doneKeys,
		scopedAccount,
		tab,
		activePlatform,
		search,
		suggestionsByKey,
	]);

	const active = useMemo(
		() => filtered.find((c) => c.id === activeId) ?? filtered[0] ?? null,
		[filtered, activeId],
	);
	const mobileActive = useMemo(
		() =>
			mobileActiveId
				? (filtered.find((c) => c.id === mobileActiveId) ?? null)
				: null,
		[filtered, mobileActiveId],
	);
	const activeKey = active ? keyForConversation(active) : null;
	const activeSuggestion = activeKey
		? suggestionsByKey.get(activeKey)
		: undefined;
	const { draftingLabel, startDrafting, stopDrafting } =
		useConversationPresence(authUser, activeKey);

	const availableTabs = useMemo(
		() => tabsForPlatform(activePlatform),
		[activePlatform],
	);
	const tabIds = useMemo(() => availableTabs.map((t) => t.id), [availableTabs]);
	const onTablistKey = useTablistKeyboardNav({
		ids: tabIds,
		activeId: tab,
		onNavigate: (id) => setTab(id as TabKey),
		orientation: "horizontal",
		scopeSelector: '[data-tablist="inbox-tabs"]',
	});

	const setTab = (next: TabKey) => {
		if (!supportsTabForPlatform(activePlatform, next)) return;
		setTabState(next);
		setSearchParams(
			(prev) => {
				const qp = new URLSearchParams(prev);
				if (next === "dm") qp.delete("tab");
				else qp.set("tab", next);
				return qp;
			},
			{ replace: true },
		);
	};

	const setInboxPlatform = (next: PlatformKind) => {
		if (scopedAccount) return;
		setPlatform(next);
		if (!supportsTabForPlatform(next, tab)) {
			const fallback = defaultTabForPlatform(next);
			setTabState(fallback);
			setSearchParams(
				(prev) => {
					const qp = new URLSearchParams(prev);
					if (fallback === defaultTabForPlatform(next)) qp.delete("tab");
					else qp.set("tab", fallback);
					return qp;
				},
				{ replace: true },
			);
		}
	};

	useEffect(() => {
		if (!scopedAccount || supportsTabForPlatform(scopedAccount.platform, tab))
			return;
		const fallback = defaultTabForPlatform(scopedAccount.platform);
		setTabState(fallback);
		setSearchParams(
			(prev) => {
				const qp = new URLSearchParams(prev);
				if (fallback === defaultTabForPlatform(scopedAccount.platform))
					qp.delete("tab");
				else qp.set("tab", fallback);
				return qp;
			},
			{ replace: true },
		);
	}, [scopedAccount, tab, setSearchParams]);

	useEffect(() => {
		if (active && activeId !== active.id) setActiveId(active.id);
		if (!active && activeId !== null) setActiveId(null);
	}, [active, activeId]);

	useEffect(() => {
		if (typeof window === "undefined" || conversations.length === 0) return;
		try {
			const raw = window.sessionStorage.getItem(INBOX_REPLY_DRAFT_KEY);
			if (!raw) return;
			const draft = JSON.parse(raw) as {
				conversationId?: string | undefined;
				text?: string | undefined;
			};
			if (!draft.conversationId || typeof draft.text !== "string") return;
			const match = conversations.find(
				(conversation) => conversation.id === draft.conversationId,
			);
			if (!match) return;
			setActiveId(match.id);
			setMobileActiveId(match.id);
			setReplyText(draft.text);
			window.sessionStorage.removeItem(INBOX_REPLY_DRAFT_KEY);
			appToast.success("Reply draft loaded", {
				description: match.user.handle,
			});
		} catch {
			window.sessionStorage.removeItem(INBOX_REPLY_DRAFT_KEY);
		}
	}, [conversations]);

	const performSend = useCallback(async (): Promise<boolean> => {
		if (!active || !replyText.trim()) return false;
		if (sendingConversationId === active.id) return false;
		const content = replyText.trim();
		const convo = liveConversations.find((c) => c.id === active.id);
		const replyMeta = convo?.reply;
		if (!replyMeta?.accountId) {
			appToast.error("Can't send - account link missing for this thread");
			return false;
		}

		setSendingConversationId(active.id);
		const localTurn: ChatTurn = {
			id: `local-${Date.now()}`,
			from: "me",
			text: content,
			time: "just now",
		};
		setConversations((prev) =>
			prev.map((c) =>
				c.id === active.id
					? {
							...c,
							turns: [...c.turns, localTurn],
							snippet: content,
							ago: "just now",
						}
					: c,
			),
		);
		setReplyText("");
		let result: Awaited<ReturnType<typeof sendReply>> = {
			ok: false,
			error: "Reply was not sent",
		};
		try {
			result = await sendReply({
				platform: replyMeta.platform,
				accountId: replyMeta.accountId,
				replyToId: replyMeta.replyToId,
				conversationId: replyMeta.conversationId,
				content,
				kind: replyMeta.kind,
				idempotencyKey: `inbox-reply:${active.id}:${randomUUID()}`,
				context: replyMeta.context,
			});
		} finally {
			setSendingConversationId((current) => (current === active.id ? null : current));
		}
		if (!result.ok) {
			setConversations((prev) =>
				prev.map((c) =>
					c.id === active.id
						? {
								...c,
								turns: c.turns.filter((turn) => turn.id !== localTurn.id),
								snippet: convo?.snippet ?? c.snippet,
								ago: convo?.ago ?? c.ago,
							}
						: c,
				),
			);
			setReplyText(content);
			appToast.error("Reply failed", { description: result.error });
			return false;
		}
		setDoneKeys((prev) => new Set(prev).add(conversationKey(active)));
		void markInboxRead({ messageId: inboxMessageId(active), read: true }).catch(() => {
			appToast.error("Reply sent, but Inbox done state did not sync");
		});
		return true;
	}, [active, liveConversations, replyText, sendingConversationId, setConversations]);

	const guarded = useCallback(
		async (action: () => void | Promise<void>) => {
			if (!active) return;
			try {
				const result = await checkInboxContradiction({
					composerText: replyText,
					lastReplies: active.turns.slice(-3).map((turn) => turn.text),
				});
				if (result.contradicts) {
					setSafetyWarning({
						description:
							"The draft reads as the opposite sentiment from the recent thread. Send anyway?",
						action,
					});
					return;
				}
			} catch {
				const warning = contradictionWarning(replyText, active.turns);
				if (warning) {
					setSafetyWarning({ description: warning, action });
					return;
				}
			}
			void action();
		},
		[active, replyText],
	);
	const send = useCallback(
		() =>
			guarded(async () => {
				stopDrafting();
				await performSend();
			}),
		[guarded, performSend, stopDrafting],
	);
	const acceptSuggestion = (suggestion: InboxSuggestion) => {
		setReplyText(suggestion.suggestion_text);
		void updateInboxSuggestion({
			id: suggestion.id,
			conversationKey: suggestion.conversation_key,
			status: "accepted",
		});
		setSuggestionsByKey((prev) => {
			const next = new Map(prev);
			next.delete(suggestion.conversation_key);
			return next;
		});
	};
	const rejectSuggestion = (suggestion: InboxSuggestion) => {
		void updateInboxSuggestion({
			id: suggestion.id,
			conversationKey: suggestion.conversation_key,
			status: "rejected",
		});
		setSuggestionsByKey((prev) => {
			const next = new Map(prev);
			next.delete(suggestion.conversation_key);
			return next;
		});
	};
	const regenerateSuggestion = () => {
		if (!activeKey) return;
		updateInboxSuggestion({ conversationKey: activeKey, regenerate: true })
			.then((suggestion) => {
				if (suggestion)
					setSuggestionsByKey((prev) =>
						new Map(prev).set(activeKey, suggestion),
					);
			})
			.catch(() => appToast.error("Could not regenerate suggestion"));
	};

	const toggleInstagramCommentLike = useCallback(async () => {
		if (!active || active.platform !== "instagram" || active.type !== "comment")
			return;
		const accountId = active.reply.accountId;
		const commentId = active.reply.replyToId;
		if (!accountId || !commentId) {
			appToast.error("Can't like this comment", {
				description: "The Instagram account or comment id is missing.",
			});
			return;
		}
		const currentlyLiked = likedCommentIds.has(commentId);
		setLikeBusyIds((prev) => new Set(prev).add(commentId));
		try {
			if (currentlyLiked) {
				await instagramService.unlikeComment(accountId, commentId);
				setLikedCommentIds((prev) => {
					const next = new Set(prev);
					next.delete(commentId);
					return next;
				});
				appToast.success("Comment unliked");
			} else {
				await instagramService.likeComment(accountId, commentId);
				setLikedCommentIds((prev) => new Set(prev).add(commentId));
				appToast.success("Comment liked");
			}
		} catch (error) {
			appToast.error(currentlyLiked ? "Unlike failed" : "Like failed", {
				description: error instanceof Error ? error.message : undefined,
			});
		} finally {
			setLikeBusyIds((prev) => {
				const next = new Set(prev);
				next.delete(commentId);
				return next;
			});
		}
	}, [active, likedCommentIds]);

	const activeDone = activeKey ? doneKeys.has(activeKey) : false;
	const activeNeedsAttention =
		!!active &&
		!activeDone &&
		needsAttention(active, activeSuggestion);

	const setConversationDone = useCallback(
		(conversation: Conversation, done: boolean) => {
			const key = conversationKey(conversation);
			setDoneKeys((prev) => {
				const next = new Set(prev);
				if (done) next.add(key);
				else next.delete(key);
				return next;
			});
			appToast.success(done ? "Marked done" : "Moved back to attention", {
				description: conversation.user.handle,
			});
			void markInboxRead({ messageId: inboxMessageId(conversation), read: done }).catch(() => {
				appToast.error("Inbox workflow did not sync", {
					description: "The local view updated, but the durable task state failed to save.",
				});
			});
		},
		[],
	);

	const toggleActiveDone = useCallback(() => {
		if (!active) return;
		setConversationDone(active, !activeDone);
	}, [active, activeDone, setConversationDone]);

	const convertActiveToIdea = useCallback(() => {
		if (!active) return;
		const now = new Date().toISOString();
		const account = active.reply.accountId
			? connectedAccounts.find((candidate) => candidate.id === active.reply.accountId)
			: null;
		const threadText = active.turns
			.map((turn) => `${turn.from === "me" ? "Us" : active.user.handle}: ${turn.text}`)
			.join("\n");
		const idea = {
			id: randomUUID(),
			title: `Follow up with ${active.user.name}`.slice(0, 72),
			body: [
				`Turn this ${active.platform} ${active.type} into a post idea.`,
				`Account: ${active.toAccount}`,
				`Thread:\n${threadText || active.snippet}`,
			].join("\n\n"),
			linkUrl: null,
			imageUrl: null,
			audioUrl: null,
			transcript: null,
			status: "inbox",
			accountId: active.reply.accountId,
			groupId: account?.groupId ?? null,
			source: "rough",
			variants: [],
			createdAt: now,
			updatedAt: now,
		};
		const key = ideasBoardKey(authUser?.id ?? null);
		try {
			const raw = window.localStorage.getItem(key);
			const existing = raw ? JSON.parse(raw) : [];
			const next = Array.isArray(existing) ? [idea, ...existing] : [idea];
			window.localStorage.setItem(key, JSON.stringify(next));
			appToast.success("Added to Ideas", {
				description: "Ready to shape into a post.",
				action: {
					label: "Open",
					onClick: () => navigate("/ideas"),
				},
			});
		} catch (error) {
			appToast.error("Could not add idea", {
				description: error instanceof Error ? error.message : undefined,
			});
		}
	}, [active, authUser?.id, connectedAccounts, navigate]);

	const commandActions = useMemo<InboxCommand[]>(() => {
		const commands: InboxCommand[] = [];
		for (const member of teamMembers) {
			commands.push({
				id: `assign:${member.id}`,
				label: `Assign to ${member.name}`,
				group: "Assign",
				run: () => {
					if (active)
						void assignInboxItem(
							inboxAssignmentSource(active),
							active.id,
							member.id,
						);
				},
			});
		}
		return commands;
	}, [active, assignInboxItem, teamMembers]);

	useEffect(() => {
		const onKey = (e: KeyboardEvent) => {
			const target = e.target as HTMLElement | null;
			const typing =
				target &&
				(target.tagName === "INPUT" ||
					target.tagName === "TEXTAREA" ||
					target.isContentEditable);
			if (typing) {
				if (e.key === "Escape") (target as HTMLElement).blur();
				if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
					e.preventDefault();
					send();
				}
				return;
			}
			if (!filtered.length) return;
			const idx = filtered.findIndex((c) => c.id === activeId);
			if (e.key === "j" || e.key === "ArrowDown") {
				e.preventDefault();
				setActiveId(
					filtered[Math.min(filtered.length - 1, idx < 0 ? 0 : idx + 1)]!.id,
				);
			} else if (e.key === "k" || e.key === "ArrowUp") {
				e.preventDefault();
				setActiveId(filtered[Math.max(0, idx < 0 ? 0 : idx - 1)]!.id);
			} else if (e.key.toLowerCase() === "r" && active) {
				e.preventDefault();
				replyRef.current?.focus();
			} else if (e.key === "a" && active) {
				e.preventDefault();
				if (!authUser) return appToast.error("Not signed in");
				void assignInboxItem(
					inboxAssignmentSource(active),
					active.id,
					authUser.id,
				).then((ok) =>
					ok
						? appToast.success("Assigned to you", {
								description: active.user.handle,
							})
						: appToast.error("Could not assign"),
				);
			} else if (e.key.toLowerCase() === "d" && active) {
				e.preventDefault();
				setConversationDone(active, !doneKeys.has(conversationKey(active)));
			} else if (e.key.toLowerCase() === "i" && active) {
				e.preventDefault();
				convertActiveToIdea();
			}
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, [
		filtered,
		activeId,
		active,
		assignInboxItem,
		authUser,
		send,
		doneKeys,
		setConversationDone,
		convertActiveToIdea,
	]);

	const hasAnyConversations = conversations.length > 0;
	const showNoAccountsEmpty =
		onboarding.ready && !onboarding.hasConnectedAccounts;
	const showSyncPendingEmpty =
		onboarding.ready &&
		onboarding.hasConnectedAccounts &&
		!inboxLoading &&
		!hasAnyConversations;

	return {
		active,
		activeDone,
		activeNeedsAttention,
		activeSuggestion,
		commandActions,
		commandOpen,
		connectedAccounts,
		conversations,
		counts,
		draftingLabel,
		doneKeys,
		filtered,
		identityAdvisories,
		inboxLoading,
		keyForConversation,
		mobileActive,
		mobileActiveId,
		navigate,
		onTablistKey,
		platform: activePlatform,
		regenerateSuggestion,
		isSending: sendingConversationId === active?.id,
		rejectSuggestion,
		acceptSuggestion,
		convertActiveToIdea,
		toggleActiveDone,
		toggleInstagramCommentLike,
		likedCommentIds,
		likeBusyIds,
		replyRef,
		replyText,
		sendingConversationId,
		safetyWarning,
		scopedAccount,
		search,
		send,
		setActiveId,
		setCommandOpen,
		setMobileActiveId,
		setPlatform: setInboxPlatform,
		setReplyText,
		setSafetyWarning,
		setSearch,
		setTab,
		setViewingThread,
		showNoAccountsEmpty,
		showSyncPendingEmpty,
		startDrafting,
		stopDrafting,
		suggestionsByKey,
		tab,
		viewingThread,
		workflowCounts,
		workflowFilter,
		setWorkflowFilter,
	};
}
