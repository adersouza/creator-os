// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useState } from "react";
import type React from "react";
import { HelpCircle, MessageCircleReply, Reply, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/Button";
import {
	Command,
	CommandEmpty,
	CommandGroup,
	CommandItem,
	CommandList,
} from "@/components/ui/Command";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { Separator } from "@/components/ui/Separator";
import { Textarea } from "@/components/ui/Textarea";
import { Kbd } from "./helpers";
import type { InboxSuggestion } from "./types";

interface ReplySlashCommand {
	id: string;
	label: string;
	hint: string;
	run: () => void;
}

export function ReplyComposer({
	handle,
	replyText,
	suggestion,
	onReplyChange,
	onSend,
	isSending = false,
	onRegenerateSuggestion,
	onFocus,
	onBlur,
	replyRef,
}: {
	handle: string;
	replyText: string;
	suggestion?: InboxSuggestion | undefined;
	onReplyChange: (v: string) => void;
	onSend: () => void;
	isSending?: boolean | undefined;
	onRegenerateSuggestion?: (() => void) | undefined;
	onFocus?: (() => void) | undefined;
	onBlur?: (() => void) | undefined;
	replyRef: React.RefObject<HTMLTextAreaElement | null>;
}) {
	const [slashOpen, setSlashOpen] = useState(false);
	const [slashQuery, setSlashQuery] = useState("");

	const removeSlashToken = () => {
		const el = replyRef.current;
		const cursor = el?.selectionStart ?? replyText.length;
		const before = replyText.slice(0, cursor);
		const match = before.match(/(^|\s)\/[\w-]*$/);
		if (!match || match.index === undefined) return cursor;
		const start = match.index + match[1]!.length;
		const nextText = `${replyText.slice(0, start)}${replyText.slice(cursor)}`;
		onReplyChange(nextText);
		requestAnimationFrame(() => {
			replyRef.current?.focus();
			replyRef.current?.setSelectionRange(start, start);
		});
		return start;
	};

	const replaceSlashToken = (value: string) => {
		const el = replyRef.current;
		const cursor = el?.selectionStart ?? replyText.length;
		const before = replyText.slice(0, cursor);
		const match = before.match(/(^|\s)\/[\w-]*$/);
		if (!match || match.index === undefined) {
			onReplyChange(`${replyText}${value}`);
			return;
		}
		const start = match.index + match[1]!.length;
		const nextText = `${replyText.slice(0, start)}${value}${replyText.slice(cursor)}`;
		onReplyChange(nextText);
		requestAnimationFrame(() => {
			replyRef.current?.focus();
			const nextCursor = start + value.length;
			replyRef.current?.setSelectionRange(nextCursor, nextCursor);
		});
	};

	const commands: ReplySlashCommand[] = [
		...(suggestion
			? [
					{
						id: "draft",
						label: "/draft",
						hint: "Use the pending AI suggestion",
						run: () => onReplyChange(suggestion.suggestion_text),
					},
				]
			: []),
		...(onRegenerateSuggestion
			? [
					{
						id: "regenerate",
						label: "/regenerate",
						hint: "Request a fresh reply suggestion",
						run: () => {
							removeSlashToken();
							onRegenerateSuggestion();
						},
					},
				]
			: []),
		{
			id: "thanks",
			label: "/thanks",
			hint: "Insert a concise acknowledgement",
			run: () => replaceSlashToken("Thanks for sending this over - "),
		},
		{
			id: "clear",
			label: "/clear",
			hint: "Clear the reply draft",
			run: () => onReplyChange(""),
		},
		{
			id: "send",
			label: "/send",
			hint: "Send this reply",
			run: () => {
				if (isSending) return;
				removeSlashToken();
				onSend();
			},
		},
	];

	const query = slashQuery.toLowerCase();
	const filteredCommands = query
		? commands.filter((command) =>
				`${command.id} ${command.label} ${command.hint}`
					.toLowerCase()
					.includes(query),
			)
		: commands;

	const runSlashCommand = (command: ReplySlashCommand) => {
		command.run();
		setSlashOpen(false);
		setSlashQuery("");
	};

	const appendQuickReply = (value: string) => {
		const separator = replyText.trim() ? " " : "";
		onReplyChange(`${replyText}${separator}${value}`);
		requestAnimationFrame(() => {
			replyRef.current?.focus();
			const nextCursor = `${replyText}${separator}${value}`.length;
			replyRef.current?.setSelectionRange(nextCursor, nextCursor);
		});
	};

	return (
		<div className="border-t border-border px-4 md:px-6 py-4 shrink-0">
			<NovaCard
				variant="panel"
				className="shadow-none focus-within:border-ring"
				contentClassName="p-0"
			>
				<div className="flex items-center justify-between px-3.5 py-2">
					<span className="text-[0.6875rem] text-muted-foreground inline-flex items-center gap-1.5">
						<Reply className="size-3" /> Replying to
						<span className="font-mono text-foreground">@{handle}</span>
					</span>
					<span className="text-[0.625rem] text-muted-foreground hidden md:inline">
						<Kbd>R</Kbd> to focus
					</span>
				</div>
				<Separator />
				{suggestion && (
					<div className="flex items-center justify-between gap-2 px-3.5 py-2">
						<Button
							type="button"
							onClick={() => onReplyChange(suggestion.suggestion_text)}
							variant="ghost"
							size="sm"
							className="min-h-8 min-w-0 justify-start px-2 text-left text-[0.71875rem] text-muted-foreground truncate"
						>
							Auto-draft: {suggestion.suggestion_text}
						</Button>
						<div className="shrink-0 flex items-center gap-1">
							<Button
								type="button"
								onClick={() => {
									onReplyChange(suggestion.suggestion_text);
									window.requestAnimationFrame(() => {
										replyRef.current?.focus();
										const end = suggestion.suggestion_text.length;
										replyRef.current?.setSelectionRange(end, end);
									});
								}}
								variant="ghost"
								size="sm"
								className="h-8 px-2 text-[0.75rem]"
							>
								Edit
							</Button>
							<Button
								type="button"
								onClick={onRegenerateSuggestion}
								variant="ghost"
								size="sm"
								className="h-8 px-2 text-[0.75rem]"
							>
								<RotateCcw data-icon="start" aria-hidden="true" />
								Regenerate
							</Button>
						</div>
					</div>
				)}
				{suggestion ? <Separator /> : null}
				<Textarea
					ref={replyRef}
					value={replyText}
					onChange={(e) => {
						const next = e.target.value;
						onReplyChange(next);
						const cursor = e.target.selectionStart ?? next.length;
						const before = next.slice(0, cursor);
						const match = before.match(/(^|\s)\/([\w-]*)$/);
						if (match) {
							setSlashOpen(true);
							setSlashQuery(match[2] ?? "");
						} else {
							setSlashOpen(false);
							setSlashQuery("");
						}
					}}
					onKeyDown={(event) => {
						if (!slashOpen) return;
						if (event.key === "Escape") {
							event.preventDefault();
							setSlashOpen(false);
							setSlashQuery("");
						}
						if (event.key === "Enter" && filteredCommands[0]) {
							event.preventDefault();
							runSlashCommand(filteredCommands[0]);
						}
					}}
					onFocus={onFocus}
					onBlur={onBlur}
					placeholder="Reply or press / for AI commands..."
					rows={3}
					className="min-h-0 w-full resize-none border-transparent bg-transparent px-4 py-3 text-[0.84375rem] leading-[1.5] shadow-none focus-visible:border-transparent focus-visible:ring-0"
				/>
				{slashOpen && (
					<Command className="mx-3.5 mb-2 rounded-lg border border-border bg-popover shadow-sm">
						<CommandList className="max-h-56">
							<CommandGroup heading="Reply commands">
								{filteredCommands.length === 0 ? (
									<CommandEmpty>No command matches /{slashQuery}</CommandEmpty>
								) : (
									filteredCommands.map((command) => (
										<CommandItem
											key={command.id}
											onMouseDown={(event) => event.preventDefault()}
											onSelect={() => runSlashCommand(command)}
											className="items-start"
										>
											<span className="block text-[0.8125rem] font-medium text-foreground">
												{command.label}
											</span>
											<span className="block text-[0.6875rem] text-muted-foreground">
												{command.hint}
											</span>
										</CommandItem>
									))
								)}
							</CommandGroup>
						</CommandList>
					</Command>
				)}
				<Separator />
				<div className="px-3.5 py-2">
					<div className="mb-2 flex flex-wrap items-center gap-1.5">
						<Button
							type="button"
							onClick={() => appendQuickReply("Happy to help -")}
							variant="secondary"
							size="sm"
							className="h-7 rounded-full px-2.5 text-[0.6875rem]"
						>
							<span className="inline-flex items-center gap-1">
								<MessageCircleReply data-icon="start" aria-hidden="true" />
								Answer
							</span>
						</Button>
						<Button
							type="button"
							onClick={() => appendQuickReply("Thanks for asking -")}
							variant="secondary"
							size="sm"
							className="h-7 rounded-full px-2.5 text-[0.6875rem]"
						>
							Thank
						</Button>
						<Button
							type="button"
							onClick={() =>
								appendQuickReply("Quick question before I answer:")
							}
							variant="secondary"
							size="sm"
							className="h-7 rounded-full px-2.5 text-[0.6875rem]"
						>
							<span className="inline-flex items-center gap-1">
								<HelpCircle data-icon="start" aria-hidden="true" />
								Question
							</span>
						</Button>
					</div>
					<div className="flex items-center justify-between">
						<Button
							type="button"
							onClick={() => onReplyChange("")}
							disabled={!replyText}
							variant="ghost"
							size="sm"
							className="h-8 px-2.5 text-[0.75rem]"
						>
							Clear
						</Button>
						<div className="flex items-center gap-1.5">
							<Button
								type="button"
								onClick={onSend}
								disabled={!replyText.trim() || isSending}
								variant="default"
								size="md"
								className="h-9 px-4 text-[0.8125rem] font-semibold"
							>
								{isSending ? "Sending" : "Send"}
								<span className="hidden md:inline-flex">
									<Kbd dark>⌘↵</Kbd>
								</span>
							</Button>
						</div>
					</div>
				</div>
			</NovaCard>
		</div>
	);
}
