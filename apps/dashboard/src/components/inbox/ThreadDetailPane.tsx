import type React from "react";
import {
	CheckCircle2,
	ChevronLeft,
	Heart,
	Lightbulb,
	MessageSquare,
} from "lucide-react";
import { AssignmentChip } from "@/components/inbox/AssignmentChip";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Separator } from "@/components/ui/Separator";
import { cn } from "@/lib/utils";
import { ContextRail } from "./ContextRail";
import {
	Avatar,
	Kbd,
	PlatformGlyph,
	TYPE_ICON,
	inboxAssignmentSource,
} from "./helpers";
import { ReplyComposer } from "./ReplyComposer";
import { SentimentBadge } from "./SentimentBadge";
import { ThreadMessages } from "./ThreadMessages";
import type { Conversation, InboxSuggestion } from "./types";

export function ThreadDetailPane({
	conversation,
	suggestion,
	identityAdvisory,
	replyText,
	onReplyChange,
	onSend,
	isSending,
	onBack,
	onRegenerateSuggestion,
	presenceLabel,
	onComposerFocus,
	onComposerBlur,
	replyRef,
	liked,
	likeBusy,
	onToggleLike,
	isDone,
	needsAttention,
	onToggleDone,
	onConvertToIdea,
	mobileChrome = false,
}: {
	conversation: Conversation;
	suggestion?: InboxSuggestion | undefined;
	identityAdvisory?: string | undefined;
	replyText: string;
	onReplyChange: (v: string) => void;
	onSend: () => void;
	isSending?: boolean | undefined;
	onBack: () => void;
	onRegenerateSuggestion?: (() => void) | undefined;
	presenceLabel?: string | null | undefined;
	onComposerFocus?: (() => void) | undefined;
	onComposerBlur?: (() => void) | undefined;
	replyRef: React.RefObject<HTMLTextAreaElement | null>;
	liked?: boolean | undefined;
	likeBusy?: boolean | undefined;
	onToggleLike?: (() => void) | undefined;
	isDone?: boolean | undefined;
	needsAttention?: boolean | undefined;
	onToggleDone?: (() => void) | undefined;
	onConvertToIdea?: (() => void) | undefined;
	/** Promote header to a glass strip on mobile (matches MobileInbox top bar). */
	mobileChrome?: boolean | undefined;
}) {
	const c = conversation;
	const TypeIcon = TYPE_ICON[c.type];

	return (
		<>
			<div
				className={cn(
					"min-h-16 flex flex-wrap items-center justify-between gap-2 px-3 md:px-5 py-3 shrink-0",
					mobileChrome
						? "rounded-none border-x-0 border-t-0 border-b border-border bg-card shadow-sm sticky top-0 z-20"
						: "border-b border-border",
					c.sentiment === "negative" &&
						"bg-[color-mix(in_srgb,var(--color-negative)_7%,transparent)] ring-1 ring-inset ring-[color-mix(in_srgb,var(--color-negative)_22%,transparent)]",
				)}
			>
				<div className="flex items-center gap-2.5 min-w-0 flex-1 basis-[220px]">
					<Button
						type="button"
						onClick={onBack}
						aria-label="Back to list"
						variant="ghost"
						size="icon"
						className="size-8 md:hidden"
					>
						<ChevronLeft aria-hidden="true" />
					</Button>
					<Avatar
						from={c.user.avatarFrom}
						to={c.user.avatarTo}
						initial={c.user.name[0] ?? "?"}
						size={28}
					/>
					<div className="min-w-0">
						<div className="text-[0.875rem] font-semibold text-foreground truncate tracking-[-0.005em] flex items-center gap-1.5">
							<span className="truncate">{c.user.name}</span>
							<SentimentBadge sentiment={c.sentiment} compact />
						</div>
						<div className="mt-0.5 text-[0.6875rem] text-muted-foreground flex items-center gap-1">
							<PlatformGlyph platform={c.platform} className="size-2.5" />
							<span>@{c.user.handle}</span>
							<span className="text-muted-foreground/60">·</span>
							<TypeIcon className="size-2.5" aria-hidden="true" />
							<span className="capitalize">
								{c.type === "dm" ? "DM" : c.type}
							</span>
							<span className="text-muted-foreground/60">·</span>
							<span>to {c.toAccount}</span>
						</div>
					</div>
				</div>
				<div className="flex min-w-0 flex-wrap items-center justify-end gap-1.5 shrink">
					{needsAttention && !isDone ? (
						<Badge tone="oxblood" className="h-8 px-2.5 text-[0.75rem]">
							Needs attention
						</Badge>
					) : null}
					{onConvertToIdea ? (
						<Button
							type="button"
							onClick={onConvertToIdea}
							aria-label="Convert thread to idea"
							variant="secondary"
							size="sm"
							className="h-8 px-2.5 text-[0.75rem]"
						>
							<Lightbulb aria-hidden="true" />
							Idea
						</Button>
					) : null}
					{onToggleDone ? (
						<Button
							type="button"
							onClick={onToggleDone}
							aria-pressed={isDone}
							aria-label={
								isDone ? "Reopen conversation" : "Mark conversation done"
							}
							variant="secondary"
							size="sm"
							className={cn(
								"h-8 px-2.5 text-[0.75rem]",
								isDone && "text-[color:var(--color-health-good)]",
							)}
						>
							<CheckCircle2
								className={cn(isDone && "fill-current")}
								aria-hidden="true"
							/>
							{isDone ? "Done" : "Mark done"}
						</Button>
					) : null}
					{c.platform === "instagram" &&
						c.type === "comment" &&
						onToggleLike && (
							<Button
								type="button"
								onClick={onToggleLike}
								disabled={likeBusy}
								aria-pressed={liked}
								aria-label={liked ? "Unlike comment" : "Like comment"}
								variant="secondary"
								size="sm"
								className={cn(
									"h-8 px-2.5 text-[0.75rem]",
									liked && "text-[color:var(--color-oxblood)]",
								)}
							>
								<Heart
									className={cn(liked && "fill-current")}
									aria-hidden="true"
								/>
								{liked ? "Liked" : "Like"}
							</Button>
						)}
					<AssignmentChip source={inboxAssignmentSource(c)} messageId={c.id} />
				</div>
			</div>

			<div className="flex-1 overflow-y-auto min-h-0 px-4 md:px-6 py-5 md:py-6">
				<div className="flex flex-col lg:flex-row gap-5">
					<ThreadMessages conversation={c} />
					<ContextRail
						conversation={c}
						identityAdvisory={identityAdvisory}
						suggestion={suggestion}
						isDone={isDone}
						needsAttention={needsAttention}
						onToggleDone={onToggleDone}
						onConvertToIdea={onConvertToIdea}
						onUseSuggestion={onReplyChange}
					/>
				</div>
			</div>

			{presenceLabel && (
				<div className="px-4 md:px-8 py-2 text-[0.71875rem] text-muted-foreground">
					<Separator className="mb-2" />
					{presenceLabel}
				</div>
			)}
			<ReplyComposer
				handle={c.user.handle}
				replyText={replyText}
				suggestion={suggestion}
				onReplyChange={onReplyChange}
				onSend={onSend}
				isSending={isSending}
				onRegenerateSuggestion={onRegenerateSuggestion}
				onFocus={onComposerFocus}
				onBlur={onComposerBlur}
				replyRef={replyRef}
			/>
		</>
	);
}

export function EmptyDetail() {
	return (
		<NovaEmpty
			className="m-4 min-h-[calc(100%-2rem)] flex-1 border-0 bg-transparent"
			icon={<MessageSquare data-icon aria-hidden="true" />}
			title="Select a message"
			description="Pick a conversation on the left to read and reply."
		>
			<p className="text-[0.75rem] text-muted-foreground">
				Press <Kbd>R</Kbd> to focus the composer.
			</p>
		</NovaEmpty>
	);
}
