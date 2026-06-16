// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import type React from "react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
	User as UserIcon,
	Bell,
	Building2,
	Palette,
	Blocks,
	Key,
	Webhook,
	FlaskConical,
	ShieldCheck,
	ShieldAlert,
	AlertTriangle,
	LogOut,
	Zap,
	ScrollText,
	MessageSquare,
	Activity,
} from "lucide-react";
import { appToast } from "@/lib/toast";
import { supabase } from "@/services/supabase";
import { useTablistKeyboardNav } from "@/hooks/useTablistKeyboardNav";
import {
	getUserSetting,
	upsertUserSetting,
} from "@/services/userSettingsService";
import { NovaScreen } from "@/components/layout/NovaScreen";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { FormSection } from "@/components/ui/FormSection";
import { Input } from "@/components/ui/Input";
import {
	NovaCard,
	NovaHeader,
	NovaSection,
	NovaToolbar,
} from "@/components/ui/NovaPrimitives";
import { Separator } from "@/components/ui/Separator";
import { Slider } from "@/components/ui/Slider";
import { Switch } from "@/components/ui/Switch";
import { cn } from "@/lib/utils";
import { useAuthUser } from "@/hooks/useAuthUser";
import { useWorkspaceStore } from "@/stores/useWorkspaceStore";
import {
	deleteWorkspace as deleteWorkspaceService,
	transferOwnership as transferOwnershipService,
} from "@/services/teamService";
import { SectionHeader } from "../components/settings/shared";
import { NotificationsTabContent } from "../components/settings/NotificationsTabContent";
import { ConnectionsTabContent } from "../components/settings/ConnectionsTabContent";
import { APITabContent } from "../components/settings/APITabContent";
import { WebhooksTabContent } from "../components/settings/WebhooksTabContent";
import { VoiceProfilesEditorTab } from "../components/settings/VoiceProfilesEditorTab";
import {
	WhiteLabelTabContent,
	WorkspaceTabContent,
} from "../components/settings/WorkspaceTabContent";
import { SecurityTabContent } from "../components/settings/SecurityTabContent";
import { ProfileTab } from "../components/settings/ProfileTabContent";
import { AppearanceTab } from "../components/settings/AppearanceTabContent";
import {
	LabsTab,
	DataTab,
	AuditTab,
	UxHealthTab,
} from "../components/settings/AdminTabsContent";

type TabId =
	| "profile"
	| "appearance"
	| "notifications"
	| "security"
	| "workspace"
	| "whitelabel"
	| "connections"
	| "voice"
	| "autopilot"
	| "api"
	| "webhooks"
	| "labs"
	| "ux-health"
	| "audit"
	| "data"
	| "danger";

interface TabDef {
	id: TabId;
	label: string;
	icon: React.ComponentType<{ className?: string | undefined }>;
	/** When set, renders a small badge next to the label in the sidebar. */
	badge?: "soon" | undefined;
}

interface TabGroup {
	label: string;
	tabs: TabDef[];
}

const GROUPS: TabGroup[] = [
	{
		label: "You",
		tabs: [
			{ id: "profile", label: "Profile", icon: UserIcon },
			{ id: "appearance", label: "Appearance", icon: Palette },
			{ id: "notifications", label: "Notifications", icon: Bell },
			{ id: "security", label: "Security", icon: ShieldCheck },
		],
	},
	{
		label: "Workspace",
		tabs: [
			{ id: "workspace", label: "Preferences", icon: Building2 },
			{ id: "whitelabel", label: "White-label", icon: Palette },
			{ id: "connections", label: "Connections", icon: Blocks },
			{ id: "voice", label: "Voice profiles", icon: MessageSquare },
			{ id: "autopilot", label: "Automation", icon: Zap },
		],
	},
	{
		label: "Developer",
		tabs: [
			{ id: "api", label: "API keys", icon: Key },
			{ id: "webhooks", label: "Webhooks", icon: Webhook },
		],
	},
	{
		label: "Privacy",
		tabs: [
			{ id: "data", label: "Data & privacy", icon: ShieldCheck },
		],
	},
];

const CONTEXTUAL_TABS: TabDef[] = [
	{ id: "labs", label: "Beta labs", icon: FlaskConical },
	{ id: "audit", label: "Audit log", icon: ScrollText },
	{ id: "danger", label: "Danger zone", icon: ShieldAlert },
	{ id: "ux-health", label: "UX health", icon: Activity },
];

const VISIBLE_TABS: TabDef[] = GROUPS.flatMap((g) => g.tabs);
const ALL_TABS: TabDef[] = [...VISIBLE_TABS, ...CONTEXTUAL_TABS];

/* ============================================================================
   Autopilot — enable / approval threshold / cooldown
   ========================================================================= */

function AutopilotTab() {
	const AUTOPILOT_SETTINGS_KEY = "autopilot_preferences";
	const _authUser = useAuthUser();
	const [enabled, setEnabled] = useState(false);
	const [threshold, setThreshold] = useState(85); // % confidence required for auto-approve
	const [cooldownHours, setCooldownHours] = useState(6);
	const [hydrated, setHydrated] = useState(false);
	const [saving, setSaving] = useState(false);

	interface AutopilotSettingsValue {
		enabled?: boolean | undefined;
		threshold?: number | undefined;
		cooldownHours?: number | undefined;
	}

	useEffect(() => {
		let cancelled = false;
		(async () => {
			const {
				data: { user },
			} = await supabase.auth.getUser();
			if (!user || cancelled) {
				setHydrated(true);
				return;
			}
			const data = await getUserSetting(user.id, AUTOPILOT_SETTINGS_KEY).catch(
				() => null,
			);
			if (cancelled) return;
			if (data && typeof data === "object" && !Array.isArray(data)) {
				const settings = data as AutopilotSettingsValue;
				if (typeof settings.enabled === "boolean") setEnabled(settings.enabled);
				if (typeof settings.threshold === "number")
					setThreshold(settings.threshold);
				if (typeof settings.cooldownHours === "number")
					setCooldownHours(settings.cooldownHours);
			}
			setHydrated(true);
		})();
		return () => {
			cancelled = true;
		};
	}, []);

	const persist = async (patch: Partial<AutopilotSettingsValue>) => {
		const {
			data: { user },
		} = await supabase.auth.getUser();
		if (!user) return;
		setSaving(true);
		try {
			await upsertUserSetting(user.id, AUTOPILOT_SETTINGS_KEY, {
				enabled,
				threshold,
				cooldownHours,
				...patch,
			});
		} catch (err) {
			appToast.error("Could not save automation settings", {
				description:
					err instanceof Error ? err.message : "Try again in a moment.",
			});
		} finally {
			setSaving(false);
		}
	};

	return (
		<div className="flex w-full flex-col gap-6">
			<SectionHeader
				title="Automation"
				description="Let Juno33 publish approved drafts, reply to safe comments, and pause underperforming accounts automatically. You stay in control — set the confidence bar and the cooldown."
			/>

			<FormSection>
				<div className="flex items-start justify-between gap-6">
					<div className="flex-1 min-w-0">
						<div className="text-[0.8125rem] font-medium text-foreground">
							Enable automation
						</div>
						<p className="mt-1 text-[0.78125rem] text-muted-foreground leading-[1.55]">
							Master switch. When off, Automation will not take any action —
							scheduled posts still publish on their own schedule, but nothing
							is auto-generated, auto-approved, or auto-paused.
						</p>
					</div>
					<Switch
						checked={enabled}
						onCheckedChange={(v) => {
							setEnabled(v);
							void persist({ enabled: v });
						}}
						disabled={!hydrated}
						className="mt-1"
					/>
				</div>
			</FormSection>

			<FormSection
				className={cn(
					"transition-opacity",
					!enabled && "opacity-50 pointer-events-none",
				)}
				contentClassName="flex flex-col gap-5"
			>
				<div>
					<div className="flex items-baseline justify-between gap-4">
						<div>
							<div className="text-[0.8125rem] font-medium text-foreground">
								Approval threshold
							</div>
							<p className="mt-1 text-[0.78125rem] text-muted-foreground leading-[1.55] max-w-[480px]">
								Minimum confidence score required for Automation to act without
								asking. Below this, items land in your approval queue.
							</p>
						</div>
						<div className="text-[1.25rem] font-semibold text-foreground tabular-nums">
							{threshold}%
						</div>
					</div>
					<Slider
						min={50}
						max={99}
						step={1}
						value={[threshold]}
						onValueChange={(value) => setThreshold(value[0] ?? threshold)}
						onValueCommit={(value) =>
							void persist({ threshold: value[0] ?? threshold })
						}
						className="mt-3"
					/>
					<div className="flex items-center justify-between text-[0.65625rem] text-muted-foreground tabular-nums mt-1">
						<span>50% · aggressive</span>
						<span>75% · balanced</span>
						<span>99% · cautious</span>
					</div>
				</div>

				<Separator />
				<div>
					<div className="flex items-baseline justify-between gap-4">
						<div>
							<div className="text-[0.8125rem] font-medium text-foreground">
								Cooldown between actions
							</div>
							<p className="mt-1 text-[0.78125rem] text-muted-foreground leading-[1.55] max-w-[480px]">
								Minimum hours between automated actions on the same account.
								Protects against unnatural posting cadence that trips Meta's
								spam filters.
							</p>
						</div>
						<div className="flex items-baseline gap-2">
							<Input
								type="number"
								min={1}
								max={48}
								value={cooldownHours}
								onChange={(e) =>
									setCooldownHours(
										Math.max(
											1,
											Math.min(48, parseInt(e.target.value || "0", 10)),
										),
									)
								}
								onBlur={() => void persist({ cooldownHours })}
								sizeVariant="sm"
								className="w-16 text-right"
							/>
							<span className="text-[0.78125rem] text-muted-foreground">
								hours
							</span>
						</div>
					</div>
				</div>
			</FormSection>

			<div className="text-[0.71875rem] text-muted-foreground tabular-nums">
				{!hydrated
					? "Loading…"
					: saving
						? "Saving…"
						: enabled
							? "Automation is active."
							: "Automation is off — all actions require manual approval."}
			</div>
		</div>
	);
}

/* ============================================================================
   Danger zone
   ========================================================================= */

function DangerZone() {
	const authUser = useAuthUser();
	const navigate = useNavigate();
	const currentWorkspace = useWorkspaceStore((s) => s.currentWorkspace);
	const members = useWorkspaceStore((s) => s.members);
	const refreshMembers = useWorkspaceStore((s) => s.refreshMembers);
	const refreshWorkspaces = useWorkspaceStore((s) => s.refreshWorkspaces);
	const selectWorkspace = useWorkspaceStore((s) => s.selectWorkspace);
	const resetWorkspaceStore = useWorkspaceStore((s) => s.reset);
	const [deleteInput, setDeleteInput] = useState("");
	const [transferEmail, setTransferEmail] = useState("");
	const [deleting, setDeleting] = useState(false);
	const [transferring, setTransferring] = useState(false);
	const [confirmSignOutAll, setConfirmSignOutAll] = useState(false);
	const [confirmTransfer, setConfirmTransfer] = useState(false);
	const [confirmDelete, setConfirmDelete] = useState(false);
	const [pendingTransferMember, setPendingTransferMember] = useState<{
		userId: string;
		displayName?: string | null | undefined;
		email?: string | null | undefined;
	} | null>(null);
	const deleteConfirmPhrase = "delete my workspace";
	const canDelete =
		deleteInput.trim().toLowerCase() === deleteConfirmPhrase && !deleting;

	const signOutAll = () => setConfirmSignOutAll(true);
	const runSignOutAll = async () => {
		setConfirmSignOutAll(false);
		try {
			await supabase.auth.signOut({ scope: "global" });
		} catch {
			/* ignore */
		}
	};

	const transferOwnership = () => {
		if (!transferEmail.trim() || transferring) return;
		if (!currentWorkspace?.id) {
			appToast.error("No workspace selected.");
			return;
		}
		const normalizedEmail = transferEmail.trim().toLowerCase();
		const nextOwner = members.find(
			(member) => member.email?.trim().toLowerCase() === normalizedEmail,
		);
		if (!nextOwner) {
			appToast.error("That email is not a member of this workspace.", {
				description: "Transfer ownership only works for an existing member.",
			});
			return;
		}
		setPendingTransferMember({
			userId: nextOwner.userId,
			displayName: nextOwner.displayName,
			email: nextOwner.email,
		});
		setConfirmTransfer(true);
	};

	const runTransferOwnership = async () => {
		if (!currentWorkspace?.id || !pendingTransferMember) return;
		setConfirmTransfer(false);
		setTransferring(true);
		try {
			await transferOwnershipService(
				currentWorkspace.id,
				pendingTransferMember.userId,
			);
			await Promise.all([refreshMembers(), refreshWorkspaces()]);
			await selectWorkspace(currentWorkspace.id);
			setTransferEmail("");
			appToast.success("Ownership transferred", {
				description: `${pendingTransferMember.displayName || pendingTransferMember.email || "The selected member"} is now the workspace owner.`,
			});
		} catch (err) {
			const description =
				err instanceof Error ? err.message : "Could not transfer ownership.";
			appToast.error("Transfer failed", { description });
		} finally {
			setPendingTransferMember(null);
			setTransferring(false);
		}
	};

	const deleteWorkspace = () => {
		if (!canDelete) return;
		if (!currentWorkspace?.id) {
			appToast.error("No workspace selected.");
			return;
		}
		setConfirmDelete(true);
	};

	const runDeleteWorkspace = async () => {
		if (!currentWorkspace?.id) return;
		setConfirmDelete(false);
		setDeleting(true);
		try {
			await deleteWorkspaceService(currentWorkspace.id);
			const remaining = await refreshWorkspaces();
			if (remaining.length > 0) {
				await selectWorkspace(remaining[0]!.id);
			} else {
				resetWorkspaceStore();
				navigate("/dashboard", { replace: true });
			}
			appToast.success("Workspace deleted", {
				description:
					remaining.length > 0
						? `Switched to ${remaining[0]!.name}.`
						: "This workspace has been removed.",
			});
		} catch (err) {
			const description =
				err instanceof Error ? err.message : "Deletion failed.";
			appToast.error("Could not delete workspace", { description });
		} finally {
			setDeleteInput("");
			setDeleting(false);
		}
	};

	return (
		<div className="flex flex-col gap-6">
			<SectionHeader
				title="Danger zone"
				description="Destructive actions affecting your whole workspace. Read carefully before confirming."
			/>

			{/* Sign out everywhere */}
			<NovaCard
				className="border-[color-mix(in_srgb,var(--color-oxblood)_18%,var(--color-border))]"
				contentClassName="flex items-start gap-4"
			>
				<span
					className="w-9 h-9 rounded-md flex items-center justify-center shrink-0"
					style={{
						backgroundColor:
							"color-mix(in srgb, var(--color-oxblood) 10%, transparent)",
						color: "var(--color-oxblood)",
					}}
				>
					<LogOut className="w-4 h-4" />
				</span>
				<div className="flex-1 min-w-0">
					<div className="text-[0.84375rem] font-medium text-foreground">
						Sign out everywhere
					</div>
					<p className="text-[0.75rem] text-muted-foreground mt-0.5 max-w-[52ch] leading-relaxed">
						Force logout on every device signed in to{" "}
						<span className="text-muted-foreground">
							{authUser?.email ?? "your account"}
						</span>
						. Use this if you think a session is compromised.
					</p>
					<Button
						type="button"
						onClick={signOutAll}
						variant="outline"
						size="sm"
						className="mt-3 text-[color:var(--color-oxblood)] hover:border-[color:var(--color-oxblood)]"
					>
						Sign out all sessions
					</Button>
				</div>
			</NovaCard>

			{/* Transfer ownership */}
			<NovaCard
				className="border-[color-mix(in_srgb,var(--color-oxblood)_18%,var(--color-border))]"
				contentClassName="flex items-start gap-4"
			>
				<span
					className="w-9 h-9 rounded-md flex items-center justify-center shrink-0"
					style={{
						backgroundColor:
							"color-mix(in srgb, var(--color-oxblood) 10%, transparent)",
						color: "var(--color-oxblood)",
					}}
				>
					<UserIcon className="w-4 h-4" />
				</span>
				<div className="flex-1 min-w-0">
					<div className="text-[0.84375rem] font-medium text-foreground">
						Transfer ownership
					</div>
					<p className="text-[0.75rem] text-muted-foreground mt-0.5 max-w-[52ch] leading-relaxed">
						Hand this workspace off to another admin. You'll keep Admin access;
						they'll become Owner. Billing responsibility transfers with
						ownership.
					</p>
					<div className="mt-3 flex flex-col sm:flex-row gap-2">
							<Input
								type="email"
								placeholder="admin@agency.com"
								value={transferEmail}
								onChange={(e) => setTransferEmail(e.target.value)}
								className="sm:max-w-[280px]"
							/>
						<Button
							type="button"
							onClick={transferOwnership}
							disabled={!transferEmail.trim() || transferring}
							variant="outline"
							size="sm"
							className="whitespace-nowrap text-[color:var(--color-oxblood)] hover:border-[color:var(--color-oxblood)]"
						>
							{transferring ? "Transferring…" : "Transfer ownership"}
						</Button>
					</div>
				</div>
			</NovaCard>

			{/* Delete workspace */}
			<NovaCard
				className="border-[color-mix(in_srgb,var(--color-oxblood)_30%,var(--color-border))] bg-[color-mix(in_srgb,var(--color-oxblood)_3%,var(--color-card))]"
				contentClassName="flex items-start gap-4"
			>
				<span
					className="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground"
				>
					<AlertTriangle data-icon="inline-start" aria-hidden="true" />
				</span>
				<div className="flex-1 min-w-0">
					<div className="text-[0.84375rem] font-semibold text-foreground">
						Delete workspace
					</div>
					<p className="text-[0.75rem] text-muted-foreground mt-0.5 max-w-[52ch] leading-relaxed">
						Permanently delete this workspace, its team access, activity log,
						alerts, autopilot queues, and workspace-level configuration.
						Personal account connections and user-owned posts are not deleted
						here. This action is immediate and cannot be reversed.
					</p>
					<div className="mt-3">
						<label
							htmlFor="delete-workspace-confirm"
							className="block text-[0.71875rem] font-medium text-muted-foreground mb-1.5"
						>
							Type{" "}
							<span className="font-mono text-foreground">
								{deleteConfirmPhrase}
							</span>{" "}
							to confirm
						</label>
						<div className="flex flex-col sm:flex-row gap-2">
							<Input
								id="delete-workspace-confirm"
								type="text"
								value={deleteInput}
								onChange={(e) => setDeleteInput(e.target.value)}
								placeholder={deleteConfirmPhrase}
								disabled={deleting}
								className={cn("sm:max-w-[280px] font-mono", deleting && "opacity-60")}
							/>
							<Button
								type="button"
								onClick={() => void deleteWorkspace()}
								disabled={!canDelete}
								variant="danger"
								size="sm"
								className="whitespace-nowrap"
							>
								{deleting ? "Deleting…" : "Delete workspace permanently"}
							</Button>
						</div>
					</div>
				</div>
			</NovaCard>

			<ConfirmDialog
				open={confirmSignOutAll}
				onClose={() => setConfirmSignOutAll(false)}
				onConfirm={runSignOutAll}
				title="Sign out everywhere?"
				description="Sign out all active sessions on every device, including this one?"
				confirmLabel="Sign out everywhere"
				destructive
			/>
			<ConfirmDialog
				open={confirmTransfer}
				onClose={() => {
					setConfirmTransfer(false);
					setPendingTransferMember(null);
				}}
				onConfirm={runTransferOwnership}
				title="Transfer ownership?"
				description={`Transfer ownership to ${pendingTransferMember?.email || transferEmail}? You'll be downgraded to Admin.`}
				confirmLabel="Transfer ownership"
				destructive
				busy={transferring}
			/>
			<ConfirmDialog
				open={confirmDelete}
				onClose={() => setConfirmDelete(false)}
				onConfirm={runDeleteWorkspace}
				title="Delete workspace permanently?"
				description="Final confirmation — this deletes the workspace, its team access, activity, alerts, autopilot queues, and workspace-level links/config. Personal account connections and user-owned posts are not deleted here. It cannot be undone."
				confirmLabel="Delete workspace"
				destructive
				busy={deleting}
			/>
		</div>
	);
}

/* ============================================================================
   Shell
   ========================================================================= */

const TAB_RENDER: Record<TabId, () => React.ReactElement> = {
	profile: ProfileTab,
	appearance: AppearanceTab,
	notifications: NotificationsTabContent,
	security: SecurityTabContent,
	workspace: WorkspaceTabContent,
	whitelabel: WhiteLabelTabContent,
	connections: ConnectionsTabContent,
	voice: VoiceProfilesEditorTab,
	autopilot: AutopilotTab,
	api: APITabContent,
	webhooks: WebhooksTabContent,
	labs: LabsTab,
	"ux-health": UxHealthTab,
	audit: AuditTab,
	data: DataTab,
	danger: DangerZone,
};

const LAST_PANE_KEY = "juno33-settings-last-pane";

function readLastPane(): TabId | null {
	if (typeof localStorage === "undefined") return null;
	const raw = localStorage.getItem(LAST_PANE_KEY);
	return VISIBLE_TABS.find((t) => t.id === raw)?.id ?? null;
}

export function Settings() {
	const params = useParams<{ tab?: string | undefined }>();
	const navigate = useNavigate();
	const tabFromUrl = ALL_TABS.find((t) => t.id === params.tab)?.id;
	// No tab in URL → restore last visited (or default to profile).
	const initialTab: TabId = tabFromUrl ?? readLastPane() ?? "profile";
	const [active, setActiveState] = useState<TabId>(initialTab);

	// If the user hit /settings bare, rewrite the URL so refresh + back-button
	// both land on the same pane they're looking at.
	useEffect(() => {
		if (!tabFromUrl) {
			navigate(`/settings/${initialTab}`, { replace: true });
		}
	}, [initialTab, tabFromUrl, navigate]); // eslint-disable-line react-hooks/exhaustive-deps

	// Sync URL → state when the deep link changes
	useEffect(() => {
		if (tabFromUrl && tabFromUrl !== active) setActiveState(tabFromUrl);
	}, [tabFromUrl, active]); // eslint-disable-line react-hooks/exhaustive-deps

	const setActive = (next: TabId) => {
		setActiveState(next);
		navigate(`/settings/${next}`, { replace: true });
	};

	const activeTab = useMemo(
		() => ALL_TABS.find((t) => t.id === active),
		[active],
	);
	const activeTabIsVisible = useMemo(
		() => VISIBLE_TABS.some((t) => t.id === active),
		[active],
	);
	const contextualActiveTab =
		activeTab && !activeTabIsVisible ? activeTab : null;
	const visibleTabIds = useMemo(() => VISIBLE_TABS.map((t) => t.id), []);
	const desktopTabIds = useMemo(
		() =>
			contextualActiveTab
				? [...visibleTabIds, contextualActiveTab.id]
				: visibleTabIds,
		[contextualActiveTab, visibleTabIds],
	);
	const mobileTabs = useMemo(
		() =>
			contextualActiveTab
				? [contextualActiveTab, ...VISIBLE_TABS]
				: VISIBLE_TABS,
		[contextualActiveTab],
	);
	const mobileTabIds = useMemo(() => mobileTabs.map((t) => t.id), [mobileTabs]);
	const onTablistKey = useTablistKeyboardNav({
		ids: desktopTabIds,
		activeId: active,
		onNavigate: (id) => setActive(id as TabId),
		orientation: "vertical",
		scopeSelector: '[data-tablist="settings-desktop"]',
	});
	const onMobileTablistKey = useTablistKeyboardNav({
		ids: mobileTabIds,
		activeId: active,
		onNavigate: (id) => setActive(id as TabId),
		orientation: "horizontal",
		scopeSelector: '[data-tablist="settings-mobile"]',
	});

	const ActiveComponent = TAB_RENDER[active];

	// Keep document.title + last-pane memory in sync with the active tab.
	useEffect(() => {
		if (!activeTab) return;
		document.title = `${activeTab.label} · Juno33 Settings`;
		if (activeTabIsVisible && typeof localStorage !== "undefined") {
			localStorage.setItem(LAST_PANE_KEY, active);
		}
		return () => {
			document.title = "Juno33";
		};
	}, [active, activeTab, activeTabIsVisible]);

	return (
		<NovaScreen className="settings-page flex-col md:flex-row min-h-full" width="full" density="compact">
			{/* Desktop sidebar */}
			<nav
				role="tablist"
				aria-orientation="vertical"
				aria-label="Settings sections"
				data-tablist="settings-desktop"
				onKeyDown={onTablistKey}
				className="hidden md:flex w-[232px] shrink-0 border-r border-border flex-col py-5 px-3 gap-4 sticky top-12 self-start max-h-[calc(100dvh-48px)] overflow-y-auto scroll-edge-fade"
			>
				{GROUPS.map((g) => (
					<div key={g.label}>
						<div className="px-2.5 mb-1.5 text-[0.6875rem] font-medium text-muted-foreground">
							{g.label}
						</div>
						<div className="flex flex-col gap-0.5">
							{g.tabs.map((t) => {
								const isActive = active === t.id;
								return (
									<Button
										type="button"
										key={t.id}
										id={`settings-tab-${t.id}`}
										role="tab"
										aria-selected={isActive}
										aria-controls={`settings-panel-${t.id}`}
										data-tab-id={t.id}
										tabIndex={isActive ? 0 : -1}
										onClick={() => setActive(t.id)}
										className={cn(
											"relative flex h-8 w-full items-center justify-start gap-2.5 rounded-full px-2.5 text-left text-[0.78125rem]",
											"outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood-strong)]",
											isActive
												? "bg-[color-mix(in_srgb,var(--color-oxblood)_10%,transparent)] text-[var(--color-oxblood)] shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--color-oxblood)_20%,transparent)]"
												: "text-muted-foreground hover:text-foreground hover:bg-muted",
										)}
										variant="ghost"
										size="sm"
									>
										<t.icon
											className={cn(
												"w-3.5 h-3.5 shrink-0",
												isActive
													? "text-[var(--color-oxblood)]"
													: "text-muted-foreground",
											)}
										/>
										<span className="truncate flex-1">{t.label}</span>
										{t.badge === "soon" && (
											<span
												className="h-[15px] px-1.5 rounded-full text-[0.5625rem] font-semibold uppercase tracking-[0.1em] inline-flex items-center shrink-0"
												style={{
													color: "var(--color-oxblood)",
													backgroundColor:
														"color-mix(in srgb, var(--color-oxblood) 12%, transparent)",
												}}
											>
												Soon
											</span>
										)}
									</Button>
								);
							})}
						</div>
					</div>
				))}
				{contextualActiveTab ? (
					<div>
						<div className="px-2.5 mb-1.5 text-[0.6875rem] font-medium text-muted-foreground">
							Direct link
						</div>
						<div className="flex flex-col gap-0.5">
							<Button
								type="button"
								key={contextualActiveTab.id}
								id={`settings-tab-${contextualActiveTab.id}`}
								role="tab"
								aria-selected
								aria-controls={`settings-panel-${contextualActiveTab.id}`}
								data-tab-id={contextualActiveTab.id}
								tabIndex={0}
								onClick={() => setActive(contextualActiveTab.id)}
								className={cn(
									"relative flex h-8 w-full items-center justify-start gap-2.5 rounded-full px-2.5 text-left text-[0.78125rem]",
									"bg-[color-mix(in_srgb,var(--color-oxblood)_10%,transparent)] text-[var(--color-oxblood)] shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--color-oxblood)_20%,transparent)]",
									"outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood-strong)]",
								)}
								variant="ghost"
								size="sm"
							>
								<contextualActiveTab.icon className="w-3.5 h-3.5 shrink-0 text-[var(--color-oxblood)]" />
								<span className="truncate flex-1">{contextualActiveTab.label}</span>
							</Button>
							<Button
								type="button"
								onClick={() => setActive("profile")}
								className="h-8 justify-start rounded-full px-2.5 text-[0.78125rem]"
								variant="ghost"
								size="sm"
							>
								Back to Settings
							</Button>
						</div>
					</div>
				) : null}
			</nav>

			{/* Mobile horizontal tabs */}
			<nav
				role="tablist"
				aria-label="Settings sections"
				data-tablist="settings-mobile"
				onKeyDown={onMobileTablistKey}
				className="flex md:hidden overflow-x-auto gap-1 px-3 py-2 border-b border-border hide-scrollbar shrink-0 sticky top-0 z-10 bg-background/95 backdrop-blur-[8px]"
			>
				{mobileTabs.map((t) => {
					const isActive = active === t.id;
					return (
						<Button
							type="button"
							key={t.id}
							id={`settings-tab-mobile-${t.id}`}
							role="tab"
							aria-selected={isActive}
							aria-controls={`settings-panel-${t.id}`}
							data-tab-id={t.id}
							tabIndex={isActive ? 0 : -1}
							onClick={() => setActive(t.id)}
							className={cn(
								"shrink-0 inline-flex h-11 items-center gap-1.5 rounded-md px-3.5 text-[0.78125rem] whitespace-nowrap",
								"outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)]",
								isActive
									? "bg-foreground text-background"
									: "text-muted-foreground bg-muted",
							)}
							variant="ghost"
							size="md"
						>
							<t.icon className="w-3.5 h-3.5" />
							{t.label}
						</Button>
					);
				})}
			</nav>

			{/* Panel — section, not main, since Layout already provides <main>. */}
			<section
				id={`settings-panel-${active}`}
				role="tabpanel"
				aria-labelledby={`settings-tab-${active}`}
				className="flex-1 min-w-0 px-4 md:px-10 py-6 md:py-10"
			>
				<NovaSection key={active} className="w-full">
					<NovaHeader
						eyebrow="Settings"
						title={activeTab?.label ?? "Settings"}
						meta={activeTab?.label ?? "Preferences"}
						description={
							<>
								<strong className="font-semibold text-foreground">
									Workspace controls and operator preferences.
								</strong>{" "}
								Configure the surface, security, connected services, and
								developer access from one place.
							</>
						}
						filters={
							<NovaToolbar>
								<Badge tone="outline">{active}</Badge>
								<Badge
									tone={
										active === "danger"
											? "danger"
											: activeTabIsVisible
												? "secondary"
												: "outline"
									}
								>
									{active === "danger"
										? "destructive"
										: activeTabIsVisible
											? "config"
											: "direct link"}
								</Badge>
							</NovaToolbar>
						}
					/>
					<ActiveComponent />
				</NovaSection>
			</section>
		</NovaScreen>
	);
}
