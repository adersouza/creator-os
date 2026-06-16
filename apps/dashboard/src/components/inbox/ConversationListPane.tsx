import { useMemo, useState } from "react";
import {
	CheckCircle2,
	Inbox as InboxIcon,
	Search,
	SlidersHorizontal,
} from "lucide-react";
import type { ConnectedAccount } from "@/hooks/useConnectedAccounts";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { ListRow } from "@/components/ui/ListRow";
import { NovaEmpty } from "@/components/ui/NovaPrimitives";
import { TogglePill } from "@/components/ui/TogglePill";
import { VirtualizedList } from "@/components/ui/VirtualizedList";
import { cn } from "@/lib/utils";
import { MobilePageShell, MobileSection } from "@/components/layout/mobile";
import { ConversationRow } from "./ConversationRow";
import { SentimentBadge } from "./SentimentBadge";
import { Avatar, tabsForPlatform, TYPE_ICON } from "./helpers";
import { isEmojiOnlyComment } from "./helpers";
import { needsAttention } from "./helpers";
import type {
	Conversation,
	InboxSuggestion,
	InboxWorkflowFilter,
	PlatformKind,
	TabKey,
} from "./types";

export function ConversationListPane({
	conversations,
	activeConversation,
	tab,
	platform,
	search,
	viewingThread,
	identityAdvisories,
	suggestionsByKey,
	keyForConversation,
	onSearchChange,
	workflowFilter,
	workflowCounts,
	doneKeys,
	onWorkflowFilterChange,
	onOpen,
	onAcceptSuggestion,
	onRejectSuggestion,
}: {
	conversations: Conversation[];
	activeConversation: Conversation | null;
	tab: TabKey;
	platform: PlatformKind;
	search: string;
	viewingThread: boolean;
	identityAdvisories: Map<string, string>;
	suggestionsByKey: Map<string, InboxSuggestion>;
	keyForConversation: (conversation: Conversation) => string;
	onSearchChange: (v: string) => void;
	workflowFilter: InboxWorkflowFilter;
	workflowCounts: Record<InboxWorkflowFilter, number>;
	doneKeys: Set<string>;
	onWorkflowFilterChange: (filter: InboxWorkflowFilter) => void;
	onOpen: (id: string) => void;
	onAcceptSuggestion: (suggestion: InboxSuggestion) => void;
	onRejectSuggestion: (suggestion: InboxSuggestion) => void;
}) {
	const [noiseExpanded, setNoiseExpanded] = useState(false);
	const noise = useMemo(
		() => conversations.filter(isEmojiOnlyComment),
		[conversations],
	);
	const visible = useMemo(
		() => conversations.filter((c) => noiseExpanded || !isEmojiOnlyComment(c)),
		[conversations, noiseExpanded],
	);

	return (
		<aside
			className={cn(
				"flex w-full shrink-0 flex-col border-r border-border bg-card transition-transform duration-300 md:w-[384px] md:translate-x-0 xl:w-[420px]",
				viewingThread
					? "-translate-x-full absolute md:relative inset-0 md:inset-auto h-full z-10 md:z-auto"
					: "translate-x-0",
			)}
		>
			<div className="border-b border-border px-4 pb-3 pt-4">
				<div className="mb-3 flex items-center justify-between gap-3">
					<div className="min-w-0">
						<div className="text-[0.71875rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
							Conversations
						</div>
						<div className="mt-0.5 text-[0.8125rem] font-medium text-foreground">
							{visible.length} visible
						</div>
					</div>
					<Badge tone="outline" className="h-8 gap-1.5">
						<SlidersHorizontal aria-hidden="true" />
						Filter
					</Badge>
				</div>
				<label htmlFor="inbox-search-desktop" className="block">
					<Input
						id="inbox-search-desktop"
						data-inbox-search
						type="search"
						value={search}
						onChange={(e) => onSearchChange(e.target.value)}
						placeholder="Search messages"
						leadingIcon={<Search aria-hidden="true" />}
						sizeVariant="lg"
						className="bg-muted"
					/>
				</label>
				<div className="mt-2.5 flex items-center gap-1.5 overflow-x-auto hide-scrollbar">
					<WorkflowPill
						active={workflowFilter === "attention"}
						label="Needs attention"
						count={workflowCounts.attention}
						onClick={() => onWorkflowFilterChange("attention")}
					/>
					<WorkflowPill
						active={workflowFilter === "open"}
						label="Open"
						count={workflowCounts.open}
						onClick={() => onWorkflowFilterChange("open")}
					/>
					<WorkflowPill
						active={workflowFilter === "done"}
						label="Done"
						count={workflowCounts.done}
						onClick={() => onWorkflowFilterChange("done")}
					/>
				</div>
			</div>

			<div className="flex min-h-0 flex-1 flex-col px-2.5 py-2.5">
				{noise.length > 1 && (
					<Button
						type="button"
						onClick={() => setNoiseExpanded((v) => !v)}
						variant="ghost"
						size="sm"
						className="mb-2 h-auto w-full justify-start px-3 py-2 text-left text-[0.75rem]"
					>
						{noiseExpanded ? "Hide" : "Show"} {noise.length} emoji-only comments
					</Button>
				)}
				<VirtualizedList
					items={visible}
					estimateSize={132}
					height="100%"
					getItemKey={(conversation) => conversation.id}
					ariaLabel="Conversation list"
					className="min-h-0 flex-1 rounded-none border-0 bg-transparent"
					contentClassName="pb-2"
					empty={
						<NovaEmpty
							className="m-8"
							icon={<CheckCircle2 data-icon aria-hidden="true" />}
							title="Inbox zero"
							description={`Nothing in ${
								tabsForPlatform(platform)
									.find((t) => t.id === tab)
									?.label.toLowerCase() ?? "this view"
							} for this filter.`}
						/>
					}
					renderItem={(c) => (
						<div className="pb-2.5">
							<ConversationRow
								conversation={c}
								active={activeConversation?.id === c.id}
								identityAdvisory={identityAdvisories.get(c.id)}
								suggestion={suggestionsByKey.get(keyForConversation(c))}
								done={doneKeys.has(keyForConversation(c))}
								needsAttention={needsAttention(
									c,
									suggestionsByKey.get(keyForConversation(c)),
								)}
								onClick={() => onOpen(c.id)}
								onAcceptSuggestion={onAcceptSuggestion}
								onRejectSuggestion={onRejectSuggestion}
							/>
						</div>
					)}
				/>
			</div>
		</aside>
	);
}

function WorkflowPill({
	active,
	label,
	count,
	onClick,
}: {
	active: boolean;
	label: string;
	count: number;
	onClick: () => void;
}) {
	return (
		<TogglePill
			active={active}
			onClick={onClick}
			className="h-8 text-[0.75rem]"
			trailing={
				<span
					className={cn(
						"text-[0.65625rem] tabular-nums px-1 rounded-full",
						active ? "td-on-primary-count" : "text-muted-foreground",
					)}
				>
					{count}
				</span>
			}
		>
			{label}
		</TogglePill>
	);
}

export function MobileInbox({
	conversations,
	totalCount,
	scopedAccount,
	activeId,
	tab,
	platform,
	tabCounts,
	search,
	workflowFilter,
	workflowCounts,
	doneKeys,
	suggestionsByKey,
	keyForConversation,
	onOpen,
	onTabChange,
	onSearchChange,
	onWorkflowFilterChange,
}: {
	conversations: Conversation[];
	totalCount: number;
	scopedAccount: ConnectedAccount | null;
	activeId: string | null;
	tab: TabKey;
	platform: PlatformKind;
	tabCounts: Record<TabKey, number>;
	search: string;
	workflowFilter: InboxWorkflowFilter;
	workflowCounts: Record<InboxWorkflowFilter, number>;
	doneKeys: Set<string>;
	suggestionsByKey: Map<string, InboxSuggestion>;
	keyForConversation: (conversation: Conversation) => string;
	onOpen: (id: string) => void;
	onTabChange: (t: TabKey) => void;
	onSearchChange: (v: string) => void;
	onWorkflowFilterChange: (filter: InboxWorkflowFilter) => void;
}) {
	const messageTabs = tabsForPlatform(platform);
	const showTabFilters = !scopedAccount || messageTabs.length > 1;

	return (
		<MobilePageShell>
			<style>{`
        @keyframes inbox-msg-pulse-mobile {
          0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--color-oxblood) 35%, transparent); }
          70% { box-shadow: 0 0 0 6px color-mix(in srgb, var(--color-oxblood) 0%, transparent); }
        }
        .inbox-live-dot-mobile { animation: inbox-msg-pulse-mobile 2s ease-out infinite; }
        @media (prefers-reduced-motion: reduce) { .inbox-live-dot-mobile { animation: none; } }
      `}</style>

			{/* Hero — mirrors desktop Inbox header */}
			<header className="mb-4">
				<div className="flex items-center gap-1.5">
					<span
						className="size-1.5 rounded-full inbox-live-dot-mobile"
						style={{ background: "var(--color-oxblood)" }}
						aria-hidden="true"
					/>
					<span className="text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-[color:var(--color-oxblood)]">
						Messages
					</span>
				</div>
				<h1 className="mt-1 text-[1.625rem] font-bold leading-none tracking-[-0.03em] text-foreground">
					Inbox
				</h1>
				<p className="mt-2 text-[0.8125rem] leading-[1.45] text-muted-foreground">
					{totalCount === 0
						? "Inbox zero."
						: `${totalCount} active conversation${totalCount === 1 ? "" : "s"}.`}
				</p>
				<div className="mt-2 flex flex-wrap gap-1.5">
					<Badge tone={totalCount > 0 ? "oxblood" : "secondary"}>
						{totalCount > 0 ? `${totalCount} active` : "Inbox zero"}
					</Badge>
					{scopedAccount ? (
						<Badge tone="outline">{scopedAccount.handle}</Badge>
					) : null}
				</div>
			</header>

			{/* Sticky filter strip */}
			<div className="sticky top-0 z-20 -mx-4 mb-3 rounded-none border-x-0 border-t-0 border-b border-border bg-card px-4 py-3 shadow-sm">
				<label htmlFor="inbox-search-mobile" className="block">
					<Input
						id="inbox-search-mobile"
						data-inbox-search
						type="search"
						value={search}
						onChange={(e) => onSearchChange(e.target.value)}
						placeholder="Search messages"
						leadingIcon={<Search aria-hidden="true" />}
						sizeVariant="lg"
						className="bg-muted"
					/>
				</label>
				{showTabFilters ? (
					<div className="mt-2.5 flex items-center gap-1.5 overflow-x-auto hide-scrollbar -mx-4 px-4 pb-1">
						{messageTabs.map((t) => {
							const active = t.id === tab;
							return (
								<TogglePill
									key={t.id}
									active={active}
									onClick={() => onTabChange(t.id)}
									trailing={
										<span
											className={cn(
												"text-[0.65625rem] tabular-nums px-1 rounded-full",
												active
													? "td-on-primary-count"
													: "text-muted-foreground",
											)}
										>
											{tabCounts[t.id]}
										</span>
									}
								>
									{t.label}
								</TogglePill>
							);
						})}
					</div>
				) : null}
				<div className="mt-2 flex items-center gap-1.5 overflow-x-auto hide-scrollbar -mx-4 px-4 pb-1">
					<WorkflowPill
						active={workflowFilter === "attention"}
						label="Needs attention"
						count={workflowCounts.attention}
						onClick={() => onWorkflowFilterChange("attention")}
					/>
					<WorkflowPill
						active={workflowFilter === "open"}
						label="Open"
						count={workflowCounts.open}
						onClick={() => onWorkflowFilterChange("open")}
					/>
					<WorkflowPill
						active={workflowFilter === "done"}
						label="Done"
						count={workflowCounts.done}
						onClick={() => onWorkflowFilterChange("done")}
					/>
				</div>
			</div>
			<ul className="flex flex-col gap-2">
				{conversations.length === 0 && totalCount === 0 ? (
					<li>
						<MobileSection>
							<NovaEmpty
								className="border-0 bg-transparent py-2"
								icon={<InboxIcon data-icon aria-hidden="true" />}
								title="Inbox syncs as messages arrive"
								description="Instagram DMs and Threads replies or mentions land here once the first sync completes."
							/>
						</MobileSection>
					</li>
				) : conversations.length === 0 ? (
					<li>
						<MobileSection>
							<NovaEmpty
								className="border-0 bg-transparent py-2"
								icon={<CheckCircle2 data-icon aria-hidden="true" />}
								title="Inbox zero"
								description={`Nothing in ${
									tabsForPlatform(platform)
										.find((t) => t.id === tab)
										?.label.toLowerCase() ?? "this view"
								} for this filter.`}
							/>
						</MobileSection>
					</li>
				) : (
					conversations.map((c) => (
						<MobileConversationRow
							key={c.id}
							conversation={c}
							active={activeId === c.id}
							done={doneKeys.has(keyForConversation(c))}
							needsAttention={needsAttention(
								c,
								suggestionsByKey.get(keyForConversation(c)),
							)}
							onOpen={() => onOpen(c.id)}
						/>
					))
				)}
			</ul>
		</MobilePageShell>
	);
}

function MobileConversationRow({
	conversation,
	active,
	done,
	needsAttention: attention,
	onOpen,
}: {
	conversation: Conversation;
	active: boolean;
	done?: boolean | undefined;
	needsAttention?: boolean | undefined;
	onOpen: () => void;
}) {
	const c = conversation;
	const TypeIcon = TYPE_ICON[c.type];
	return (
		<li>
			<ListRow
				onClick={onOpen}
				selected={active}
				accentColor={c.network.color}
				density="comfortable"
				separator={false}
				pressFeedback
				className={cn(
					"flex w-full items-start gap-3 rounded-xl border border-border bg-card text-left shadow-sm",
					done && "opacity-70",
					!done &&
						c.sentiment === "negative" &&
						"ring-1 ring-inset ring-[color-mix(in_srgb,var(--color-negative)_22%,transparent)]",
				)}
			>
				<Avatar
					from={c.user.avatarFrom}
					to={c.user.avatarTo}
					initial={c.user.name[0] ?? "?"}
					size={40}
				/>
				<div className="flex-1 min-w-0">
					<div className="flex items-baseline gap-1.5 mb-0.5">
						<span className="text-[0.8125rem] truncate tracking-[-0.005em] font-medium text-foreground">
							{c.user.name}
						</span>
						<TypeIcon
							className="size-3 shrink-0 text-muted-foreground"
							aria-hidden="true"
						/>
						<span className="ml-auto flex items-center gap-1.5 shrink-0">
							<span className="text-[0.65625rem] text-muted-foreground tabular-nums">
								{c.ago}
							</span>
						</span>
					</div>
					<p className="text-[0.78125rem] leading-[1.45] line-clamp-2 text-muted-foreground">
						{c.snippet}
					</p>
					<div className="mt-1.5 flex items-center gap-1.5 text-[0.65625rem] text-muted-foreground">
						<span
							className="size-1 rounded-full"
							style={{ backgroundColor: c.network.color }}
							aria-hidden="true"
						/>
						<span>{c.network.label}</span>
						<span className="text-muted-foreground/60">·</span>
						<span className="font-mono">{c.toAccount}</span>
						<span className="text-muted-foreground/60">·</span>
						<SentimentBadge sentiment={c.sentiment} compact />
						{attention && !done ? (
							<>
								<span className="text-muted-foreground/60">·</span>
								<span className="text-[color:var(--color-oxblood)] font-medium">
									Needs attention
								</span>
							</>
						) : null}
						{done ? (
							<>
								<span className="text-muted-foreground/60">·</span>
								<span className="text-[color:var(--color-health-good)] font-medium">
									Done
								</span>
							</>
						) : null}
					</div>
				</div>
			</ListRow>
		</li>
	);
}
