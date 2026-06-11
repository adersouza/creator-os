import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
	AutopilotSkeleton,
	ContentLibrarySkeleton,
	DashboardSkeleton,
	SettingsSkeleton,
} from "@/components/skeletons/PageSkeletons";
import { protectedRedirects, protectedRoutes } from "@/routes/appRoutes";
import {
	APP_ROUTE_COMMANDS as REGISTRY_ROUTE_COMMANDS,
	ACCOUNT_MENU_NAV as REGISTRY_ACCOUNT_MENU_NAV,
	MOBILE_MORE_SECTIONS as REGISTRY_MOBILE_MORE_SECTIONS,
	PRIMARY_NAV as REGISTRY_PRIMARY_NAV,
	SECONDARY_NAV as REGISTRY_SECONDARY_NAV,
	breadcrumbForPathname,
	protectedRedirectRegistry,
	protectedRouteRegistry,
	routeFallbackForPathname,
} from "@/routes/routeRegistry";
import {
	ACCOUNT_MENU_NAV,
	PRIMARY_NAV,
	SECONDARY_NAV,
} from "./Layout";
import { MOBILE_MORE_SECTIONS } from "./MobileTabBar";
import { APP_ROUTE_COMMANDS } from "./CommandPalette";

const labels = <T extends { label: string }>(items: readonly T[]) =>
	items.map((item) => item.label);

const paths = <T extends { path: string }>(items: readonly T[]) =>
	items.map((item) => item.path);

const appRoutesSource = readFileSync("src/App.tsx", "utf8");
const layoutSource = readFileSync("src/components/layout/Layout.tsx", "utf8");
const commandPaletteSource = readFileSync(
	"src/components/layout/CommandPalette.tsx",
	"utf8",
);
const mobileTabBarSource = readFileSync(
	"src/components/layout/MobileTabBar.tsx",
	"utf8",
);

describe("app shell IA contract", () => {
	it("uses the route registry as the only source for route shell metadata", () => {
		expect(PRIMARY_NAV).toBe(REGISTRY_PRIMARY_NAV);
		expect(SECONDARY_NAV).toBe(REGISTRY_SECONDARY_NAV);
		expect(ACCOUNT_MENU_NAV).toBe(REGISTRY_ACCOUNT_MENU_NAV);
		expect(MOBILE_MORE_SECTIONS).toBe(REGISTRY_MOBILE_MORE_SECTIONS);
		expect(APP_ROUTE_COMMANDS).toBe(REGISTRY_ROUTE_COMMANDS);

		expect(layoutSource).not.toContain("export const PRIMARY_NAV: NavItem[] = [");
		expect(commandPaletteSource).not.toContain("export const APP_ROUTE_COMMANDS");
		expect(mobileTabBarSource).not.toContain("export const MOBILE_MORE_SECTIONS:");
	});

	it("keeps registry route ids, paths, commands, and redirects unique", () => {
		const ids = protectedRouteRegistry.map((route) => route.id);
		expect(new Set(ids).size).toBe(ids.length);

		const protectedPaths = protectedRouteRegistry.flatMap((route) => route.paths);
		expect(new Set(protectedPaths).size).toBe(protectedPaths.length);

		const commandIds = APP_ROUTE_COMMANDS.map((command) => command.id);
		expect(new Set(commandIds).size).toBe(commandIds.length);

		const redirectPaths = protectedRedirectRegistry.map((redirect) => redirect.path);
		expect(new Set(redirectPaths).size).toBe(redirectPaths.length);
	});

	it("keeps the desktop sidebar focused on primary and more product surfaces", () => {
		expect(labels(PRIMARY_NAV)).toEqual([
			"Dashboard",
			"Content",
			"Calendar",
			"Composer",
			"Inbox",
			"Analytics",
			"Accounts",
		]);

		expect(labels(SECONDARY_NAV)).toEqual([
			"Links",
			"Ideas",
			"Autopilot",
			"Listening",
			"Reports",
			"Attribution",
		]);

		expect(paths([...PRIMARY_NAV, ...SECONDARY_NAV])).not.toContain("/billing");
		expect(paths([...PRIMARY_NAV, ...SECONDARY_NAV])).not.toContain(
			"/reliability",
		);
	});

	it("keeps billing in account/settings rather than product navigation", () => {
		expect(ACCOUNT_MENU_NAV).toEqual([
			{ label: "Settings", path: "/settings" },
			{ label: "Billing & plans", path: "/billing" },
		]);
	});

	it("groups mobile More destinations by operator intent", () => {
		expect(
			MOBILE_MORE_SECTIONS.map((section) => ({
				title: section.title,
				items: section.items.map((item) => [item.label, item.to]),
			})),
		).toEqual([
			{
				title: "Primary work",
				items: [
					["Content", "/content"],
					["Inbox", "/inbox"],
				],
			},
			{
				title: "Publishing",
				items: [
					["Ideas", "/ideas"],
					["Autopilot", "/autopilot"],
				],
			},
			{
				title: "Growth",
				items: [
					["Smart Links", "/links"],
					["Listening", "/listening"],
					["Reports", "/reports"],
					["Attribution", "/attribution"],
				],
			},
			{
				title: "Account & settings",
				items: [["Settings", "/settings"]],
			},
		]);
	});

	it("keeps command palette route categories aligned to the IA", () => {
		const byId = new Map(APP_ROUTE_COMMANDS.map((command) => [command.id, command]));

		for (const id of [
			"nav-home",
			"nav-content",
			"nav-calendar",
			"nav-composer",
			"nav-inbox",
			"nav-analytics",
			"nav-accounts",
		]) {
			expect(byId.get(id)?.category).toBe("Primary");
		}

		for (const id of [
			"nav-ideas",
			"act-auto",
			"nav-links",
			"nav-listening",
			"nav-reports",
			"nav-attribution",
		]) {
			expect(byId.get(id)?.category).toBe("More");
		}

		expect(byId.get("nav-content-assets")).toMatchObject({
			label: "Media assets",
			route: "content-library",
			category: "Content",
		});
		expect(byId.get("nav-billing")).toMatchObject({
			label: "Billing & plans",
			route: "billing",
			category: "Settings",
		});
	});

	it("keeps registry commands pointing to routable protected destinations", () => {
		const protectedPathBases = new Set(
			protectedRoutes.map((route) => route.path.split("/:")[0]?.replace(/^\//, "")),
		);
		const redirectPathBases = new Set(
			protectedRedirects.map((route) => route.path.replace(/^\//, "")),
		);

		for (const command of APP_ROUTE_COMMANDS) {
			const routeBase = command.route.split("?")[0]?.replace(/^\//, "");
			expect(routeBase).toBeTruthy();
			expect(
				protectedPathBases.has(routeBase ?? "") ||
					redirectPathBases.has(routeBase ?? ""),
			).toBe(true);
		}
	});

	it("keeps registered fallbacks and breadcrumbs stable for key paths", () => {
		expect(routeFallbackForPathname("/")).toMatchObject({
			type: DashboardSkeleton,
		});
		expect(routeFallbackForPathname("/content-library")).toMatchObject({
			type: ContentLibrarySkeleton,
		});
		expect(routeFallbackForPathname("/autopilot/queue")).toMatchObject({
			type: AutopilotSkeleton,
		});
		expect(routeFallbackForPathname("/settings/security")).toMatchObject({
			type: SettingsSkeleton,
		});

		expect(breadcrumbForPathname("/autopilot/queue")).toEqual({
			root: "Autopilot",
			current: "Queue",
			rootPath: "/autopilot",
		});
		expect(breadcrumbForPathname("/settings/security")).toEqual({
			root: "Workspace",
			current: "Settings",
			rootPath: "/dashboard",
		});
		expect(breadcrumbForPathname("/handoff/example-post")).toEqual({
			root: "Handoff",
			current: "Post",
			rootPath: "/calendar",
		});
	});

	it("keeps contextual and direct-link routes routable without surfacing them in shell nav", () => {
		const protectedPaths = protectedRoutes.map((route) => route.path);
		expect(protectedPaths).toEqual(
			expect.arrayContaining([
				"/content-library",
				"/approval-queue",
				"/handoff/:postId",
				"/setup/publishing",
				"/reliability",
				"/billing",
				"/settings/:tab",
			]),
		);

		const shellPaths = new Set([
			...paths(PRIMARY_NAV),
			...paths(SECONDARY_NAV),
			...ACCOUNT_MENU_NAV.map((item) => item.path),
			...MOBILE_MORE_SECTIONS.flatMap((section) =>
				section.items.map((item) => item.to),
			),
		]);

		for (const directLinkPath of [
			"/content-library",
			"/approval-queue",
			"/handoff/:postId",
			"/setup/publishing",
			"/reliability",
		]) {
			expect(shellPaths.has(directLinkPath)).toBe(false);
		}

		expect(protectedRedirects.map((route) => route.path)).toEqual(
			expect.arrayContaining([
				"/ask",
				"/checkout",
				"/posts",
				"/threads-inbox",
				"/media-library",
				"/content-pillars",
				"/groups",
				"/account-groups",
				"/auto-poster",
			]),
		);

		for (const directLinkRoute of [
			'path="/share/:token"',
			'path="/welcome"',
			'path="/privacy"',
			'path="/terms"',
			'path="/gdpr-deletion"',
			'path="/auth/callback"',
			'path="/auth/reset-password"',
			'path="/auth/threads/callback"',
			'path="/auth/instagram/callback"',
			'path="/auth/facebook/callback"',
			'path="/invite/:code"',
		]) {
			expect(appRoutesSource).toContain(directLinkRoute);
		}
	});
});
