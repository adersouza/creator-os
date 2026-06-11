// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useMemo } from "react";
import { MessageSquareText } from "lucide-react";
import { useContentMixHealth } from "@/hooks/useContentMixHealth";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import { InvestigateButton } from "@/components/analytics/InvestigateButton";
import { AnalyticsActionLink } from "@/components/analytics-v2/AnalyticsActionLink";
import { scopedRoute } from "@/lib/scopedRoutes";
import type { ScopedAccountLite } from "@/components/analytics/analyticsShared";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { EvidenceTile } from "../EvidenceTile";

type MixPoint = {
	reelsPct: number;
	feedPct: number;
	storyPct: number;
	totalReach: number;
};

const VERTICES = {
	reels: { x: 50, y: 10 },
	feed: { x: 12, y: 86 },
	story: { x: 88, y: 86 },
};

/**
 * #35 ContentMix ternary. Analytics is the correct home because the useful
 * question is drift over the trailing ~90d, not today's dashboard status.
 * Uses `useContentMixHealth`, whose fallback builds the 12-week trail from
 * Instagram posts when the content-type endpoint lacks historical rows.
 */
interface Props {
	days?: number | undefined;
	scopedAccount?: ScopedAccountLite | undefined;
	accountIds?: string[] | undefined;
}

export function ContentMixTernaryTile({
	days = 90,
	scopedAccount: scopedAccountProp,
	accountIds,
}: Props) {
	const storeScopedAccount = useAccountScopeStore((s) => s.scopedAccount);
	const scopedAccount = scopedAccountProp ?? storeScopedAccount;
	const accountId =
		scopedAccount?.platform === "instagram" ? (scopedAccount.id ?? null) : null;
	const { current, trail, isLoading, hasError } = useContentMixHealth(
		accountId,
		accountId ? undefined : accountIds,
		days,
	);

	const currentPoint = useMemo<MixPoint | null>(() => {
		const reels = current.reels?.reach ?? 0;
		const feed = current.feed?.reach ?? 0;
		const story = current.story?.reach ?? 0;
		const totalReach = reels + feed + story;
		if (totalReach <= 0) return null;
		return {
			reelsPct: (reels / totalReach) * 100,
			feedPct: (feed / totalReach) * 100,
			storyPct: (story / totalReach) * 100,
			totalReach,
		};
	}, [current]);

	if (!currentPoint && !isLoading) {
		return (
			<EvidenceTile
				state="empty"
				label="Content mix"
				title="Content mix ternary"
				note={
					hasError
						? "Content mix drift could not load. Refresh to retry Instagram post mix data."
						: "No Instagram reach mix exists yet. The ternary drift plot appears once posts have Reels, Feed, or Story reach."
				}
			/>
		);
	}

	const trailPoints =
		trail.length > 0 ? trail : currentPoint ? [currentPoint] : [];
	const drift =
		trailPoints.length >= 2
			? distance(trailPoints[0]!, trailPoints[trailPoints.length - 1]!)
			: 0;
	const reelsPct = currentPoint?.reelsPct ?? 0;
	const mixNeedsAction = reelsPct < 25 || reelsPct >= 55 || drift >= 18;

	return (
		<EvidenceCard
			eyebrow="Content mix"
			title="Content mix ternary"
			description="Trailing 90d drift · reach-weighted"
			action={
				<>
					{mixNeedsAction ? (
						<AnalyticsActionLink
							to={scopedRoute("/composer?platform=instagram&format=reel", {
								scopedAccount,
								accountIds,
								platform: "instagram",
							})}
							label={reelsPct < 25 ? "Plan Reel" : "Rebalance"}
							icon={MessageSquareText}
							tone="primary"
						/>
					) : null}
					<InvestigateButton
						accountId={accountId}
						metric="reach"
						metricLabel="Content mix drift"
						periodDays={days}
					/>
				</>
			}
			contentClassName="flex h-full flex-col gap-4"
		>
			<div className="analytics-content-mix-chart">
				<TernarySvg trail={trailPoints} current={currentPoint} />
				<div className="analytics-content-mix-stats">
					<MixStat
						label="Reels"
						value={currentPoint?.reelsPct ?? 0}
						color="var(--color-chart-1)"
					/>
					<MixStat
						label="Feed"
						value={currentPoint?.feedPct ?? 0}
						color="var(--color-chart-2)"
					/>
					<MixStat
						label="Stories"
						value={currentPoint?.storyPct ?? 0}
						color="var(--color-chart-4)"
					/>
				</div>
			</div>

			<div className="grid grid-cols-2 gap-3">
				<div className="rounded-md border border-border bg-muted/35 px-3 py-2">
					<div className="text-[0.625rem] uppercase tracking-[0.1em] text-muted-foreground">
						Reach sample
					</div>
					<div className="mt-1 font-mono text-[0.8125rem] text-foreground tabular-nums">
						{formatCompact(currentPoint?.totalReach ?? 0)}
					</div>
				</div>
				<div className="rounded-md border border-border bg-muted/35 px-3 py-2">
					<div className="text-[0.625rem] uppercase tracking-[0.1em] text-muted-foreground">
						Drift
					</div>
					<div className="mt-1 font-mono text-[0.8125rem] text-foreground tabular-nums">
						{drift.toFixed(1)} pts
					</div>
				</div>
			</div>
		</EvidenceCard>
	);
}

function TernarySvg({
	trail,
	current,
}: {
	trail: MixPoint[];
	current: MixPoint | null;
}) {
	const coords = trail.map(toXY);
	const path = coords
		.map(
			(point, index) =>
				`${index === 0 ? "M" : "L"} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`,
		)
		.join(" ");
	const currentCoord = current ? toXY(current) : null;

	return (
		<svg
			viewBox="0 0 100 100"
			role="img"
			aria-label="Ternary content mix plot"
			className="w-full min-h-[168px] max-h-[260px]"
		>
			<polygon
				points={`${VERTICES.reels.x},${VERTICES.reels.y} ${VERTICES.story.x},${VERTICES.story.y} ${VERTICES.feed.x},${VERTICES.feed.y}`}
				fill="var(--color-chart-area)"
				stroke="var(--color-border)"
				strokeWidth="0.8"
			/>
			{[25, 50, 75].map((pct) => (
				<GridLines key={pct} pct={pct} />
			))}
			{path ? (
				<path
					d={path}
					fill="none"
					stroke="var(--color-chart-2)"
					strokeWidth="1.6"
					strokeLinecap="round"
					strokeLinejoin="round"
					opacity="0.8"
				/>
			) : null}
			{coords.map((point, index) => (
				<circle
					key={`${point.x}-${point.y}-${index}`}
					cx={point.x}
					cy={point.y}
					r={index === coords.length - 1 ? 2.7 : 1.8}
					fill={
						index === coords.length - 1
							? "var(--color-chart-1)"
							: "var(--color-chart-2)"
					}
					opacity={index === coords.length - 1 ? 0.95 : 0.55}
				/>
			))}
			{currentCoord ? (
				<circle
					cx={currentCoord.x}
					cy={currentCoord.y}
					r="5"
					fill="none"
					stroke="var(--color-chart-1)"
					strokeWidth="1"
					opacity="0.55"
				/>
			) : null}
			<Label x={50} y={5} text="Reels" />
			<Label x={8} y={95} text="Feed" anchor="start" />
			<Label x={92} y={95} text="Stories" anchor="end" />
		</svg>
	);
}

function GridLines({ pct }: { pct: number }) {
	const t = pct / 100;
	const a = interpolate(VERTICES.feed, VERTICES.reels, t);
	const b = interpolate(VERTICES.story, VERTICES.reels, t);
	const c = interpolate(VERTICES.reels, VERTICES.feed, t);
	const d = interpolate(VERTICES.story, VERTICES.feed, t);
	const e = interpolate(VERTICES.reels, VERTICES.story, t);
	const f = interpolate(VERTICES.feed, VERTICES.story, t);
	return (
		<g stroke="var(--color-border)" strokeWidth="0.45" opacity="0.55">
			<line x1={a.x} y1={a.y} x2={b.x} y2={b.y} />
			<line x1={c.x} y1={c.y} x2={d.x} y2={d.y} />
			<line x1={e.x} y1={e.y} x2={f.x} y2={f.y} />
		</g>
	);
}

function MixStat({
	label,
	value,
	color,
}: {
	label: string;
	value: number;
	color: string;
}) {
	return (
		<div>
			<div className="flex items-center gap-1.5 text-[0.625rem] uppercase tracking-[0.1em] text-muted-foreground">
				<span className="size-2 rounded-sm" style={{ background: color }} />
				{label}
			</div>
			<div className="mt-1 font-mono text-[0.875rem] text-foreground tabular-nums">
				{value.toFixed(0)}%
			</div>
		</div>
	);
}

function Label({
	x,
	y,
	text,
	anchor = "middle",
}: {
	x: number;
	y: number;
	text: string;
	anchor?: "start" | "middle" | "end" | undefined;
}) {
	return (
		<text
			x={x}
			y={y}
			textAnchor={anchor}
			className="fill-muted-foreground text-[6px] uppercase tracking-wide"
		>
			{text}
		</text>
	);
}

function toXY(point: MixPoint) {
	const reels = point.reelsPct / 100;
	const feed = point.feedPct / 100;
	const story = point.storyPct / 100;
	return {
		x:
			reels * VERTICES.reels.x +
			feed * VERTICES.feed.x +
			story * VERTICES.story.x,
		y:
			reels * VERTICES.reels.y +
			feed * VERTICES.feed.y +
			story * VERTICES.story.y,
	};
}

function interpolate(
	a: { x: number; y: number },
	b: { x: number; y: number },
	t: number,
) {
	return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
}

function distance(a: MixPoint, b: MixPoint) {
	return Math.hypot(
		a.reelsPct - b.reelsPct,
		a.feedPct - b.feedPct,
		a.storyPct - b.storyPct,
	);
}

function formatCompact(value: number) {
	if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
	if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
	return value.toLocaleString();
}
