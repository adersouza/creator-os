// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import React, { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
	Bell,
	BookOpen,
	CreditCard,
	LogOut,
	Menu,
	Search,
	Settings as SettingsIcon,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Toaster } from "@/components/ui/Toast";
import { ComposerModal } from "@/components/composer/ComposerModal";
import {
	Breadcrumb,
	BreadcrumbItem,
	BreadcrumbLink,
	BreadcrumbList,
	BreadcrumbPage,
	BreadcrumbSeparator,
} from "@/components/ui/Breadcrumb";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import {
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuLabel,
	DropdownMenuRoot,
	DropdownMenuSeparator,
	DropdownMenuTrigger,
} from "@/components/ui/DropdownMenu";
import { Kbd } from "@/components/ui/Kbd";
import { OfflineBanner } from "@/components/ui/OfflineBanner";
import { Separator } from "@/components/ui/Separator";
import {
	Sidebar,
	SidebarContent,
	SidebarFooter,
	SidebarGroup,
	SidebarGroupContent,
	SidebarGroupLabel,
	SidebarHeader,
	SidebarInset,
	SidebarMenu,
	SidebarMenuBadge,
	SidebarMenuButton,
	SidebarMenuItem,
	SidebarProvider,
	SidebarRail,
	SidebarSeparator,
	SidebarTrigger,
} from "@/components/ui/Sidebar";
import { Sigil33 } from "@/components/ui/Sigil33";
import { TooltipProvider } from "@/components/ui/Tooltip";
import { ActivityContext } from "@/contexts/ActivityContext";
import { ComposerContext } from "@/contexts/ComposerContext";
import { useActivityEvents } from "@/hooks/useActivityEvents";
import { useAuthUser } from "@/hooks/useAuthUser";
import {
	type ShortcutKey,
	useKeyboardShortcuts,
} from "@/hooks/useKeyboardShortcuts";
import { useNeedsAttention } from "@/hooks/useNeedsAttention";
import { isMacLike } from "@/lib/platform";
import { isFleetResetMainNavPath, mainSidebarRoute } from "@/lib/scopedRoutes";
import {
	ACCOUNT_MENU_NAV,
	PRIMARY_NAV,
	SECONDARY_NAV,
	breadcrumbForPathname,
} from "@/routes/routeRegistry";
import { supabase } from "@/services/supabase";
import { notificationService } from "@/services/notificationService";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import { useWorkspaceStore } from "@/stores/useWorkspaceStore";
import type { Notification as AppNotification } from "@/types/index";
import {
	ActivityPanel,
	activityStorageKey,
	isActionableActivityEvent,
	loadIdSet,
	persistIdSet,
} from "./ActivityPanel";
import { MobileTabBar } from "./MobileTabBar";
import { applyNotificationLocalState } from "./notificationState";
import { ThemeToggle } from "./ThemeToggle";

const CommandPalette = lazy(() =>
	import("./CommandPalette").then((m) => ({ default: m.CommandPalette })),
);
const ShortcutsHelp = lazy(() =>
	import("./ShortcutsHelp").then((m) => ({ default: m.ShortcutsHelp })),
);

interface LayoutProps {
	children: React.ReactNode;
}

type NavItem = {
	path: string;
	label: string;
	icon: LucideIcon;
	badge?: "attention" | undefined;
};

export { ACCOUNT_MENU_NAV, PRIMARY_NAV, SECONDARY_NAV };

const APP_SIDEBAR_WIDTH = "12.75rem";

function useBreadcrumb(): {
	root: string;
	current: string;
	rootPath: string | null;
} {
	const { pathname } = useLocation();
	return breadcrumbForPathname(pathname);
}

export function Layout({ children }: LayoutProps) {
	const [showNotifications, setShowNotifications] = useState(false);
	const [isPaletteOpen, setIsPaletteOpen] = useState(false);
	const [isHelpOpen, setIsHelpOpen] = useState(false);
	const [isComposerOpen, setIsComposerOpen] = useState(false);
	const [composerDirty, setComposerDirty] = useState(false);
	const [composerConfirmOpen, setComposerConfirmOpen] = useState(false);
	const [composerConfirmBusy, setComposerConfirmBusy] = useState(false);
	const composerSaveDraftRef = React.useRef<(() => Promise<void> | void) | null>(null);
	const location = useLocation();
	const navigate = useNavigate();
	const { root, current, rootPath } = useBreadcrumb();
	const isComposerRoute = location.pathname.startsWith("/composer");

	const authUser = useAuthUser();
	const mainContentRef = React.useRef<HTMLElement | null>(null);
	const readKey = activityStorageKey("read", authUser?.id);
	const deletedKey = activityStorageKey("deleted", authUser?.id);
	const [readIds, setReadIds] = useState<Set<string>>(() => loadIdSet(readKey));
	const [deletedIds, setDeletedIds] = useState<Set<string>>(() => loadIdSet(deletedKey));
	const [notifications, setNotifications] = useState<AppNotification[]>([]);
	const [notificationsError, setNotificationsError] = useState(false);
	const notificationReadOverridesRef = React.useRef<Set<string>>(new Set());
	const notificationDeletedOverridesRef = React.useRef<Set<string>>(new Set());

	useEffect(() => {
		setReadIds(loadIdSet(readKey));
		setDeletedIds(loadIdSet(deletedKey));
		notificationReadOverridesRef.current = new Set();
		notificationDeletedOverridesRef.current = new Set();
	}, [readKey, deletedKey]);

	useEffect(() => {
		const _routeScrollKey = `${location.pathname}${location.search}`;
		window.scrollTo(0, 0);
		mainContentRef.current?.scrollTo({ top: 0, left: 0 });
	}, [location.pathname, location.search]);

	useEffect(() => {
		persistIdSet(readKey, readIds);
	}, [readIds, readKey]);

	useEffect(() => {
		persistIdSet(deletedKey, deletedIds);
	}, [deletedIds, deletedKey]);

	useEffect(() => {
		setNotifications([]);
		setNotificationsError(false);
		if (!authUser?.id) return;
		return notificationService.subscribeToNotifications(
			(next) => {
				setNotifications(
					applyNotificationLocalState(next, {
						readIds: notificationReadOverridesRef.current,
						deletedIds: notificationDeletedOverridesRef.current,
					}),
				);
				setNotificationsError(false);
			},
			() => setNotificationsError(true),
		);
	}, [authUser?.id]);

	const applyNotificationOverridesToCurrent = React.useCallback(() => {
		setNotifications((items) =>
			applyNotificationLocalState(items, {
				readIds: notificationReadOverridesRef.current,
				deletedIds: notificationDeletedOverridesRef.current,
			}),
		);
	}, []);

	const stageNotificationReads = React.useCallback(
		(ids: readonly string[]) => {
			if (ids.length === 0) return;
			for (const id of ids) notificationReadOverridesRef.current.add(id);
			applyNotificationOverridesToCurrent();
		},
		[applyNotificationOverridesToCurrent],
	);

	const stageNotificationDeletes = React.useCallback(
		(ids: readonly string[]) => {
			if (ids.length === 0) return;
			for (const id of ids) notificationDeletedOverridesRef.current.add(id);
			applyNotificationOverridesToCurrent();
		},
		[applyNotificationOverridesToCurrent],
	);

	const rollbackNotificationReads = React.useCallback((ids: readonly string[]) => {
		if (ids.length === 0) return;
		for (const id of ids) notificationReadOverridesRef.current.delete(id);
		void notificationService.getNotifications().then((next) => {
			setNotifications(
				applyNotificationLocalState(next, {
					readIds: notificationReadOverridesRef.current,
					deletedIds: notificationDeletedOverridesRef.current,
				}),
			);
		});
	}, []);

	const rollbackNotificationDeletes = React.useCallback(
		(ids: readonly string[]) => {
			if (ids.length === 0) return;
			for (const id of ids) notificationDeletedOverridesRef.current.delete(id);
			void notificationService.getNotifications().then((next) => {
				setNotifications(
					applyNotificationLocalState(next, {
						readIds: notificationReadOverridesRef.current,
						deletedIds: notificationDeletedOverridesRef.current,
					}),
				);
			});
		},
		[],
	);

	const { events: activityEvents } = useActivityEvents();
	const unreadNotificationCount = useMemo(
		() => notifications.filter((notification) => !notification.read).length,
		[notifications],
	);
	const unreadActivityCount = useMemo(
		() =>
			activityEvents.filter(
				(event) =>
					isActionableActivityEvent(event) &&
					!readIds.has(event.id) &&
					!deletedIds.has(event.id),
			).length,
		[activityEvents, readIds, deletedIds],
	);
	const unreadTotalCount = unreadActivityCount + unreadNotificationCount;

	useKeyboardShortcuts({
		disabled: isPaletteOpen || isComposerOpen,
		onShortcut: (key: ShortcutKey) => {
			switch (key) {
				case "go-overview":
					navigate("/dashboard");
					break;
				case "go-accounts":
					navigate("/accounts");
					break;
				case "go-scheduler":
					navigate("/calendar");
					break;
				case "go-composer":
					navigate("/composer");
					break;
				case "go-analytics":
					navigate("/analytics");
					break;
				case "go-smartlinks":
					navigate("/links");
					break;
				case "new-post":
					setIsComposerOpen(true);
					break;
				case "toggle-help":
					setIsHelpOpen((value) => !value);
					break;
				case "close":
					setIsHelpOpen(false);
					setShowNotifications(false);
					setIsComposerOpen(false);
					break;
			}
		},
	});

	useEffect(() => {
		const handler = (event: KeyboardEvent) => {
			if ((event.metaKey || event.ctrlKey) && event.key === "k") {
				const active = document.activeElement;
				const selectedEditableText =
					(active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement) &&
					typeof active.selectionStart === "number" &&
					typeof active.selectionEnd === "number" &&
					active.selectionEnd > active.selectionStart;
				if (selectedEditableText) return;
				event.preventDefault();
				setIsPaletteOpen((value) => !value);
			} else if (event.key === "Escape" && isPaletteOpen) {
				setIsPaletteOpen(false);
			}
		};
		window.addEventListener("keydown", handler);
		return () => window.removeEventListener("keydown", handler);
	}, [isPaletteOpen]);

	const closeComposer = () => {
		setIsComposerOpen(false);
		setComposerConfirmOpen(false);
		setComposerDirty(false);
		composerSaveDraftRef.current = null;
	};

	return (
		<TooltipProvider delayDuration={200}>
			<SidebarProvider
				defaultOpen
				style={{ "--sidebar-width": APP_SIDEBAR_WIDTH } as React.CSSProperties}
			>
				<AppSidebar />
				<SidebarInset className="min-h-svh overflow-hidden bg-[var(--color-surface-frame)]">
					<a
						href="#main-content"
						className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:inline-flex focus:h-9 focus:items-center focus:rounded-md focus:bg-primary focus:px-4 focus:text-sm focus:font-medium focus:text-primary-foreground focus:outline-none"
					>
						Skip to main content
					</a>
					<header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 border-b border-border bg-[var(--color-surface-frame)] px-4">
						<SidebarTrigger className="shrink-0" />
						<Separator orientation="vertical" className="h-5" />
						<Breadcrumb className="min-w-0 flex-1">
							<BreadcrumbList className="flex-nowrap">
								<BreadcrumbItem className="min-w-0">
									{rootPath ? (
										<BreadcrumbLink asChild>
											<Button variant="ghost" size="sm" onClick={() => navigate(rootPath)} className="px-1">
												<span className="truncate">{root}</span>
											</Button>
										</BreadcrumbLink>
									) : (
										<span className="truncate text-sm text-muted-foreground">{root}</span>
									)}
								</BreadcrumbItem>
								<BreadcrumbSeparator />
								<BreadcrumbItem className="min-w-0">
									<BreadcrumbPage className="truncate text-sm font-medium">{current}</BreadcrumbPage>
								</BreadcrumbItem>
							</BreadcrumbList>
						</Breadcrumb>
						<div className="flex shrink-0 items-center gap-2">
							<Button
								type="button"
								variant="outline"
								size="sm"
								onClick={() => setIsPaletteOpen(true)}
								className="hidden min-w-56 justify-start gap-2 text-muted-foreground md:inline-flex"
								aria-label="Open command palette"
							>
								<Search data-icon="inline-start" aria-hidden="true" />
								<span className="truncate">Search or run command</span>
								<span className="ml-auto flex items-center gap-1">
									<Kbd>{isMacLike() ? "⌘" : "Ctrl"}</Kbd>
									<Kbd>K</Kbd>
								</span>
							</Button>
							<Button type="button" variant="ghost" size="icon" onClick={() => setIsHelpOpen(true)} aria-label="Keyboard shortcuts">
								<BookOpen aria-hidden="true" />
							</Button>
							<ThemeToggle />
							<Button type="button" variant="ghost" size="icon" onClick={() => setShowNotifications(true)} aria-label="Notifications" className="relative">
								<Bell aria-hidden="true" />
								{unreadTotalCount > 0 ? (
									<span className="absolute right-1.5 top-1.5 size-2 rounded-full bg-primary" aria-hidden="true" />
								) : null}
							</Button>
						</div>
					</header>
					<main ref={mainContentRef} id="main-content" aria-label="Page content" className="min-h-0 flex-1 overflow-y-auto bg-[var(--color-surface-frame)]">
						<ComposerContext.Provider
							value={{
								isOpen: isComposerOpen,
								open: () => setIsComposerOpen(true),
								close: closeComposer,
								requestClose: () => {
									if (composerDirty) setComposerConfirmOpen(true);
									else setIsComposerOpen(false);
								},
								setDirtyState: (dirty, saveDraft) => {
									setComposerDirty(dirty);
									composerSaveDraftRef.current = saveDraft ?? null;
								},
							}}
						>
							<ActivityContext.Provider
								value={{
									isOpen: showNotifications,
									open: () => setShowNotifications(true),
									close: () => setShowNotifications(false),
								}}
							>
								<div
									key={location.pathname}
									className={
										isComposerRoute
											? "min-h-full"
											: "min-h-full pb-[calc(6rem+env(safe-area-inset-bottom,0px))] md:pb-0"
									}
								>
									{children}
								</div>
							</ActivityContext.Provider>
						</ComposerContext.Provider>
					</main>
				</SidebarInset>

				{showNotifications ? (
					<ActivityPanel
						onClose={() => setShowNotifications(false)}
						readIds={readIds}
						setReadIds={setReadIds}
						deletedIds={deletedIds}
						setDeletedIds={setDeletedIds}
						notifications={notifications}
						notificationsError={notificationsError}
						stageNotificationReads={stageNotificationReads}
						stageNotificationDeletes={stageNotificationDeletes}
						rollbackNotificationReads={rollbackNotificationReads}
						rollbackNotificationDeletes={rollbackNotificationDeletes}
					/>
				) : null}

				{isPaletteOpen ? (
					<Suspense fallback={null}>
						<CommandPalette
							isOpen={isPaletteOpen}
							onClose={() => setIsPaletteOpen(false)}
							onNavigate={(route) => {
								setIsPaletteOpen(false);
								navigate(`/${route}`);
							}}
						/>
					</Suspense>
				) : null}

				{isHelpOpen ? (
					<Suspense fallback={null}>
						<ShortcutsHelp isOpen={isHelpOpen} onClose={() => setIsHelpOpen(false)} />
					</Suspense>
				) : null}

				<ComposerModal
					isOpen={isComposerOpen}
					onClose={() => {
						if (composerDirty) setComposerConfirmOpen(true);
						else setIsComposerOpen(false);
					}}
				/>
				<ConfirmDialog
					open={composerConfirmOpen}
					onClose={() => setComposerConfirmOpen(false)}
					busy={composerConfirmBusy}
					title="Unsaved changes"
					description="You have unsaved caption or media. Save as a draft first, or discard?"
					cancelLabel="Keep editing"
					confirmLabel="Discard"
					onConfirm={closeComposer}
					secondaryLabel="Save draft & close"
					onSecondary={async () => {
						const save = composerSaveDraftRef.current;
						setComposerConfirmBusy(true);
						try {
							if (save) await save();
						} finally {
							setComposerConfirmBusy(false);
							closeComposer();
						}
					}}
				/>
				<Toaster position="bottom-right" richColors />
				<OfflineBanner />
				{isComposerRoute ? null : <MobileTabBar />}
			</SidebarProvider>
		</TooltipProvider>
	);
}

function AppSidebar() {
	const location = useLocation();
	const navigate = useNavigate();
	const attention = useNeedsAttention();
	const scopedAccount = useAccountScopeStore((state) => state.scopedAccount);
	const clearScope = useAccountScopeStore((state) => state.clearScope);
	const clearGroupScope = useWorkspaceStore((state) => state.setSelectedGroupId);
	const currentWorkspace = useWorkspaceStore((state) => state.currentWorkspace);
	const resetWorkspace = useWorkspaceStore((state) => state.reset);
	const [isSigningOut, setIsSigningOut] = useState(false);

	const routeFor = (path: string) =>
		path === "/settings" ? path : mainSidebarRoute(path, { scopedAccount });

	const handleNav = (path: string) => {
		if (isFleetResetMainNavPath(path)) {
			clearScope();
			clearGroupScope(null);
		}
		navigate(routeFor(path));
	};

	const handleSignOut = async () => {
		if (isSigningOut) return;
		setIsSigningOut(true);
		try {
			const { error } = await supabase.auth.signOut();
			if (error) throw error;
			resetWorkspace();
			navigate("/login", { replace: true });
		} finally {
			setIsSigningOut(false);
		}
	};

	return (
		<Sidebar variant="inset" collapsible="icon">
			<SidebarHeader>
				<SidebarMenu>
					<SidebarMenuItem>
						<SidebarMenuButton asChild size="lg" tooltip="Juno33" className="text-[0.9375rem]">
							<Link to="/dashboard">
								<Sigil33 size={28} />
								<span className="min-w-0">
									<span className="block truncate font-semibold">Juno33</span>
									<span className="block truncate text-xs text-muted-foreground">
										{currentWorkspace?.name ?? "Workspace"}
									</span>
								</span>
							</Link>
						</SidebarMenuButton>
					</SidebarMenuItem>
				</SidebarMenu>
			</SidebarHeader>
			<SidebarContent>
				<SidebarGroup>
					<SidebarGroupLabel>Primary</SidebarGroupLabel>
					<SidebarGroupContent>
						<SidebarMenu>
							{PRIMARY_NAV.map((item) => (
								<AppSidebarItem
									key={item.path}
									item={item}
									active={isActivePath(location.pathname, item.path)}
									badge={item.badge === "attention" ? attention.totalCount : undefined}
									onNavigate={handleNav}
								/>
							))}
						</SidebarMenu>
					</SidebarGroupContent>
				</SidebarGroup>
				<SidebarSeparator />
				<SidebarGroup>
					<SidebarGroupLabel>More</SidebarGroupLabel>
					<SidebarGroupContent>
						<SidebarMenu>
							{SECONDARY_NAV.map((item) => (
								<AppSidebarItem
									key={item.path}
									item={item}
									active={isActivePath(location.pathname, item.path)}
									onNavigate={handleNav}
								/>
							))}
						</SidebarMenu>
					</SidebarGroupContent>
				</SidebarGroup>
			</SidebarContent>
			<SidebarFooter>
				<SidebarMenu>
					<SidebarMenuItem>
						<SidebarMenuButton
							asChild
							isActive={isActivePath(location.pathname, "/settings")}
							tooltip="Settings"
							className="text-[0.9375rem]"
						>
							<Link to="/settings">
								<SettingsIcon aria-hidden="true" />
								<span>Settings</span>
							</Link>
						</SidebarMenuButton>
					</SidebarMenuItem>
					<SidebarMenuItem>
						<DropdownMenuRoot>
							<DropdownMenuTrigger asChild>
								<SidebarMenuButton tooltip="Account" className="text-[0.9375rem]">
									<Menu aria-hidden="true" />
									<span>Account</span>
								</SidebarMenuButton>
							</DropdownMenuTrigger>
							<DropdownMenuContent side="right" align="end">
								<DropdownMenuLabel>{currentWorkspace?.name ?? "Workspace"}</DropdownMenuLabel>
								<DropdownMenuSeparator />
								{ACCOUNT_MENU_NAV.map((item) => {
									const Icon = item.path === "/billing" ? CreditCard : SettingsIcon;
									return (
										<DropdownMenuItem key={item.path} onSelect={() => navigate(item.path)}>
											<Icon aria-hidden="true" />
											{item.label}
										</DropdownMenuItem>
									);
								})}
								<DropdownMenuSeparator />
								<div className="px-1 py-1">
									<ThemeToggle variant="row" />
								</div>
								<DropdownMenuSeparator />
								<DropdownMenuItem destructive disabled={isSigningOut} onSelect={handleSignOut}>
									<LogOut aria-hidden="true" />
									{isSigningOut ? "Signing out..." : "Sign out"}
								</DropdownMenuItem>
							</DropdownMenuContent>
						</DropdownMenuRoot>
					</SidebarMenuItem>
				</SidebarMenu>
			</SidebarFooter>
			<SidebarRail />
		</Sidebar>
	);
}

function AppSidebarItem({
	item,
	active,
	badge,
	onNavigate,
}: {
	item: NavItem;
	active: boolean;
	badge?: number | undefined;
	onNavigate: (path: string) => void;
}) {
	const Icon = item.icon;
	return (
		<SidebarMenuItem>
			<SidebarMenuButton
				type="button"
				isActive={active}
				tooltip={item.label}
				onClick={() => onNavigate(item.path)}
				className="text-[0.9375rem]"
			>
				<Icon aria-hidden />
				<span>{item.label}</span>
			</SidebarMenuButton>
			{badge && badge > 0 ? <SidebarMenuBadge>{badge}</SidebarMenuBadge> : null}
		</SidebarMenuItem>
	);
}

function isActivePath(pathname: string, target: string) {
	if (target === "/dashboard") return pathname === "/" || pathname === "/dashboard";
	return pathname.startsWith(target);
}
