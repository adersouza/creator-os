import type { CSSProperties } from "react";
import { lazy, Suspense, useEffect, useMemo } from "react";
import {
	type Platform as AnalyticsPlatform,
	daysToFleetTimeframe,
	type ScopedAccountLite,
	toFleetPlatform,
} from "@/components/analytics/analyticsShared";
import { useConnectedAccounts } from "@/hooks/useConnectedAccounts";
import {
	type FleetMetricsState,
	useFleetMetrics,
} from "@/hooks/useFleetMetrics";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { Skeleton } from "@/components/ui/Skeleton";
import type { Platform } from "./shared";

const loadViewsBySourceChart = () => import("./evidence/ViewsBySourceChart");
const loadAnnotationSwimLanesTile = () =>
	import("./evidence/AnnotationSwimLanesTile");
const loadAudienceOverlapTable = () =>
	import("./evidence/AudienceOverlapTable");
const loadCompetitorBenchmarkPanel = () =>
	import("./evidence/CompetitorBenchmarkPanel");
const loadEngagerRetentionTile = () =>
	import("./evidence/EngagerRetentionTile");
const loadEqsForecastCiTile = () => import("./evidence/EqsForecastCiTile");
const loadDiscoveryFunnel = () => import("./evidence/DiscoveryFunnel");
const loadFormatMixWowTrend = () => import("./evidence/FormatMixWowTrend");
const loadGhostPostQueueTile = () => import("./evidence/GhostPostQueueTile");
const loadHashtagPerformanceTable = () =>
	import("./evidence/HashtagPerformanceTable");
const loadIGFormatBreakdownTile = () =>
	import("./evidence/IGFormatBreakdownTile");
const loadIGReachSourceMixTile = () =>
	import("./evidence/IGReachSourceMixTile");
const loadNonFollowerReachTrendTile = () =>
	import("./evidence/NonFollowerReachTrendTile");
const loadQuoteReplyRatioTile = () => import("./evidence/QuoteReplyRatioTile");
const loadReelsSkipRateHistogram = () =>
	import("./evidence/ReelsSkipRateHistogram");
const loadReplyDepthDistributionTile = () =>
	import("./evidence/ReplyDepthDistributionTile");
const loadTopBottomPostsTable = () => import("./evidence/TopBottomPostsTable");
const loadTopicTagLiftCurves = () => import("./evidence/TopicTagLiftCurves");
const loadEngagementVelocityChart = () =>
	import("./evidence/EngagementVelocityChart");
const loadFollowerFlowTile = () => import("./evidence/FollowerFlowTile");
const loadTrajectoryPanel = () => import("./evidence/TrajectoryPanel");
const loadDistributionInputsPanel = () =>
	import("./evidence/DistributionInputsPanel");
const loadConversationSystemPanel = () =>
	import("./evidence/ConversationSystemPanel");
const loadContentMixTernaryTile = () =>
	import("./evidence/ContentMixTernaryTile");
const loadMatrixCoordinateTile = () =>
	import("./evidence/MatrixCoordinateTile");
const loadPostingCadenceHeatmapTile = () =>
	import("./evidence/PostingCadenceHeatmapTile");
const loadStoriesFunnelTile = () =>
	import("@/components/dashboard-v2/tiles/StoriesFunnelTile");
const loadBioLinkFunnelTile = () =>
	import("@/components/dashboard-v2/tiles/BioLinkFunnelTile");
const loadQualityByPillarTile = () =>
	import("@/components/dashboard-v2/tiles/QualityByPillarTile");
const loadHookClassLiftTile = () =>
	import("@/components/dashboard-v2/tiles/HookClassLiftTile");
const loadVanityQualityGapTile = () =>
	import("./evidence/VanityQualityGapTile");
const loadOriginalityRiskTile = () => import("./evidence/OriginalityRiskTile");

const ViewsBySourceChart = lazy(() =>
	loadViewsBySourceChart().then((m) => ({ default: m.ViewsBySourceChart })),
);
const AnnotationSwimLanesTile = lazy(() =>
	loadAnnotationSwimLanesTile().then((m) => ({
		default: m.AnnotationSwimLanesTile,
	})),
);
const AudienceOverlapTable = lazy(() =>
	loadAudienceOverlapTable().then((m) => ({ default: m.AudienceOverlapTable })),
);
const CompetitorBenchmarkPanel = lazy(() =>
	loadCompetitorBenchmarkPanel().then((m) => ({
		default: m.CompetitorBenchmarkPanel,
	})),
);
const EngagerRetentionTile = lazy(() =>
	loadEngagerRetentionTile().then((m) => ({ default: m.EngagerRetentionTile })),
);
const EqsForecastCiTile = lazy(() =>
	loadEqsForecastCiTile().then((m) => ({ default: m.EqsForecastCiTile })),
);
const DiscoveryFunnel = lazy(() =>
	loadDiscoveryFunnel().then((m) => ({ default: m.DiscoveryFunnel })),
);
const FormatMixWowTrend = lazy(() =>
	loadFormatMixWowTrend().then((m) => ({ default: m.FormatMixWowTrend })),
);
const GhostPostQueueTile = lazy(() =>
	loadGhostPostQueueTile().then((m) => ({ default: m.GhostPostQueueTile })),
);
const HashtagPerformanceTable = lazy(() =>
	loadHashtagPerformanceTable().then((m) => ({
		default: m.HashtagPerformanceTable,
	})),
);
const IGFormatBreakdownTile = lazy(() =>
	loadIGFormatBreakdownTile().then((m) => ({
		default: m.IGFormatBreakdownTile,
	})),
);
const IGReachSourceMixTile = lazy(() =>
	loadIGReachSourceMixTile().then((m) => ({
		default: m.IGReachSourceMixTile,
	})),
);
const NonFollowerReachTrendTile = lazy(() =>
	loadNonFollowerReachTrendTile().then((m) => ({
		default: m.NonFollowerReachTrendTile,
	})),
);
const QuoteReplyRatioTile = lazy(() =>
	loadQuoteReplyRatioTile().then((m) => ({ default: m.QuoteReplyRatioTile })),
);
const ReelsSkipRateHistogram = lazy(() =>
	loadReelsSkipRateHistogram().then((m) => ({
		default: m.ReelsSkipRateHistogram,
	})),
);
const ReplyDepthDistributionTile = lazy(() =>
	loadReplyDepthDistributionTile().then((m) => ({
		default: m.ReplyDepthDistributionTile,
	})),
);
const TopBottomPostsTable = lazy(() =>
	loadTopBottomPostsTable().then((m) => ({ default: m.TopBottomPostsTable })),
);
const TopicTagLiftCurves = lazy(() =>
	loadTopicTagLiftCurves().then((m) => ({ default: m.TopicTagLiftCurves })),
);
const EngagementVelocityChart = lazy(() =>
	loadEngagementVelocityChart().then((m) => ({
		default: m.EngagementVelocityChart,
	})),
);
const FollowerFlowTile = lazy(() =>
	loadFollowerFlowTile().then((m) => ({ default: m.FollowerFlowTile })),
);
const TrajectoryPanel = lazy(() =>
	loadTrajectoryPanel().then((m) => ({ default: m.TrajectoryPanel })),
);
const DistributionInputsPanel = lazy(() =>
	loadDistributionInputsPanel().then((m) => ({
		default: m.DistributionInputsPanel,
	})),
);
const ConversationSystemPanel = lazy(() =>
	loadConversationSystemPanel().then((m) => ({
		default: m.ConversationSystemPanel,
	})),
);
const ContentMixTernaryTile = lazy(() =>
	loadContentMixTernaryTile().then((m) => ({
		default: m.ContentMixTernaryTile,
	})),
);
const MatrixCoordinateTile = lazy(() =>
	loadMatrixCoordinateTile().then((m) => ({ default: m.MatrixCoordinateTile })),
);
const PostingCadenceHeatmapTile = lazy(() =>
	loadPostingCadenceHeatmapTile().then((m) => ({
		default: m.PostingCadenceHeatmapTile,
	})),
);
const StoriesFunnelTile = lazy(() =>
	loadStoriesFunnelTile().then((m) => ({ default: m.StoriesFunnelTile })),
);
const BioLinkFunnelTile = lazy(() =>
	loadBioLinkFunnelTile().then((m) => ({ default: m.BioLinkFunnelTile })),
);
const QualityByPillarTile = lazy(() =>
	loadQualityByPillarTile().then((m) => ({ default: m.QualityByPillarTile })),
);
const HookClassLiftTile = lazy(() =>
	loadHookClassLiftTile().then((m) => ({ default: m.HookClassLiftTile })),
);
const VanityQualityGapTile = lazy(() =>
	loadVanityQualityGapTile().then((m) => ({ default: m.VanityQualityGapTile })),
);
const OriginalityRiskTile = lazy(() =>
	loadOriginalityRiskTile().then((m) => ({ default: m.OriginalityRiskTile })),
);

interface EvidenceRowsProps {
	platform: Platform;
	/** Real day count from the date range. */
	days: number;
	/** Pre-fetched fleet metrics from the parent. When provided, child evidence
	 *  panels can avoid redundant fleet hook calls. */
	fleet?: FleetMetricsState | undefined;
	accountIds?: string[] | undefined;
	groupId?: string | null | undefined;
}

/**
 * Evidence 2-up rows — spec §7. Each row uses the intentional 5/4 asymmetric
 * split (left = col-1-5, right = col 6-9 — left is wider for denser text
 * content like bullet charts + attribution lists). Section anchors
 * (id="evidence-N") are the scroll targets for .ev links in the hero
 * narrative.
 */
export function EvidenceRows({
	platform,
	days,
	fleet: fleetProp,
	accountIds,
	groupId,
}: EvidenceRowsProps) {
	const scopedAccount = useAccountScopeStore((s) => s.scopedAccount);
	const fleetTimeframe = useMemo(() => daysToFleetTimeframe(days), [days]);
	const fallbackFleet = useFleetMetrics(
		fleetTimeframe,
		toFleetPlatform(platform),
		scopedAccount,
		{ enabled: !fleetProp, accountIds, groupId },
	);
	const fleet = fleetProp ?? fallbackFleet;
	const { accounts } = useConnectedAccounts();

	const visibleAccounts = useMemo(() => {
		if (scopedAccount?.id) {
			const scoped = accounts.find((a) => a.id === scopedAccount.id);
			return scoped ? [scoped] : [];
		}
		const scopedIds =
			accountIds && accountIds.length > 0 ? new Set(accountIds) : null;
		const scopedAccounts = scopedIds
			? accounts.filter((a) => scopedIds.has(a.id))
			: accounts;
		if (platform === "ig") {
			return scopedAccounts.filter((a) => a.platform === "instagram");
		}
		if (platform === "threads") {
			return scopedAccounts.filter((a) => a.platform === "threads");
		}
		return scopedAccounts;
	}, [accounts, accountIds, platform, scopedAccount]);
	const visibleAccountIds = useMemo(
		() => {
			const hasFleetScope =
				!scopedAccount?.id && !!(groupId || (accountIds && accountIds.length > 0));
			return hasFleetScope ? visibleAccounts.map((a) => a.id) : undefined;
		},
		[accountIds, groupId, scopedAccount, visibleAccounts],
	);

	// Scope resolution for views-by-source: single account drill-in beats
	// the fleet filter, else pass every Threads id visible to the viewer.
	const viewsByScope = useMemo(() => {
		if (scopedAccount?.id && scopedAccount.platform === "threads") {
			return { accountId: scopedAccount.id, accountIds: null };
		}
		const threadsIds = visibleAccounts
			.filter((a) => a.platform === "threads")
			.map((a) => a.id);
		return { accountId: null, accountIds: threadsIds };
	}, [scopedAccount, visibleAccounts]);
	const viewsDays = days;

	const analyticsPlatform = platform as AnalyticsPlatform;
	const igEvidencePlatform = platform === "ig" ? "instagram" : "all";

	useEffect(() => {
		if (isPhoneLikeViewport()) return undefined;
		return warmEvidenceChunks(platform);
	}, [platform]);

	return (
		<div className="flex flex-col gap-5">
			{platform !== "threads" ? (
				<Section
					title="Growth research"
					eyebrow="Stories · Bio · Quality · Research"
					defer
					anchorIds={[
						"evidence-stories-funnel",
						"evidence-bio-link-funnel",
						"evidence-quality-by-pillar",
						"evidence-hook-class-lift",
						"evidence-content-mix",
						"evidence-quality-gap",
					]}
				>
					<Bento>
						<BentoCell id="evidence-quality-by-pillar" span={7} size="feature">
							<DashboardTileBridge>
								<QualityByPillarTile
									scopedAccount={scopedAccount}
									accountIds={visibleAccountIds}
									groupId={groupId}
									platform={igEvidencePlatform}
								/>
							</DashboardTileBridge>
						</BentoCell>
						<BentoCell id="evidence-hook-class-lift" span={5} size="standard">
							<DashboardTileBridge>
								<HookClassLiftTile
									scopedAccount={scopedAccount}
									accountIds={visibleAccountIds}
									groupId={groupId}
									platform={igEvidencePlatform}
								/>
							</DashboardTileBridge>
						</BentoCell>
						<BentoCell id="evidence-content-mix" span={6} size="standard">
							<ContentMixTernaryTile
								days={days}
								scopedAccount={scopedAccount as ScopedAccountLite}
								accountIds={visibleAccountIds}
							/>
						</BentoCell>
						<BentoCell id="evidence-stories-funnel" span={3} size="compact">
							<DashboardTileBridge>
								<StoriesFunnelTile
									scopedAccount={scopedAccount}
									accountIds={visibleAccountIds}
									groupId={groupId}
								/>
							</DashboardTileBridge>
						</BentoCell>
						<BentoCell id="evidence-bio-link-funnel" span={3} size="compact">
							<DashboardTileBridge>
								<BioLinkFunnelTile
									scopedAccount={scopedAccount}
									accountIds={visibleAccountIds}
									groupId={groupId}
								/>
							</DashboardTileBridge>
						</BentoCell>
						<BentoCell id="evidence-quality-gap" span={12} size="compact">
							<VanityQualityGapTile
								days={days}
								scopedAccount={scopedAccount as ScopedAccountLite}
								accountIds={visibleAccountIds}
							/>
						</BentoCell>
					</Bento>
				</Section>
			) : null}

			<Section
				title="Fleet anomaly view"
				eyebrow="Metric matrix"
				defer
				anchorIds={["evidence-matrix"]}
			>
				<Bento>
					<BentoCell id="evidence-matrix" span={12} size="table">
						<MatrixCoordinateTile fleet={fleet} />
					</BentoCell>
				</Bento>
			</Section>

			{platform !== "threads" ? (
				<Section
					title="Acquisition path"
					eyebrow="Discovery funnel · Engagement velocity"
					defer
					anchorIds={["evidence-8", "evidence-velocity"]}
				>
					<Bento>
						<BentoCell id="evidence-8" span={4} size="compact">
							<DiscoveryFunnel
								days={days}
								accountIds={visibleAccountIds}
								groupId={groupId}
							/>
						</BentoCell>
						<BentoCell id="evidence-velocity" span={8} size="feature">
							<EngagementVelocityChart
								days={days}
								platform={platform === "all" ? "all" : "instagram"}
								scopedAccount={scopedAccount as ScopedAccountLite}
								accountIds={visibleAccountIds}
								groupId={groupId}
							/>
						</BentoCell>
					</Bento>
				</Section>
			) : null}

			<Section
				title="Trajectory"
				eyebrow={
					platform === "threads"
						? "EQS forecast · annotations"
						: "EQS forecast · discovery split · confidence · annotations"
				}
				defer
				anchorIds={[
					"evidence-trajectory",
					"evidence-eqs-forecast-ci",
					"evidence-annotation-lanes",
				]}
			>
				<Bento>
					<BentoCell id="evidence-trajectory" span={12} size="hero">
						<TrajectoryPanel
							platform={analyticsPlatform}
							days={days}
							scopedAccount={scopedAccount as ScopedAccountLite}
							live={fleet}
							accounts={visibleAccounts}
						/>
					</BentoCell>
					<BentoCell id="evidence-eqs-forecast-ci" span={7} size="feature">
						<EqsForecastCiTile
							platform={analyticsPlatform}
							days={days}
							scopedAccount={scopedAccount as ScopedAccountLite}
							live={fleet}
						/>
					</BentoCell>
					<BentoCell id="evidence-annotation-lanes" span={5} size="compact">
						<AnnotationSwimLanesTile
							days={days}
							scopedAccount={scopedAccount as ScopedAccountLite}
							accounts={visibleAccounts}
						/>
					</BentoCell>
				</Bento>
			</Section>

			{platform !== "threads" ? (
				<Section
					title="Distribution system"
					eyebrow="Format · surface · hashtags · Reels friction"
					defer
					anchorIds={[
						"evidence-distribution-inputs",
						"evidence-non-follower-reach",
						"evidence-ig-reach-mix",
						"evidence-ig-format-breakdown",
						"evidence-hashtag-performance",
						"evidence-reels-skip-rate",
					]}
				>
					<Bento>
						<BentoCell id="evidence-distribution-inputs" span={12} size="feature">
							<DistributionInputsPanel
								days={days}
								scopedAccount={scopedAccount as ScopedAccountLite}
								platform={platform === "all" ? "all" : "instagram"}
								accountIds={visibleAccountIds}
								groupId={groupId}
							/>
						</BentoCell>
						<BentoCell id="evidence-hashtag-performance" span={7} size="table">
							<HashtagPerformanceTable
								days={days}
								platform={platform === "ig" ? "instagram" : "all"}
								scopedAccount={scopedAccount}
								accountIds={visibleAccountIds}
								groupId={groupId}
							/>
						</BentoCell>
						<BentoStackCell span={5}>
							<BentoStackItem id="evidence-reels-skip-rate" size="feature">
								<ReelsSkipRateHistogram
									days={days}
									scopedAccount={scopedAccount as ScopedAccountLite}
									accountIds={visibleAccountIds}
									groupId={groupId}
								/>
							</BentoStackItem>
							<BentoStackItem id="evidence-non-follower-reach">
								<NonFollowerReachTrendTile
									days={days}
									scopedAccount={scopedAccount as ScopedAccountLite}
									accountIds={visibleAccountIds}
									groupId={groupId}
								/>
							</BentoStackItem>
							<BentoStackItem id="evidence-ig-reach-mix">
								<IGReachSourceMixTile
									days={days}
									scopedAccount={scopedAccount as ScopedAccountLite}
									accountIds={visibleAccountIds}
									groupId={groupId}
								/>
							</BentoStackItem>
							<BentoStackItem id="evidence-ig-format-breakdown">
								<IGFormatBreakdownTile
									days={days}
									scopedAccount={scopedAccount as ScopedAccountLite}
									accountIds={visibleAccountIds}
								/>
							</BentoStackItem>
						</BentoStackCell>
					</Bento>
				</Section>
			) : (
				<Section
					title="Audience + content"
					eyebrow="Follower flow · Format mix"
					defer
					anchorIds={["evidence-6", "evidence-3"]}
				>
					<Bento>
						<BentoCell id="evidence-6" span={4} size="feature">
							<FollowerFlowTile
								platform={analyticsPlatform}
								days={days}
								scopedAccount={scopedAccount as ScopedAccountLite}
								accountIds={visibleAccountIds}
							/>
						</BentoCell>
						<BentoCell id="evidence-3" span={8} size="feature">
							<FormatMixWowTrend
								metric="views"
								scopedAccount={scopedAccount}
								accountIds={visibleAccountIds}
								groupId={groupId}
							/>
						</BentoCell>
					</Bento>
				</Section>
			)}

			<Section
				title="Publishing cadence"
				eyebrow="Account × day heatmap"
				defer
				anchorIds={["evidence-cadence-heatmap"]}
			>
				<Bento>
					<BentoCell id="evidence-cadence-heatmap" span={12} size="table">
						<PostingCadenceHeatmapTile
							platform={platform}
							days={days}
							scopedAccount={scopedAccount as ScopedAccountLite}
							accountIds={visibleAccountIds}
							groupId={groupId}
						/>
					</BentoCell>
				</Bento>
			</Section>

			{platform !== "ig" ? (
				<Section
					title="Conversation system"
					eyebrow="Reply depth · quote ratio · suppression · originality · overlap"
					defer
					anchorIds={[
						"evidence-conversation-system",
						"evidence-reply-depth-distribution",
						"evidence-quote-reply-ratio",
						"evidence-ghost-post-queue",
						"evidence-audience-overlap",
					]}
				>
					<Bento>
						<BentoCell id="evidence-conversation-system" span={12} size="hero">
							<ConversationSystemPanel
								days={days}
								scopedAccount={scopedAccount as ScopedAccountLite}
								accountIds={visibleAccountIds}
								platform={platform === "threads" ? "threads" : "all"}
							/>
						</BentoCell>
						<BentoCell id="evidence-reply-depth-distribution" span={6} size="standard">
							<ReplyDepthDistributionTile
								days={days}
								scopedAccount={scopedAccount as ScopedAccountLite}
							/>
						</BentoCell>
						<BentoCell id="evidence-quote-reply-ratio" span={6} size="standard">
							<QuoteReplyRatioTile
								days={days}
								scopedAccount={scopedAccount as ScopedAccountLite}
								accountIds={visibleAccountIds}
							/>
						</BentoCell>
						<BentoCell id="evidence-ghost-post-queue" span={5} size="compact">
							<GhostPostQueueTile accountIds={visibleAccountIds} />
						</BentoCell>
						<BentoCell id="evidence-audience-overlap" span={7} size="table">
							<AudienceOverlapTable
								scopedAccount={scopedAccount}
								accountIds={visibleAccountIds}
								groupId={groupId}
							/>
						</BentoCell>
					</Bento>
				</Section>
			) : null}

			<Section
				title="Post performance"
				eyebrow={
					platform === "ig"
						? "Top/bottom posts · Originality risk"
						: "Top/bottom posts"
				}
				defer
				anchorIds={
					platform === "ig" ? ["evidence-15", "evidence-5"] : ["evidence-15"]
				}
			>
				<Bento>
					<BentoCell id="evidence-15" span={platform === "ig" ? 8 : 12} size="table">
						<TopBottomPostsTable
							days={days}
							platform={
								platform === "all"
									? "all"
									: platform === "ig"
										? "instagram"
										: "threads"
							}
							scopedAccount={scopedAccount}
							accountIds={visibleAccountIds}
							groupId={groupId}
						/>
					</BentoCell>
					{platform === "ig" ? (
						<BentoCell id="evidence-5" span={4} size="compact">
							<OriginalityRiskTile
								platform="instagram"
								days={days}
								accountIds={visibleAccountIds}
								groupId={groupId}
							/>
						</BentoCell>
					) : null}
				</Bento>
			</Section>

			<Section
				title={
					platform === "threads" ? "Distribution + benchmarks" : "Benchmarks"
				}
				eyebrow={
					platform === "threads" ? "Source mix · Benchmarks" : "Peer comparison"
				}
				defer
				anchorIds={
					platform === "threads"
						? ["evidence-source-mix", "evidence-11"]
						: ["evidence-11"]
				}
			>
				<Bento>
					{platform === "threads" ? (
						<BentoCell id="evidence-source-mix" span={7} size="table">
							<ViewsBySourceChart
								accountId={viewsByScope.accountId}
								accountIds={viewsByScope.accountIds}
								days={viewsDays}
							/>
						</BentoCell>
					) : null}
					{platform === "threads" ? (
						<BentoCell id="evidence-11" span={5} size="compact">
							<CompetitorBenchmarkPanel
								platform="threads"
								scopedAccount={scopedAccount}
								accountIds={visibleAccountIds}
								groupId={groupId}
							/>
						</BentoCell>
					) : null}
					{platform !== "threads" ? (
						<BentoCell id="evidence-11" span={12} size="compact">
							<CompetitorBenchmarkPanel
								platform="instagram"
								scopedAccount={scopedAccount}
								accountIds={visibleAccountIds}
								groupId={groupId}
							/>
						</BentoCell>
					) : null}
				</Bento>
			</Section>

			<Section
				title={
					platform === "threads" ? "Topic retention" : "Signals + retention"
				}
				eyebrow={
					platform === "threads"
						? "Topics · Retention"
						: platform === "ig"
							? "Follower flow · Topics · Retention"
							: "Follower flow · Topics · Retention"
				}
				defer
				anchorIds={
					platform !== "threads"
						? ["evidence-6", "evidence-topic-curves"]
						: ["evidence-topic-curves", "evidence-18"]
				}
			>
				{platform !== "threads" ? (
					<Bento>
						<BentoCell id="evidence-6" span={4} size="feature">
							<FollowerFlowTile
								platform={analyticsPlatform}
								days={days}
								scopedAccount={scopedAccount as ScopedAccountLite}
								accountIds={visibleAccountIds}
							/>
						</BentoCell>
						<BentoCell id="evidence-topic-curves" span={8} size="feature">
							<TopicTagLiftCurves
								periodDays={days}
								platform={platform === "ig" ? "instagram" : "all"}
								scopedAccount={scopedAccount}
								accountIds={visibleAccountIds}
								groupId={groupId}
							/>
						</BentoCell>
					</Bento>
				) : (
					<Bento>
						<BentoCell id="evidence-topic-curves" span={7} size="table">
							<TopicTagLiftCurves
								periodDays={days}
								platform="threads"
								scopedAccount={scopedAccount}
								accountIds={visibleAccountIds}
								groupId={groupId}
							/>
						</BentoCell>
						<BentoCell id="evidence-18" span={5} size="standard">
							<EngagerRetentionTile
								platform="threads"
								periodDays={days}
								scopedAccount={scopedAccount}
								accountIds={visibleAccountIds}
								groupId={groupId}
							/>
						</BentoCell>
					</Bento>
				)}
			</Section>
		</div>
	);
}

function DashboardTileBridge({ children }: { children: React.ReactNode }) {
	return (
		<EvidenceCard className="h-full" contentClassName="h-full p-0 [&>*]:h-full">
			{children}
		</EvidenceCard>
	);
}

function Section({
	title,
	eyebrow,
	children,
	anchorIds = [],
}: {
	title: string;
	eyebrow: string;
	children: React.ReactNode;
	defer?: boolean | undefined;
	anchorIds?: string[] | undefined;
}) {
	return (
		<section
			aria-label={`${title}: ${eyebrow}`}
			className="analytics-evidence-section relative flex flex-col scroll-mt-24"
		>
			<div className="flex items-center gap-3 pt-1">
				<h2 className="text-[0.75rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
					{title}
				</h2>
				<div className="h-px flex-1 bg-border/70" aria-hidden="true" />
			</div>
			{anchorIds.map((id) => (
				<span key={id} id={id} className="absolute top-0 scroll-mt-24" />
			))}
			<Suspense fallback={<DeferredSectionSkeleton />}>
				<div className="analytics-evidence-stack flex flex-col gap-5">
					{children}
				</div>
			</Suspense>
		</section>
	);
}

function isPhoneLikeViewport() {
	if (typeof window === "undefined") return false;
	return window.matchMedia(
		"(max-width: 767px) and (hover: none) and (pointer: coarse)",
	).matches;
}

function DeferredSectionSkeleton() {
	return (
		<div
			className="grid grid-cols-1 lg:grid-cols-2 gap-4"
			aria-label="Loading analytics widgets"
			role="status"
		>
			{[0, 1].map((index) => (
				<EvidenceCard
					key={index}
					state="loading"
					className="min-h-[260px]"
					contentClassName="flex min-h-[260px] flex-col gap-8"
				>
					<div className="flex flex-col gap-3">
						<Skeleton className="h-3 w-28 rounded-full" />
						<Skeleton className="h-5 w-48 max-w-[70%] rounded-full" />
						<Skeleton className="h-3 w-64 max-w-[86%] rounded-full" />
					</div>
					<div className="flex flex-col gap-3">
						<Skeleton className="h-3 w-[88%] rounded-full" />
						<Skeleton className="h-3 w-[64%] rounded-full" />
						<Skeleton className="h-3 w-[76%] rounded-full" />
					</div>
					<div className="grid grid-cols-3 gap-2">
						{[0, 1, 2].map((metric) => (
							<div
								key={metric}
								className="rounded-lg border border-border bg-muted/35 p-3"
							>
								<Skeleton className="h-7 w-14 rounded-md" />
								<Skeleton className="mt-2 h-2 w-16 rounded-full" />
							</div>
						))}
					</div>
				</EvidenceCard>
			))}
		</div>
	);
}

function Bento({ children }: { children: React.ReactNode }) {
	return (
		<div className="analytics-evidence-bento grid grid-cols-1 lg:grid-cols-12 items-stretch">
			{children}
		</div>
	);
}

function BentoCell({
	children,
	id,
	span,
	compact = false,
	size = "standard",
}: {
	children: React.ReactNode;
	id: string;
	span: 3 | 4 | 5 | 6 | 7 | 8 | 12;
	compact?: boolean | undefined;
	size?: "compact" | "standard" | "feature" | "table" | "hero" | undefined;
}) {
	const resolvedSize = compact ? "compact" : size;
	return (
		<div
			id={id}
			className={[
				"analytics-evidence-bento-cell scroll-mt-24 h-full min-w-0 [&>*]:h-full",
				"empty:hidden",
				`analytics-evidence-bento-cell-${resolvedSize}`,
			].join(" ")}
			style={{ "--analytics-bento-span": span } as CSSProperties}
		>
			{children}
		</div>
	);
}

function BentoStackCell({
	children,
	span,
}: {
	children: React.ReactNode;
	span: 3 | 4 | 5 | 6 | 7 | 8 | 12;
}) {
	return (
		<div
			className="analytics-evidence-bento-cell analytics-evidence-bento-stack-cell min-w-0"
			style={{ "--analytics-bento-span": span } as CSSProperties}
		>
			{children}
		</div>
	);
}

function BentoStackItem({
	children,
	id,
	size = "compact",
}: {
	children: React.ReactNode;
	id: string;
	size?: "compact" | "feature";
}) {
	return (
		<div
			id={id}
			className={`analytics-evidence-bento-stack-item analytics-evidence-bento-stack-item-${size} scroll-mt-24 min-w-0`}
		>
			{children}
		</div>
	);
}

function warmEvidenceChunks(platform: Platform) {
	if (typeof window === "undefined") return;

	const sharedCritical = [
		loadTrajectoryPanel,
		loadEqsForecastCiTile,
		loadAnnotationSwimLanesTile,
		loadFollowerFlowTile,
		loadFormatMixWowTrend,
		loadPostingCadenceHeatmapTile,
		loadTopBottomPostsTable,
		loadCompetitorBenchmarkPanel,
		loadTopicTagLiftCurves,
		loadEngagerRetentionTile,
	];
	const igCritical = [
		loadStoriesFunnelTile,
		loadBioLinkFunnelTile,
		loadQualityByPillarTile,
		loadHookClassLiftTile,
		loadContentMixTernaryTile,
		loadVanityQualityGapTile,
		loadDiscoveryFunnel,
		loadEngagementVelocityChart,
		loadDistributionInputsPanel,
		loadNonFollowerReachTrendTile,
		loadIGReachSourceMixTile,
		loadIGFormatBreakdownTile,
		loadHashtagPerformanceTable,
		loadReelsSkipRateHistogram,
		loadOriginalityRiskTile,
	];
	const threadsCritical = [
		loadConversationSystemPanel,
		loadReplyDepthDistributionTile,
		loadQuoteReplyRatioTile,
		loadGhostPostQueueTile,
		loadAudienceOverlapTable,
		loadOriginalityRiskTile,
		loadViewsBySourceChart,
	];

	const loaders = [
		...sharedCritical,
		...(platform !== "threads" ? igCritical : []),
		...(platform !== "ig" ? threadsCritical : []),
	];

	let index = 0;
	let cancelled = false;
	const runNext = () => {
		if (cancelled) return;
		const load = loaders[index];
		index += 1;
		if (!load) return;
		void load()
			.catch(() => {})
			.finally(scheduleNext);
	};
	const scheduleNext = () => {
		if (cancelled || index >= loaders.length) return;
		const idle = (
			window as Window & {
				requestIdleCallback?: (
					callback: () => void,
					opts?: { timeout: number },
				) => number | undefined;
			}
		).requestIdleCallback;
		if (idle) idle(runNext, { timeout: 1200 });
		else window.setTimeout(runNext, 80);
	};

	scheduleNext();
	return () => {
		cancelled = true;
	};
}
