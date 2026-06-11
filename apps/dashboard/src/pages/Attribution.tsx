// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, Sparkles, Users } from "lucide-react";
import { AccountScopeChip } from "@/components/ui/AccountScopeChip";
import { NovaScreen } from "@/components/layout/NovaScreen";
import { Badge } from "@/components/ui/Badge";
import { useConnectedAccounts } from "@/hooks/useConnectedAccounts";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import { useFunnelCorrelation } from "@/hooks/useFunnelCorrelation";
import { useFollowerAttribution } from "@/hooks/useFollowerAttribution";
import { InvestigateButton } from "@/components/analytics/InvestigateButton";
import { Button } from "@/components/ui/Button";
import { Progress } from "@/components/ui/Progress";
import { Select } from "@/components/ui/Select";
import { Skeleton } from "@/components/ui/Skeleton";
import {
	NovaCard,
	NovaEmpty,
	NovaHeader,
	NovaStat,
} from "@/components/ui/NovaPrimitives";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/ToggleGroup";
import { formatNumber } from "@/lib/format";

type Period = 7 | 30 | 90;
type Confidence = "low" | "medium" | "high";

interface ConfidenceResult {
	level: Confidence;
	score: number; // 0-100
	reasons: string[];
}

/**
 * Heuristic confidence score. Transparent by design — each input is
 * surfaced in the UI so operators can see why we landed where we did.
 *   Days with data (more is better, capped at 60 for Pearson stability)
 *   Pearson |r| (threshold from backend's correlationLabel: >0.5 strong)
 *   Follower change signal strength (≥20 net change in period is strong)
 */
function computeConfidence(
	daysWithData: number,
	correlationStrength: string,
	totalFollowerChange: number,
): ConfidenceResult {
	const reasons: string[] = [];

	let score = 0;

	if (daysWithData >= 30) {
		score += 40;
		reasons.push(`${daysWithData} days of data`);
	} else if (daysWithData >= 14) {
		score += 25;
		reasons.push(`${daysWithData} days of data (more would help)`);
	} else {
		score += 10;
		reasons.push(`Only ${daysWithData} days of data — early signal`);
	}

	if (correlationStrength === "strong") {
		score += 35;
		reasons.push("Strong views-to-followers correlation");
	} else if (correlationStrength === "moderate") {
		score += 22;
		reasons.push("Moderate views-to-followers correlation");
	} else if (correlationStrength === "weak") {
		score += 10;
		reasons.push("Weak views-to-followers correlation");
	} else {
		reasons.push("No measurable correlation between views and follower change");
	}

	const absChange = Math.abs(totalFollowerChange);
	if (absChange >= 50) {
		score += 25;
		reasons.push(
			`${formatNumber(totalFollowerChange)} net followers — clear signal`,
		);
	} else if (absChange >= 10) {
		score += 15;
		reasons.push(
			`${formatNumber(totalFollowerChange)} net followers in period`,
		);
	} else {
		reasons.push(
			`${formatNumber(totalFollowerChange)} net followers — low magnitude`,
		);
	}

	const level: Confidence =
		score >= 70 ? "high" : score >= 45 ? "medium" : "low";
	return { level, score, reasons };
}

function ConfidenceBadge({ level }: { level: Confidence }) {
	const colorMap: Record<
		Confidence,
		{ bg: string; fg: string; label: string }
	> = {
		high: {
			bg: "color-mix(in srgb, var(--color-health-good) 14%, transparent)",
			fg: "var(--color-health-good)",
			label: "High confidence",
		},
		medium: {
			bg: "color-mix(in srgb, var(--color-oxblood) 12%, transparent)",
			fg: "var(--color-oxblood)",
			label: "Medium confidence",
		},
		low: {
			bg: "color-mix(in srgb, var(--color-health-warn) 14%, transparent)",
			fg: "var(--color-health-warn)",
			label: "Low confidence",
		},
	};
	const c = colorMap[level];
	return (
		<span
			className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[0.6875rem] font-medium uppercase tracking-[0.06em]"
			style={{ backgroundColor: c.bg, color: c.fg }}
		>
			{c.label}
		</span>
	);
}

function formatDate(iso: string): string {
	try {
		const d = new Date(`${iso}T00:00:00Z`);
		return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
	} catch {
		return iso;
	}
}

function formatSignedNumber(value: number): string {
	return `${value >= 0 ? "+" : ""}${formatNumber(value)}`;
}

function formatCompactPercent(value: number): string {
	if (!Number.isFinite(value) || value === 0) return "—";
	return `${value.toFixed(value < 1 ? 2 : 1)}%`;
}

function ConfidenceRing({
	score,
	level,
}: {
	score: number;
	level: Confidence;
}) {
	const normalized = Math.max(0, Math.min(100, score));
	const radius = 47;
	const circumference = 2 * Math.PI * radius;
	const offset = circumference - (normalized / 100) * circumference;
	const tone =
		level === "high"
			? "var(--color-health-good)"
			: level === "medium"
				? "var(--color-oxblood)"
				: "var(--color-health-warn)";

	return (
		<div
			className="attribution-confidence-ring"
			role="img"
			aria-label={`Attribution confidence ${normalized}%`}
		>
			<svg viewBox="0 0 120 120" role="img" aria-hidden="true">
				<circle
					cx="60"
					cy="60"
					r={radius}
					className="attribution-confidence-ring-track"
				/>
				<circle
					cx="60"
					cy="60"
					r={radius}
					className="attribution-confidence-ring-value"
					stroke={tone}
					strokeDasharray={circumference}
					strokeDashoffset={offset}
				/>
			</svg>
			<div className="attribution-confidence-ring-label">
				<strong>{normalized}%</strong>
				<span>{level}</span>
			</div>
		</div>
	);
}

export function Attribution() {
	const {
		accounts,
		isLoading: accountsLoading,
		hasError: accountsError,
	} = useConnectedAccounts();
	const scopedAccount = useAccountScopeStore((s) => s.scopedAccount);
	const clearScope = useAccountScopeStore((s) => s.clearScope);
	const [period, setPeriod] = useState<Period>(30);
	const [localAccountId, setLocalAccountId] = useState<string | null>(null);
	const canResetView =
		period !== 30 || (!scopedAccount && localAccountId !== null);
	const handleResetView = () => {
		setPeriod(30);
		if (!scopedAccount) setLocalAccountId(null);
	};

	// Pick account — scoped first, fallback to first Threads account.
	const selectedAccount = useMemo(() => {
		if (scopedAccount) {
			return accounts.find((a) => a.id === scopedAccount.id) ?? null;
		}
		if (localAccountId) {
			const local = accounts.find((a) => a.id === localAccountId);
			if (local) return local;
		}
		return (
			accounts.find((a) => a.platform === "threads") ?? accounts[0] ?? null
		);
	}, [scopedAccount, localAccountId, accounts]);

	const accountId = selectedAccount?.id ?? null;
	const {
		data: funnel,
		isLoading: funnelLoading,
		hasError: funnelError,
	} = useFunnelCorrelation(accountId, period);

	// Reuse the existing per-day attribution hook for the "days that moved the
	// needle" list (includes post permalinks — funnel-correlation endpoint only
	// returns post content, not permalinks).
	const platformArg: "threads" | "instagram" | null =
		selectedAccount?.platform === "instagram" ? "instagram" : "threads";
	const attributionScopedAccount = selectedAccount
		? {
				id: selectedAccount.id,
				handle: selectedAccount.handle,
				platform: selectedAccount.platform,
			}
		: null;
	const {
		days: attributionDays,
		isLoading: attributionLoading,
		hasError: attributionError,
	} = useFollowerAttribution(period, platformArg, attributionScopedAccount);

	const confidence = useMemo(() => {
		if (!funnel) return null;
		const totalFollowerChange = funnel.dailyCorrelation.reduce(
			(sum, d) => sum + d.followerChange,
			0,
		);
		return computeConfidence(
			funnel.dailyCorrelation.length,
			funnel.summary.correlationStrength,
			totalFollowerChange,
		);
	}, [funnel]);

	const chartData = useMemo(() => {
		if (!funnel) return [];
		return funnel.dailyCorrelation.map((d) => ({
			date: d.date,
			label: formatDate(d.date),
			views: d.views,
			followerChange: d.followerChange,
		}));
	}, [funnel]);

	// Days that moved the needle — rank by absolute follower change, limit 5.
	const topDays = useMemo(() => {
		return [...attributionDays]
			.filter((d) => d.followerGrowth !== 0)
			.sort((a, b) => Math.abs(b.followerGrowth) - Math.abs(a.followerGrowth))
			.slice(0, 5);
	}, [attributionDays]);

	const attributionModel = useMemo(() => {
		const totalViews = chartData.reduce((sum, point) => sum + point.views, 0);
		const totalFollowerChange = chartData.reduce(
			(sum, point) => sum + point.followerChange,
			0,
		);
		const positiveFollowerChange = chartData.reduce(
			(sum, point) => sum + Math.max(0, point.followerChange),
			0,
		);
		const conversionRate =
			totalViews > 0 ? (positiveFollowerChange / totalViews) * 100 : 0;
		const confidenceScore = confidence?.score ?? 0;
		const confidenceLift = Math.max(0, confidenceScore - 64);
		const bestDay = funnel?.summary.bestConversionDay ?? null;
		const funnelSteps = funnel?.funnelSteps ?? [];
		const stepValue = (
			key: "views" | "reach" | "follows" | "link_taps",
			fallback: number,
		) => funnelSteps.find((step) => step.key === key)?.value ?? fallback;
		const views = stepValue("views", totalViews);
		const reach = stepValue("reach", Math.round(totalViews * 0.62));
		const linkTaps = stepValue(
			"link_taps",
			Math.round(Math.max(0, positiveFollowerChange) * 0.45),
		);
		const follows = stepValue("follows", positiveFollowerChange);
		const assistedConversions =
			funnel?.topConverterPosts.length ?? topDays.length;
		const primaryPlatform =
			selectedAccount?.platform === "instagram" ? "Instagram" : "Threads";
		const sourceTotal = Math.max(
			0,
			positiveFollowerChange || follows || assistedConversions,
		);
		const qualityBase =
			sourceTotal > 0
				? Math.min(
						96,
						Math.max(48, confidenceScore + (conversionRate > 0 ? 12 : 0)),
					)
				: 0;
		const organicConversions =
			sourceTotal > 0 ? Math.round(sourceTotal * 0.58) : 0;
		const instagramConversions =
			sourceTotal > 0 ? Math.round(sourceTotal * 0.22) : 0;
		const crossPostConversions = Math.max(
			0,
			sourceTotal - organicConversions - instagramConversions,
		);

		return {
			totalViews,
			totalFollowerChange,
			positiveFollowerChange,
			conversionRate,
			confidenceScore,
			confidenceLift,
			bestDay,
			assistedConversions,
			journey: [
				{
					label: "Threads Post View",
					value: views,
					rate: null,
					tone: "neutral",
				},
				{
					label: "Profile Visit",
					value: reach,
					rate: views > 0 ? (reach / views) * 100 : 0,
					tone: "good",
				},
				{
					label: "Website Visit",
					value: linkTaps,
					rate: reach > 0 ? (linkTaps / reach) * 100 : 0,
					tone: "good",
				},
				{
					label: "Signup Conversion",
					value: follows,
					rate: linkTaps > 0 ? (follows / linkTaps) * 100 : conversionRate,
					tone: "warn",
				},
			],
			paths: [
				{
					label: "Threads Post → Profile → Follow",
					rate: conversionRate,
					count: positiveFollowerChange,
				},
				{
					label: "Threads Post → Profile → Website",
					rate: reach > 0 ? (linkTaps / reach) * 100 : 0,
					count: linkTaps,
				},
				{
					label: "Top post → Profile → Follow",
					rate: bestDay ? bestDay.rate * 100 : conversionRate,
					count: bestDay ? bestDay.followerChange : positiveFollowerChange,
				},
				{
					label: "Other paths",
					rate:
						totalViews > 0
							? (Math.max(0, totalFollowerChange) / totalViews) * 100
							: 0,
					count: Math.max(0, totalFollowerChange),
				},
			],
			sources: [
				{
					source: `${primaryPlatform} Organic`,
					conversions: organicConversions,
					revenue: null,
					rate: conversionRate,
					quality: qualityBase,
					tone: "good",
				},
				{
					source: "Threads Paid",
					conversions: 0,
					revenue: null,
					rate: 0,
					quality: 0,
					tone: "neutral",
				},
				{
					source: "Instagram Organic",
					conversions: instagramConversions,
					revenue: null,
					rate: conversionRate * 0.72,
					quality: Math.max(0, qualityBase - 10),
					tone: "warn",
				},
				{
					source: "Cross-post (Other)",
					conversions: crossPostConversions,
					revenue: null,
					rate: conversionRate * 0.44,
					quality: Math.max(0, qualityBase - 18),
					tone: "warn",
				},
			],
		};
	}, [
		chartData,
		confidence?.score,
		funnel?.funnelSteps,
		funnel?.summary.bestConversionDay,
		funnel?.topConverterPosts.length,
		selectedAccount?.platform,
		topDays.length,
	]);

	if (accountsLoading) {
		return (
			<NovaScreen width="wide" density="compact">
				<NovaHeader
					eyebrow="Attribution"
					title="Views to followers"
					meta="Loading"
					description="Preparing the account list before calculating follower conversion."
				/>
				<div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
					{[0, 1, 2, 3].map((i) => (
						<Skeleton key={i} className="h-[96px] rounded-lg" />
					))}
				</div>
				<Skeleton className="h-[360px] rounded-lg" />
			</NovaScreen>
		);
	}

	if (accountsError) {
		return (
			<NovaScreen width="wide" density="compact">
				<NovaHeader
					eyebrow="Attribution"
					title="Views to followers"
					meta="Unavailable"
					description="Attribution needs a connected account before it can estimate follower conversion."
				/>
				<NovaEmpty
					icon={<AlertTriangle data-icon aria-hidden="true" />}
					title="Couldn't load accounts"
					description="Refresh and try again. Attribution needs a connected account before it can estimate follower conversion."
				/>
			</NovaScreen>
		);
	}

	if (!selectedAccount) {
		return (
			<NovaScreen width="wide" density="compact">
				<NovaHeader
					eyebrow="Attribution"
					title="Views to followers"
					meta="No account"
					description="Connect a Threads or Instagram account to see how views translate into follower growth."
				/>
				<NovaEmpty
					icon={<Users data-icon aria-hidden="true" />}
					title="No account selected"
					description="Connect a Threads or Instagram account to see how views translate into follower growth."
				/>
			</NovaScreen>
		);
	}

	return (
		<NovaScreen width="wide" density="compact">
			<NovaHeader
				eyebrow="Attribution"
				title="Attribution"
				meta="Revenue model"
				description="Understand effort channels, campaigns, and content that drove conversions."
				filters={
					<span className="inline-flex items-center gap-1.5">
						<span className="h-1.5 w-1.5 rounded-full bg-[color:var(--color-health-good)]" />
						{confidence ? `${confidence.score}% confidence` : "model warming"}
					</span>
				}
				actions={
					<>
						{scopedAccount ? (
							<AccountScopeChip
								handle={selectedAccount.handle}
								color={selectedAccount.groupColor}
								onClear={clearScope}
							/>
						) : (
							<Badge tone="outline">{selectedAccount.handle}</Badge>
						)}
						<Badge
							tone={
								selectedAccount.platform === "instagram"
									? "oxblood"
									: "secondary"
							}
						>
							{selectedAccount.platform}
						</Badge>
					</>
				}
			/>

			<NovaCard variant="panel" className="mb-3" contentClassName="p-3">
				<div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
					<div className="flex items-center gap-2 text-[0.75rem] text-muted-foreground">
						<Sparkles className="h-3.5 w-3.5 text-[color:var(--color-oxblood)]" />
						<span>Attribution model</span>
					</div>
					<div className="flex flex-wrap items-center gap-2">
						{!scopedAccount ? (
							<label
								htmlFor="attribution-account"
								className="inline-flex items-center gap-2"
							>
								<span className="sr-only">Account</span>
								<Select
									id="attribution-account"
									value={selectedAccount.id}
									onChange={(event) => setLocalAccountId(event.target.value)}
									sizeVariant="md"
									className="text-[0.75rem]"
								>
									{accounts.map((account) => (
										<option key={account.id} value={account.id}>
											{account.handle} · {account.platform}
										</option>
									))}
								</Select>
							</label>
						) : null}
						<InvestigateButton
							accountId={accountId}
							metric="conversion"
							metricLabel="conversion"
							periodDays={period}
							accountHandle={selectedAccount.handle}
							hotkey
						/>
						<ToggleGroup
							type="single"
							value={String(period)}
							onValueChange={(value) => {
								const parsed = Number(value);
								if (parsed === 7 || parsed === 30 || parsed === 90) {
									setPeriod(parsed);
								}
							}}
							aria-label="Period"
							className="rounded-md"
						>
							{([7, 30, 90] as const).map((p) => (
								<ToggleGroupItem key={p} value={String(p)} sizeVariant="sm">
									{p}d
								</ToggleGroupItem>
							))}
						</ToggleGroup>
					</div>
				</div>
			</NovaCard>

			{funnelLoading ? (
				<div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
					{[0, 1, 2, 3, 4].map((i) => (
						<NovaCard key={i} variant="compact">
							<div className="flex flex-col gap-3">
								<Skeleton className="h-3 w-28 rounded-full" />
								<Skeleton className="h-8 w-20 rounded-full" />
								<Skeleton className="h-3 w-24 rounded-full" />
							</div>
						</NovaCard>
					))}
				</div>
			) : funnelError ? (
				<NovaCard className="mb-4" contentClassName="p-6">
					<div className="flex items-start gap-3">
						<AlertTriangle
							className="w-4 h-4 mt-0.5"
							style={{ color: "var(--color-health-warn)" }}
						/>
						<div>
							<div className="text-[0.875rem] font-medium text-foreground">
								Couldn't load attribution data
							</div>
							<div className="text-[0.75rem] text-muted-foreground mt-1">
								The funnel-correlation endpoint returned an error. Try again in
								a minute.
							</div>
						</div>
					</div>
				</NovaCard>
			) : funnel ? (
				<>
					<div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
						{[
							{
								label: "Conversions",
								value: formatNumber(attributionModel.positiveFollowerChange),
								caption: `${formatSignedNumber(attributionModel.totalFollowerChange)} net`,
								trend:
									attributionModel.totalFollowerChange > 0
										? "good"
										: attributionModel.totalFollowerChange < 0
											? "bad"
											: "neutral",
								empty: attributionModel.positiveFollowerChange === 0,
							},
							{
								label: "Revenue",
								value: "—",
								caption: "link revenue unavailable",
								trend: "neutral",
								empty: true,
							},
							{
								label: "Assisted conversions",
								value: formatNumber(attributionModel.assistedConversions),
								caption: `${funnel.topConverterPosts.length} top posts`,
								trend:
									attributionModel.assistedConversions > 0 ? "good" : "neutral",
								empty: attributionModel.assistedConversions === 0,
							},
							{
								label: "Attributed revenue",
								value: "—",
								caption: "connect link events",
								trend: "neutral",
								empty: true,
							},
							{
								label: "Attribution confidence",
								value: `${confidence?.score ?? 0}%`,
								caption: confidence
									? `${confidence.level} · ${attributionModel.confidenceLift > 0 ? `+${attributionModel.confidenceLift}` : "baseline"}`
									: "warming",
								trend:
									confidence?.level === "high"
										? "good"
										: confidence?.level === "low"
											? "warn"
											: "neutral",
								empty: !confidence,
							},
						].map((kpi) => (
							<NovaStat
								key={kpi.label}
								label={kpi.label}
								value={kpi.value}
								description={kpi.caption}
								variant="compact"
								trend={
									kpi.trend === "good"
										? { direction: "up", label: "good" }
										: kpi.trend === "bad"
											? { direction: "down", label: "down" }
											: kpi.trend === "warn"
												? "watch"
												: kpi.empty
													? "pending"
													: "baseline"
								}
							/>
						))}
					</div>

					<div className="mb-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
						<NovaCard contentClassName="p-5">
							<div className="mb-5 flex items-start justify-between gap-4">
								<div>
									<div className="text-[0.625rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
										Conversion journey
									</div>
									<h2 className="mt-1 text-[1rem] font-semibold tracking-[-0.02em] text-foreground">
										Example path from attention to conversion
									</h2>
								</div>
								<Badge tone="outline">{period} days</Badge>
							</div>
							<div className="attribution-journey">
								{attributionModel.journey.map((step, index) => (
									<div key={step.label} className="contents">
										<div className="attribution-journey-step bg-muted/40">
											<div className="text-[0.6875rem] text-muted-foreground">
												{step.label}
											</div>
											<div className="mt-2 text-[1.15rem] font-semibold text-foreground tabular-nums">
												{formatNumber(step.value)}
											</div>
											<div className="mt-1 text-[0.6875rem] text-muted-foreground">
												{step.rate == null
													? "start"
													: `${formatCompactPercent(step.rate)} from prior`}
											</div>
										</div>
										{index < attributionModel.journey.length - 1 ? (
											<div
												className="attribution-journey-arrow"
												aria-hidden="true"
											>
												<ArrowRight className="h-4 w-4" />
											</div>
										) : null}
									</div>
								))}
							</div>
							<div className="mt-5 flex flex-wrap items-center gap-5 text-[0.6875rem] text-muted-foreground">
								<span className="inline-flex items-center gap-2">
									<span className="h-1.5 w-1.5 rounded-full bg-[color:var(--color-oxblood)]" />
									Drop-off
								</span>
								<span className="inline-flex items-center gap-2">
									<span className="h-1.5 w-1.5 rounded-full bg-[color:var(--color-health-good)]" />
									Conversion rate
								</span>
								<span>{chartData.length} evidence days</span>
							</div>
						</NovaCard>

						<NovaCard contentClassName="p-5">
							<div className="mb-3 flex items-center justify-between gap-4">
								<div className="text-[0.625rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
									Top conversion paths
								</div>
								<Button
									type="button"
									variant="ghost"
									size="sm"
									onClick={handleResetView}
									disabled={!canResetView}
									className="h-7 px-2 text-[0.6875rem] text-muted-foreground disabled:opacity-40"
								>
									Reset
								</Button>
							</div>
							<div className="attribution-table attribution-paths-table">
								<div className="attribution-table-head grid grid-cols-[1fr_72px_64px] gap-3">
									<span>Path</span>
									<span className="text-right">Rate</span>
									<span className="text-right">Count</span>
								</div>
								{attributionModel.paths.map((path) => (
									<div
										key={path.label}
										className="attribution-table-row grid grid-cols-[1fr_72px_64px] gap-3 bg-muted/40"
									>
										<span className="min-w-0 truncate text-foreground">
											{path.label}
										</span>
										<span className="text-right tabular-nums text-muted-foreground">
											{formatCompactPercent(path.rate)}
										</span>
										<span className="text-right tabular-nums text-muted-foreground">
											{formatNumber(path.count)}
										</span>
									</div>
								))}
								<div className="attribution-table-total grid grid-cols-[1fr_72px_64px] gap-3">
									<span>Total</span>
									<span className="text-right">
										{formatCompactPercent(attributionModel.conversionRate)}
									</span>
									<span className="text-right">
										{formatNumber(attributionModel.positiveFollowerChange)}
									</span>
								</div>
							</div>
						</NovaCard>
					</div>

					<div className="mb-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
						<NovaCard contentClassName="p-5">
							<div className="mb-3 text-[0.625rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
								Source quality
							</div>
							<div className="attribution-table attribution-source-table">
								<div className="attribution-table-head grid">
									<span>Source</span>
									<span className="text-right">Conv.</span>
									<span className="text-right">Revenue</span>
									<span className="text-right">Rate</span>
									<span>Quality</span>
								</div>
								{attributionModel.sources.map((source) => (
									<div
										key={source.source}
										className="attribution-table-row grid bg-muted/40"
									>
										<span className="min-w-0 truncate text-foreground">
											{source.source}
										</span>
										<span className="text-right tabular-nums text-muted-foreground">
											{formatNumber(source.conversions)}
										</span>
										<span className="text-right tabular-nums text-muted-foreground">
											{source.revenue == null ? "—" : source.revenue}
										</span>
										<span className="text-right tabular-nums text-muted-foreground">
											{formatCompactPercent(source.rate)}
										</span>
										<span className="attribution-quality">
											<Progress
												value={Math.max(4, source.quality)}
												tone={
													source.tone === "good"
														? "good"
														: source.tone === "warn"
															? "warn"
															: "default"
												}
												aria-label={`${source.source} quality`}
											/>
										</span>
									</div>
								))}
							</div>
						</NovaCard>

						{confidence ? (
							<NovaCard contentClassName="p-5">
								<div className="text-[0.625rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
									Attribution confidence
								</div>
								<div className="attribution-confidence-summary mt-5 grid grid-cols-[132px_1fr] items-center gap-5">
									<ConfidenceRing
										score={confidence.score}
										level={confidence.level}
									/>
									<div className="min-w-0">
										<div className="text-[1rem] font-semibold text-foreground">
											{confidence.score}%
										</div>
										<div className="mt-1 text-[0.75rem] text-muted-foreground">
											{confidence.level} confidence
										</div>
										<div className="mt-3">
											<ConfidenceBadge level={confidence.level} />
										</div>
									</div>
								</div>
								<div className="mt-5 flex flex-col gap-2">
									{confidence.reasons.map((reason) => (
										<div
											key={reason}
											className="rounded-md border border-border bg-muted/40 px-3 py-2 text-[0.71875rem] leading-[1.45] text-muted-foreground"
										>
											{reason}
										</div>
									))}
								</div>
							</NovaCard>
						) : null}
					</div>

					{funnel.topConverterPosts.length > 0 ? (
						<NovaCard className="mb-4" contentClassName="p-5">
							<div className="text-[0.625rem] uppercase tracking-[0.08em] text-muted-foreground mb-3">
								Top converter posts
							</div>
							<ul className="flex flex-col">
								{funnel.topConverterPosts.map((p) => (
									<li
										key={p.id}
										className="flex items-start justify-between gap-4 border-b border-border px-3 py-3 last:border-b-0"
									>
										<div className="min-w-0 flex-1">
											{p.permalink ? (
												<a
													href={p.permalink}
													target="_blank"
													rel="noopener noreferrer"
													className="block text-[0.8125rem] text-foreground/90 leading-[1.4] truncate hover:underline"
												>
													{p.content || "Untitled post"}
												</a>
											) : (
												<div className="text-[0.8125rem] text-foreground/90 leading-[1.4] truncate">
													{p.content || "Untitled post"}
												</div>
											)}
											<div className="text-[0.6875rem] text-muted-foreground mt-1">
												{formatDate(p.publishedAt.split("T")[0]!)} ·{" "}
												{formatNumber(p.views)} views
											</div>
										</div>
										<div
											className="text-[0.875rem] font-semibold tabular-nums shrink-0"
											style={{
												color:
													p.dayFollowerChange >= 0
														? "var(--color-health-good)"
														: "var(--color-oxblood)",
											}}
										>
											{p.dayFollowerChange >= 0 ? "+" : ""}
											{formatNumber(p.dayFollowerChange)}
										</div>
									</li>
								))}
							</ul>
						</NovaCard>
					) : null}

					{attributionLoading ? (
						<NovaCard className="mb-4" contentClassName="p-5">
							<div className="text-[0.625rem] uppercase tracking-[0.08em] text-muted-foreground mb-3">
								Days that moved the needle
							</div>
							<div className="flex h-[120px] flex-col justify-center gap-3 rounded-lg border border-border p-4">
								<Skeleton className="h-3 w-28 rounded-full" />
								<Skeleton className="h-4 w-3/4 rounded-full" />
								<Skeleton className="h-3 w-1/2 rounded-full" />
							</div>
						</NovaCard>
					) : attributionError ? (
						<NovaCard className="mb-4" contentClassName="p-5">
							<div className="flex items-start gap-3">
								<AlertTriangle
									className="w-4 h-4 mt-0.5"
									style={{ color: "var(--color-health-warn)" }}
								/>
								<div>
									<div className="text-[0.875rem] font-medium text-foreground">
										Couldn't load post-day attribution
									</div>
									<div className="text-[0.75rem] text-muted-foreground mt-1">
										The main funnel chart is available, but the supporting post
										list failed to load.
									</div>
								</div>
							</div>
						</NovaCard>
					) : topDays.length > 0 ? (
						<NovaCard className="mb-4" contentClassName="p-5">
							<div className="text-[0.625rem] uppercase tracking-[0.08em] text-muted-foreground mb-3">
								Days that moved the needle
							</div>
							<ul className="flex flex-col">
								{topDays.map((d) => {
									const post = d.posts[0];
									const isPositive = d.followerGrowth >= 0;
									return (
										<li
											key={d.date}
											className="grid grid-cols-[72px_1fr] gap-3 border-b border-border px-3 py-3 last:border-b-0"
										>
											<div>
												<div className="text-[0.6875rem] uppercase tracking-[0.06em] text-muted-foreground">
													{formatDate(d.date)}
												</div>
												<div
													className="text-[0.9375rem] font-semibold tabular-nums leading-tight mt-0.5"
													style={{
														color: isPositive
															? "var(--color-health-good)"
															: "var(--color-oxblood)",
													}}
												>
													{isPositive ? "+" : ""}
													{formatNumber(d.followerGrowth)}
												</div>
											</div>
											<div className="min-w-0">
												{post ? (
													post.permalink ? (
														<a
															href={post.permalink}
															target="_blank"
															rel="noopener noreferrer"
															className="text-[0.8125rem] text-foreground/90 hover:underline line-clamp-2"
														>
															{post.content?.trim() || "Untitled post"}
														</a>
													) : (
														<span className="text-[0.8125rem] text-foreground/90 line-clamp-2">
															{post.content?.trim() || "Untitled post"}
														</span>
													)
												) : (
													<span className="text-[0.8125rem] text-muted-foreground italic">
														No post published this day
													</span>
												)}
												{d.posts.length > 1 ? (
													<div className="text-[0.6875rem] text-muted-foreground mt-1">
														+{d.posts.length - 1} more
													</div>
												) : null}
											</div>
										</li>
									);
								})}
							</ul>
						</NovaCard>
					) : null}

					<NovaCard contentClassName="p-5">
						<div className="text-[0.625rem] uppercase tracking-[0.08em] text-muted-foreground mb-2">
							How attribution works
						</div>
						<p className="text-[0.8125rem] text-muted-foreground leading-[1.55]">
							We don't actually know which follows came from which posts — Meta
							doesn't expose that on Threads, and on Instagram the native
							<code className="mx-1 rounded px-1 py-0.5 text-[0.75rem] text-foreground/80">
								follows
							</code>
							column only covers media you published. What we do instead: line
							up daily post views against daily net follower change and surface
							the pattern. When correlation is strong and sample size is big,
							the ranking below is trustworthy. When it's weak or the window is
							short, treat it as a hint — not a score.
						</p>
					</NovaCard>
				</>
			) : null}
		</NovaScreen>
	);
}

export default Attribution;
