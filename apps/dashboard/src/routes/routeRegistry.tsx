import type { ComponentType, ReactNode } from "react";
import { Navigate } from "react-router-dom";
import {
	BarChart3,
	Bot,
	CalendarDays,
	CreditCard,
	FileText,
	Home,
	Inbox as InboxIcon,
	Library,
	Lightbulb,
	Link2,
	PenSquare,
	Radio,
	Settings,
	Sparkles,
	TrendingUp,
	Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {
	AccountsSkeleton,
	AnalyticsSkeleton,
	AttributionSkeleton,
	AutopilotSkeleton,
	AuthCheckingFallback,
	BillingSkeleton,
	CalendarSkeleton,
	ComposerSkeleton,
	ContentLibrarySkeleton,
	DashboardSkeleton,
	InboxSkeleton,
	ReportsSkeleton,
	SettingsSkeleton,
	SmartLinksSkeleton,
} from "@/components/skeletons/PageSkeletons";
import { lazyWithRetry } from "@/lib/lazyWithRetry";

export const Dashboard = lazyWithRetry(() =>
	import("@/pages/Dashboard").then((m) => ({ default: m.Dashboard })),
);
export const Analytics = lazyWithRetry(() =>
	import("@/pages/Analytics").then((m) => ({ default: m.Analytics })),
);
export const Attribution = lazyWithRetry(() =>
	import("@/pages/Attribution").then((m) => ({ default: m.Attribution })),
);
export const Listening = lazyWithRetry(() =>
	import("@/pages/Listening").then((m) => ({ default: m.Listening })),
);
export const Reports = lazyWithRetry(() =>
	import("@/pages/Reports").then((m) => ({ default: m.Reports })),
);
export const Reliability = lazyWithRetry(() =>
	import("@/pages/Reliability").then((m) => ({ default: m.Reliability })),
);
export const Calendar = lazyWithRetry(() =>
	import("@/pages/Calendar").then((m) => ({ default: m.Calendar })),
);
export const Accounts = lazyWithRetry(() =>
	import("@/pages/Accounts").then((m) => ({ default: m.Accounts })),
);
export const Inbox = lazyWithRetry(() =>
	import("@/pages/Inbox").then((m) => ({ default: m.Inbox })),
);
export const Content = lazyWithRetry(() =>
	import("@/pages/Content").then((m) => ({ default: m.Content })),
);
export const ContentLibrary = lazyWithRetry(() =>
	import("@/pages/ContentLibrary").then((m) => ({ default: m.ContentLibrary })),
);
export const Ideas = lazyWithRetry(() =>
	import("@/pages/Ideas").then((m) => ({ default: m.Ideas })),
);
export const Links = lazyWithRetry(() =>
	import("@/pages/Links").then((m) => ({ default: m.Links })),
);
export const Autopilot = lazyWithRetry(() =>
	import("@/pages/Autopilot").then((m) => ({ default: m.Autopilot })),
);
export const ApprovalQueue = lazyWithRetry(() =>
	import("@/pages/ApprovalQueue").then((m) => ({ default: m.ApprovalQueue })),
);
export const Layout = lazyWithRetry(() =>
	import("@/components/layout/Layout").then((m) => ({ default: m.Layout })),
);
export const Composer = lazyWithRetry(() =>
	import("@/pages/Composer").then((m) => ({ default: m.Composer })),
);
export const Handoff = lazyWithRetry(() =>
	import("@/pages/Handoff").then((m) => ({ default: m.Handoff })),
);
export const PublishingSetup = lazyWithRetry(() =>
	import("@/pages/PublishingSetup").then((m) => ({ default: m.PublishingSetup })),
);
export const SettingsPage = lazyWithRetry(() =>
	import("@/pages/Settings").then((m) => ({ default: m.Settings })),
);
export const Billing = lazyWithRetry(() =>
	import("@/pages/Billing").then((m) => ({ default: m.Billing })),
);
export const Login = lazyWithRetry(() =>
	import("@/pages/auth/Login").then((m) => ({ default: m.Login })),
);
export const Signup = lazyWithRetry(() =>
	import("@/pages/auth/Signup").then((m) => ({ default: m.Signup })),
);
export const Welcome = lazyWithRetry(() =>
	import("@/pages/auth/Welcome").then((m) => ({ default: m.Welcome })),
);
export const AuthCallback = lazyWithRetry(() =>
	import("@/pages/auth/AuthCallback").then((m) => ({
		default: m.AuthCallback,
	})),
);
export const OAuthCallback = lazyWithRetry(() =>
	import("@/pages/auth/OAuthCallback").then((m) => ({
		default: m.OAuthCallback,
	})),
);
export const ResetPassword = lazyWithRetry(() =>
	import("@/pages/auth/ResetPassword").then((m) => ({
		default: m.ResetPassword,
	})),
);
export const InviteAccept = lazyWithRetry(() =>
	import("@/pages/auth/InviteAccept").then((m) => ({
		default: m.InviteAccept,
	})),
);
export const LegalPage = lazyWithRetry(() =>
	import("@/pages/legal/LegalPage").then((m) => ({ default: m.LegalPage })),
);
export const Landing = lazyWithRetry(() =>
	import("@/pages/Landing").then((m) => ({ default: m.Landing })),
);
export const SharedReport = lazyWithRetry(() =>
	import("@/pages/SharedReport").then((m) => ({ default: m.SharedReport })),
);

export type ProtectedRouteId =
	| "dashboard"
	| "analytics"
	| "attribution"
	| "listening"
	| "reports"
	| "reliability"
	| "calendar"
	| "accounts"
	| "inbox"
	| "content"
	| "content-library"
	| "ideas"
	| "links"
	| "autopilot"
	| "composer"
	| "handoff"
	| "publishing-setup"
	| "settings"
	| "billing"
	| "approval-queue";

export type NavGroup = "primary" | "secondary" | "account";
export type MobileMoreGroup =
	| "Primary work"
	| "Publishing"
	| "Growth"
	| "Account & settings";

export type RouteNavItem = {
	path: string;
	label: string;
	icon: LucideIcon;
	badge?: "attention" | undefined;
};

export type RouteCommand = {
	id: string;
	label: string;
	icon: LucideIcon;
	route: string;
	shortcut?: string | undefined;
	subtitle?: string | undefined;
	category: string;
};

export type MobileMoreSection = {
	title: MobileMoreGroup;
	items: { to: string; label: string; Icon: LucideIcon }[];
};

type ProtectedRouteDefinition = {
	id: ProtectedRouteId;
	paths: readonly string[];
	component: ComponentType;
	fallback: ReactNode;
	fallbackPrefixes?: readonly string[];
	nav?: {
		group: NavGroup;
		path?: string;
		label: string;
		icon: LucideIcon;
		order: number;
		badge?: "attention" | undefined;
	};
	mobileMore?: {
		group: MobileMoreGroup;
		label?: string;
		icon?: LucideIcon;
		order: number;
	};
	command?: Omit<RouteCommand, "icon"> & {
		icon?: LucideIcon;
		order: number;
	};
	breadcrumb?: {
		root?: string;
		current: string;
		rootPath?: string | null;
	};
};

type RedirectDefinition = {
	path: string;
	to: string;
};

export const protectedRouteRegistry: readonly ProtectedRouteDefinition[] = [
	{
		id: "dashboard",
		paths: ["/dashboard"],
		component: Dashboard,
		fallback: <DashboardSkeleton />,
		fallbackPrefixes: ["/", "/dashboard"],
		nav: { group: "primary", label: "Dashboard", icon: Home, order: 1 },
		command: {
			id: "nav-home",
			label: "Go to Dashboard",
			subtitle: "Fleet overview and daily action list",
			shortcut: "G O",
			category: "Primary",
			route: "dashboard",
			order: 1,
		},
		breadcrumb: { current: "Dashboard" },
	},
	{
		id: "analytics",
		paths: ["/analytics"],
		component: Analytics,
		fallback: <AnalyticsSkeleton />,
		nav: { group: "primary", label: "Analytics", icon: BarChart3, order: 6 },
		command: {
			id: "nav-analytics",
			label: "Analytics",
			subtitle: "Campaign quality and evidence rows",
			shortcut: "G Y",
			category: "Primary",
			route: "analytics",
			order: 6,
		},
		breadcrumb: { current: "Analytics", rootPath: "/dashboard" },
	},
	{
		id: "attribution",
		paths: ["/attribution"],
		component: Attribution,
		fallback: <AttributionSkeleton />,
		nav: { group: "secondary", label: "Attribution", icon: Sparkles, order: 6 },
		mobileMore: { group: "Growth", label: "Attribution", icon: TrendingUp, order: 4 },
		command: {
			id: "nav-attribution",
			label: "Attribution",
			subtitle: "Revenue, source quality, and conversion evidence",
			category: "More",
			route: "attribution",
			icon: BarChart3,
			order: 13,
		},
		breadcrumb: { current: "Attribution", rootPath: "/dashboard" },
	},
	{
		id: "listening",
		paths: ["/listening"],
		component: Listening,
		fallback: <DashboardSkeleton />,
		nav: { group: "secondary", label: "Listening", icon: Radio, order: 4 },
		mobileMore: { group: "Growth", order: 2 },
		command: {
			id: "nav-listening",
			label: "Listening",
			subtitle: "Mentions, competitor spikes, and trend monitors",
			shortcut: "G M",
			category: "More",
			route: "listening",
			order: 11,
		},
		breadcrumb: { current: "Listening", rootPath: "/dashboard" },
	},
	{
		id: "reports",
		paths: ["/reports"],
		component: Reports,
		fallback: <ReportsSkeleton />,
		nav: { group: "secondary", label: "Reports", icon: FileText, order: 5 },
		mobileMore: { group: "Growth", order: 3 },
		command: {
			id: "nav-reports",
			label: "Reports",
			subtitle: "Scheduled reports, share links, and PDFs",
			shortcut: "G R",
			category: "More",
			route: "reports",
			order: 12,
		},
		breadcrumb: { current: "Reports", rootPath: "/dashboard" },
	},
	{
		id: "reliability",
		paths: ["/reliability"],
		component: Reliability,
		fallback: <DashboardSkeleton />,
		breadcrumb: { current: "Reliability", rootPath: "/dashboard" },
	},
	{
		id: "calendar",
		paths: ["/calendar"],
		component: Calendar,
		fallback: <CalendarSkeleton />,
		nav: { group: "primary", label: "Calendar", icon: CalendarDays, order: 3 },
		command: {
			id: "nav-calendar",
			label: "Scheduler",
			subtitle: "Queue, cadence, gaps, and reschedules",
			shortcut: "G S",
			category: "Primary",
			route: "calendar",
			icon: CalendarDays,
			order: 3,
		},
		breadcrumb: { current: "Calendar", rootPath: "/dashboard" },
	},
	{
		id: "accounts",
		paths: ["/accounts"],
		component: Accounts,
		fallback: <AccountsSkeleton />,
		nav: { group: "primary", label: "Accounts", icon: Users, order: 7, badge: "attention" },
		command: {
			id: "nav-accounts",
			label: "Accounts",
			subtitle: "Health, tokens, groups, and account map",
			shortcut: "G A",
			category: "Primary",
			route: "accounts",
			order: 7,
		},
		breadcrumb: { current: "Accounts", rootPath: "/dashboard" },
	},
	{
		id: "inbox",
		paths: ["/inbox"],
		component: Inbox,
		fallback: <InboxSkeleton />,
		nav: { group: "primary", label: "Inbox", icon: InboxIcon, order: 5 },
		mobileMore: { group: "Primary work", order: 2 },
		command: {
			id: "nav-inbox",
			label: "Inbox",
			subtitle: "DMs, comments, mentions, and suggestions",
			category: "Primary",
			route: "inbox",
			order: 5,
		},
		breadcrumb: { current: "Inbox", rootPath: "/dashboard" },
	},
	{
		id: "content",
		paths: ["/content"],
		component: Content,
		fallback: <AnalyticsSkeleton />,
		nav: { group: "primary", label: "Content", icon: Library, order: 2 },
		mobileMore: { group: "Primary work", order: 1 },
		command: {
			id: "nav-content",
			label: "Content",
			subtitle: "Published posts, performance, and content review",
			shortcut: "G T",
			category: "Primary",
			route: "content",
			order: 2,
		},
		breadcrumb: { current: "Content", rootPath: "/dashboard" },
	},
	{
		id: "content-library",
		paths: ["/content-library"],
		component: ContentLibrary,
		fallback: <ContentLibrarySkeleton />,
		command: {
			id: "nav-content-assets",
			label: "Media assets",
			subtitle: "Content > media library and reusable assets",
			category: "Content",
			route: "content-library",
			icon: Library,
			order: 14,
		},
		breadcrumb: { root: "Content", current: "Media library", rootPath: "/content" },
	},
	{
		id: "ideas",
		paths: ["/ideas"],
		component: Ideas,
		fallback: <DashboardSkeleton />,
		nav: { group: "secondary", label: "Ideas", icon: Lightbulb, order: 2 },
		mobileMore: { group: "Publishing", order: 1 },
		command: {
			id: "nav-ideas",
			label: "Ideas",
			subtitle: "Capture thoughts, links, screenshots, and voice notes",
			shortcut: "G I",
			category: "More",
			route: "ideas",
			order: 8,
		},
		breadcrumb: { current: "Ideas", rootPath: "/dashboard" },
	},
	{
		id: "links",
		paths: ["/links"],
		component: Links,
		fallback: <SmartLinksSkeleton />,
		nav: { group: "secondary", label: "Links", icon: Link2, order: 1 },
		mobileMore: { group: "Growth", label: "Smart Links", order: 1 },
		command: {
			id: "nav-links",
			label: "Smart Links",
			subtitle: "Bio links, pixels, and conversion paths",
			shortcut: "G L",
			category: "More",
			route: "links",
			order: 10,
		},
		breadcrumb: { current: "Links", rootPath: "/dashboard" },
	},
	{
		id: "autopilot",
		paths: ["/autopilot/:section/:runId", "/autopilot/:section"],
		component: Autopilot,
		fallback: <AutopilotSkeleton />,
		fallbackPrefixes: ["/autopilot"],
		nav: { group: "secondary", label: "Autopilot", icon: Bot, order: 3, path: "/autopilot" },
		mobileMore: { group: "Publishing", icon: Sparkles, order: 2 },
		command: {
			id: "act-auto",
			label: "Open Autopilot",
			subtitle: "Open automation controls and queue health",
			category: "More",
			route: "autopilot",
			icon: Bot,
			order: 9,
		},
		breadcrumb: { root: "Autopilot", current: "Queue", rootPath: "/autopilot" },
	},
	{
		id: "composer",
		paths: ["/composer"],
		component: Composer,
		fallback: <ComposerSkeleton />,
		nav: { group: "primary", label: "Composer", icon: PenSquare, order: 4 },
		command: {
			id: "nav-composer",
			label: "Composer",
			subtitle: "Draft, adapt, preview, and publish",
			shortcut: "G C",
			category: "Primary",
			route: "composer",
			order: 4,
		},
		breadcrumb: { current: "Composer", rootPath: "/dashboard" },
	},
	{
		id: "handoff",
		paths: ["/handoff/:postId"],
		component: Handoff,
		fallback: <DashboardSkeleton />,
		fallbackPrefixes: ["/handoff"],
		breadcrumb: { root: "Handoff", current: "Post", rootPath: "/calendar" },
	},
	{
		id: "publishing-setup",
		paths: ["/setup/publishing"],
		component: PublishingSetup,
		fallback: <DashboardSkeleton />,
		fallbackPrefixes: ["/setup/publishing"],
		breadcrumb: { root: "Setup", current: "Publishing", rootPath: "/dashboard" },
	},
	{
		id: "settings",
		paths: ["/settings", "/settings/:tab"],
		component: SettingsPage,
		fallback: <SettingsSkeleton />,
		fallbackPrefixes: ["/settings"],
		nav: { group: "account", label: "Settings", icon: Settings, order: 1 },
		mobileMore: { group: "Account & settings", order: 1 },
		command: {
			id: "nav-settings",
			label: "Settings",
			subtitle: "Workspace, security, API, and integrations",
			category: "Settings",
			route: "settings",
			icon: Settings,
			order: 15,
		},
		breadcrumb: { current: "Settings", rootPath: "/dashboard" },
	},
	{
		id: "billing",
		paths: ["/billing"],
		component: Billing,
		fallback: <BillingSkeleton />,
		nav: { group: "account", label: "Billing & plans", icon: CreditCard, order: 2 },
		command: {
			id: "nav-billing",
			label: "Billing & plans",
			subtitle: "Usage, plan comparison, and portal access",
			category: "Settings",
			route: "billing",
			icon: CreditCard,
			order: 16,
		},
		breadcrumb: { current: "Billing & plans", rootPath: "/settings" },
	},
	{
		id: "approval-queue",
		paths: ["/approval-queue"],
		component: ApprovalQueue,
		fallback: <DashboardSkeleton />,
		breadcrumb: { current: "Approval queue", rootPath: "/dashboard" },
	},
] as const;

export const protectedRedirectRegistry = [
	{ path: "/ask", to: "/dashboard" },
	{ path: "/autopilot", to: "/autopilot/queue" },
	{ path: "/checkout", to: "/billing" },
	{ path: "/posts", to: "/calendar" },
	{ path: "/threads-inbox", to: "/inbox" },
	{ path: "/media-library", to: "/content-library" },
	{ path: "/content-pillars", to: "/content-library" },
	{ path: "/groups", to: "/accounts" },
	{ path: "/account-groups", to: "/accounts" },
	{ path: "/auto-poster", to: "/autopilot/queue" },
] as const satisfies readonly RedirectDefinition[];

export const PRIMARY_NAV = navItemsForGroup("primary");
export const SECONDARY_NAV = navItemsForGroup("secondary");
export const ACCOUNT_MENU_NAV = protectedRouteRegistry
	.filter((route) => route.nav?.group === "account")
	.sort((a, b) => (a.nav?.order ?? 0) - (b.nav?.order ?? 0))
	.map((route) => ({
		path: route.nav?.path ?? route.paths[0] ?? "/",
		label: route.nav?.label ?? route.breadcrumb?.current ?? route.id,
	})) as readonly { path: string; label: string }[];

export const MOBILE_MORE_SECTIONS = mobileMoreSections();
export const APP_ROUTE_COMMANDS = protectedRouteRegistry
	.filter((route) => route.command)
	.sort((a, b) => (a.command?.order ?? 0) - (b.command?.order ?? 0))
	.map((route) => ({
		id: route.command?.id ?? route.id,
		label: route.command?.label ?? route.nav?.label ?? titleize(route.id),
		icon: route.command?.icon ?? route.nav?.icon ?? Home,
		route: route.command?.route ?? (route.nav?.path ?? route.paths[0] ?? "/").replace(/^\//, ""),
		shortcut: route.command?.shortcut,
		subtitle: route.command?.subtitle,
		category: route.command?.category ?? "More",
	})) as readonly RouteCommand[];

export function protectedRouteElements(): { path: string; element: ReactNode }[] {
	return protectedRouteRegistry.flatMap((route) =>
		route.paths.map((path) => {
			const Component = route.component;
			return { path, element: <Component /> };
		}),
	);
}

export function protectedRedirectElements(): { path: string; element: ReactNode }[] {
	return protectedRedirectRegistry.map((redirect) => ({
		path: redirect.path,
		element: <Navigate to={redirect.to} replace />,
	}));
}

export function routeFallbackForPathname(pathname: string): ReactNode {
	const normalized = pathname || "/";
	const exactRoot = protectedRouteRegistry.find((route) =>
		route.fallbackPrefixes?.includes("/"),
	);
	if (normalized === "/" && exactRoot) return exactRoot.fallback;

	const match = protectedRouteRegistry
		.flatMap((route) =>
			fallbackPrefixesFor(route).map((prefix) => ({ route, prefix })),
		)
		.filter(({ prefix }) => prefix !== "/")
		.sort((a, b) => b.prefix.length - a.prefix.length)
		.find(({ prefix }) => normalized === prefix || normalized.startsWith(`${prefix}/`));

	return match?.route.fallback ?? <AuthCheckingFallback />;
}

export function breadcrumbForPathname(pathname: string): {
	root: string;
	current: string;
	rootPath: string | null;
} {
	const match = protectedRouteRegistry
		.flatMap((route) =>
			breadcrumbPrefixesFor(route).map((prefix) => ({ route, prefix })),
		)
		.sort((a, b) => b.prefix.length - a.prefix.length)
		.find(({ prefix }) => pathname === prefix || pathname.startsWith(`${prefix}/`));

	if (!match) return { root: "Workspace", current: "Dashboard", rootPath: null };

	const breadcrumb = match.route.breadcrumb;
	const fallbackCurrent = match.route.nav?.label ?? titleize(match.route.id);
	return {
		root: breadcrumb?.root ?? "Workspace",
		current: breadcrumb?.current ?? fallbackCurrent,
		rootPath: breadcrumb?.rootPath ?? (match.route.id === "dashboard" ? null : "/dashboard"),
	};
}

function navItemsForGroup(group: NavGroup): RouteNavItem[] {
	return protectedRouteRegistry
		.filter((route) => route.nav?.group === group)
		.sort((a, b) => (a.nav?.order ?? 0) - (b.nav?.order ?? 0))
		.map((route) => ({
			path: route.nav?.path ?? route.paths[0] ?? "/",
			label: route.nav?.label ?? route.breadcrumb?.current ?? titleize(route.id),
			icon: route.nav?.icon ?? Home,
			badge: route.nav?.badge,
		}));
}

function mobileMoreSections(): MobileMoreSection[] {
	const order: MobileMoreGroup[] = [
		"Primary work",
		"Publishing",
		"Growth",
		"Account & settings",
	];
	return order
		.map((title) => ({
			title,
			items: protectedRouteRegistry
				.filter((route) => route.mobileMore?.group === title)
				.sort((a, b) => (a.mobileMore?.order ?? 0) - (b.mobileMore?.order ?? 0))
				.map((route) => ({
					to: route.nav?.path ?? route.paths[0] ?? "/",
					label:
						route.mobileMore?.label ??
						route.nav?.label ??
						route.breadcrumb?.current ??
						titleize(route.id),
					Icon: route.mobileMore?.icon ?? route.nav?.icon ?? Home,
				})),
		}))
		.filter((section) => section.items.length > 0);
}

function fallbackPrefixesFor(route: ProtectedRouteDefinition): string[] {
	if (route.fallbackPrefixes) return [...route.fallbackPrefixes];
	return route.paths.map(pathBase);
}

function breadcrumbPrefixesFor(route: ProtectedRouteDefinition): string[] {
	return route.paths.map(pathBase);
}

function pathBase(path: string): string {
	const segments = path.split("/").filter(Boolean);
	const staticSegments = segments.filter((segment) => !segment.startsWith(":"));
	return `/${staticSegments.join("/")}`;
}

function titleize(value: string): string {
	return value
		.split("-")
		.map((word) => `${word.slice(0, 1).toUpperCase()}${word.slice(1)}`)
		.join(" ");
}
