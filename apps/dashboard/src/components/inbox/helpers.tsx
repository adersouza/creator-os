// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import type React from "react";
import { AtSign, MessageCircle, MessageSquare } from "lucide-react";
import { cn } from "@/lib/utils";
import type {
	Conversation,
	InboxSuggestion,
	MessageType,
	PlatformKind,
	Sentiment,
	TabKey,
} from "./types";

export const INBOX_TABS_BY_PLATFORM: Record<
	PlatformKind,
	{ id: TabKey; label: string }[]
> = {
	threads: [
		{ id: "comment", label: "Replies" },
		{ id: "mention", label: "Mentions" },
	],
	instagram: [
		{ id: "dm", label: "DMs" },
		{ id: "comment", label: "Comments" },
	],
};

export function tabsForPlatform(
	platform: PlatformKind,
): { id: TabKey; label: string }[] {
	return INBOX_TABS_BY_PLATFORM[platform];
}

export function supportsTabForPlatform(
	platform: PlatformKind,
	tab: TabKey,
): boolean {
	return tabsForPlatform(platform).some((entry) => entry.id === tab);
}

export function defaultTabForPlatform(platform: PlatformKind): TabKey {
	return platform === "threads" ? "comment" : "dm";
}

export function tabLabel(platform: PlatformKind, tab: TabKey): string {
	return (
		tabsForPlatform(platform).find((entry) => entry.id === tab)?.label ?? tab
	);
}

export const TYPE_ICON: Record<
	MessageType,
	React.ComponentType<{ className?: string | undefined }>
> = {
	dm: MessageSquare,
	mention: AtSign,
	comment: MessageCircle,
};

export function conversationKey(
	c: Pick<Conversation, "platform" | "type" | "id">,
): string {
	return `${c.platform}:${c.type}:${c.id}`;
}

export function inboxAssignmentSource(
	c: Pick<Conversation, "platform" | "type">,
): "threads_reply" | "threads_mention" | "ig_comment" | "ig_mention" | "ig_dm" {
	if (c.platform === "threads")
		return c.type === "mention" ? "threads_mention" : "threads_reply";
	if (c.type === "dm") return "ig_dm";
	return c.type === "mention" ? "ig_mention" : "ig_comment";
}

export function formatFollowers(n: number): string {
	if (n >= 1_000_000)
		return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
	if (n >= 1_000) return `${(n / 1_000).toFixed(1).replace(/\.0$/, "")}K`;
	return n.toString();
}

export function sentimentLabel(sentiment: Sentiment | undefined): Sentiment {
	return sentiment ?? "neutral";
}

export function sentimentColor(
	sentiment: Sentiment | undefined,
): string | undefined {
	if (sentiment === "positive") return "var(--color-gold)";
	if (sentiment === "negative") return "var(--color-negative)";
	return undefined;
}

export function isEmojiOnlyComment(c: Conversation): boolean {
	if (c.type !== "comment") return false;
	const text = c.snippet.trim();
	if (!text) return false;
	return /^[\p{Emoji}\s]+$/u.test(text);
}

export function needsAttention(
	c: Conversation,
	suggestion?: InboxSuggestion | undefined,
): boolean {
	if (c.sentiment === "negative") return true;
	if (c.isTopEngager) return true;
	if (suggestion) return true;
	const lastTurn = c.turns[c.turns.length - 1];
	if (
		lastTurn?.from === "them" &&
		/[?？]|\b(can|could|would|should|how|what|when|where|why|help)\b/i.test(
			lastTurn.text,
		)
	) {
		return true;
	}
	return false;
}

function normalizeName(name: string): string {
	return name.trim().toLowerCase().replace(/\s+/g, " ");
}

function handlePrefix(handle: string): string {
	return handle
		.toLowerCase()
		.replace(/^@/, "")
		.replace(/[^a-z0-9_]/g, "")
		.split(/[_\d]/)[0]!
		.slice(0, 8);
}

export function buildIdentityAdvisories(
	conversations: Conversation[],
): Map<string, string> {
	const byName = new Map<string, Conversation[]>();
	for (const c of conversations) {
		const key = normalizeName(c.user.name);
		if (!key || key === "unknown") continue;
		const group = byName.get(key) ?? [];
		group.push(c);
		byName.set(key, group);
	}

	const advisories = new Map<string, string>();
	for (const group of byName.values()) {
		const threads = group.filter((c) => c.platform === "threads");
		const instagram = group.filter((c) => c.platform === "instagram");
		if (!threads.length || !instagram.length) continue;

		const matched = threads.some((t) => {
			const tPrefix = handlePrefix(t.user.handle);
			if (tPrefix.length < 3) return false;
			return instagram.some((ig) => {
				const igPrefix = handlePrefix(ig.user.handle);
				return (
					igPrefix.length >= 3 &&
					(tPrefix.startsWith(igPrefix) || igPrefix.startsWith(tPrefix))
				);
			});
		});

		if (!matched) continue;
		for (const c of group) {
			advisories.set(c.id, "Likely same person across Threads + Instagram");
		}
	}
	return advisories;
}

export function PlatformGlyph({
	platform,
	className,
}: {
	platform: PlatformKind;
	className?: string | undefined;
}) {
	if (platform === "threads") {
		return (
			<span
				role="img"
				aria-label="Threads"
				className={cn(
					"inline-flex items-center justify-center font-mono font-semibold",
					className,
				)}
			>
				@
			</span>
		);
	}
	return (
		<svg
			aria-label="Instagram"
			viewBox="0 0 14 14"
			className={className}
			fill="none"
			stroke="currentColor"
			strokeWidth="1.2"
		>
			<rect x="2" y="2" width="10" height="10" rx="2.5" />
			<circle cx="7" cy="7" r="2.2" />
			<circle cx="10" cy="4" r="0.5" fill="currentColor" />
		</svg>
	);
}

export function Avatar({
	from,
	to,
	initial,
	size = 36,
	className,
}: {
	from: string;
	to: string;
	initial: string;
	size?: number | undefined;
	className?: string | undefined;
}) {
	return (
		<div
			className={cn(
				"rounded-full shrink-0 flex items-center justify-center font-semibold text-white shadow-[inset_0_1px_0_color-mix(in_srgb,var(--color-primary-foreground)_18%,transparent)]",
				className,
			)}
			style={{
				width: size,
				height: size,
				fontSize: size * 0.38,
				background: `linear-gradient(135deg, ${from}, ${to})`,
			}}
			aria-hidden="true"
		>
			{initial}
		</div>
	);
}

export function Kbd({
	children,
	dark,
}: {
	children: React.ReactNode;
	dark?: boolean | undefined;
}) {
	return (
		<kbd
			className={cn(
				"font-mono text-[0.59375rem] rounded px-1 py-[1px] border",
				dark
					? "bg-primary-foreground/15 border-primary-foreground/20 text-primary-foreground"
					: "bg-muted border-border text-muted-foreground",
			)}
		>
			{children}
		</kbd>
	);
}
