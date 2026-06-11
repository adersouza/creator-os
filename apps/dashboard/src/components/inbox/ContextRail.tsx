import {
	Award,
	CheckCircle2,
	History,
	Lightbulb,
	Sparkles,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { Separator } from "@/components/ui/Separator";
import { cn } from "@/lib/utils";
import { formatFollowers, sentimentColor } from "./helpers";
import type { Conversation, InboxSuggestion } from "./types";

function ContextRow({
	label,
	value,
	dot,
	capitalize,
	color,
}: {
	label: string;
	value: string;
	dot?: string | undefined;
	capitalize?: boolean | undefined;
	color?: string | undefined;
}) {
	return (
		<div className="flex items-center justify-between gap-2">
			<span className="text-muted-foreground text-[0.6875rem]">{label}</span>
			<span
				className={cn(
					"inline-flex items-center gap-1.5 text-foreground font-medium tabular-nums",
					capitalize && "capitalize",
				)}
				style={color ? { color } : undefined}
			>
				{dot && (
					<span className="size-1.5 rounded-full" style={{ background: dot }} />
				)}
				{value}
			</span>
		</div>
	);
}

export function ContextRail({
	conversation,
	identityAdvisory,
	suggestion,
	isDone,
	needsAttention,
	onToggleDone,
	onConvertToIdea,
	onUseSuggestion,
}: {
	conversation: Conversation;
	identityAdvisory?: string | undefined;
	suggestion?: InboxSuggestion | undefined;
	isDone?: boolean | undefined;
	needsAttention?: boolean | undefined;
	onToggleDone?: (() => void) | undefined;
	onConvertToIdea?: (() => void) | undefined;
	onUseSuggestion?: ((text: string) => void) | undefined;
}) {
	const c = conversation;
	return (
		<aside className="hidden lg:flex w-64 xl:w-72 shrink-0 flex-col gap-3">
			<NovaCard
				eyebrow="Contact"
				variant="compact"
				contentClassName="p-3.5 pt-0"
			>
				<div className="flex items-center justify-between gap-3">
					<div className="min-w-0">
						<div className="truncate text-[0.875rem] font-semibold text-foreground">
							@{c.user.handle}
						</div>
						<div className="mt-0.5 truncate text-[0.6875rem] text-muted-foreground">
							{c.user.name} · {c.platform}
						</div>
					</div>
					<Badge
						tone={needsAttention && !isDone ? "oxblood" : "outline"}
						className={cn(
							"h-7 px-2 text-[0.625rem] uppercase tracking-[0.08em]",
							isDone && "text-[color:var(--color-health-good)]",
						)}
					>
						{isDone ? "Done" : needsAttention ? "High" : "Open"}
					</Badge>
				</div>
			</NovaCard>
			{c.isTopEngager && (
				<NovaCard
					variant="panel"
					className="border-[color-mix(in_srgb,var(--color-gold)_22%,var(--color-border))]"
					contentClassName="p-3.5"
				>
					<div
						className="flex items-center gap-1.5 mb-1.5"
						style={{ color: "var(--color-gold)" }}
					>
						<Award data-icon="inline-start" />
						<span className="text-[0.59375rem] font-semibold uppercase tracking-[0.14em]">
							Top engager
						</span>
					</div>
					<p className="text-[0.71875rem] text-muted-foreground leading-[1.5]">
						In your top 1% this month.
					</p>
				</NovaCard>
			)}
			{identityAdvisory && (
				<NovaCard
					eyebrow="Identity stitching"
					variant="compact"
					contentClassName="p-3.5 pt-0"
				>
					<p className="text-[0.71875rem] text-muted-foreground leading-[1.5]">
						{identityAdvisory}
					</p>
				</NovaCard>
			)}
			<NovaCard
				eyebrow="Audience"
				variant="compact"
				contentClassName="p-3.5 pt-0"
			>
				<div className="flex flex-col gap-2 text-[0.71875rem]">
					<ContextRow
						label="Followers"
						value={formatFollowers(c.user.followers)}
					/>
					<ContextRow
						label="Group"
						value={c.network.label}
						dot={c.network.color}
					/>
					<ContextRow
						label="Sentiment"
						value={c.sentiment ?? "neutral"}
						capitalize
						color={sentimentColor(c.sentiment)}
					/>
					<ContextRow label="Verified" value={c.user.verified ? "Yes" : "No"} />
				</div>
			</NovaCard>
			<NovaCard
				eyebrow={
					<span className="inline-flex items-center gap-1.5">
						<History data-icon="inline-start" />
						Conversation history
					</span>
				}
				variant="compact"
				contentClassName="p-3.5 pt-0"
			>
				<div className="flex flex-col gap-2 text-[0.71875rem] text-muted-foreground">
					<ContextRow label="Last touch" value={c.ago} />
					<ContextRow label="Thread turns" value={String(c.turns.length)} />
					<ContextRow
						label="Source"
						value={c.type === "dm" ? "DM" : c.type}
						capitalize
					/>
				</div>
			</NovaCard>
			<NovaCard
				eyebrow={
					<span className="inline-flex items-center gap-1.5">
						<Sparkles data-icon="inline-start" />
						Next step
					</span>
				}
				variant="compact"
				contentClassName="p-3.5 pt-0"
			>
				<div className="flex flex-col gap-2">
					{suggestion && onUseSuggestion ? (
						<Button
							type="button"
							onClick={() => onUseSuggestion(suggestion.suggestion_text)}
							variant="secondary"
							size="sm"
							className="min-h-9 justify-start px-3 text-left text-[0.75rem]"
						>
							Use AI draft
						</Button>
					) : null}
					{onConvertToIdea ? (
						<Button
							type="button"
							onClick={onConvertToIdea}
							variant="secondary"
							size="sm"
							className="min-h-9 justify-start px-3 text-left text-[0.75rem]"
						>
							<Lightbulb data-icon="inline-start" aria-hidden="true" />
							Convert to idea
						</Button>
					) : null}
					{onToggleDone ? (
						<Button
							type="button"
							onClick={onToggleDone}
							aria-pressed={isDone}
							variant="secondary"
							size="sm"
							className="min-h-9 justify-start px-3 text-left text-[0.75rem]"
						>
							<CheckCircle2 data-icon="inline-start" aria-hidden="true" />
							{isDone ? "Reopen conversation" : "Mark done"}
						</Button>
					) : null}
					{!suggestion && !onConvertToIdea && !onToggleDone ? (
						<>
							<Separator />
							<p className="text-[0.71875rem] text-muted-foreground">
								No follow-up actions available.
							</p>
						</>
					) : null}
				</div>
			</NovaCard>
		</aside>
	);
}
