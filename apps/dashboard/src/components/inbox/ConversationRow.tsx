import { ChevronDown, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ListRow } from "@/components/ui/ListRow";
import {
	PopoverContent,
	PopoverRoot,
	PopoverTrigger,
} from "@/components/ui/Popover";
import { cn } from "@/lib/utils";
import { Avatar, TYPE_ICON } from "./helpers";
import { SentimentBadge } from "./SentimentBadge";
import type { Conversation, InboxSuggestion } from "./types";

export function ConversationRow({
	conversation,
	active,
	identityAdvisory,
	suggestion,
	done,
	needsAttention,
	onClick,
	onAcceptSuggestion,
	onRejectSuggestion,
}: {
	conversation: Conversation;
	active: boolean;
	identityAdvisory?: string | undefined;
	suggestion?: InboxSuggestion | undefined;
	done?: boolean | undefined;
	needsAttention?: boolean | undefined;
	onClick: () => void;
	onAcceptSuggestion?: ((suggestion: InboxSuggestion) => void) | undefined;
	onRejectSuggestion?: ((suggestion: InboxSuggestion) => void) | undefined;
}) {
	const c = conversation;
	const TypeIcon = TYPE_ICON[c.type];
	const priorityLabel = done
		? "Done"
		: needsAttention || c.sentiment === "negative"
			? "High"
			: c.isTopEngager
				? "Medium"
				: "Low";
	const priorityClass = done
		? "border-[color-mix(in_srgb,var(--color-health-good)_28%,transparent)] bg-[color-mix(in_srgb,var(--color-health-good)_9%,transparent)] text-[color:var(--color-health-good)]"
		: priorityLabel === "High"
			? "border-[color-mix(in_srgb,var(--color-oxblood)_28%,transparent)] bg-[color-mix(in_srgb,var(--color-oxblood)_9%,transparent)] text-[color:var(--color-oxblood)]"
			: priorityLabel === "Medium"
				? "border-[color-mix(in_srgb,var(--color-gold)_28%,transparent)] bg-[color-mix(in_srgb,var(--color-gold)_10%,transparent)] text-[color:var(--color-gold)]"
				: "border-border bg-muted text-muted-foreground";
	return (
		<div
			className={cn(
				done
					? "opacity-70"
					: c.sentiment === "negative" &&
							"rounded-md bg-[color-mix(in_srgb,var(--color-negative)_7%,transparent)] ring-1 ring-inset ring-[color-mix(in_srgb,var(--color-negative)_22%,transparent)]",
			)}
		>
			<ListRow
				onClick={onClick}
				selected={active}
				accentColor={c.network.color}
				density="compact"
				separator={false}
				pressFeedback
			>
				<div className="flex gap-2.5">
					<Avatar
						from={c.user.avatarFrom}
						to={c.user.avatarTo}
						initial={c.user.name[0] ?? "?"}
						size={34}
					/>
					<div className="min-w-0 flex-1">
						<div className="flex items-baseline justify-between gap-2 mb-0.5">
							<div className="flex items-center gap-1.5 min-w-0">
								<span className="text-[0.8125rem] truncate tracking-[-0.005em] font-semibold text-foreground">
									{c.user.name}
								</span>
								{c.user.verified && (
									<svg
										viewBox="0 0 12 12"
										className="size-3 shrink-0"
										aria-label="verified"
										style={{ color: "var(--color-oxblood)" }}
									>
										<path
											d="M6 0.5 L7.3 1.8 L9 1.5 L9.6 3.1 L11 4 L10.5 5.7 L11 7.3 L9.6 8.3 L9 9.9 L7.3 9.6 L6 10.9 L4.7 9.6 L3 9.9 L2.4 8.3 L1 7.3 L1.5 5.7 L1 4 L2.4 3.1 L3 1.5 L4.7 1.8 Z"
											fill="currentColor"
										/>
										<path
											d="M4 6 L5.4 7.4 L8 4.6"
											stroke="var(--color-primary-foreground)"
											strokeWidth="1.2"
											strokeLinecap="round"
											strokeLinejoin="round"
											fill="none"
										/>
									</svg>
								)}
								<TypeIcon
									className="size-3 shrink-0 text-muted-foreground"
									aria-hidden="true"
								/>
							</div>
							<div className="flex items-center gap-1.5 shrink-0">
								<span
									className={cn(
										"inline-flex h-5 items-center rounded-full border px-1.5 text-[0.59375rem] font-semibold uppercase tracking-[0.08em]",
										priorityClass,
									)}
								>
									{priorityLabel}
								</span>
								<span className="text-[0.65625rem] text-muted-foreground tabular-nums">
									{c.ago}
								</span>
							</div>
						</div>
						<p className="text-[0.75rem] leading-[1.45] line-clamp-2 text-muted-foreground">
							{c.snippet}
						</p>
						<div className="mt-2 flex items-center gap-1.5 text-[0.625rem] text-muted-foreground flex-wrap">
							<span className="inline-flex items-center gap-1">
								<span
									className="size-1 rounded-full"
									style={{ background: c.network.color }}
								/>
								{c.network.label}
							</span>
							<span className="text-muted-foreground/60">·</span>
							<span className="font-mono text-[0.625rem] text-muted-foreground">
								{c.toAccount}
							</span>
							<span className="text-muted-foreground/60">·</span>
							<SentimentBadge sentiment={c.sentiment} compact />
							{needsAttention && !done && (
								<>
									<span className="text-muted-foreground/60">·</span>
									<span className="text-[color:var(--color-oxblood)] font-medium">
										Needs attention
									</span>
								</>
							)}
							{done && (
								<>
									<span className="text-muted-foreground/60">·</span>
									<span className="text-[color:var(--color-health-good)] font-medium">
										Done
									</span>
								</>
							)}
							{identityAdvisory && (
								<>
									<span className="text-muted-foreground/60">·</span>
									<span className="text-muted-foreground">
										{identityAdvisory}
									</span>
								</>
							)}
							{suggestion && (
								<>
									<Badge tone="outline" className="text-[0.625rem]">
										<Sparkles aria-hidden="true" />
										AI provenance
									</Badge>
									<SuggestionChip
										suggestion={suggestion}
										onAccept={onAcceptSuggestion}
										onReject={onRejectSuggestion}
									/>
								</>
							)}
						</div>
					</div>
				</div>
			</ListRow>
		</div>
	);
}

function SuggestionChip({
	suggestion,
	onAccept,
	onReject,
}: {
	suggestion: InboxSuggestion;
	onAccept?: ((suggestion: InboxSuggestion) => void) | undefined;
	onReject?: ((suggestion: InboxSuggestion) => void) | undefined;
}) {
	return (
		<PopoverRoot>
			<PopoverTrigger asChild>
				<Button
					type="button"
					onClick={(event) => event.stopPropagation()}
					variant="outline"
					size="sm"
					className="min-h-8 px-2.5 py-1 text-[0.625rem]"
				>
					<Sparkles aria-hidden="true" />
					AI draft
					<ChevronDown aria-hidden="true" />
				</Button>
			</PopoverTrigger>
			<PopoverContent
				className="w-72 p-3"
				onClick={(event) => event.stopPropagation()}
			>
				<div className="text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
					Suggested reply
				</div>
				<p className="mt-1.5 text-[0.75rem] leading-[1.5] text-foreground">
					{suggestion.suggestion_text}
				</p>
				{suggestion.reasoning && (
					<p className="mt-2 text-[0.6875rem] leading-[1.45] text-muted-foreground">
						{suggestion.reasoning}
					</p>
				)}
				{suggestion.alternatives.length > 0 && (
					<div className="mt-2 flex flex-col gap-1">
						{suggestion.alternatives.map((alt) => (
							<Button
								type="button"
								key={alt}
								onClick={() =>
									onAccept?.({ ...suggestion, suggestion_text: alt })
								}
								variant="ghost"
								size="sm"
								className="min-h-8 w-full justify-start px-2 py-1 text-left text-[0.6875rem]"
							>
								{alt}
							</Button>
						))}
					</div>
				)}
				<div className="mt-3 flex justify-end gap-1.5">
					<Button
						type="button"
						onClick={() => onReject?.(suggestion)}
						variant="ghost"
						size="sm"
						className="h-8 px-2 text-[0.75rem]"
					>
						Reject
					</Button>
					<Button
						type="button"
						onClick={() => onAccept?.(suggestion)}
						size="sm"
						className="h-8 px-2.5 text-[0.75rem] font-medium"
					>
						Accept
					</Button>
				</div>
			</PopoverContent>
		</PopoverRoot>
	);
}
