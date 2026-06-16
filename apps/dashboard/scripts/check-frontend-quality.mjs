#!/usr/bin/env node
import { existsSync, readFileSync } from "node:fs";

const read = (file) => readFileSync(file, "utf8");

const checks = [
	{
		file: "src/components/layout/NovaScreen.tsx",
		mustInclude: ["overflow-x-clip", "bg-[var(--color-surface-frame)]"],
	},
	{
		file: "src/components/ui/DataTable.tsx",
		mustInclude: ["max-w-full", "analytics-table-frame", "data-table-toolbar", "data-table-footer"],
	},
	{
		file: "src/components/ui/Upload.tsx",
		mustInclude: ["UploadZone", "UploadStatusList", "upload-zone", "upload-status-row", "border-dashed"],
	},
	{
		file: "src/components/ui/CommandMenuShell.tsx",
		mustInclude: ["CommandMenuShell", "CommandMenuActionRow", "command-menu-shell", "command-menu-action-row"],
	},
	{
		file: "src/components/ui/Form.tsx",
		mustInclude: [
			"react-hook-form",
			"FormProvider",
			"FormField",
			"FormInputField",
			"FormTextareaField",
			"FormSelectField",
			"FormSwitchField",
			"FormCheckboxField",
			"data-invalid",
		],
	},
	{
		file: "src/components/ui/VirtualizedList.tsx",
		mustInclude: [
			"@tanstack/react-virtual",
			"VirtualizedList",
			"useVirtualizer",
			"initialRect",
			"role=\"list\"",
		],
	},
	{
		file: "src/components/settings/ProfileTabContent.tsx",
		mustInclude: ["useForm", "zodResolver", "FormInputField", "<Form"],
		mustNotInclude: ["onClick={() => void save()}"],
	},
	{
		file: "src/components/settings/WorkspaceTabContent.tsx",
		mustInclude: ["useForm", "zodResolver", "FormInputField", "FormSelectField", "<Form"],
	},
	{
		file: "src/components/reports/ReportEditor.tsx",
		mustInclude: ["useForm", "zodResolver", "FormInputField", "FormSelectField", "<Form"],
		mustNotInclude: ["<Select"],
	},
	{
		file: "src/components/inbox/ConversationListPane.tsx",
		mustInclude: ["VirtualizedList", "estimateSize={132}", "ariaLabel=\"Conversation list\""],
	},
	{
		file: "src/components/ui/FrontendQuality.stories.tsx",
		mustInclude: [
			"Frontend Quality/Shared Patterns",
			"DashboardStatsDark",
			"DenseTable",
			"UploadAndCommand",
			"CalendarAndAccountDetail",
		],
	},
	{
		file: "scripts/run-chromatic-if-token.mjs",
		mustInclude: [
			"CHROMATIC_PROJECT_TOKEN",
			"Skipping Chromatic",
			"npx",
			"chromatic",
			"--exit-zero-on-changes",
		],
	},
	{
		file: "src/components/ui/NovaPrimitives.tsx",
		mustInclude: ["NovaUsageList", "nova-usage-row", "conic-gradient"],
	},
	{
		file: "src/components/content-library/MediaUploadZone.tsx",
		mustInclude: ["UploadZone", "UploadStatusList", "50MB"],
	},
	{
		file: "src/components/composer/MediaGrid.tsx",
		mustInclude: ["UploadZone", "Drop media here or choose files"],
	},
	{
		file: "src/pages/Composer.tsx",
		mustInclude: ["CommandMenuShell", "UploadStatusList", "Bulk upload queue"],
	},
	{
		file: "src/pages/Billing.tsx",
		mustInclude: [
			"Highest tier active",
			"Stripe portal",
			"Payment details are requested only during checkout.",
			"Manage billing in Stripe",
		],
		mustNotInclude: ["You are on the highest self-serve tier"],
	},
	{
		file: "src/components/layout/CommandPalette.tsx",
		mustInclude: ["CommandMenuActionRow", "command-menu-shell"],
	},
	{
		file: "src/components/composer/SlashMenu.tsx",
		mustInclude: ["CommandMenuActionRow", "command-menu-shell"],
	},
	{
		file: "src/pages/Content.tsx",
		mustInclude: [
			"const CONTENT_STAT_CLASS",
			"max-sm:[&_.nova-card-content]:min-h-[88px]",
			"<NovaScreen width=\"wide\" density=\"compact\">",
			"grid grid-cols-2 gap-3 xl:grid-cols-4",
			"tableClassName=\"min-w-[820px] xl:min-w-full\"",
			"const CONTENT_TABLE_FRAME_CLASS = \"max-h-[min(62vh,720px)] overflow-auto\";",
			"const CONTENT_MOBILE_LIST_CLASS = \"h-[min(58vh,30rem)] min-h-[18rem] pr-1\";",
			"VirtualizedList",
			"ariaLabel=\"Recent posts\"",
			"frameClassName={CONTENT_TABLE_FRAME_CLASS}",
			"className={CONTENT_MOBILE_LIST_CLASS}",
			"content-followup-grid grid-cols-1 lg:grid-cols-3",
			"className=\"h-full\"",
		],
		mustNotInclude: [
			"grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4",
			"tableClassName=\"min-w-[900px] lg:min-w-[1080px]\"",
			"tableClassName=\"min-w-[1220px]\"",
			"frameClassName=\"max-h-[min(72vh,920px)] overflow-auto\"",
			"max-h-[32rem] overflow-y-auto",
			"grid-cols-1 xl:grid-cols-3",
			"grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3",
			"content-followup-grid grid-cols-1 lg:grid-cols-2",
			"className=\"h-full lg:col-span-2 2xl:col-span-1\"",
		],
	},
	{
		file: "src/pages/Analytics.tsx",
		mustInclude: [
			"grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4",
			"tableClassName=\"min-w-[980px] lg:min-w-[1180px]\"",
			"const SAVED_ANALYTICS_VIEWS",
			"Audience data readiness",
			"Compare readiness",
		],
		mustNotInclude: [
			"grid grid-cols-2 gap-3 lg:grid-cols-4",
			"tableClassName=\"min-w-[1180px]\"",
		],
	},
	{
		file: "src/pages/Links.tsx",
		mustInclude: [
			"xl:grid-cols-[minmax(0,1.35fr)_minmax(360px,0.65fr)]",
			"2xl:grid-cols-[minmax(0,1.45fr)_minmax(420px,0.55fr)]",
		],
		mustNotInclude: [
			"2xl:grid-cols-[minmax(520px,0.95fr)_minmax(0,1.25fr)]",
		],
	},
	{
		file: "src/components/links/LinkDetailPane.tsx",
		mustInclude: [
			"2xl:grid-cols-[minmax(0,1fr)_300px]",
			"className=\"hidden 2xl:block justify-self-stretch\"",
			"bg-popover",
			"text-popover-foreground",
		],
		mustNotInclude: [
			"sm:p-5 xl:grid-cols-[minmax(0,1fr)_300px]",
			"className=\"hidden xl:block justify-self-stretch\"",
			"bg-[#09090b]",
			"text-white",
			"text-zinc",
			"border-white",
			"bg-white",
		],
	},
	{
		file: "src/components/dashboard-v2/DashboardV2.tsx",
		mustInclude: [
			"function PlatformInsightGrid",
			"dashboard-platform-insights min-w-0",
			"desktopColumns?: [number[], number[]] | undefined;",
			"desktopColumns={[[0, 2, 3, 7], [1, 4, 5, 6]]}",
			"desktopColumns={[[0, 2, 7, 8, 10], [1, 3, 4, 5, 6, 9]]}",
			"xl:grid xl:grid-cols-2",
			"function PlatformInsightSection",
			"grid items-stretch gap-6 md:gap-7 xl:grid-cols-2",
		],
		mustNotInclude: [
			"<div className=\"grid min-w-0 gap-5 md:gap-6 xl:grid-cols-2\">",
			"xl:columns-2",
			"grid items-start gap-6 md:gap-7 xl:grid-cols-2",
		],
	},
	{
		file: "src/pages/Calendar.tsx",
		mustInclude: [
			"width=\"full\"",
			"density=\"compact\"",
			"className=\"calendar-page calendar-page--nova px-3 md:px-5 xl:px-6\"",
			"contentClassName=\"px-2 pb-2 pt-0 sm:px-3 sm:pb-3 md:px-4 md:pb-4\"",
			"const calendarShellClassName",
			"max-h-[min(76vh,900px)] min-h-[560px] sm:min-h-[640px]",
			"Swipe the schedule horizontally to inspect the full week.",
			"min-w-[1120px] min-[1600px]:min-w-[1360px] min-[1920px]:min-w-[1480px]",
			"min-[1920px]:grid-cols-[minmax(0,1fr)_360px]",
			"eventMinHeight={56}",
		],
		mustNotInclude: [
			"nova-calendar-shell min-h-[720px] overflow-auto sm:min-h-[820px]",
			"nova-calendar-shell min-h-[760px] overflow-auto sm:min-h-[880px]",
			"viewMode === \"week\" ? \"min-w-[1040px]\" : \"min-w-0\"",
			"viewMode === \"week\" ? \"min-w-[1240px]\" : \"min-w-0\"",
			"min-w-[1240px] min-[1536px]:min-w-[1360px] min-[1800px]:min-w-[1480px]",
			"min-w-[1080px] min-[1536px]:min-w-[1180px] min-[1800px]:min-w-[1240px]",
			"min-w-[1160px] min-[1536px]:min-w-[1320px] min-[1800px]:min-w-[1440px]",
			"min-[1800px]:grid-cols-[minmax(0,1fr)_360px]",
			"max-h-[440px]",
		],
	},
	{
		file: "src/pages/Autopilot.tsx",
		mustInclude: [
			"grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-3 lg:min-w-[260px]",
		],
		mustNotInclude: ["grid grid-cols-3 gap-2 min-w-[260px]"],
	},
	{
		file: "src/pages/Accounts.tsx",
		mustInclude: [
			"<MobileAccounts",
			"className=\"hidden md:block\"",
		],
		mustNotInclude: [
			"usePhoneChrome",
			"className={phoneChrome ? \"hidden\" : undefined}",
		],
	},
	{
		file: "src/pages/Settings.tsx",
		mustInclude: [
			"const CONTEXTUAL_TABS",
			"label: \"Privacy\"",
			"const contextualActiveTab",
			"const mobileTabs",
			"Direct link",
		],
		mustNotInclude: ['label: "Advanced"'],
	},
	{
		file: "src/components/settings/AppearanceTabContent.tsx",
		mustInclude: [
			"Palette locked",
			"removeAttribute('data-theme')",
			"localStorage.removeItem('juno33-palette')",
			"Nova/zinc + Juno oxblood",
		],
		mustNotInclude: [
			"const paletteOptions",
			"<PalettePreview",
			"label: 'Neptune'",
			"label: 'Apollo'",
			"setAttribute('data-theme'",
		],
	},
	{
		file: "public/theme-init.js",
		mustInclude: [
			"removeAttribute('data-theme')",
			"removeItem('juno33-palette')",
			"locked to Nova/zinc + Juno oxblood",
		],
		mustNotInclude: ["setAttribute('data-theme'"],
	},
	{
		file: "src/components/layout/MobileTabBar.tsx",
		mustInclude: [
			"flex items-start justify-between px-3 pt-2.5",
			"mobile-tab-item flex min-h-[48px] w-12 min-w-0 flex-col",
			"mobile-tab-item relative flex min-h-[48px] w-12 min-w-0 flex-col",
		],
		mustNotInclude: ["flex items-start justify-around px-2.5 pt-2.5"],
	},
	{
		file: "src/main.tsx",
		mustInclude: [
			"@fontsource/inter/400.css",
			"@fontsource/inter/500.css",
			"@fontsource/inter/600.css",
			"@fontsource/inter/700.css",
		],
	},
	{
		file: "src/index.css",
		mustInclude: [
			"--color-surface-frame: var(--color-muted);",
			"background: var(--color-surface-frame);",
			".nova-screen,",
			"height: 5.75rem !important;",
			".calendar-page--nova .nova-calendar-event__title",
			"--font-sans: \"Inter\", \"Satoshi\", ui-sans-serif, system-ui, sans-serif;",
		],
		mustNotInclude: ["\"Geist Sans\""],
	},
	{
		file: "src/components/ui/Motion.tsx",
		mustInclude: [
			"useReducedMotion",
			"MotionReveal",
			"MotionList",
			"MotionCard",
			"Math.min(delay, 0.18)",
			"staggerChildren: Math.min(stagger, 0.05)",
		],
	},
	{
		file: "src/components/ui/Button.tsx",
		mustInclude: [
			"haptic = \"none\"",
			"event.defaultPrevented",
			"haptics.selection()",
			"haptics.success()",
			"haptics.warning()",
			"haptics.error()",
		],
	},
	{
		file: "src/components/ui/ProcessingState.tsx",
		mustInclude: [
			"role=\"status\"",
			"aria-live=\"polite\"",
			"MatrixLoader",
			"role=\"presentation\"",
			"aria-hidden=\"true\"",
		],
	},
	{
		file: "src/utils/haptics.ts",
		mustInclude: [
			"prefers-reduced-motion: reduce",
			"navigator.vibrate(vibrationPattern)",
			"if (!force && prefersReducedMotion())",
		],
	},
	{
		file: "src/pages/Composer.tsx",
		mustInclude: [
			"ProcessingState",
			"haptics.success()",
			"haptics.warning()",
			"haptics.error()",
		],
	},
	{
		file: "src/pages/Calendar.tsx",
		mustInclude: [
			"haptics.selection()",
			"haptics.success()",
			"haptics.error()",
		],
	},
	{
		file: "src/components/dashboard-v2/DashboardV2.tsx",
		mustInclude: ["MotionReveal", "MatrixLoader"],
	},
];

const failures = [];

for (const check of checks) {
	if (!existsSync(check.file)) {
		failures.push(`${check.file}: file is missing`);
		continue;
	}
	const source = read(check.file);
	for (const needle of check.mustInclude ?? []) {
		if (!source.includes(needle)) {
			failures.push(`${check.file}: missing required frontend-quality marker: ${needle}`);
		}
	}
	for (const needle of check.mustNotInclude ?? []) {
		if (source.includes(needle)) {
			failures.push(`${check.file}: found banned frontend-quality regression: ${needle}`);
		}
	}
}

const productRouteFiles = [
	"src/pages/Dashboard.tsx",
	"src/components/dashboard-v2/DashboardV2.tsx",
	"src/pages/Content.tsx",
	"src/pages/Calendar.tsx",
	"src/pages/Composer.tsx",
	"src/pages/Inbox.tsx",
	"src/pages/Analytics.tsx",
	"src/pages/Accounts.tsx",
	"src/pages/Links.tsx",
	"src/pages/Ideas.tsx",
	"src/pages/Listening.tsx",
	"src/pages/Autopilot.tsx",
	"src/pages/Settings.tsx",
	"src/pages/Billing.tsx",
	"src/components/layout/Layout.tsx",
	"src/components/layout/MobileTabBar.tsx",
	"src/components/layout/CommandPalette.tsx",
];

const directRegistryImport = /from\s+["']@\/components\/shadcn\//;
const directRHFImport = /from\s+["']react-hook-form["']/;
const backendJargon = /\b(queue health|webhook replay|operator dispatcher|payload hash|Sync lane|Webhook lane)\b/i;
const broadRawColor = /className=.*(?:bg|text|border)-(?:white|black)\b|#[0-9a-fA-F]{3,8}/;

for (const file of productRouteFiles) {
	if (!existsSync(file)) continue;
	const source = read(file);
	if (directRegistryImport.test(source)) {
		failures.push(`${file}: product routes must import Juno wrappers, not raw shadcn source`);
	}
	if (directRHFImport.test(source)) {
		failures.push(`${file}: product routes must use Juno form adapters, not direct react-hook-form imports`);
	}
	if (backendJargon.test(source)) {
		failures.push(`${file}: primary/user-facing route contains backend/operator jargon`);
	}
	if (broadRawColor.test(source)) {
		failures.push(`${file}: route-level visible styling should use semantic tokens, not raw colors`);
	}
}

const docs = read("docs/FRONTEND_2026_PRO_MASTER_PLAN.md");
if (!docs.includes("Final Route QA Scorecard")) {
	failures.push("docs/FRONTEND_2026_PRO_MASTER_PLAN.md: missing Final Route QA Scorecard section");
}
if (!docs.includes("Final preset lock: Nova/zinc/Lucide/default radius with Inter")) {
	failures.push("docs/FRONTEND_2026_PRO_MASTER_PLAN.md: missing final preset lock statement");
}
if (!docs.includes("Primary routes rate at least **8.5/10**")) {
	failures.push("docs/FRONTEND_2026_PRO_MASTER_PLAN.md: final primary route threshold must be 8.5/10");
}
if (!docs.includes("Secondary/account routes rate at least **8.0/10**")) {
	failures.push("docs/FRONTEND_2026_PRO_MASTER_PLAN.md: final secondary/account route threshold must be 8.0/10");
}
if (!docs.includes("[x] Motion/haptics/loading are restrained and reduced-motion safe.")) {
	failures.push("docs/FRONTEND_2026_PRO_MASTER_PLAN.md: motion/haptics/loading acceptance must be checked after implementation");
}

if (failures.length > 0) {
	console.error("Frontend quality audit failed:");
	for (const failure of failures) console.error(`- ${failure}`);
	process.exit(1);
}

console.log("Frontend quality audit passed");
