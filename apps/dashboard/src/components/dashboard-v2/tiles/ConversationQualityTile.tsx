// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useMemo } from "react";
import { Badge } from "@/components/ui/Badge";
import { NovaCard, NovaEmpty, NovaInset, NovaMiniStat } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";
import {
	useReplyDepthLeaders,
	type ReplyChainItem,
} from "@/hooks/useReplyDepthLeaders";
import { RangeChip, rangeToDays, usePersistedRange } from "../atoms/RangeChip";
import type { DashboardScopeProps } from "../scope";

/**
 * Conversation quality — Threads view band 0 dark anchor (mockup #11).
 *
 * Shows the top thread by reply depth × replies, a mini reply-tree
 * visualization, and a 3-metric grid (Max depth · Replies/1h · Creator
 * engagement). Replaces the prior fleet-aggregate "score" number.
 *
 */
export function ConversationQualityTile({
	scopedAccount,
	accountIds,
	groupId,
}: DashboardScopeProps) {
	const [range, setRange] = usePersistedRange(
		"dv2.conversationQuality.range.v2",
		"30d",
	);
	const days = rangeToDays(range);
	const { leaders, isLoading } = useReplyDepthLeaders(
		days,
		scopedAccount,
		accountIds,
		groupId,
	);

	const top = leaders[0] ?? null;
	const hasData = top != null;

	const repliesPerHour = useMemo(() => {
		if (!top?.publishedAt) return null;
		const ageHours = Math.max(
			1,
			(Date.now() - new Date(top.publishedAt).getTime()) / 36e5,
		);
		return Math.round(top.replies / ageHours);
	}, [top]);

	const medianRepliesPerHour = useMemo(() => {
		const values = leaders
			.filter((p) => p.id !== top?.id && p.publishedAt)
			.map((p) => {
				const ageHours = Math.max(
					1,
					(Date.now() - new Date(p.publishedAt as string).getTime()) / 36e5,
				);
				return p.replies / ageHours;
			})
			.filter((v) => Number.isFinite(v) && v >= 0)
			.sort((a, b) => a - b);
		if (values.length === 0) return null;
		return values[Math.floor(values.length / 2)] ?? null;
	}, [leaders, top?.id]);

	const creatorEngagementPct =
		top?.creatorRepliesCount != null && top.replies > 0
			? Math.round((top.creatorRepliesCount / top.replies) * 100)
			: null;
	const walkerDepth = useMemo(() => {
		if (!top?.replyChain || top.replyChain.length === 0) return null;
		const byId = new Map(top.replyChain.map((c) => [c.id, c]));
		let max = 1;
		for (const item of top.replyChain) {
			let d = 1;
			let cur: ReplyChainItem | undefined = item;
			const seen = new Set<string>();
			while (cur?.replied_to && d < 6) {
				if (seen.has(cur.id)) break;
				seen.add(cur.id);
				const parent = byId.get(cur.replied_to);
				if (!parent) break;
				d++;
				cur = parent;
			}
			max = Math.max(max, d);
		}
		return max;
	}, [top?.replyChain]);
	const displayDepth = walkerDepth ?? top?.replyDepth ?? null;
	const depthTitle =
		walkerDepth != null && top != null && walkerDepth !== top.replyDepth
			? `Walker depth · derived from reply chain. Cached depth: ${top.replyDepth}.`
			: undefined;

	const ageLabel = top?.publishedAt
		? formatAgo(new Date(top.publishedAt))
		: isLoading
			? "Syncing"
			: "No publish time";

	return (
		<NovaCard
			variant="compact"
			eyebrow="Conversation quality · top thread"
			title="Reply depth"
			description="Top thread by reply depth, reply velocity, and creator participation."
			action={
				<div className="flex items-center gap-2">
					<Badge variant="outline">{ageLabel}</Badge>
					<RangeChip
						value={range}
						onChange={setRange}
						ariaLabel="Conversation quality window"
					/>
				</div>
			}
		>
				{hasData ? (
					<>
						<NovaInset className="p-3">
							<div className="line-clamp-2 text-sm font-semibold leading-snug text-foreground">
								{top.content?.trim() || "— no caption recorded"}
							</div>
							<div className="mt-2 text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
								{ageLabel}
							</div>
						</NovaInset>

						{top.replyChain && top.replyChain.length > 0 ? (
							<ReplyTextTree
								rootText={top.content?.trim() ?? ""}
								chain={top.replyChain}
							/>
						) : (
							// Cron hasn't populated reply_chain yet — fall back to the
							// dot-and-bar skeleton tree at reduced opacity. The shape
							// still conveys "this is where the conversation will render."
							<div style={{ opacity: 0.5 }}>
								<ReplyTreeMini depth={top.replyDepth} replies={top.replies} />
							</div>
						)}

						<div className="mt-3 grid grid-cols-3 gap-2 border-t border-border pt-3">
							<NovaMiniStat
								label="Max depth"
								value={displayDepth != null ? `D${displayDepth}` : "D0"}
								description={depthTitle}
								size="compact"
							/>
							<NovaMiniStat
								label="Avg replies/hr (lifetime)"
								value={repliesPerHour != null ? `${repliesPerHour}` : "0"}
								trend={
									repliesPerHour != null &&
									medianRepliesPerHour != null &&
									repliesPerHour > medianRepliesPerHour
										? "↑"
										: undefined
								}
								size="compact"
							/>
							<NovaMiniStat
								label="Creator replies"
								value={
									creatorEngagementPct != null
										? `${creatorEngagementPct}%`
										: "0%"
								}
								size="compact"
							/>
						</div>
					</>
				) : (
					<ConversationEmpty isLoading={isLoading} />
				)}
		</NovaCard>
	);
}

function ConversationEmpty({ isLoading }: { isLoading: boolean }) {
	if (isLoading) {
		return (
			<NovaInset>
				<Skeleton className="h-3 w-5/6" />
				<Skeleton className="mt-2 h-3 w-3/5" />
				<div className="mt-4 opacity-60">
					<ReplyTreeMini depth={2} replies={4} />
				</div>
			</NovaInset>
		);
	}

	return (
		<NovaEmpty
			title="No reply-depth leader yet"
			description="Top thread fills in once a published Threads post earns more than two levels of reply depth."
		/>
	);
}

/**
 * Text-bearing reply tree — renders root post + up to 4 reply rows from
 * cron-cached posts.reply_chain. Each row shows username pill + text
 * (line-clamp 2) + depth badge. Depth derives from walking replied_to
 * back to root.
 */
function ReplyTextTree({
	rootText,
	chain,
}: {
	rootText: string;
	chain: ReplyChainItem[];
}) {
	// Compute depth-from-root for each chain item by walking replied_to
	// until we either hit the root post (replied_to == null) or exceed a
	// safety bound. Items with cycles or missing parents are clamped to 1.
	const depths = useMemo(() => {
		const byId = new Map(chain.map((c) => [c.id, c]));
		return chain.map((item) => {
			let d = 1;
			let cur: ReplyChainItem | undefined = item;
			const seen = new Set<string>();
			while (cur?.replied_to && d < 6) {
				if (seen.has(cur.id)) break;
				seen.add(cur.id);
				const parent = byId.get(cur.replied_to);
				if (!parent) break; // parent is root (or unknown) — stop
				d++;
				cur = parent;
			}
			return d;
		});
	}, [chain]);

	// Show 4 reply rows (mockup shows 5 lines including root).
	const visible = chain.slice(0, 4);

	return (
		<div style={{ marginTop: 12, marginBottom: 4, paddingLeft: 6 }}>
			<ReplyRow
				indent={0}
				username="creator"
				text={rootText}
				depthLabel="root"
				tone="creator"
			/>
			{visible.map((r, i) => (
				<ReplyRow
					key={r.id}
					indent={Math.min(3, depths[i]!)}
					username={r.username}
					text={r.text ?? ""}
					depthLabel={`d${depths[i]}`}
					tone={depths[i] === 1 ? "creator" : depths[i] === 2 ? "muted" : "dim"}
				/>
			))}
		</div>
	);
}

function ReplyRow({
	indent,
	username,
	text,
	depthLabel,
	tone,
}: {
	indent: number;
	username: string | null;
	text: string;
	depthLabel: string;
	tone: "creator" | "muted" | "dim";
}) {
	const dotColor =
		tone === "creator"
			? "var(--color-oxblood)"
			: tone === "muted"
				? "var(--color-muted-foreground)"
				: "color-mix(in srgb, var(--color-muted-foreground) 55%, transparent)";
	const dotSize = tone === "creator" ? 5 : 4;
	return (
		<div
			style={{
				display: "flex",
				alignItems: "flex-start",
				gap: 8,
				marginTop: 5,
				paddingLeft: indent * 14,
				position: "relative",
			}}
		>
			{indent > 0 ? (
				<>
					<span
						aria-hidden="true"
						style={{
							position: "absolute",
							left: indent * 14 - 7,
							top: -5,
							bottom: "50%",
							width: 1,
							background:
								"color-mix(in srgb, var(--color-foreground) 14%, transparent)",
						}}
					/>
					<span
						aria-hidden="true"
						style={{
							position: "absolute",
							left: indent * 14 - 7,
							top: 8,
							width: 6,
							height: 0,
							borderTop:
								"1px solid color-mix(in srgb, var(--color-foreground) 14%, transparent)",
						}}
					/>
				</>
			) : null}
			<span
				style={{
					width: dotSize,
					height: dotSize,
					borderRadius: "50%",
					background: dotColor,
					flexShrink: 0,
					marginTop: 6,
				}}
			/>
			<div style={{ flex: 1, minWidth: 0 }}>
				{username ? (
					<span
						className="app-data"
						style={{
						fontSize: 9,
						letterSpacing: "0.01em",
						color: "var(--color-muted-foreground)",
						marginRight: 6,
					}}
					>
						@{username}
					</span>
				) : null}
				<span
					style={{
						fontSize: 12,
						lineHeight: 1.35,
						color: "var(--color-foreground)",
						display: "-webkit-box",
						WebkitLineClamp: 2,
						WebkitBoxOrient: "vertical",
						overflow: "hidden",
					}}
				>
					{text || "No reply text recorded"}
				</span>
			</div>
			<span
				className="app-data"
				style={{
					fontSize: 8,
					letterSpacing: "0.02em",
					textTransform: "uppercase",
					color: "var(--color-muted-foreground)",
					flexShrink: 0,
					marginTop: 4,
				}}
			>
				{depthLabel}
			</span>
		</div>
	);
}

function ReplyTreeMini({ depth, replies }: { depth: number; replies: number }) {
	// Tree visualization — root + first-level branches + nested depth chain.
	// Each row is a node-dot + skeleton bar suggesting reply content (we don't
	// fetch actual reply text without an extra Threads API call per post). The
	// visual weight scales with replies + depth so the tile reads "active vs
	// sparse" at a glance.
	const branches = Math.max(2, Math.min(4, Math.ceil(replies / 4)));
	const nesting = Math.max(1, Math.min(3, depth - 1));

	// Pre-baked bar widths — visually varied without random jitter on every render.
	const branchWidths = [82, 65, 74, 58];
	const nestWidths = [52, 44, 38];

	return (
		<div
			style={{
				marginTop: 12,
				marginBottom: 4,
				position: "relative",
				paddingLeft: 6,
			}}
		>
			<TreeRow indent={0} width={88} tone="ox" />
			{Array.from({ length: branches }).map((_, i) => (
				<TreeRow
					key={`b${i}`}
					indent={1}
					width={branchWidths[i % branchWidths.length]!}
					tone={i === 0 ? "creator" : "muted"}
					connector
				/>
			))}
			{Array.from({ length: nesting }).map((_, j) => (
				<TreeRow
					key={`n${j}`}
					indent={2 + j}
					width={nestWidths[j % nestWidths.length]!}
					tone={j % 2 === 0 ? "creator" : "dim"}
					connector
				/>
			))}
		</div>
	);
}

function TreeRow({
	indent,
	width,
	tone,
	connector,
}: {
	indent: number;
	width: number;
	tone: "ox" | "muted" | "dim" | "creator";
	connector?: boolean | undefined;
}) {
	const dotColor: Record<string, string> = {
		ox: "var(--color-oxblood)",
		creator: "var(--color-oxblood)",
		muted: "var(--color-muted-foreground)",
		dim: "color-mix(in srgb, var(--color-muted-foreground) 55%, transparent)",
	};
	const barColor: Record<string, string> = {
		ox: "color-mix(in srgb, var(--color-foreground) 14%, transparent)",
		creator: "color-mix(in srgb, var(--color-oxblood) 30%, transparent)",
		muted: "color-mix(in srgb, var(--color-foreground) 9%, transparent)",
		dim: "color-mix(in srgb, var(--color-foreground) 6%, transparent)",
	};
	const dotSize = tone === "ox" ? 6 : tone === "creator" ? 5 : 4;
	return (
		<div
			style={{
				display: "flex",
				alignItems: "center",
				gap: 8,
				marginTop: 5,
				paddingLeft: indent * 14,
				position: "relative",
			}}
		>
			{connector ? (
				<span
					aria-hidden="true"
					style={{
						position: "absolute",
						left: indent * 14 - 7,
						top: -5,
						bottom: "50%",
						width: 1,
						background:
							"color-mix(in srgb, var(--color-foreground) 14%, transparent)",
					}}
				/>
			) : null}
			{connector ? (
				<span
					aria-hidden="true"
					style={{
						position: "absolute",
						left: indent * 14 - 7,
						top: "50%",
					width: 6,
					height: 0,
					borderTop:
						"1px solid color-mix(in srgb, var(--color-foreground) 14%, transparent)",
				}}
			/>
			) : null}
			<span
				style={{
					width: dotSize,
					height: dotSize,
					borderRadius: "50%",
					background: dotColor[tone],
					flexShrink: 0,
				}}
			/>
			<span
				style={{
					height: 6,
					width: `${width}%`,
					maxWidth: 180,
					borderRadius: 2,
					background: barColor[tone],
				}}
			/>
			{tone === "creator" ? (
				<span
					className="font-mono"
					style={{
						fontSize: 8,
						letterSpacing: "0.05em",
						textTransform: "uppercase",
						color: "var(--color-muted-foreground)",
						flexShrink: 0,
					}}
				>
					OP
				</span>
			) : null}
		</div>
	);
}

function formatAgo(d: Date): string {
	const ms = Date.now() - d.getTime();
	const m = Math.floor(ms / 60000);
	if (m < 1) return "just now";
	if (m < 60) return `${m}m ago`;
	const h = Math.floor(m / 60);
	if (h < 24) return `${h}h ago`;
	const days = Math.floor(h / 24);
	return `${days}d ago`;
}
