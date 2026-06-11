import { cn } from "@/lib/utils";
import { Avatar } from "./helpers";
import type { ChatTurn, Conversation } from "./types";

export function ThreadMessages({
	conversation,
}: {
	conversation: Conversation;
}) {
	const c = conversation;
	return (
		<div className="flex-1 min-w-0 flex flex-col gap-3">
			{c.postContext && (
				<div className="rounded-xl border border-border bg-card p-3.5 shadow-sm flex gap-3 items-start mb-1">
					<div
						className="size-10 rounded-md shrink-0"
						style={{
							background: `linear-gradient(135deg, ${c.postContext.accent}, color-mix(in srgb, ${c.postContext.accent} 50%, var(--color-ink)))`,
						}}
						aria-hidden="true"
					/>
					<div className="min-w-0 flex-1">
						<div className="text-[0.59375rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-0.5">
							{c.type === "comment" ? "On your post" : "Mentioned in"}
						</div>
						<p className="text-[0.75rem] text-muted-foreground leading-[1.5] line-clamp-2">
							{c.postContext.caption}
						</p>
						<div className="mt-1 text-[0.625rem] text-muted-foreground tabular-nums">
							{c.postContext.sentAt} · {c.postContext.kind}
						</div>
					</div>
				</div>
			)}

			{c.turns.map((turn) => (
				<ChatBubble
					key={turn.id}
					turn={turn}
					sender={turn.from === "me" ? null : c.user}
				/>
			))}
		</div>
	);
}

function ChatBubble({
	turn,
	sender,
}: {
	turn: ChatTurn;
	sender: { name: string; avatarFrom: string; avatarTo: string } | null;
}) {
	const mine = turn.from === "me";
	return (
		<div
			className={cn(
				"flex gap-2.5 items-end",
				mine ? "flex-row-reverse" : "flex-row",
			)}
		>
			{sender ? (
				<Avatar
					from={sender.avatarFrom}
					to={sender.avatarTo}
					initial={sender.name[0] ?? "?"}
					size={28}
				/>
			) : (
				<div className="size-7 shrink-0" aria-hidden="true" />
			)}
			<div
				className={cn(
					"flex flex-col max-w-[520px] min-w-0",
					mine ? "items-end" : "items-start",
				)}
			>
				<div
					className={cn(
						"px-3.5 py-2.5 rounded-xl text-[0.84375rem] leading-[1.5] tracking-[-0.005em]",
						mine
							? "bg-primary text-primary-foreground rounded-br-[4px]"
							: "bg-card border border-border text-foreground rounded-bl-[4px]",
					)}
					style={
						mine
							? {
									boxShadow:
										"0 2px 6px color-mix(in_srgb,var(--color-foreground)_12%,transparent)",
								}
							: undefined
					}
				>
					{turn.text}
				</div>
				<span className="mt-1 text-[0.625rem] text-muted-foreground tabular-nums px-1">
					{turn.time}
				</span>
			</div>
		</div>
	);
}
