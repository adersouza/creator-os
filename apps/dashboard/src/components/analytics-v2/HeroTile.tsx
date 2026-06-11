// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.

import { Sparkles } from "lucide-react";
import { useCallback, useId, useMemo } from "react";
import {
	daysToFleetTimeframe,
	toFleetPlatform,
} from "@/components/analytics/analyticsShared";
import { InvestigateButton } from "@/components/analytics/InvestigateButton";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { useAnomalyFeed } from "@/hooks/useAnomalyFeed";
import {
	type FleetMetricsState,
	useFleetMetrics,
} from "@/hooks/useFleetMetrics";
import {
	type NarrativeInput,
	useNarrativeBrief,
} from "@/hooks/useNarrativeBrief";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import {
	fillTokens,
	NARRATIVES,
	type NarrativeTemplate,
	renderEmphasized,
} from "./hero/narratives";
import { formatDeltaPct, type Platform } from "./shared";

interface HeroTileProps {
	platform: Platform;
	/** Real day count from the date range — replaces the legacy `'7' | '30' | '90'` enum. */
	days: number;
	/** Pre-fetched fleet metrics from the page; when omitted the tile fetches
	 *  its own (back-compat for any caller outside Analytics.tsx). */
	fleet?: FleetMetricsState | undefined;
	accountIds?: string[] | undefined;
	groupId?: string | null | undefined;
	scopeLabel?: string | undefined;
	snapshotTitle?: string | undefined;
	scopeSubject?: string | undefined;
}

interface CommandRow {
	targetId: string;
	label: string;
	caption: string;
	badge: string;
}

/**
 * Hero tile — spec §3. Five stacked regions inside one tile:
 *   1. Eyebrow + meta + anomaly badge
 *   2. Narrative (bold-emphasized headline + body with inline .ev links)
 *   3. CTA row (Investigate + Pin)
 *   4. Sparkline
 *   5. 4-KPI strip
 *
 * Narrative is LLM-generated via /api/ai?action=generate-narrative when the
 * user has an AI key + the tier gate clears. Falls back to the hardcoded
 * per-platform NARRATIVES table on any non-2xx (no key, rate-limit, 5xx).
 * Token placeholders like {{REACH_DELTA}} are filled with live fleet metrics
 * at render time regardless of source — so the prose stays truthful.
 */
export function HeroTile({
	platform,
	days,
	fleet,
	accountIds,
	groupId,
	scopeLabel,
	scopeSubject,
}: HeroTileProps) {
	const scopedAccount = useAccountScopeStore((s) => s.scopedAccount);
	const fleetPlatform = toFleetPlatform(platform);
	const fleetTimeframe = useMemo(() => daysToFleetTimeframe(days), [days]);
	// Mounted unconditionally (rules of hooks). When the parent supplies fleet
	// metrics, we disable the fetch so children don't redundantly hit the RPC.
	const fallbackMetrics = useFleetMetrics(
		fleetTimeframe,
		fleetPlatform,
		scopedAccount,
		{ enabled: !fleet, accountIds, groupId },
	);
	const metrics = fleet ?? fallbackMetrics;
	const { alerts: anomalyAlerts, isLoading: anomalyAlertsLoading } =
		useAnomalyFeed({ hours: 72 }, "all", scopedAccount, accountIds, groupId);

	const sparklinePoints = useMemo(
		() => metrics.series.map((p) => p.reach).filter((n) => Number.isFinite(n)),
		[metrics.series],
	);
	const accountScopeLabel = scopedAccount?.handle
		? scopedAccount.handle.startsWith("@")
			? scopedAccount.handle
			: `@${scopedAccount.handle}`
		: null;
	const heroPlatform: Platform =
		scopedAccount?.platform === "instagram"
			? "ig"
			: scopedAccount?.platform === "threads"
				? "threads"
				: platform;

	// Tokens are filled on both the LLM narrative and the hardcoded fallback —
	// both flow through fillTokens() so the rendered prose references real
	// fleet numbers regardless of source.
	const atRiskCount = metrics.accounts.filter(
		(a) => a.posts > 0 && a.eqs < 40,
	).length;
	const tokens = useMemo(
		() => ({
			REACH_DELTA: formatDeltaPct(metrics.reachDeltaPct, 0),
			AT_RISK_COUNT: atRiskCount.toString(),
		}),
		[metrics.reachDeltaPct, atRiskCount],
	);

	// LLM narrative inputs — filter to matching-platform alerts (all=both), map
	// alert severity into the schema the handler expects. Kept intentionally
	// compact so we don't send a large payload per render.
	const narrativeInput = useMemo<NarrativeInput | null>(() => {
		if (metrics.isLoading) return null;
		const accountCount = metrics.accounts.length;
		if (accountCount === 0) return null;

		// Build a username lookup from fleet metrics so LLM gets "@handle" not raw IDs.
		const usernameById = new Map<string, string>();
		for (const acct of metrics.accounts) {
			if (acct.username) usernameById.set(acct.accountId, acct.username);
		}

		const relevant = anomalyAlerts.filter((a) => {
			if (heroPlatform === "all") return true;
			if (heroPlatform === "threads") return a.platform === "threads";
			return a.platform === "instagram";
		});
		const ranked = [...relevant].sort(
			(a, b) => sevRank(b.severity) - sevRank(a.severity),
		);
		const topAnomalies = ranked.slice(0, 5).map((a) => {
			const rawId = a.accountId ?? a.instagramAccountId ?? undefined;
			const username = rawId ? usernameById.get(rawId) : undefined;
			return {
				accountLabel: username ? `@${username}` : rawId,
				reason: a.title,
				severity:
					a.severity === "critical"
						? ("critical" as const)
						: ("warning" as const),
				description: a.description ?? undefined,
			};
		});
		return {
			platform: heroPlatform,
			reachDeltaPct: metrics.reachDeltaPct,
			atRiskCount,
			accountCount,
			anomalyCount: relevant.length,
			topAnomalies,
		};
	}, [
		heroPlatform,
		metrics.isLoading,
		metrics.accounts,
		metrics.reachDeltaPct,
		atRiskCount,
		anomalyAlerts,
	]);

	const narrativeReady = narrativeInput !== null && !anomalyAlertsLoading;
	const brief = useNarrativeBrief(narrativeInput, { enabled: narrativeReady });

	const fallback: NarrativeTemplate = NARRATIVES[heroPlatform];
	const narrative: NarrativeTemplate = brief.narrative ?? fallback;
	const displayNarrative = useMemo<NarrativeTemplate>(() => {
		const selectedSubject =
			accountScopeLabel ? "this account" : scopeSubject ?? null;
		if (!selectedSubject || selectedSubject === "all accounts") return narrative;
		const rewrite = (text: string) => {
			const singular = accountScopeLabel ? "account" : selectedSubject;
			return text
				.replace(/your fleet/gi, selectedSubject)
				.replace(/fleet-wide/gi, `${singular}-wide`)
				.replace(/\bfleet\b/gi, singular)
				.replace(/\bfleets\b/gi, selectedSubject)
				.replace(/\baccounts\b/gi, accountScopeLabel ? "account" : "accounts");
		};
		return {
			...narrative,
			headline: rewrite(narrative.headline),
			body: narrative.body.map((segment) =>
				typeof segment === "string" ? rewrite(segment) : segment,
			),
		};
	}, [accountScopeLabel, narrative, scopeSubject]);
	const narrativeSource: "llm" | "fallback" = brief.isFresh
		? "llm"
		: "fallback";

	const scrollToEvidence = useCallback((targetId: string) => {
		const el = document.getElementById(targetId);
		if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
	}, []);

	// Use the LLM call's actual completion timestamp when available so the
	// ticker doesn't read as "live" when the narrative is stale-from-cache.
	// Falls back to wall clock only for the static-fallback path where the
	// timestamp would be meaningless anyway.
	const generatedLabel = (
		brief.generatedAt ? new Date(brief.generatedAt) : new Date()
	).toLocaleString(undefined, {
		month: "short",
		day: "numeric",
		hour: "numeric",
		minute: "2-digit",
	});
	const generatedAgeMs = brief.generatedAt
		? Date.now() - new Date(brief.generatedAt).getTime()
		: Number.POSITIVE_INFINITY;
	const sourceLabel =
		narrativeSource === "llm"
			? generatedAgeMs < 2 * 60 * 1000
				? "LIVE · LLM"
				: "CACHE · LLM"
			: narrativeReady && brief.isLoading
				? "BASELINE · AI QUEUED"
				: !narrativeReady && metrics.isLoading
					? "LOCAL · LOADING"
					: "BASELINE";

	// Only show the anomaly pill when there's something to show. Hardcoded
	// "loading…" copy in the previous version read as a stuck spinner.
	const anomalyCount = anomalyAlerts.filter((a) => {
		if (heroPlatform === "all") return true;
		if (heroPlatform === "threads") return a.platform === "threads";
		return a.platform === "instagram";
	}).length;
	const commandRows = buildCommandRows({
		platform: heroPlatform,
		atRiskCount,
		reachDelta: formatDeltaPct(metrics.reachDeltaPct, 1),
		postCount: metrics.postCount,
		days,
		scoped: !!accountScopeLabel,
	});
	const recommendedCopy = buildRecommendedCopy({
		platform: heroPlatform,
		reachDelta: formatDeltaPct(metrics.reachDeltaPct, 1),
		atRiskCount,
		postCount: metrics.postCount,
		days,
		scoped: !!accountScopeLabel,
	});

	return (
		<NovaCard className="w-full overflow-hidden" contentClassName="p-0">
			<div className="p-6">
				<div className="flex items-center justify-between gap-3">
					<div className="flex min-w-0 flex-wrap items-center gap-2">
						<span className="eyebrow inline-flex shrink-0 items-center gap-1">
							{narrativeSource === "llm" ? (
								<Sparkles
									className="h-3 w-3 text-[var(--color-oxblood)]"
									aria-hidden="true"
								/>
							) : null}
							{displayNarrative.eyebrow}
						</span>
						<span className="ticker">
							· {generatedLabel.toUpperCase()} · {sourceLabel}
						</span>
					</div>
					{anomalyCount > 0 ? (
						<Badge tone="secondary" className="anom-note shrink-0">
							{anomalyCount} anomal{anomalyCount === 1 ? "y" : "ies"} · 72h
						</Badge>
					) : null}
				</div>

				<div className="mt-4">
					<h2 className="app-page-title max-w-[760px] text-foreground">
						{renderEmphasized(
							fillTokens(displayNarrative.headline, tokens),
						).map((seg, i) =>
							seg.kind === "bold" ? (
								<strong
									key={i}
									className="font-bold text-foreground underline decoration-[color-mix(in_srgb,var(--color-oxblood)_55%,transparent)] decoration-1 underline-offset-[5px]"
								>
									{seg.text}
								</strong>
							) : (
								<span key={i}>{seg.text}</span>
							),
						)}
					</h2>
					<p className="mt-3 max-w-[740px] text-[0.875rem] leading-relaxed text-muted-foreground">
						The evidence below shows the drivers, affected accounts, and next
						best action for {scopeLabel ?? accountScopeLabel ?? "all accounts"}.
					</p>
				</div>

				<div className="analytics-hero-card mt-6 overflow-hidden rounded-[var(--radius-lg)] border border-[color-mix(in_srgb,var(--color-foreground)_11%,var(--color-border))] bg-[var(--color-card)]">
					<div className="flex flex-wrap items-start justify-between gap-3 border-b border-[color-mix(in_srgb,var(--color-foreground)_8%,var(--color-border))] px-5 py-4">
						<div className="min-w-0">
							<h3 className="text-[1rem] font-semibold tracking-[-0.02em] text-foreground">
								Investigation path
							</h3>
							<p className="mt-1 text-[0.82rem] leading-relaxed text-muted-foreground">
								Jump into the checks that explain the current movement.
							</p>
						</div>
						<Badge tone="outline" className="bg-muted/55 text-muted-foreground">
							{days}d ·{" "}
							{accountScopeLabel
								? "Account"
								: heroPlatform === "all"
									? "Workspace"
									: heroPlatform}
						</Badge>
					</div>

					<div className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_minmax(320px,0.48fr)]">
						<div className="grid gap-2">
							{commandRows.map((row, index) => (
								<Button
									key={row.targetId}
									type="button"
									aria-label={`Jump to ${row.label}`}
									variant="outline"
									className="group grid min-h-[4.25rem] w-full grid-cols-[2rem_minmax(0,1fr)_auto] items-center gap-3 bg-muted/35 px-3.5 text-left hover:border-[color-mix(in_srgb,var(--color-oxblood)_34%,var(--color-border))] hover:bg-[color-mix(in_srgb,var(--color-oxblood)_7%,var(--color-muted))]"
									onClick={() => scrollToEvidence(row.targetId)}
								>
									<span
										className={`flex h-8 w-8 items-center justify-center rounded-md border text-[0.75rem] font-semibold ${
											index === 0
												? "border-[color-mix(in_srgb,var(--color-oxblood)_42%,var(--color-border))] bg-[color-mix(in_srgb,var(--color-oxblood)_12%,transparent)] text-[var(--color-oxblood)]"
												: "border-border bg-card text-muted-foreground"
										}`}
									>
										{index + 1}
									</span>
									<span className="min-w-0">
										<span className="block truncate text-[0.92rem] font-semibold text-foreground">
											{row.label}
										</span>
										<span className="mt-0.5 block truncate text-[0.78rem] text-muted-foreground">
											{row.caption}
										</span>
									</span>
									<Badge tone="outline" className="bg-card text-muted-foreground">
										{row.badge}
									</Badge>
								</Button>
							))}
						</div>

						<aside className="flex min-h-[13rem] flex-col justify-between rounded-lg border border-border bg-muted/35 p-4">
							<div>
								<span className="text-[0.78rem] font-medium text-muted-foreground">
									Recommended action
								</span>
								<strong className="mt-2 block text-[1.08rem] font-semibold leading-tight tracking-[-0.025em] text-foreground">
									{accountScopeLabel
										? "Inspect the selected account delta."
										: "Sort the account grid by delta."}
								</strong>
								<p className="mt-2 text-[0.82rem] leading-relaxed text-muted-foreground">
									{recommendedCopy}
								</p>
							</div>
							<div className="mt-4">
								<InvestigateButton
									accountId={scopedAccount?.id ?? null}
									metric="reach"
									metricLabel={heroPlatform === "threads" ? "Views" : "Reach"}
									periodDays={days}
									hotkey
								/>
							</div>
						</aside>
					</div>

					<div className="border-t border-[color-mix(in_srgb,var(--color-foreground)_8%,var(--color-border))] bg-muted/20 p-4">
						<CommandPreviewChart points={sparklinePoints} />
					</div>
				</div>
			</div>
		</NovaCard>
	);
}

function CommandPreviewChart({ points }: { points: number[] }) {
	const chartId = useId().replace(/:/g, "");
	const safePoints = points.filter((point) => Number.isFinite(point));
	const width = 960;
	const height = 190;
	const padX = 28;
	const padY = 22;
	const plotBottom = height - 32;
	const plotHeight = plotBottom - padY;

	if (safePoints.length < 2) {
		return (
			<div className="rounded-lg border border-[color-mix(in_srgb,var(--color-foreground)_11%,var(--color-border))] bg-[color-mix(in_srgb,var(--color-background)_38%,transparent)] px-3 py-3">
				<div className="flex items-center justify-between">
					<Badge tone="outline" className="bg-background/60">
						Reach trace
					</Badge>
					<Badge tone="outline" className="bg-background/60">
						No sample
					</Badge>
				</div>
				<div className="mt-3 h-[170px] rounded-md border border-dashed border-[color-mix(in_srgb,var(--color-foreground)_10%,var(--color-border))] bg-[repeating-linear-gradient(90deg,color-mix(in_srgb,var(--color-foreground)_6%,transparent)_0_1px,transparent_1px_48px)]" />
			</div>
		);
	}

	const min = Math.min(...safePoints);
	const max = Math.max(...safePoints);
	const range = max - min || 1;
	const baseline = safePoints[0]!;
	const last = safePoints[safePoints.length - 1]!;
	const scaleX = (index: number) =>
		padX + (index / (safePoints.length - 1)) * (width - padX * 2);
	const scaleY = (value: number) => padY + ((max - value) / range) * plotHeight;
	const coords = safePoints.map((value, index) => ({
		value,
		x: scaleX(index),
		y: scaleY(value),
	}));
	const path = coords
		.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`)
		.join(" ");
	const firstPoint = coords[0]!;
	const lastPoint = coords[coords.length - 1]!;
	const areaPath = `${path} L ${lastPoint.x} ${plotBottom} L ${firstPoint.x} ${plotBottom} Z`;
	const baselineY = scaleY(baseline);
	const deltaPct = baseline === 0 ? 0 : ((last - baseline) / baseline) * 100;
	const trendLabel =
		deltaPct < -0.5
			? `${Math.round(deltaPct)}% vs start`
			: deltaPct > 0.5
				? `+${Math.round(deltaPct)}% vs start`
				: "flat vs start";
	const strokeGradientId = `commandPreviewStroke-${chartId}`;
	const fillGradientId = `commandPreviewFill-${chartId}`;

	return (
		<div className="overflow-hidden rounded-lg border border-[color-mix(in_srgb,var(--color-foreground)_12%,var(--color-border))] bg-[linear-gradient(180deg,color-mix(in_srgb,var(--color-background)_44%,transparent),color-mix(in_srgb,var(--color-background)_70%,transparent))] shadow-[inset_0_1px_0_color-mix(in_srgb,var(--color-foreground)_8%,transparent)]">
			<div className="flex items-center justify-between gap-3 border-b border-[color-mix(in_srgb,var(--color-foreground)_8%,var(--color-border))] px-3 py-2">
				<Badge tone="outline" className="bg-background/60">
					Reach trace
				</Badge>
				<Badge tone="outline" className="bg-background/60">
					{trendLabel}
				</Badge>
			</div>
			<svg
				viewBox={`0 0 ${width} ${height}`}
				className="block h-[190px] w-full"
				role="img"
				aria-label={`Reach trace ${trendLabel}`}
			>
				<defs>
					<linearGradient id={strokeGradientId} x1="0" x2="1" y1="0" y2="0">
						<stop offset="0%" stopColor="var(--color-foreground)" />
						<stop offset="56%" stopColor="var(--color-oxblood)" />
						<stop offset="100%" stopColor="var(--color-gold)" />
					</linearGradient>
					<linearGradient id={fillGradientId} x1="0" x2="0" y1="0" y2="1">
						<stop
							offset="0%"
							stopColor="var(--color-oxblood)"
							stopOpacity="0.26"
						/>
						<stop
							offset="100%"
							stopColor="var(--color-oxblood)"
							stopOpacity="0"
						/>
					</linearGradient>
				</defs>

				<rect
					x={width - 172}
					y={padY}
					width="144"
					height={plotHeight}
					fill="var(--color-foreground)"
					opacity="0.025"
				/>
				{[0, 1, 2, 3].map((index) => {
					const y = padY + (index / 3) * plotHeight;
					return (
						<line
							key={`h-${index}`}
							x1={padX}
							x2={width - padX}
							y1={y}
							y2={y}
							stroke="var(--color-foreground)"
							strokeOpacity="0.08"
							strokeWidth="1"
						/>
					);
				})}
				{[0, 1, 2, 3, 4].map((index) => {
					const x = padX + (index / 4) * (width - padX * 2);
					return (
						<line
							key={`v-${index}`}
							x1={x}
							x2={x}
							y1={padY}
							y2={plotBottom}
							stroke="var(--color-foreground)"
							strokeOpacity="0.045"
							strokeWidth="1"
						/>
					);
				})}
				<line
					x1={padX}
					x2={width - padX}
					y1={baselineY}
					y2={baselineY}
					stroke="var(--color-foreground)"
					strokeDasharray="4 6"
					strokeOpacity="0.24"
					strokeWidth="1"
				/>
				<path d={areaPath} fill={`url(#${fillGradientId})`} />
				<path
					d={path}
					fill="none"
					stroke={`url(#${strokeGradientId})`}
					strokeLinecap="round"
					strokeLinejoin="round"
					strokeWidth="2.2"
				/>
				<circle
					cx={lastPoint.x}
					cy={lastPoint.y}
					r="3"
					fill="var(--color-foreground)"
					stroke="var(--color-background)"
					strokeWidth="2"
				/>
				<text
					x={padX}
					y={height - 7}
					fill="var(--color-foreground)"
					fillOpacity="0.42"
					fontFamily="var(--font-sans)"
					fontSize="10"
					fontWeight="700"
				>
					Start
				</text>
				<text
					x={width - padX}
					y={height - 7}
					textAnchor="end"
					fill="var(--color-foreground)"
					fillOpacity="0.42"
					fontFamily="var(--font-sans)"
					fontSize="10"
					fontWeight="700"
				>
					Now
				</text>
			</svg>
		</div>
	);
}

function buildCommandRows({
	platform,
	atRiskCount,
	reachDelta,
	postCount,
	days,
	scoped,
}: {
	platform: Platform;
	atRiskCount: number;
	reachDelta: string;
	postCount: number;
	days: number;
	scoped: boolean;
}): CommandRow[] {
	const atRiskLabel = scoped
		? atRiskCount > 0
			? "Selected account at risk"
			: "Selected account"
		: platform === "threads"
			? `${atRiskCount.toLocaleString()} Threads accounts at risk`
			: platform === "ig"
				? `${atRiskCount.toLocaleString()} IG accounts at risk`
				: `${atRiskCount.toLocaleString()} accounts at risk`;
	const firstRow: CommandRow = {
		targetId: "evidence-1",
		label: atRiskLabel,
		caption: scoped
			? `${reachDelta} ${platform === "threads" ? "views" : "reach"} vs prior · single-account view`
			: `${reachDelta} ${platform === "threads" ? "views" : "reach"} vs prior · sorted worst-first`,
		badge: scoped ? "Account" : "Fleet grid",
	};
	const secondRow: CommandRow =
		platform === "threads"
			? {
					targetId: "evidence-source-mix",
					label: "Source mix",
					caption: scoped
						? "Check whether feed or search discovery is shifting on this account"
						: "Check whether feed or search discovery is shifting",
					badge: "Source",
				}
			: platform === "ig"
				? {
						targetId: "evidence-distribution-inputs",
						label: "Distribution inputs",
						caption: scoped
							? "Check format, hashtags, Reels friction, and surface mix for this account"
							: "Check format, hashtags, Reels friction, and surface mix",
						badge: "Inputs",
					}
				: {
						targetId: "evidence-matrix",
						label: "Metric matrix",
						caption: scoped
							? "Scan this account by reach, engagement, save rate, and flags"
							: "Scan accounts by reach, engagement, save rate, and flags",
						badge: "Matrix",
					};
	const thirdRow: CommandRow =
		platform === "threads"
			? {
					targetId: "evidence-conversation-system",
					label: "Conversation system",
					caption: scoped
						? "Review reply depth, quote ratio, and suppression risk on this account"
						: "Review reply depth, quote ratio, and suppression risk",
					badge: "Conversation",
				}
			: {
					targetId: "evidence-15",
					label: "Post performance table",
					caption: `${postCount.toLocaleString()} posts sampled over ${days}d`,
					badge: "Posts",
				};

	return [
		{
			...firstRow,
			caption:
				atRiskCount > 0
					? firstRow.caption
					: scoped
						? `No EQS-at-risk signal on this account · ${reachDelta} ${platform === "threads" ? "views" : "reach"} vs prior`
						: `No EQS-at-risk accounts · ${reachDelta} ${platform === "threads" ? "views" : "reach"} vs prior`,
		},
		secondRow,
		thirdRow,
	];
}

function buildRecommendedCopy({
	platform,
	reachDelta,
	atRiskCount,
	postCount,
	days,
	scoped,
}: {
	platform: Platform;
	reachDelta: string;
	atRiskCount: number;
	postCount: number;
	days: number;
	scoped: boolean;
}) {
	const metric = platform === "threads" ? "views" : "reach";
	const metricLabel = metric[0]!.toUpperCase() + metric.slice(1);
	const sampleText = `${postCount.toLocaleString()} posts over ${days}d`;

	if (atRiskCount === 0) {
		return scoped
			? `${metricLabel} is ${reachDelta} vs prior across ${sampleText}. No EQS-at-risk signal is showing on this account; use the view to check whether the movement is broad or isolated.`
			: `${metricLabel} is ${reachDelta} vs prior across ${sampleText}. No accounts are below the EQS at-risk threshold; use the grid to check whether the movement is broad or isolated.`;
	}

	return scoped
		? `${metricLabel} is ${reachDelta} vs prior across ${sampleText}. This account is below the EQS at-risk threshold, so start with the worst deltas before changing strategy.`
		: `${metricLabel} is ${reachDelta} vs prior across ${sampleText}. ${atRiskCount === 1 ? "1 account is" : `${atRiskCount.toLocaleString()} accounts are`} below the EQS at-risk threshold, so start with the worst account deltas before changing strategy.`;
}

function sevRank(sev: string): number {
	if (sev === "critical" || sev === "crit") return 3;
	if (sev === "warning" || sev === "warn") return 2;
	if (sev === "info" || sev === "note") return 1;
	return 0;
}
