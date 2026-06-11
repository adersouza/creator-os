#!/usr/bin/env node
import { readFileSync } from "node:fs";

const files = [
	"src/components/layout/Layout.tsx",
	"src/components/layout/ActivityPanel.tsx",
	"src/components/layout/AuthLayout.tsx",
	"src/components/layout/MobileTabBar.tsx",
	"src/components/layout/NovaScreen.tsx",
	"src/components/layout/ShortcutsHelp.tsx",
	"src/components/layout/mobile/MobileSection.tsx",
	"src/components/layout/mobile/MobileSegmented.tsx",
	"src/components/layout/mobile/MobileTopBar.tsx",
	"src/pages/Dashboard.tsx",
	"src/components/dashboard-v2/DashboardV2.tsx",
	"src/components/dashboard-v2/tiles/HeroTile.tsx",
	"src/components/dashboard-v2/tiles/AnomalyFeedTile.tsx",
	"src/components/dashboard-v2/tiles/BioLinkFunnelTile.tsx",
	"src/components/dashboard-v2/tiles/ConversationQualityTile.tsx",
	"src/components/dashboard-v2/tiles/FollowsTodayTile.tsx",
	"src/components/dashboard-v2/tiles/HookClassLiftTile.tsx",
	"src/components/dashboard-v2/tiles/HookStrengthTile.tsx",
	"src/components/dashboard-v2/tiles/IgV2Tiles.tsx",
	"src/components/dashboard-v2/tiles/LiveFirstSixHoursTile.tsx",
	"src/components/dashboard-v2/tiles/LivePulsePanel.tsx",
	"src/components/dashboard-v2/tiles/ManagerReadinessTile.tsx",
	"src/components/dashboard-v2/tiles/NeedsPostsTile.tsx",
	"src/components/dashboard-v2/tiles/OperatorTaskQueueTile.tsx",
	"src/components/dashboard-v2/tiles/OpsHealthTile.tsx",
	"src/components/dashboard-v2/tiles/QualityByPillarTile.tsx",
	"src/components/dashboard-v2/tiles/ReplyDepthLeadersTile.tsx",
	"src/components/dashboard-v2/tiles/ScorecardTile.tsx",
	"src/components/dashboard-v2/tiles/SmallTiles.tsx",
	"src/components/dashboard-v2/tiles/StoriesFunnelTile.tsx",
	"src/components/dashboard-v2/tiles/StreakTile.tsx",
	"src/components/dashboard-v2/tiles/ThreadsTiles.tsx",
	"src/pages/Analytics.tsx",
	"src/pages/Billing.tsx",
	"src/pages/Composer.tsx",
	"src/pages/Calendar.tsx",
	"src/pages/Content.tsx",
	"src/pages/ContentLibrary.tsx",
	"src/pages/Settings.tsx",
	"src/pages/Attribution.tsx",
	"src/pages/ApprovalQueue.tsx",
	"src/pages/Listening.tsx",
	"src/components/dashboard/MobileOverview.tsx",
	"src/components/dashboard-v2/tiles/FleetDotGrid.tsx",
	"src/components/skeletons/PageSkeletons.tsx",
	"src/components/analytics/analyticsShared.ts",
	"src/components/analytics/AutoInsightsFeed.tsx",
	"src/components/analytics/InvestigateButton.tsx",
	"src/components/analytics/InvestigatePanel.tsx",
	"src/components/analytics/widgets/explorer/SelfCompareDeepDive.tsx",
	"src/components/analytics/widgets/system/SmartLinksAnalytics.tsx",
	"src/components/analytics-v2/ExportCsvButton.tsx",
	"src/components/composer/ComposerFormControls.tsx",
	"src/components/composer/SchedulingOptions.tsx",
	"src/components/composer/VariantsLab.tsx",
	"src/components/composer/CrossPostDiffResolver.tsx",
	"src/components/composer/CustomPromptModal.tsx",
	"src/components/composer/VoiceContextFile.tsx",
	"src/components/composer/ComposerTopStrip.tsx",
	"src/components/composer/SlashMenu.tsx",
	"src/components/composer/SelectionActionBar.tsx",
	"src/components/composer/InstagramOptionsPanel.tsx",
	"src/components/composer/ThreadsOptionsPanel.tsx",
	"src/components/composer/MediaGrid.tsx",
	"src/components/composer/AccountSelector.tsx",
	"src/components/composer/ComposerStatusChip.tsx",
	"src/components/composer/ChannelHealthPills.tsx",
	"src/components/composer/PreviewSection.tsx",
	"src/components/composer/ComposerModal.tsx",
	"src/components/composer/CritiquePanel.tsx",
	"src/components/calendar/MonthViewGrid.tsx",
	"src/components/calendar/PortfolioMatrix.tsx",
	"src/components/calendar/PostingStreakMatrix.tsx",
	"src/components/calendar/CalendarFilterBar.tsx",
	"src/components/calendar/CalendarHero.tsx",
	"src/components/calendar/WeekViewGrid.tsx",
	"src/components/calendar/PostCardRow.tsx",
	"src/components/calendar/CalendarListView.tsx",
	"src/components/calendar/BulkActionBar.tsx",
	"src/components/calendar/RescheduleDiffCard.tsx",
	"src/components/calendar/CampaignFactoryAudioReviewQueue.tsx",
	"src/components/calendar/QueueHealthStrip.tsx",
	"src/components/calendar/CommandPalette.tsx",
	"src/components/calendar/PostDetailSlideOver.tsx",
	"src/components/accounts/MobileAccounts.tsx",
	"src/components/accounts/AccountGroupsPanel.tsx",
	"src/components/accounts/AccountsFilterBar.tsx",
	"src/components/accounts/AccountBulkBar.tsx",
	"src/components/accounts/AccountMoveGroupModal.tsx",
	"src/components/accounts/AccountReconnectModal.tsx",
	"src/components/accounts/AccountMapView.tsx",
	"src/components/accounts/AccountsHero.tsx",
	"src/components/accounts/AccountListView.tsx",
	"src/components/accounts/AccountGroupsRail.tsx",
	"src/components/accounts/AccountDetailSlideOver.tsx",
	"src/components/settings/ProfileTabContent.tsx",
	"src/components/settings/WorkspaceTabContent.tsx",
	"src/components/settings/VoiceProfilesEditorTab.tsx",
	"src/components/settings/AppearanceTabContent.tsx",
	"src/components/settings/CohortSharingCard.tsx",
	"src/components/settings/DataExportCard.tsx",
	"src/components/settings/SecurityTabContent.tsx",
	"src/components/settings/BetaProgramTab.tsx",
	"src/components/settings/DeletionStatusTab.tsx",
	"src/components/settings/NotificationsTabContent.tsx",
	"src/components/settings/WebhooksTabContent.tsx",
	"src/components/settings/APITabContent.tsx",
	"src/components/settings/AdminTabsContent.tsx",
	"src/components/settings/ConnectionsTabContent.tsx",
	"src/components/settings/VoiceProfileEditor.tsx",
	"src/components/ui/ListRow.tsx",
	"src/components/ui/NovaPrimitives.tsx",
	"src/components/inbox/ActionIconButton.tsx",
	"src/components/inbox/ReplyComposer.tsx",
	"src/components/inbox/ConversationRow.tsx",
	"src/components/inbox/ContextRail.tsx",
	"src/components/inbox/AssignmentChip.tsx",
	"src/components/inbox/ThreadDetailPane.tsx",
	"src/components/inbox/ConversationListPane.tsx",
	"src/components/inbox/InboxChrome.tsx",
	"src/components/content-library/ContentHero.tsx",
	"src/components/content-library/MediaView.tsx",
	"src/components/content-library/MediaUploadZone.tsx",
	"src/components/content-library/RecentStrip.tsx",
	"src/components/content-library/shared.tsx",
	"src/components/content-library/UnavailablePanel.tsx",
	"src/pages/Links.tsx",
	"src/components/links/EmptyDetail.tsx",
	"src/components/links/LinkRow.tsx",
	"src/pages/Reports.tsx",
	"src/pages/PublishingSetup.tsx",
	"src/pages/Handoff.tsx",
	"src/pages/SharedReport.tsx",
	"src/pages/Ideas.tsx",
	"src/pages/Autopilot.tsx",
	"src/pages/Landing.tsx",
	"src/pages/legal/LegalPage.tsx",
	"src/pages/auth/AuthCallback.tsx",
	"src/pages/auth/InviteAccept.tsx",
	"src/pages/auth/Login.tsx",
	"src/pages/auth/OAuthCallback.tsx",
	"src/pages/auth/ResetPassword.tsx",
	"src/pages/auth/Signup.tsx",
	"src/pages/auth/Welcome.tsx",
	"src/components/links/AIEnhancePanel.tsx",
	"src/components/links/BlockListEditor.tsx",
	"src/components/links/LinkDetailPane.tsx",
	"src/components/links/LinkPagePreview.tsx",
	"src/components/links/PixelExtensionsPanel.tsx",
	"src/components/reports/ReportEditor.tsx",
	"src/components/autopilot/AutopilotModePages.tsx",
];

const banned = [
	"OperatorPageHeader",
	"RaycastChrome",
	"RaycastTag",
	"WidgetCard",
	"MetricCard",
	"components/ui/Tile",
	"<Tile ",
	"<Tile>",
	"</Tile>",
	"EmptyState",
	"EliteEmptyState",
	"operator-",
	"dv2-",
	"j33-",
	"links-material-page",
	"links-kpi-ribbon",
	'className="card',
	"className={'card",
	'className={"card',
	"components/analytics-v2",
	"MobileActionBar",
	"MobileBarButton",
	"MobileSheet",
	"composer-preview-underline",
];

const rawControlFiles = new Set([
	"src/components/layout/ActivityPanel.tsx",
	"src/pages/Billing.tsx",
	"src/components/dashboard-v2/tiles/HeroTile.tsx",
	"src/components/dashboard-v2/tiles/ManagerReadinessTile.tsx",
	"src/pages/Calendar.tsx",
	"src/pages/ContentLibrary.tsx",
	"src/pages/Settings.tsx",
	"src/pages/Attribution.tsx",
	"src/pages/ApprovalQueue.tsx",
	"src/pages/Listening.tsx",
	"src/components/dashboard/MobileOverview.tsx",
	"src/components/dashboard-v2/tiles/FleetDotGrid.tsx",
	"src/components/analytics/InvestigateButton.tsx",
	"src/components/analytics/InvestigatePanel.tsx",
	"src/components/analytics-v2/ExportCsvButton.tsx",
	"src/components/composer/ComposerFormControls.tsx",
	"src/components/composer/SchedulingOptions.tsx",
	"src/components/composer/VariantsLab.tsx",
	"src/components/composer/CrossPostDiffResolver.tsx",
	"src/components/composer/CustomPromptModal.tsx",
	"src/components/composer/VoiceContextFile.tsx",
	"src/components/composer/ComposerTopStrip.tsx",
	"src/components/composer/SlashMenu.tsx",
	"src/components/composer/SelectionActionBar.tsx",
	"src/components/composer/InstagramOptionsPanel.tsx",
	"src/components/composer/ThreadsOptionsPanel.tsx",
	"src/components/composer/MediaGrid.tsx",
	"src/components/composer/AccountSelector.tsx",
	"src/components/calendar/MonthViewGrid.tsx",
	"src/components/calendar/PortfolioMatrix.tsx",
	"src/components/calendar/PostingStreakMatrix.tsx",
	"src/components/calendar/CalendarFilterBar.tsx",
	"src/components/calendar/CalendarHero.tsx",
	"src/components/calendar/WeekViewGrid.tsx",
	"src/components/calendar/PostCardRow.tsx",
	"src/components/calendar/CalendarListView.tsx",
	"src/components/calendar/BulkActionBar.tsx",
	"src/components/calendar/RescheduleDiffCard.tsx",
	"src/components/calendar/CampaignFactoryAudioReviewQueue.tsx",
	"src/components/calendar/QueueHealthStrip.tsx",
	"src/components/calendar/CommandPalette.tsx",
	"src/components/calendar/PostDetailSlideOver.tsx",
	"src/components/accounts/MobileAccounts.tsx",
	"src/components/accounts/AccountGroupsPanel.tsx",
	"src/components/accounts/AccountsFilterBar.tsx",
	"src/components/accounts/AccountBulkBar.tsx",
	"src/components/accounts/AccountMoveGroupModal.tsx",
	"src/components/accounts/AccountReconnectModal.tsx",
	"src/components/accounts/AccountMapView.tsx",
	"src/components/accounts/AccountsHero.tsx",
	"src/components/accounts/AccountListView.tsx",
	"src/components/accounts/AccountGroupsRail.tsx",
	"src/components/accounts/AccountDetailSlideOver.tsx",
	"src/components/inbox/ActionIconButton.tsx",
	"src/components/inbox/ReplyComposer.tsx",
	"src/components/inbox/ConversationRow.tsx",
	"src/components/inbox/ContextRail.tsx",
	"src/components/inbox/AssignmentChip.tsx",
	"src/components/inbox/ThreadDetailPane.tsx",
	"src/components/inbox/ConversationListPane.tsx",
	"src/components/inbox/InboxChrome.tsx",
	"src/components/settings/ProfileTabContent.tsx",
	"src/components/settings/WorkspaceTabContent.tsx",
	"src/components/settings/VoiceProfilesEditorTab.tsx",
	"src/components/settings/AppearanceTabContent.tsx",
	"src/components/settings/CohortSharingCard.tsx",
	"src/components/settings/DataExportCard.tsx",
	"src/components/settings/SecurityTabContent.tsx",
	"src/components/settings/BetaProgramTab.tsx",
	"src/components/settings/DeletionStatusTab.tsx",
	"src/components/settings/NotificationsTabContent.tsx",
	"src/components/settings/WebhooksTabContent.tsx",
	"src/components/settings/APITabContent.tsx",
	"src/components/settings/AdminTabsContent.tsx",
	"src/components/settings/ConnectionsTabContent.tsx",
	"src/components/settings/VoiceProfileEditor.tsx",
	"src/components/content-library/ContentHero.tsx",
	"src/components/content-library/MediaView.tsx",
	"src/components/content-library/MediaUploadZone.tsx",
	"src/components/content-library/RecentStrip.tsx",
	"src/components/content-library/shared.tsx",
	"src/components/content-library/UnavailablePanel.tsx",
	"src/pages/Links.tsx",
	"src/components/links/EmptyDetail.tsx",
	"src/components/links/LinkRow.tsx",
	"src/pages/Reports.tsx",
	"src/pages/PublishingSetup.tsx",
	"src/pages/Handoff.tsx",
	"src/pages/SharedReport.tsx",
	"src/pages/Ideas.tsx",
	"src/pages/Autopilot.tsx",
	"src/pages/Landing.tsx",
	"src/pages/legal/LegalPage.tsx",
	"src/pages/auth/AuthCallback.tsx",
	"src/pages/auth/InviteAccept.tsx",
	"src/pages/auth/Login.tsx",
	"src/pages/auth/OAuthCallback.tsx",
	"src/pages/auth/ResetPassword.tsx",
	"src/pages/auth/Signup.tsx",
	"src/pages/auth/Welcome.tsx",
	"src/components/links/AIEnhancePanel.tsx",
	"src/components/links/BlockListEditor.tsx",
	"src/components/links/LinkDetailPane.tsx",
	"src/components/links/LinkPagePreview.tsx",
	"src/components/links/PixelExtensionsPanel.tsx",
	"src/components/reports/ReportEditor.tsx",
	"src/components/autopilot/AutopilotModePages.tsx",
	"src/components/layout/MobileTabBar.tsx",
	"src/components/layout/ShortcutsHelp.tsx",
	"src/components/layout/mobile/MobileSection.tsx",
	"src/components/layout/mobile/MobileSegmented.tsx",
	"src/components/layout/mobile/MobileTopBar.tsx",
	"src/components/layout/AuthLayout.tsx",
]);

const rawControlTokens = ["<button", "<input", "<select", "<textarea"];

const semanticTokenCleanFiles = new Set([
	"src/pages/Composer.tsx",
	"src/components/composer/ComposerFormControls.tsx",
	"src/components/composer/SchedulingOptions.tsx",
	"src/components/composer/VariantsLab.tsx",
	"src/components/composer/CrossPostDiffResolver.tsx",
	"src/components/composer/CustomPromptModal.tsx",
	"src/components/composer/VoiceContextFile.tsx",
	"src/components/composer/ComposerTopStrip.tsx",
	"src/components/composer/SlashMenu.tsx",
	"src/components/composer/SelectionActionBar.tsx",
	"src/components/composer/InstagramOptionsPanel.tsx",
	"src/components/composer/ThreadsOptionsPanel.tsx",
	"src/components/composer/MediaGrid.tsx",
	"src/components/composer/AccountSelector.tsx",
	"src/components/composer/ComposerStatusChip.tsx",
	"src/components/composer/ChannelHealthPills.tsx",
	"src/components/composer/PreviewSection.tsx",
	"src/components/composer/ComposerModal.tsx",
	"src/components/composer/CritiquePanel.tsx",
	"src/pages/Accounts.tsx",
	"src/pages/Inbox.tsx",
	"src/components/accounts/MobileAccounts.tsx",
	"src/components/accounts/AccountGroupsPanel.tsx",
	"src/components/accounts/AccountsFilterBar.tsx",
	"src/components/accounts/AccountBulkBar.tsx",
	"src/components/accounts/AccountMoveGroupModal.tsx",
	"src/components/accounts/AccountReconnectModal.tsx",
	"src/components/accounts/AccountMapView.tsx",
	"src/components/accounts/AccountsHero.tsx",
	"src/components/accounts/AccountListView.tsx",
	"src/components/accounts/AccountGroupsRail.tsx",
	"src/components/accounts/AccountDetailSlideOver.tsx",
	"src/components/inbox/ActionIconButton.tsx",
	"src/components/inbox/ReplyComposer.tsx",
	"src/components/inbox/ConversationRow.tsx",
	"src/components/inbox/ContextRail.tsx",
	"src/components/inbox/AssignmentChip.tsx",
	"src/components/inbox/ThreadDetailPane.tsx",
	"src/components/inbox/ConversationListPane.tsx",
	"src/components/inbox/InboxChrome.tsx",
	"src/pages/Settings.tsx",
	"src/pages/Billing.tsx",
	"src/components/settings/ProfileTabContent.tsx",
	"src/components/settings/WorkspaceTabContent.tsx",
	"src/components/settings/VoiceProfilesEditorTab.tsx",
	"src/components/settings/AppearanceTabContent.tsx",
	"src/components/settings/CohortSharingCard.tsx",
	"src/components/settings/DataExportCard.tsx",
	"src/components/settings/SecurityTabContent.tsx",
	"src/components/settings/BetaProgramTab.tsx",
	"src/components/settings/DeletionStatusTab.tsx",
	"src/components/settings/NotificationsTabContent.tsx",
	"src/components/settings/WebhooksTabContent.tsx",
	"src/components/settings/APITabContent.tsx",
	"src/components/settings/AdminTabsContent.tsx",
	"src/components/settings/ConnectionsTabContent.tsx",
	"src/components/settings/VoiceProfileEditor.tsx",
	"src/components/settings/shared.tsx",
	"src/pages/Links.tsx",
	"src/components/links/AIEnhancePanel.tsx",
	"src/components/links/BlockListEditor.tsx",
	"src/components/links/LinkDetailPane.tsx",
	"src/components/links/LinkPagePreview.tsx",
	"src/components/links/LinkRow.tsx",
	"src/components/links/PixelExtensionsPanel.tsx",
	"src/components/links/EmptyDetail.tsx",
	"src/pages/ContentLibrary.tsx",
	"src/components/content-library/ContentHero.tsx",
	"src/components/content-library/MediaView.tsx",
	"src/components/content-library/MediaUploadZone.tsx",
	"src/components/content-library/RecentStrip.tsx",
	"src/components/content-library/shared.tsx",
	"src/components/content-library/UnavailablePanel.tsx",
	"src/pages/Reports.tsx",
	"src/components/reports/ReportEditor.tsx",
	"src/pages/Reliability.tsx",
	"src/pages/PublishingSetup.tsx",
	"src/pages/Attribution.tsx",
	"src/pages/Handoff.tsx",
	"src/components/publishing/PhoneSetupChecklist.tsx",
	"src/components/publishing/PublishingReadinessPanel.tsx",
	"src/components/publishing/PublishingStartCard.tsx",
	"src/components/publishing/UnifiedPublishingReadinessCard.tsx",
	"src/components/analytics/AutoInsightsFeed.tsx",
	"src/components/analytics/InvestigatePanel.tsx",
	"src/components/analytics/widgets/explorer/SelfCompareDeepDive.tsx",
	"src/components/analytics/widgets/system/SmartLinksAnalytics.tsx",
	"src/components/analytics-v2/EvidenceRows.tsx",
	"src/components/analytics-v2/EvidenceTile.tsx",
	"src/components/analytics-v2/EvidenceTileHeader.tsx",
	"src/components/analytics-v2/EmptyEvidenceTile.tsx",
	"src/components/analytics-v2/chips/CohortChip.tsx",
	"src/components/analytics-v2/chips/DateRangeChip.tsx",
	"src/components/analytics-v2/ExportCsvButton.tsx",
	"src/components/analytics-v2/HeroTile.tsx",
	"src/components/analytics-v2/InsightsRail.tsx",
	"src/components/analytics-v2/hero/KpiStrip.tsx",
	"src/components/analytics-v2/insights/InsightCard.tsx",
	"src/components/analytics-v2/hero/HeroSparkline.tsx",
	"src/components/analytics-v2/LoadingEvidenceTile.tsx",
	"src/components/analytics-v2/evidence/AnnotationSwimLanesTile.tsx",
	"src/components/analytics-v2/evidence/AudienceOverlapTable.tsx",
	"src/components/analytics-v2/evidence/CompetitorBenchmarkPanel.tsx",
	"src/components/analytics-v2/evidence/ContentMixTernaryTile.tsx",
	"src/components/analytics-v2/evidence/ConversationSystemPanel.tsx",
	"src/components/analytics-v2/evidence/DiscoveryFunnel.tsx",
	"src/components/analytics-v2/evidence/DistributionInputsPanel.tsx",
	"src/components/analytics-v2/evidence/EngagerRetentionTile.tsx",
	"src/components/analytics-v2/evidence/EqsForecastCiTile.tsx",
	"src/components/analytics-v2/evidence/FormatMixWowTrend.tsx",
	"src/components/analytics-v2/evidence/GhostPostQueueTile.tsx",
	"src/components/analytics-v2/evidence/IGFormatBreakdownTile.tsx",
	"src/components/analytics-v2/evidence/IGReachSourceMixTile.tsx",
	"src/components/analytics-v2/evidence/MatrixCoordinateTile.tsx",
	"src/components/analytics-v2/evidence/OriginalityRiskTile.tsx",
	"src/components/analytics-v2/evidence/PostingCadenceHeatmapTile.tsx",
	"src/components/analytics-v2/evidence/QuoteReplyRatioTile.tsx",
	"src/components/analytics-v2/evidence/ReplyDepthDistributionTile.tsx",
	"src/components/analytics-v2/evidence/TrajectoryPanel.tsx",
	"src/components/analytics-v2/evidence/VanityQualityGapTile.tsx",
	"src/components/analytics-v2/evidence/ViewsBySourceChart.tsx",
	"src/pages/Autopilot.tsx",
	"src/components/autopilot/AutopilotModePages.tsx",
	"src/pages/Ideas.tsx",
	"src/pages/Listening.tsx",
	"src/pages/ApprovalQueue.tsx",
	"src/pages/Landing.tsx",
	"src/pages/legal/LegalPage.tsx",
	"src/pages/auth/AuthCallback.tsx",
	"src/pages/auth/InviteAccept.tsx",
	"src/pages/auth/Login.tsx",
	"src/pages/auth/OAuthCallback.tsx",
	"src/pages/auth/ResetPassword.tsx",
	"src/pages/auth/Signup.tsx",
	"src/pages/auth/Welcome.tsx",
	"src/components/layout/AuthLayout.tsx",
	"src/components/layout/ActivityPanel.tsx",
	"src/components/layout/ShortcutsHelp.tsx",
	"src/components/layout/mobile/MobileSection.tsx",
	"src/components/layout/mobile/MobileSegmented.tsx",
	"src/components/layout/mobile/MobileTopBar.tsx",
]);

const bannedSemanticTokens = [
	"text-label-",
	"color-card-elevated",
	"auth-panel",
	"auth-field",
	"auth-primary-action",
	"auth-secondary-action",
	"auth-divider-label",
	"auth-legal-copy",
	"auth-form-heading",
	"auth-plan-strip",
	"auth-shell",
	"auth-command-panel",
	"auth-product-preview",
	"legal-prose",
	"underline-link",
];

const stylesheetFiles = ["src/index.css"];
const bannedStylesheetTokens = [
	"--j33-",
	"--operator-",
	"var(--j33",
	"var(--operator",
	"operator-page-header",
	"mobile-operator-page",
	"operator-page",
	"operator-material",
	"operator-action-",
	"operator-card-",
	"operator-widget-",
	"operator-stat-tile",
	"analytics-bridge-tile",
	"dv2-root",
	"dv2-tile",
	"dv2-empty",
	"dv2-live",
	"dv2-ghost",
	"dv2-anomaly",
	"dv2-account",
	"j33-card",
	"j33-inner",
	"j33-ribbon",
	"j33-hero",
];

const routeMetadataFiles = new Set([
	"src/routes/appRoutes.tsx",
	"src/components/layout/Layout.tsx",
	"src/components/layout/CommandPalette.tsx",
	"src/components/layout/MobileTabBar.tsx",
]);

const bannedRouteMetadataTokens = [
	"protectedRoutes: AppRoute[] = [",
	"protectedRedirects: AppRoute[] = [",
	"export const PRIMARY_NAV:",
	"export const SECONDARY_NAV:",
	"export const ACCOUNT_MENU_NAV = [",
	"export const APP_ROUTE_COMMANDS",
	"export const MOBILE_MORE_SECTIONS:",
];

const queryKeyCleanFiles = new Set([
	"src/hooks/useCalendarPosts.ts",
	"src/hooks/useBestPostingTimes.ts",
	"src/hooks/useCompetitorPulse.ts",
	"src/hooks/useCompetitorSurprises.ts",
	"src/hooks/useCrossAccountPatterns.ts",
	"src/hooks/useEQSTrendSubtitle.ts",
	"src/hooks/useFleetProfileVisits.ts",
	"src/hooks/useFleetHealth.ts",
	"src/hooks/useFleetTotals.ts",
	"src/hooks/useHookPatterns.ts",
	"src/hooks/useInstagramPublishingLimits.ts",
	"src/hooks/useOperatorSnapshot.ts",
	"src/hooks/useReelRetention.ts",
	"src/hooks/useTrialStatus.ts",
	"src/pages/Reliability.tsx",
	"src/pages/auth/Welcome.tsx",
]);

const bannedQueryKeyLiterals = [
	'["accountGroups"',
	"['accountGroups'",
	'["connectedAccounts"',
	"['connectedAccounts'",
	'["bestPostingTimes"',
	"['bestPostingTimes'",
	'["competitorPulse"',
	"['competitorPulse'",
	'["competitorSurprises"',
	"['competitorSurprises'",
	'["crossAccountPatterns"',
	"['crossAccountPatterns'",
	'["eqsTrendSubtitle"',
	"['eqsTrendSubtitle'",
	'["fleetHealth"',
	"['fleetHealth'",
	'["fleetProfileVisits"',
	"['fleetProfileVisits'",
	'["fleetTotals"',
	"['fleetTotals'",
	'["hookPatterns"',
	"['hookPatterns'",
	'["calendarPosts"',
	"['calendarPosts'",
	'["instagramPublishingLimits"',
	"['instagramPublishingLimits'",
	'["operatorSnapshot"',
	"['operatorSnapshot'",
	'["onboardingState"',
	"['onboardingState'",
	'["reliabilitySummary"',
	"['reliabilitySummary'",
	'["reelRetention"',
	"['reelRetention'",
	'["trialStatus"',
	"['trialStatus'",
];

function isAllowedHiddenFileInput(lines, index) {
	const window = lines.slice(index, index + 8).join("\n");
	return (
		window.includes("<input") &&
		window.includes('type="file"') &&
		(window.includes('className="hidden"') || window.includes('className="sr-only"'))
	);
}

const failures = [];

for (const file of files) {
	const source = readFileSync(file, "utf8");
	const lines = source.split(/\r?\n/);
	lines.forEach((line, index) => {
		for (const token of banned) {
			if (line.includes(token)) {
				failures.push(`${file}:${index + 1}: banned legacy UI token "${token}"`);
			}
		}
		if (semanticTokenCleanFiles.has(file)) {
			for (const token of bannedSemanticTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: banned legacy semantic token "${token}"`,
					);
				}
			}
		}
		if (routeMetadataFiles.has(file)) {
			for (const token of bannedRouteMetadataTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: route/nav/command metadata must come from src/routes/routeRegistry.tsx instead of "${token}"`,
					);
				}
			}
		}
		if (queryKeyCleanFiles.has(file)) {
			for (const token of bannedQueryKeyLiterals) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: use queryKeys from src/lib/queryKeys.ts instead of cache-key literal ${token}`,
					);
				}
			}
		}
		if (file === "src/pages/Composer.tsx" && line.includes("motion/react")) {
			failures.push(
				`${file}:${index + 1}: Composer route should not import route-level motion`,
			);
		}
		if (file === "src/pages/Calendar.tsx") {
			const bannedCalendarShellTokens = [
				"components/layout/AppScreen",
				"components/ui/PageHeader",
				"components/ui/DashboardCard",
				"components/ui/DataPanel",
				"components/ui/StatCard",
				"<AppScreen",
				"<PageHeader",
				"<DashboardCard",
				"<DataPanel",
				"<StatCard",
			];
			for (const token of bannedCalendarShellTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Calendar route should use Nova route primitives instead of "${token}"`,
					);
				}
			}
		}
		if (file.startsWith("src/components/calendar/")) {
			const bannedCalendarChildTokens = [
				"motion/react",
				"components/layout/AppScreen",
				"components/ui/PageHeader",
				"components/ui/DashboardCard",
				"components/ui/DataPanel",
				"components/ui/StatCard",
				"<AppScreen",
				"<PageHeader",
				"<DashboardCard",
				"<DataPanel",
				"<StatCard",
				"<motion.",
				"</motion.",
				"AnimatePresence",
			];
			for (const token of bannedCalendarChildTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Calendar child surfaces should use Nova/shadcn wrappers instead of "${token}"`,
					);
				}
			}
		}
		if (file === "src/pages/Settings.tsx" || file === "src/pages/Billing.tsx") {
			const bannedSettingsBillingShellTokens = [
				"motion/react",
				"components/layout/AppScreen",
				"components/ui/PageHeader",
				"components/ui/DashboardCard",
				"components/ui/DataPanel",
				"components/ui/StatCard",
				"<AppScreen",
				"<PageHeader",
				"<DashboardCard",
				"<DataPanel",
				"<StatCard",
			];
			for (const token of bannedSettingsBillingShellTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Settings/Billing routes should use Nova route primitives instead of "${token}"`,
					);
				}
			}
		}
		if (
			file === "src/pages/Links.tsx" ||
			file === "src/pages/ContentLibrary.tsx" ||
			file === "src/pages/Reports.tsx"
		) {
			const bannedLibraryReportShellTokens = [
				"motion/react",
				"components/layout/AppScreen",
				"components/ui/PageHeader",
				"components/ui/DashboardCard",
				"components/ui/DataPanel",
				"components/ui/StatCard",
				"<AppScreen",
				"<PageHeader",
				"<DashboardCard",
				"<DataPanel",
				"<StatCard",
				"<motion.",
				"</motion.",
				"REVEAL",
				"AnimatePresence",
			];
			for (const token of bannedLibraryReportShellTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Links/Content Library/Reports routes should use Nova route primitives instead of "${token}"`,
					);
				}
			}
		}
		if (
			file === "src/pages/Reliability.tsx" ||
			file === "src/pages/PublishingSetup.tsx"
		) {
			const bannedReliabilityPublishingShellTokens = [
				"motion/react",
				"components/layout/AppScreen",
				"components/ui/PageHeader",
				"components/ui/DashboardCard",
				"components/ui/DataPanel",
				"components/ui/StatCard",
				"<AppScreen",
				"<PageHeader",
				"<DashboardCard",
				"<DataPanel",
				"<StatCard",
				"<motion.",
				"</motion.",
				"REVEAL",
				"AnimatePresence",
			];
			for (const token of bannedReliabilityPublishingShellTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Reliability/Publishing routes should use Nova route primitives instead of "${token}"`,
					);
				}
			}
		}
		if (file === "src/pages/Attribution.tsx") {
			const bannedAttributionShellTokens = [
				"motion/react",
				"components/layout/AppScreen",
				"components/ui/PageHeader",
				"components/ui/DashboardCard",
				"components/ui/DataPanel",
				"components/ui/StatCard",
				"<AppScreen",
				"<PageHeader",
				"<DashboardCard",
				"<DataPanel",
				"<StatCard",
				"<motion.",
				"</motion.",
				"REVEAL",
				"AnimatePresence",
				"analytics-kpi-ribbon",
			];
			for (const token of bannedAttributionShellTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Attribution route should use Nova route primitives instead of "${token}"`,
					);
				}
			}
		}
		if (file === "src/pages/Analytics.tsx") {
			const bannedAnalyticsShellTokens = [
				"motion/react",
				"components/layout/AppScreen",
				"components/ui/PageHeader",
				"components/ui/DashboardCard",
				"components/ui/DataPanel",
				"components/ui/StatCard",
				"<AppScreen",
				"<PageHeader",
				"<DashboardCard",
				"<DataPanel",
				"<StatCard",
				"<motion.",
				"</motion.",
				"REVEAL",
				"AnimatePresence",
				"analytics-kpi-ribbon",
			];
			for (const token of bannedAnalyticsShellTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Analytics route should use Nova route primitives instead of "${token}"`,
					);
				}
			}
		}
		if (
			file === "src/components/analytics/widgets/system/SmartLinksAnalytics.tsx" ||
			file === "src/components/analytics/AutoInsightsFeed.tsx"
		) {
			const bannedAnalyticsChildTokens = [
				"motion/react",
				"components/ui/DashboardCard",
				"components/ui/DataPanel",
				"components/ui/StatCard",
				"components/ui/PageHeader",
				"<DashboardCard",
				"<DataPanel",
				"<StatCard",
				"<PageHeader",
				"<motion.",
				"</motion.",
				"AnimatePresence",
			];
			for (const token of bannedAnalyticsChildTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Analytics child widgets should use Nova/shadcn wrappers instead of "${token}"`,
					);
				}
			}
		}
		if (
			file === "src/components/analytics-v2/HeroTile.tsx" ||
			file === "src/components/analytics-v2/InsightsRail.tsx" ||
			file === "src/components/analytics-v2/hero/KpiStrip.tsx" ||
			file === "src/components/analytics-v2/insights/InsightCard.tsx"
		) {
			const bannedAnalyticsV2ChildTokens = [
				"motion/react",
				"components/ui/DashboardCard",
				"components/ui/DataPanel",
				"components/ui/StatCard",
				"components/ui/PageHeader",
				"<DashboardCard",
				"<DataPanel",
				"<StatCard",
				"<PageHeader",
				"<motion.",
				"</motion.",
				"AnimatePresence",
			];
			for (const token of bannedAnalyticsV2ChildTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Analytics v2 child surfaces should use Nova/shadcn wrappers instead of "${token}"`,
					);
				}
			}
		}
		if (file === "src/pages/Accounts.tsx") {
			const bannedAccountsShellTokens = [
				"motion/react",
				"components/layout/AppScreen",
				"components/ui/PageHeader",
				"components/ui/DashboardCard",
				"components/ui/DataPanel",
				"components/ui/StatCard",
				"<AppScreen",
				"<PageHeader",
				"<DashboardCard",
				"<DataPanel",
				"<StatCard",
				"<motion.",
				"</motion.",
				"REVEAL",
				"AnimatePresence",
			];
			for (const token of bannedAccountsShellTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Accounts route should use Nova route primitives instead of "${token}"`,
					);
				}
			}
		}
		if (file === "src/components/layout/NovaScreen.tsx") {
			const bannedNovaScreenBridgeTokens = [
				"components/layout/AppScreen",
				"<AppScreen",
			];
			for (const token of bannedNovaScreenBridgeTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: NovaScreen should own the route screen shell instead of delegating to "${token}"`,
					);
				}
			}
		}
		if (
			file === "src/components/dashboard-v2/DashboardV2.tsx" ||
			file.startsWith("src/components/dashboard-v2/tiles/")
		) {
			const bannedDashboardV2ShellTokens = [
				"motion/react",
				"components/layout/AppScreen",
				"components/ui/PageHeader",
				"components/ui/DashboardCard",
				"components/ui/StatCard",
				"<AppScreen",
				"<PageHeader",
				"<DashboardCard",
				"<StatCard",
				"<motion.",
				"</motion.",
				"AnimatePresence",
			];
			for (const token of bannedDashboardV2ShellTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Dashboard v2 should use Nova route primitives instead of "${token}"`,
					);
				}
			}
		}
		if (file === "src/components/layout/ShortcutsHelp.tsx") {
			const bannedShortcutsHelpTokens = [
				"motion/react",
				"<motion.",
				"</motion.",
				"AnimatePresence",
			];
			for (const token of bannedShortcutsHelpTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Shortcuts help should not depend on decorative motion token "${token}"`,
					);
				}
			}
		}
		if (file === "src/components/layout/ActivityPanel.tsx") {
			const bannedActivityPanelTokens = [
				"motion/react",
				"<motion.",
				"</motion.",
				"AnimatePresence",
			];
			for (const token of bannedActivityPanelTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Activity panel should use static Nova/shadcn shell primitives instead of "${token}"`,
					);
				}
			}
		}
		if (file === "src/components/layout/CommandPalette.tsx") {
			const bannedCommandPaletteTokens = [
				"motion/react",
				"<motion.",
				"</motion.",
				"AnimatePresence",
			];
			for (const token of bannedCommandPaletteTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Command palette should keep behavior in shadcn Command and avoid decorative motion token "${token}"`,
					);
				}
			}
		}
		if (file.startsWith("src/components/layout/mobile/")) {
			const bannedMobileShellTokens = [
				"components/ui/DashboardCard",
				"components/ui/DataPanel",
				"components/ui/StatCard",
				"components/ui/PageHeader",
				"<DashboardCard",
				"<DataPanel",
				"<StatCard",
				"<PageHeader",
			];
			for (const token of bannedMobileShellTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Mobile shell surfaces should use Nova/shadcn wrappers instead of "${token}"`,
					);
				}
			}
		}
		if (file.startsWith("src/components/accounts/")) {
			const bannedAccountsChildTokens = [
				"motion/react",
				"components/ui/DashboardCard",
				"components/ui/DataPanel",
				"components/ui/StatCard",
				"components/ui/PageHeader",
				"<DashboardCard",
				"<DataPanel",
				"<StatCard",
				"<PageHeader",
				"<motion.",
				"</motion.",
				"AnimatePresence",
			];
			for (const token of bannedAccountsChildTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Account child surfaces should use Nova/shadcn wrappers instead of "${token}"`,
					);
				}
			}
		}
		if (file === "src/pages/Handoff.tsx") {
			const bannedHandoffShellTokens = [
				"motion/react",
				"components/layout/AppScreen",
				"components/ui/PageHeader",
				"components/ui/DashboardCard",
				"components/ui/DataPanel",
				"components/ui/StatCard",
				"<AppScreen",
				"<PageHeader",
				"<DashboardCard",
				"<DataPanel",
				"<StatCard",
				"<motion.",
				"</motion.",
				"REVEAL",
				"AnimatePresence",
			];
			for (const token of bannedHandoffShellTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Handoff route should use Nova route primitives instead of "${token}"`,
					);
				}
			}
		}
		if (file === "src/pages/SharedReport.tsx") {
			const bannedSharedReportShellTokens = [
				"motion/react",
				"components/layout/AppScreen",
				"components/ui/PageHeader",
				"components/ui/DashboardCard",
				"components/ui/DataPanel",
				"components/ui/StatCard",
				"<AppScreen",
				"<PageHeader",
				"<DashboardCard",
				"<DataPanel",
				"<StatCard",
				"<motion.",
				"</motion.",
				"REVEAL",
				"AnimatePresence",
			];
			for (const token of bannedSharedReportShellTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Shared report route should use Nova route primitives instead of "${token}"`,
					);
				}
			}
		}
		if (file === "src/pages/Landing.tsx") {
			const bannedLandingShellTokens = [
				"motion/react",
				"components/layout/AppScreen",
				"components/ui/PageHeader",
				"components/ui/DashboardCard",
				"components/ui/DataPanel",
				"components/ui/StatCard",
				"<AppScreen",
				"<PageHeader",
				"<DashboardCard",
				"<DataPanel",
				"<StatCard",
				"<motion.",
				"</motion.",
				"REVEAL",
				"AnimatePresence",
			];
			for (const token of bannedLandingShellTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Landing route should use Nova route primitives instead of "${token}"`,
					);
				}
			}
		}
		if (file === "src/pages/legal/LegalPage.tsx") {
			const bannedLegalShellTokens = [
				"motion/react",
				"components/layout/AppScreen",
				"components/ui/PageHeader",
				"components/ui/DashboardCard",
				"components/ui/DataPanel",
				"components/ui/StatCard",
				"<AppScreen",
				"<PageHeader",
				"<DashboardCard",
				"<DataPanel",
				"<StatCard",
				"<motion.",
				"</motion.",
				"REVEAL",
				"AnimatePresence",
			];
			for (const token of bannedLegalShellTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Legal route should use Nova route primitives instead of "${token}"`,
					);
				}
			}
		}
		if (
			file === "src/pages/auth/AuthCallback.tsx" ||
			file === "src/pages/auth/InviteAccept.tsx" ||
			file === "src/pages/auth/OAuthCallback.tsx" ||
			file === "src/pages/auth/Signup.tsx" ||
			file === "src/pages/auth/Welcome.tsx"
		) {
			const bannedAuthShellTokens = [
				"motion/react",
				"components/layout/AppScreen",
				"components/ui/PageHeader",
				"components/ui/DashboardCard",
				"components/ui/DataPanel",
				"components/ui/StatCard",
				"<AppScreen",
				"<PageHeader",
				"<DashboardCard",
				"<DataPanel",
				"<StatCard",
				"<motion.",
				"</motion.",
				"REVEAL",
				"AnimatePresence",
			];
			for (const token of bannedAuthShellTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Auth route should use Nova route primitives instead of "${token}"`,
					);
				}
			}
		}
		if (file === "src/pages/ApprovalQueue.tsx") {
			const bannedApprovalQueueShellTokens = [
				"motion/react",
				"components/layout/AppScreen",
				"components/ui/PageHeader",
				"components/ui/DashboardCard",
				"components/ui/DataPanel",
				"components/ui/StatCard",
				"<AppScreen",
				"<PageHeader",
				"<DashboardCard",
				"<DataPanel",
				"<StatCard",
				"<motion.",
				"</motion.",
				"REVEAL",
				"AnimatePresence",
			];
			for (const token of bannedApprovalQueueShellTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Approval Queue route should use Nova route primitives instead of "${token}"`,
					);
				}
			}
		}
		if (file.startsWith("src/components/settings/")) {
			const bannedSettingsChildTokens = [
				"motion/react",
				"components/ui/DashboardCard",
				"<DashboardCard",
			];
			for (const token of bannedSettingsChildTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Settings child surfaces should use Nova/shadcn wrappers instead of "${token}"`,
					);
				}
			}
		}
		if (file.startsWith("src/components/publishing/")) {
			const bannedPublishingChildTokens = [
				"motion/react",
				"components/ui/DashboardCard",
				"components/ui/DataPanel",
				"components/ui/StatCard",
				"components/ui/PageHeader",
				"<DashboardCard",
				"<DataPanel",
				"<StatCard",
				"<PageHeader",
				"<motion.",
				"</motion.",
				"AnimatePresence",
			];
			for (const token of bannedPublishingChildTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Publishing child surfaces should use Nova/shadcn wrappers instead of "${token}"`,
					);
				}
			}
		}
		if (
			file === "src/components/autoposter/ReplyChainStats.tsx" ||
			file === "src/components/links/PixelExtensionsPanel.tsx" ||
			file === "src/components/links/AIEnhancePanel.tsx" ||
			file === "src/components/links/LinkDetailPane.tsx" ||
			file === "src/components/links/LinkPagePreview.tsx" ||
			file === "src/components/links/BlockListEditor.tsx" ||
			file === "src/components/dashboard/MobileOverview.tsx" ||
			file === "src/components/composer/ComposerTopStrip.tsx" ||
			file === "src/components/composer/CritiquePanel.tsx" ||
			file === "src/components/composer/CrossPostDiffResolver.tsx" ||
			file === "src/components/composer/MediaGrid.tsx" ||
			file === "src/components/composer/ComposerFormControls.tsx" ||
			file === "src/components/composer/VariantsLab.tsx"
		) {
			const bannedSupportChildTokens = [
				"motion/react",
				"components/ui/DashboardCard",
				"components/ui/DataPanel",
				"components/ui/StatCard",
				"components/ui/PageHeader",
				"<DashboardCard",
				"<DataPanel",
				"<StatCard",
				"<PageHeader",
				"<motion.",
				"</motion.",
				"AnimatePresence",
			];
			for (const token of bannedSupportChildTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Support child surfaces should use Nova/shadcn wrappers instead of "${token}"`,
					);
				}
			}
		}
		if (
			file === "src/components/links/BlockListEditor.tsx" ||
			file === "src/components/composer/MediaGrid.tsx"
		) {
			const bannedDragSurfaceTokens = [
				"motion/react",
				"<Reorder.",
				"components/ui/DashboardCard",
				"components/ui/DataPanel",
				"components/ui/StatCard",
				"components/ui/PageHeader",
				"<DashboardCard",
				"<DataPanel",
				"<StatCard",
				"<PageHeader",
			];
			for (const token of bannedDragSurfaceTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Drag-sort surfaces may keep Reorder temporarily but should use Nova/shadcn wrappers instead of "${token}"`,
					);
				}
			}
		}
		if (
			file === "src/components/content-library/MediaView.tsx" ||
			file === "src/components/content-library/RecentStrip.tsx" ||
			file === "src/components/content-library/shared.tsx" ||
			file === "src/components/accounts/AccountMapView.tsx"
		) {
			const bannedNestedNovaTokens = [
				"motion/react",
				"components/ui/DashboardCard",
				"components/ui/DataPanel",
				"components/ui/StatCard",
				"components/ui/PageHeader",
				"<DashboardCard",
				"<DataPanel",
				"<StatCard",
				"<PageHeader",
				"<motion.",
				"</motion.",
				"AnimatePresence",
			];
			for (const token of bannedNestedNovaTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Nested content/account surfaces should use Nova/shadcn wrappers instead of "${token}"`,
					);
				}
			}
		}
		if (file === "src/pages/Inbox.tsx" || file === "src/components/inbox/InboxChrome.tsx") {
			const bannedInboxShellTokens = [
				"motion/react",
				"components/layout/AppScreen",
				"components/ui/PageHeader",
				"components/ui/DashboardCard",
				"<AppScreen",
				"<PageHeader",
				"<DashboardCard",
			];
			for (const token of bannedInboxShellTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Inbox route surfaces should use Nova route primitives instead of "${token}"`,
					);
				}
			}
		}
		if (file.startsWith("src/components/inbox/")) {
			const bannedInboxChildTokens = [
				"motion/react",
				"components/ui/DashboardCard",
				"components/ui/DataPanel",
				"components/ui/StatCard",
				"components/ui/PageHeader",
				"<DashboardCard",
				"<DataPanel",
				"<StatCard",
				"<PageHeader",
				"<motion.",
				"</motion.",
				"AnimatePresence",
			];
			for (const token of bannedInboxChildTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Inbox child surfaces should use Nova/shadcn wrappers instead of "${token}"`,
					);
				}
			}
		}
		if (file === "src/pages/Ideas.tsx") {
			const bannedIdeasShellTokens = [
				"motion/react",
				"components/layout/AppScreen",
				"components/ui/PageHeader",
				"components/ui/DashboardCard",
				"<AppScreen",
				"<PageHeader",
				"<DashboardCard",
			];
			for (const token of bannedIdeasShellTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Ideas route should use Nova route primitives instead of "${token}"`,
					);
				}
			}
		}
		if (file === "src/pages/Listening.tsx") {
			const bannedListeningShellTokens = [
				"motion/react",
				"components/layout/AppScreen",
				"components/ui/PageHeader",
				"components/ui/DashboardCard",
				"<AppScreen",
				"<PageHeader",
				"<DashboardCard",
			];
			for (const token of bannedListeningShellTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Listening route should use Nova route primitives instead of "${token}"`,
					);
				}
			}
		}
		if (
			file === "src/pages/Autopilot.tsx" ||
			file === "src/components/autopilot/AutopilotModePages.tsx"
		) {
			const bannedAutopilotShellTokens = [
				"motion/react",
				"components/layout/AppScreen",
				"components/ui/PageHeader",
				"components/ui/DashboardCard",
				"components/ui/StatCard",
				"<AppScreen",
				"<PageHeader",
				"<DashboardCard",
				"<StatCard",
				"function StatCard",
				"AUTOPILOT_REVEAL",
			];
			for (const token of bannedAutopilotShellTokens) {
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: Autopilot route surfaces should use Nova route primitives instead of "${token}"`,
					);
				}
			}
		}
		if (rawControlFiles.has(file)) {
			for (const token of rawControlTokens) {
				if (token === "<input" && isAllowedHiddenFileInput(lines, index)) continue;
				if (line.includes(token)) {
					failures.push(
						`${file}:${index + 1}: raw control "${token}" should use a shadcn-backed wrapper`,
					);
				}
			}
		}
	});
}

for (const file of stylesheetFiles) {
	const source = readFileSync(file, "utf8");
	const lines = source.split(/\r?\n/);
	lines.forEach((line, index) => {
		for (const token of bannedStylesheetTokens) {
			if (line.includes(token)) {
				failures.push(
					`${file}:${index + 1}: banned legacy stylesheet token "${token}"`,
				);
			}
		}
	});
}

if (failures.length > 0) {
	console.error("Active legacy UI audit failed:");
	console.error(failures.join("\n"));
	process.exit(1);
}

console.log(
	"ok: active cleaned shell/dashboard/analytics/composer/calendar/content/accounts/inbox/settings/billing/content-library/links/reports/publishing/handoff/shared-report/ideas/autopilot/auth/legal/landing/attribution/approval-queue/listening/autopilot-mode surfaces and global stylesheet avoid banned legacy UI tokens",
);
