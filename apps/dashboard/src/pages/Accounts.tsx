// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useCallback, useEffect, useMemo, useState } from "react";
import type React from "react";
import {
	AlertTriangle,
	CheckCircle2,
	Clock3,
	PauseCircle,
	Plus,
} from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { z } from "zod";
import { AccountBulkBar } from "@/components/accounts/AccountBulkBar";
import { AccountDetailSlideOver } from "@/components/accounts/AccountDetailSlideOver";
import { AccountGroupsRail } from "@/components/accounts/AccountGroupsRail";
import {
	AccountListView,
	Pagination,
} from "@/components/accounts/AccountListView";
import { AccountMapView } from "@/components/accounts/AccountMapView";
import { AccountMoveGroupModal } from "@/components/accounts/AccountMoveGroupModal";
import { AccountReconnectModal } from "@/components/accounts/AccountReconnectModal";
import { AccountsFilterBar } from "@/components/accounts/AccountsFilterBar";
import { AccountsHero } from "@/components/accounts/AccountsHero";
import { MobileAccounts } from "@/components/accounts/MobileAccounts";
import { useAccountHealthSignals } from "@/components/accounts/useAccountHealthSignals";
import {
	accountSignalStatus,
	hasTokenExpiringSignal,
	PAGE_SIZE,
	type GroupFilter,
	type PlatformFilter,
	type SortKey,
	type StatusFilter,
	UNASSIGNED_COLOR,
	type ViewMode,
} from "@/components/accounts/shared";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { NovaScreen } from "@/components/layout/NovaScreen";
import { Button } from "@/components/ui/Button";
import { NovaHeader } from "@/components/ui/NovaPrimitives";
import { PublishingReadinessPanel } from "@/components/publishing/PublishingReadinessPanel";
import { PublishingStartCard } from "@/components/publishing/PublishingStartCard";
import { useAccountGroups, type AccountGroup } from "@/hooks/useAccountGroups";
import {
	resetFleetAccountsCache,
	useFleetAccounts,
	type AccountHealth,
	type FleetAccount,
	type FleetAccountTotals,
	type FleetGroupMeta,
} from "@/hooks/useFleetAccounts";
import { useOnboardingState } from "@/hooks/useOnboardingState";
import { resetFleetMetricsCache } from "@/hooks/useFleetMetrics";
import { resetTopPostsCache } from "@/hooks/useTopPosts";
import { initiateInstagramLogin, initiateLogin } from "@/services/api/accounts";
import { apiFetch } from "@/lib/apiFetch";
import { queryClient } from "@/lib/queryClient";
import { queryKeys } from "@/lib/queryKeys";
import { scopedRoute } from "@/lib/scopedRoutes";
import { appToast } from "@/lib/toast";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import { useWorkspaceStore } from "@/stores/useWorkspaceStore";
import { supabase } from "@/services/supabase";
import { buildPublishingReadinessIssues } from "@/lib/publishingReadiness";
import { trackClientEvent } from "@/services/clientTelemetry";

const apiOkSchema = z.object({ success: z.boolean().optional() }).passthrough();

function optimisticHealthForActiveState(isActive: boolean): AccountHealth {
	return isActive ? "idle" : "offline";
}

function optimisticHealthScoreForActiveState(isActive: boolean): number {
	return isActive ? 78 : 44;
}

function isTyping(t: EventTarget | null): boolean {
	const el = t as HTMLElement | null;
	if (!el) return false;
	const tag = el.tagName;
	return tag === "INPUT" || tag === "TEXTAREA" || el.isContentEditable;
}

function AccountsDesktopHeader({
	totals,
	groupsCount,
	isLoading,
	status,
	onStatusChange,
	onAddAccount,
}: {
	totals: FleetAccountTotals;
	groupsCount: number;
	isLoading: boolean;
	status: StatusFilter;
	onStatusChange: (status: StatusFilter) => void;
	onAddAccount: () => void;
}) {
	return (
		<NovaHeader
			eyebrow="Fleet live"
			title="Accounts"
			meta="Fleet · live"
			description={
				isLoading
					? "Loading coverage."
					: `${totals.total} account${totals.total === 1 ? "" : "s"} across ${groupsCount} group${groupsCount === 1 ? "" : "s"}.`
			}
			actions={
				<>
					<StatusChip
						label="Active"
						value={totals.active}
						active={status === "active"}
						onClick={() =>
							onStatusChange(status === "active" ? "all" : "active")
						}
						icon={<CheckCircle2 className="h-3.5 w-3.5" />}
						tone="good"
					/>
					<StatusChip
						label="Flagged"
						value={totals.flagged}
						active={status === "flagged"}
						onClick={() =>
							onStatusChange(status === "flagged" ? "all" : "flagged")
						}
						icon={<AlertTriangle className="h-3.5 w-3.5" />}
						tone="bad"
					/>
					<StatusChip
						label="Drifting"
						value={totals.drifting}
						active={status === "drifting"}
						onClick={() =>
							onStatusChange(status === "drifting" ? "all" : "drifting")
						}
						icon={<Clock3 className="h-3.5 w-3.5" />}
						tone="warn"
					/>
					<StatusChip
						label="Inactive"
						value={totals.inactive}
						active={status === "inactive"}
						onClick={() =>
							onStatusChange(status === "inactive" ? "all" : "inactive")
						}
						icon={<PauseCircle className="h-3.5 w-3.5" />}
					/>
					<Button type="button" onClick={onAddAccount} size="sm">
						<Plus className="h-3.5 w-3.5" aria-hidden="true" />
						Add account
					</Button>
				</>
			}
		/>
	);
}

function StatusChip({
	label,
	value,
	active,
	tone,
	icon,
	onClick,
}: {
	label: string;
	value: number;
	active: boolean;
	tone?: "good" | "warn" | "bad" | undefined;
	icon: React.ReactNode;
	onClick: () => void;
}) {
	const toneColor =
		tone === "good"
			? "var(--color-health-good)"
			: tone === "warn"
				? "var(--color-gold)"
				: tone === "bad"
					? "var(--color-oxblood)"
					: "color-mix(in_srgb,var(--color-foreground)_42%,transparent)";
	return (
		<Button
			type="button"
			onClick={onClick}
			aria-pressed={active}
			variant={active ? "default" : "outline"}
			size="sm"
		>
			<span style={{ color: active ? "currentColor" : toneColor }}>{icon}</span>
			<span>{label}</span>
			<span className="font-mono text-[0.75rem] opacity-75">{value}</span>
		</Button>
	);
}

export function Accounts() {
	const navigate = useNavigate();
	const setScope = useAccountScopeStore((s) => s.setScope);
	const selectedGroupId = useWorkspaceStore((s) => s.selectedGroupId);
	const setSelectedGroupId = useWorkspaceStore((s) => s.setSelectedGroupId);
	const onboarding = useOnboardingState();
	const {
		accounts: rawAccounts,
		groups: fleetGroups,
		totals,
		isLoading,
	} = useFleetAccounts();
	const {
		groups: accountGroups,
		isLoading: accountGroupsLoading,
		createGroup,
		updateGroup,
		deleteGroup,
	} = useAccountGroups();
	const [searchParams] = useSearchParams();
	const [search, setSearch] = useState("");
	const [groupFilter, setGroupFilter] = useState<GroupFilter>("all");
	const [platform, setPlatform] = useState<PlatformFilter>("all");
	const [status, setStatus] = useState<StatusFilter>("all");
	const [sort, setSort] = useState<SortKey>("recent");
	const [view, setView] = useState<ViewMode>("list");
	const [tagFilter, setTagFilter] = useState("all");
	const [selected, setSelected] = useState<Set<string>>(new Set());
	const [openAccount, setOpenAccount] = useState<FleetAccount | null>(null);
	const [pendingRemoval, setPendingRemoval] = useState<FleetAccount[] | null>(
		null,
	);
	const [removalBusy, setRemovalBusy] = useState(false);
	const [focusedIndex, setFocusedIndex] = useState(-1);
	const [page, setPage] = useState(1);
	const [accountOverrides, setAccountOverrides] = useState<
		Record<string, Partial<FleetAccount>>
	>({});
	const [disconnectedIds, setDisconnectedIds] = useState<Set<string>>(
		new Set(),
	);

	const applyGroupFilter = useCallback(
		(id: GroupFilter) => {
			setGroupFilter(id);
			if (id === "all" || id === "unassigned") {
				setSelectedGroupId(null);
				return;
			}
			setScope(null);
			setSelectedGroupId(id);
		},
		[setScope, setSelectedGroupId],
	);
	const [moveGroupPickerOpen, setMoveGroupPickerOpen] = useState(false);
	const [moveGroupSelection, setMoveGroupSelection] = useState<string | null>(
		null,
	);
	const [reconnectOpen, setReconnectOpen] = useState(false);

	const invalidateAccountQueries = useCallback(async () => {
		resetFleetAccountsCache();
		resetFleetMetricsCache();
		resetTopPostsCache();
		await Promise.all([
			queryClient.invalidateQueries({ queryKey: queryKeys.accounts.connectedAll }),
			queryClient.invalidateQueries({ queryKey: queryKeys.accounts.groupsAll }),
			queryClient.invalidateQueries({ queryKey: queryKeys.onboarding.all }),
			queryClient.invalidateQueries({ queryKey: queryKeys.fleet.healthAll }),
			queryClient.invalidateQueries({ queryKey: queryKeys.posts.nextUpAll }),
			queryClient.invalidateQueries({ queryKey: queryKeys.posts.needsAttentionAll }),
		]);
	}, []);

	const groups = useMemo<FleetGroupMeta[]>(
		() =>
			!accountGroupsLoading
				? accountGroups.map((group) => ({
						id: group.id,
						name: group.name,
						color: group.color,
					}))
				: fleetGroups,
		[accountGroups, accountGroupsLoading, fleetGroups],
	);

	const accounts = useMemo(
		() =>
			rawAccounts
				.map((account) =>
					accountOverrides[account.id]
						? { ...account, ...accountOverrides[account.id] }
						: account,
				)
				.filter((account) => !disconnectedIds.has(account.id)),
		[rawAccounts, accountOverrides, disconnectedIds],
	);

	const { healthSignalsByAccount, refreshSignals } =
		useAccountHealthSignals(accounts);
	const publishingReadinessIssues = useMemo(
		() =>
			buildPublishingReadinessIssues({
				hasInstagramAccount: accounts.some(
					(account) => account.platform === "instagram",
				),
				hasTokenWarning: accounts.some((account) =>
					hasTokenExpiringSignal(healthSignalsByAccount.get(account.id)),
				),
				pushState: "unknown",
				pwaState: "desktop",
				instagramReady: false,
			}).map((issue) => {
				if (issue.id === "instagram-account")
					return { ...issue, action: () => navigate("/welcome") };
				if (issue.id === "token-health")
					return { ...issue, action: () => navigate("/welcome") };
				if (issue.id === "notify-push" || issue.id === "pwa-install")
					return {
						...issue,
						action: () => navigate("/settings/notifications"),
					};
				if (issue.id === "first-handoff")
					return { ...issue, action: () => navigate("/setup/publishing") };
				return issue;
			}),
		[accounts, healthSignalsByAccount, navigate],
	);

	const showEmpty =
		!isLoading &&
		onboarding.ready &&
		(accounts.length === 0 || !onboarding.hasConnectedAccounts);

	useEffect(() => {
		const nextId = searchParams.get("id");
		const nextGroup = searchParams.get("group") ?? searchParams.get("network");
		const nextStatus = searchParams.get("status");
		const nextPlatform = searchParams.get("platform");
		const nextHandle = searchParams.get("handle");
		const nextTag = searchParams.get("tag");

		const nextGroupFilter =
			nextGroup &&
			(nextGroup === "unassigned" ||
				groups.some((group) => group.id === nextGroup))
				? nextGroup
				: !nextGroup &&
						selectedGroupId &&
						groups.some((group) => group.id === selectedGroupId)
					? selectedGroupId
					: "all";
		setGroupFilter(nextGroupFilter);
		if (nextGroupFilter === "all" || nextGroupFilter === "unassigned") {
			if (nextGroup) setSelectedGroupId(null);
		} else {
			setScope(null);
			setSelectedGroupId(nextGroupFilter);
		}
		setStatus(
			nextStatus === "active" ||
				nextStatus === "drifting" ||
				nextStatus === "flagged" ||
				nextStatus === "inactive"
				? nextStatus
				: "all",
		);
		setPlatform(
			nextPlatform === "threads" || nextPlatform === "instagram"
				? nextPlatform
				: "all",
		);
		setTagFilter(nextTag ?? "all");
		setSearch(nextHandle ?? "");
		if (nextHandle || nextId) setView("list");
	}, [searchParams, groups, selectedGroupId, setScope, setSelectedGroupId]);

	const allTags = useMemo(
		() =>
			Array.from(new Set(accounts.flatMap((account) => account.tags))).sort(
				(a, b) => a.localeCompare(b),
			),
		[accounts],
	);

	const filtered = useMemo(() => {
		const q = search.trim().toLowerCase();
		const rows = accounts.filter((account) => {
			if (
				q &&
				!account.handle.toLowerCase().includes(q) &&
				!account.displayName.toLowerCase().includes(q)
			) {
				return false;
			}
			if (groupFilter === "unassigned" && account.groupId !== null)
				return false;
			if (
				groupFilter !== "all" &&
				groupFilter !== "unassigned" &&
				account.groupId !== groupFilter
			)
				return false;
			if (platform !== "all" && account.platform !== platform) return false;
			if (tagFilter !== "all" && !account.tags.includes(tagFilter))
				return false;
			if (
				status !== "all" &&
				accountSignalStatus(
					account.health,
					healthSignalsByAccount.get(account.id),
				) !== status
			) {
				return false;
			}
			return true;
		});
		rows.sort((a, b) => {
			if (sort === "followers") return b.followers - a.followers;
			if (sort === "health") return a.healthScore - b.healthScore;
			if (sort === "posts24h") return b.posts24h - a.posts24h;
			const aH = a.lastPostHoursAgo ?? Number.POSITIVE_INFINITY;
			const bH = b.lastPostHoursAgo ?? Number.POSITIVE_INFINITY;
			return aH - bH;
		});
		return rows;
	}, [
		accounts,
		groupFilter,
		healthSignalsByAccount,
		platform,
		search,
		sort,
		status,
		tagFilter,
	]);

	const filterKey = `${search}:${groupFilter}:${platform}:${status}:${sort}:${tagFilter}`;
	useEffect(() => {
		void filterKey;
		setPage(1);
	}, [filterKey]);

	const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
	const safePage = Math.min(page, pageCount);
	const paginated = filtered.slice(
		(safePage - 1) * PAGE_SIZE,
		safePage * PAGE_SIZE,
	);
	const rangeStart = filtered.length === 0 ? 0 : (safePage - 1) * PAGE_SIZE + 1;
	const rangeEnd = Math.min(safePage * PAGE_SIZE, filtered.length);

	const clearSelection = useCallback(() => setSelected(new Set()), []);
	const toggleSelect = useCallback((id: string) => {
		setSelected((prev) => {
			const next = new Set(prev);
			if (next.has(id)) next.delete(id);
			else next.add(id);
			return next;
		});
	}, []);

	const selectedRows = useMemo(
		() => accounts.filter((account) => selected.has(account.id)),
		[accounts, selected],
	);
	const selectedTokenExpiringRows = useMemo(
		() =>
			selectedRows.filter((account) =>
				hasTokenExpiringSignal(healthSignalsByAccount.get(account.id)),
			),
		[healthSignalsByAccount, selectedRows],
	);
	const selectedTaggableRows = useMemo(
		() => selectedRows.filter((account) => account.platform === "threads"),
		[selectedRows],
	);

	const updateAccountsActiveState = async (
		rows: FleetAccount[],
		nextIsActive: boolean,
	) => {
		if (rows.length === 0) return 0;
		const threadsIds = rows
			.filter((row) => row.platform === "threads")
			.map((row) => row.id);
		const instagramIds = rows
			.filter((row) => row.platform === "instagram")
			.map((row) => row.id);
		const updatedAt = new Date().toISOString();
		const [threadsRes, instagramRes] = await Promise.all([
			threadsIds.length
				? supabase
						.from("accounts")
						.update({
							is_active: nextIsActive,
							is_retired: false,
							updated_at: updatedAt,
						})
						.in("id", threadsIds)
				: Promise.resolve({ error: null }),
			instagramIds.length
				? supabase
						.from("instagram_accounts")
						.update({ is_active: nextIsActive, updated_at: updatedAt })
						.in("id", instagramIds)
				: Promise.resolve({ error: null }),
		]);
		if (threadsRes.error) throw threadsRes.error;
		if (instagramRes.error) throw instagramRes.error;
		setAccountOverrides((prev) => {
			const next = { ...prev };
			for (const row of rows) {
				next[row.id] = {
					...next[row.id],
					isActive: nextIsActive,
					health: optimisticHealthForActiveState(nextIsActive),
					healthScore: optimisticHealthScoreForActiveState(nextIsActive),
				};
			}
			return next;
		});
		await invalidateAccountQueries();
		return rows.length;
	};

	const pauseAccount = async (account: FleetAccount) => {
		const nextIsActive = !account.isActive;
		const pendingId = appToast.loading(
			nextIsActive
				? `Resuming ${account.handle}...`
				: `Pausing ${account.handle}...`,
		);
		try {
			await updateAccountsActiveState([account], nextIsActive);
			appToast.success(
				nextIsActive ? `${account.handle} resumed` : `${account.handle} paused`,
				{ id: pendingId },
			);
		} catch (error) {
			appToast.error("Could not update account state", {
				id: pendingId,
				description: error instanceof Error ? error.message : undefined,
			});
		}
	};

	const bulkPause = async () => {
		const rows = selectedRows.filter((account) => account.isActive);
		if (rows.length === 0) {
			appToast.info("Selected accounts are already paused.");
			clearSelection();
			return;
		}
		const pendingId = appToast.loading(
			`Pausing ${rows.length} account${rows.length === 1 ? "" : "s"}...`,
		);
		try {
			const updatedCount = await updateAccountsActiveState(rows, false);
			appToast.success(
				`Paused ${updatedCount} account${updatedCount === 1 ? "" : "s"}`,
				{ id: pendingId },
			);
			clearSelection();
		} catch (error) {
			appToast.error("Could not pause selected accounts", {
				id: pendingId,
				description: error instanceof Error ? error.message : undefined,
			});
		}
	};

	const bulkReschedule = () => {
		const handles = selectedRows.map((account) =>
			account.handle.replace(/^@/, ""),
		);
		const qs = new URLSearchParams({ bulk: "reschedule" });
		if (handles.length > 0) qs.set("accounts", handles.join(","));
		navigate(`/calendar?${qs.toString()}`);
	};

	const viewScheduler = useCallback(
		(account: FleetAccount) => {
			navigate(`/calendar?accountId=${encodeURIComponent(account.id)}`);
		},
		[navigate],
	);

	const viewAnalytics = useCallback(
		(account: FleetAccount) => {
			setScope({
				id: account.id,
				handle: account.handle,
				platform: account.platform,
			});
			navigate(scopedRoute("/analytics", { scopedAccount: account }));
		},
		[navigate, setScope],
	);

	const reconnectAccount = useCallback((account: FleetAccount) => {
		void (async () => {
			try {
				localStorage.setItem("juno33-oauth-source", "accounts");
				sessionStorage.setItem(
					"juno33:oauth-reconnect",
					JSON.stringify({
						accountId: account.id,
						platform: account.platform,
						returnTo: `/accounts?reconnect=${encodeURIComponent(account.id)}`,
					}),
				);
				const { authUrl } =
					account.platform === "instagram"
						? await initiateInstagramLogin({ forceReauth: true })
						: await initiateLogin();
				window.location.assign(authUrl);
			} catch (error) {
				appToast.error("Could not start reconnect", {
					description: error instanceof Error ? error.message : undefined,
				});
			}
		})();
	}, []);

	const syncGroupMembership = async (
		rows: FleetAccount[],
		nextGroupId: string | null,
		nextGroupName: string,
		nextGroupColor: string,
	) => {
		const {
			data: { user },
		} = await supabase.auth.getUser();
		if (!user) throw new Error("Not authenticated");
		const threadsIds = rows
			.filter((row) => row.platform === "threads")
			.map((row) => row.id);
		const instagramIds = rows
			.filter((row) => row.platform === "instagram")
			.map((row) => row.id);
		const [threadsRes, instagramRes] = await Promise.all([
			threadsIds.length
				? supabase
						.from("accounts")
						.update({
							group_id: nextGroupId,
							updated_at: new Date().toISOString(),
						})
						.eq("user_id", user.id)
						.in("id", threadsIds)
				: Promise.resolve({ error: null }),
			instagramIds.length
				? supabase
						.from("instagram_accounts")
						.update({
							group_id: nextGroupId,
							updated_at: new Date().toISOString(),
						})
						.eq("user_id", user.id)
						.in("id", instagramIds)
				: Promise.resolve({ error: null }),
		]);
		if (threadsRes.error) throw threadsRes.error;
		if (instagramRes.error) throw instagramRes.error;
		const movingIds = new Set(rows.map((row) => row.id));
		const affectedGroupIds = new Set<string>();
		for (const row of rows) {
			if (row.groupId) affectedGroupIds.add(row.groupId);
		}
		if (nextGroupId) affectedGroupIds.add(nextGroupId);
		if (affectedGroupIds.size > 0) {
			const updatedAt = new Date().toISOString();
			const membershipResults = await Promise.all(
				Array.from(affectedGroupIds).map((groupId) => {
					const accountIds = accounts
						.filter((account) => {
							const effectiveGroupId = movingIds.has(account.id)
								? nextGroupId
								: account.groupId;
							return effectiveGroupId === groupId;
						})
						.map((account) => account.id);
					return supabase
						.from("account_groups")
						.update({ account_ids: accountIds, updated_at: updatedAt })
						.eq("id", groupId)
						.eq("user_id", user.id);
				}),
			);
			const membershipError = membershipResults.find(
				(result) => result.error,
			)?.error;
			if (membershipError) throw membershipError;
		}
		setAccountOverrides((prev) => {
			const next = { ...prev };
			for (const row of rows) {
				next[row.id] = {
					...next[row.id],
					groupId: nextGroupId,
					groupName: nextGroupName,
					groupColor: nextGroupColor,
				};
			}
			return next;
		});
		return rows.length;
	};

	const commitBulkMoveGroup = async () => {
		if (selectedRows.length === 0) {
			setMoveGroupPickerOpen(false);
			return;
		}
		const targetGroup = moveGroupSelection
			? (groups.find((group) => group.id === moveGroupSelection) ?? null)
			: null;
		setMoveGroupPickerOpen(false);
		const pendingId = appToast.loading(
			targetGroup
				? `Moving accounts to ${targetGroup.name}...`
				: "Unassigning accounts...",
		);
		try {
			const updatedCount = await syncGroupMembership(
				selectedRows,
				targetGroup?.id ?? null,
				targetGroup?.name ?? "Unassigned",
				targetGroup?.color ?? UNASSIGNED_COLOR,
			);
			appToast.success(
				`Updated ${updatedCount} account${updatedCount === 1 ? "" : "s"}`,
				{ id: pendingId },
			);
			clearSelection();
			await invalidateAccountQueries();
		} catch (error) {
			appToast.error("Could not move selected accounts", {
				id: pendingId,
				description: error instanceof Error ? error.message : undefined,
			});
		}
	};

	const moveSelectedToGroup = async (targetGroup: FleetGroupMeta) => {
		if (selectedRows.length === 0) return;
		const pendingId = appToast.loading(
			`Moving accounts to ${targetGroup.name}...`,
		);
		try {
			const updatedCount = await syncGroupMembership(
				selectedRows,
				targetGroup.id,
				targetGroup.name,
				targetGroup.color,
			);
			appToast.success(
				`Moved ${updatedCount} account${updatedCount === 1 ? "" : "s"} to ${targetGroup.name}`,
				{ id: pendingId },
			);
			clearSelection();
			await invalidateAccountQueries();
		} catch (error) {
			appToast.error("Could not move selected accounts", {
				id: pendingId,
				description: error instanceof Error ? error.message : undefined,
			});
		}
	};

	const unassignSelected = async () => {
		if (selectedRows.length === 0) return;
		const pendingId = appToast.loading(
			`Unassigning ${selectedRows.length} account${selectedRows.length === 1 ? "" : "s"}...`,
		);
		try {
			const updatedCount = await syncGroupMembership(
				selectedRows,
				null,
				"Unassigned",
				UNASSIGNED_COLOR,
			);
			appToast.success(
				`Unassigned ${updatedCount} account${updatedCount === 1 ? "" : "s"}`,
				{ id: pendingId },
			);
			clearSelection();
			await invalidateAccountQueries();
		} catch (error) {
			appToast.error("Could not unassign selected accounts", {
				id: pendingId,
				description: error instanceof Error ? error.message : undefined,
			});
		}
	};

	const createAccountGroup = async (input: {
		name: string;
		color: string;
		accountIds: string[];
	}): Promise<AccountGroup | null> => {
		const created = await createGroup(input);
		if (created && input.accountIds.length > 0) {
			setAccountOverrides((prev) => {
				const next = { ...prev };
				for (const row of selectedRows) {
					next[row.id] = {
						...next[row.id],
						groupId: created.id,
						groupName: created.name,
						groupColor: created.color,
					};
				}
				return next;
			});
			clearSelection();
		}
		await invalidateAccountQueries();
		return created;
	};

	const updateAccountGroup = async (input: {
		id: string;
		name: string;
		color: string;
	}): Promise<AccountGroup | null> => {
		const updated = await updateGroup(input);
		if (updated) {
			setAccountOverrides((prev) => {
				const next = { ...prev };
				for (const account of accounts) {
					if (account.groupId !== updated.id) continue;
					next[account.id] = {
						...next[account.id],
						groupName: updated.name,
						groupColor: updated.color,
					};
				}
				return next;
			});
		}
		await invalidateAccountQueries();
		return updated;
	};

	const deleteAccountGroup = async (id: string) => {
		await deleteGroup(id);
		setAccountOverrides((prev) => {
			const next = { ...prev };
			for (const account of accounts) {
				if (account.groupId !== id) continue;
				next[account.id] = {
					...next[account.id],
					groupId: null,
					groupName: "Unassigned",
					groupColor: UNASSIGNED_COLOR,
				};
			}
			return next;
		});
		if (groupFilter === id) applyGroupFilter("all");
		await invalidateAccountQueries();
	};

	const syncAccounts = async (rows: FleetAccount[]) => {
		if (rows.length === 0) return;
		const pendingId = appToast.loading(
			`Syncing ${rows.length} account${rows.length === 1 ? "" : "s"}...`,
		);
		try {
			await apiFetch("/api/accounts?action=bulk-sync", apiOkSchema, {
				method: "POST",
				json: { accountIds: rows.map((account) => account.id) },
			});
			appToast.success(
				rows.length === 1
					? `Sync queued for ${rows[0]!.handle}`
					: "Bulk sync queued",
				{ id: pendingId },
			);
			await invalidateAccountQueries();
		} catch (error) {
			appToast.error("Sync failed", {
				id: pendingId,
				description: error instanceof Error ? error.message : undefined,
			});
		}
	};

	const bulkSync = async () => {
		await syncAccounts(selectedRows);
		clearSelection();
	};

	const healthCheckAccounts = async (rows: FleetAccount[]) => {
		if (rows.length === 0) return;
		const pendingId = appToast.loading(
			`Checking ${rows.length} account${rows.length === 1 ? "" : "s"}...`,
		);
		try {
			await Promise.all(
				rows.map((account) =>
					apiFetch("/api/health?action=ping", apiOkSchema, {
						method: "POST",
						json: { accountId: account.id, platform: account.platform },
					}),
				),
			);
			refreshSignals();
			appToast.success("Health check complete", { id: pendingId });
		} catch (error) {
			appToast.error("Health check failed", {
				id: pendingId,
				description: error instanceof Error ? error.message : undefined,
			});
		}
	};

	const bulkHealthCheck = async () => {
		await healthCheckAccounts(selectedRows);
	};

	const addTagToSelected = async (tag: string) => {
		const normalized = tag
			.trim()
			.toLowerCase()
			.replace(/[^a-z0-9_-]/g, "");
		if (!normalized) return;
		const threadRows = selectedRows.filter(
			(account) => account.platform === "threads",
		);
		if (threadRows.length === 0) {
			appToast.warn("Tags are only stored for Threads accounts right now.");
			return;
		}
		const pendingId = appToast.loading(`Adding #${normalized}...`);
		try {
			const updates = await Promise.all(
				threadRows.map((account) => {
					const tags = Array.from(
						new Set([...(account.tags ?? []), normalized]),
					);
					return supabase
						.from("accounts")
						.update({ tags, updated_at: new Date().toISOString() })
						.eq("id", account.id);
				}),
			);
			const error = updates.find((result) => result.error)?.error;
			if (error) throw error;
			setAccountOverrides((prev) => {
				const next = { ...prev };
				for (const account of threadRows) {
					next[account.id] = {
						...next[account.id],
						tags: Array.from(new Set([...(account.tags ?? []), normalized])),
					};
				}
				return next;
			});
			appToast.success(
				`Added #${normalized} to ${threadRows.length} account${threadRows.length === 1 ? "" : "s"}`,
				{ id: pendingId },
			);
		} catch (error) {
			appToast.error("Could not add tag", {
				id: pendingId,
				description: error instanceof Error ? error.message : undefined,
			});
		}
	};

	const executeRemoval = async () => {
		const rows = pendingRemoval;
		if (!rows?.length) return;
		const {
			data: { user },
		} = await supabase.auth.getUser();
		if (!user) {
			appToast.error("Not authenticated");
			return;
		}
		setRemovalBusy(true);
		const pendingId = appToast.loading(
			`Removing ${rows.length} account${rows.length === 1 ? "" : "s"}...`,
		);
		try {
			await syncGroupMembership(rows, null, "Unassigned", UNASSIGNED_COLOR);
			const [threadsRes, instagramRes] = await Promise.all([
				rows.some((row) => row.platform === "threads")
					? supabase
							.from("accounts")
							.update({
								is_active: false,
								is_retired: true,
								group_id: null,
								updated_at: new Date().toISOString(),
							})
							.eq("user_id", user.id)
							.in(
								"id",
								rows
									.filter((row) => row.platform === "threads")
									.map((row) => row.id),
							)
					: Promise.resolve({ error: null }),
				rows.some((row) => row.platform === "instagram")
					? supabase
							.from("instagram_accounts")
							.update({
								is_active: false,
								group_id: null,
								updated_at: new Date().toISOString(),
							})
							.eq("user_id", user.id)
							.in(
								"id",
								rows
									.filter((row) => row.platform === "instagram")
									.map((row) => row.id),
							)
					: Promise.resolve({ error: null }),
			]);
			if (threadsRes.error) throw threadsRes.error;
			if (instagramRes.error) throw instagramRes.error;
			setDisconnectedIds(
				(prev) => new Set([...prev, ...rows.map((row) => row.id)]),
			);
			await invalidateAccountQueries();
			clearSelection();
			setOpenAccount((prev) =>
				prev && rows.some((row) => row.id === prev.id) ? null : prev,
			);
			appToast.success(
				`Removed ${rows.length} account${rows.length === 1 ? "" : "s"}`,
				{ id: pendingId },
			);
			setPendingRemoval(null);
		} catch (error) {
			appToast.error("Could not remove selected accounts", {
				id: pendingId,
				description: error instanceof Error ? error.message : undefined,
			});
		} finally {
			setRemovalBusy(false);
		}
	};

	useEffect(() => {
		const onKey = (event: KeyboardEvent) => {
			if (event.key === "Escape") {
				if (openAccount) setOpenAccount(null);
				else if (selected.size > 0) clearSelection();
				else setFocusedIndex(-1);
				return;
			}
			if (isTyping(event.target)) return;
			if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "a") {
				event.preventDefault();
				if (view === "list")
					setSelected(new Set(filtered.map((account) => account.id)));
				return;
			}
			if (view !== "list") return;
			if (event.key === "j" || event.key === "ArrowDown") {
				event.preventDefault();
				setFocusedIndex((index) =>
					Math.min(filtered.length - 1, index < 0 ? 0 : index + 1),
				);
			} else if (event.key === "k" || event.key === "ArrowUp") {
				event.preventDefault();
				setFocusedIndex((index) => Math.max(0, index - 1));
			} else if (focusedIndex >= 0 && focusedIndex < filtered.length) {
				const row = filtered[focusedIndex];
				if (event.key === " ") {
					event.preventDefault();
					setOpenAccount(row!);
				} else if (event.key.toLowerCase() === "x") {
					event.preventDefault();
					toggleSelect(row!.id);
				} else if (event.key.toLowerCase() === "e") {
					event.preventDefault();
					navigate(`/calendar?accountId=${encodeURIComponent(row!.id)}`);
				}
			}
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, [
		clearSelection,
		filtered,
		focusedIndex,
		navigate,
		openAccount,
		selected.size,
		toggleSelect,
		view,
	]);

	useEffect(() => {
		if (focusedIndex >= filtered.length) setFocusedIndex(-1);
	}, [filtered.length, focusedIndex]);

	useEffect(() => {
		const nextId = searchParams.get("id");
		const nextHandle = searchParams.get("handle");
		if (!nextHandle && !nextId) return;
		const normalizedHandle = nextHandle?.toLowerCase();
		const target = filtered.find(
			(account) =>
				account.id === nextId ||
				(normalizedHandle != null &&
					account.handle.toLowerCase() === normalizedHandle),
		);
		if (target) setOpenAccount(target);
	}, [filtered, searchParams]);

	useEffect(() => {
		const reconnect = searchParams.get("reconnect");
		if (!reconnect || accounts.length === 0) return;
		const normalized = reconnect.toLowerCase().replace(/^@/, "");
		const target = accounts.find(
			(account) =>
				account.id === reconnect ||
				account.handle.toLowerCase().replace(/^@/, "") === normalized,
		);
		if (!target) return;
		setStatus("flagged");
		setOpenAccount(target);
		appToast.warn(`${target.handle} needs to reconnect`, {
			description: "Token expired - sign in again to resume publishing.",
			action: {
				label: "Reconnect",
				onClick: () => reconnectAccount(target),
			},
			duration: 12000,
		});
	}, [accounts, reconnectAccount, searchParams]);

	return (
		<>
			<MobileAccounts
				accounts={filtered}
				allAccounts={accounts}
				totals={totals}
				groups={groups}
				groupsCount={groups.length}
				isLoading={isLoading}
				status={status}
				selected={selected}
				selectedRows={selectedRows}
				onToggleSelect={toggleSelect}
				onClearSelect={clearSelection}
				onStatusChange={setStatus}
				onCreateGroup={createAccountGroup}
				onUpdateGroup={updateAccountGroup}
				onDeleteGroup={deleteAccountGroup}
				onFilterGroup={(id) => applyGroupFilter(id as GroupFilter)}
				onMoveSelectedToGroup={moveSelectedToGroup}
				onUnassignSelected={unassignSelected}
				onOpen={setOpenAccount}
				onPause={(account) => void pauseAccount(account)}
				onViewScheduler={viewScheduler}
				onViewAnalytics={viewAnalytics}
				onMoveGroup={(account) => {
					setSelected(new Set([account.id]));
					setMoveGroupSelection(account.groupId ?? null);
					setMoveGroupPickerOpen(true);
				}}
				onSync={(account) => void syncAccounts([account])}
				onHealthCheck={(account) => void healthCheckAccounts([account])}
				onReconnect={reconnectAccount}
				onRemove={(account) => setPendingRemoval([account])}
				onAddAccount={() => navigate("/welcome")}
			/>
			<NovaScreen
				width="full"
				density="compact"
				className="hidden md:block"
			>
				{showEmpty ? (
					<div className="flex flex-col gap-3">
						<AccountsHero
							totals={totals}
							groupsCount={groups.length}
							isLoading={isLoading}
							status={status}
							showEmpty={showEmpty}
							onStatusChange={setStatus}
							onAddAccount={() => navigate("/welcome")}
						/>
						<PublishingStartCard surface="accounts_empty" />
					</div>
				) : (
					<div className="w-full pb-10">
						<AccountsDesktopHeader
							totals={totals}
							groupsCount={groups.length}
							isLoading={isLoading}
							status={status}
							onStatusChange={setStatus}
							onAddAccount={() => navigate("/welcome")}
						/>
						<div className="mb-4">
							<PublishingReadinessPanel
								issues={publishingReadinessIssues}
								compact
								onIssueAction={(issue) =>
									trackClientEvent("account_readiness_action_clicked", {
										issue_id: issue.id,
										state: issue.state,
										surface: "accounts",
									})
								}
							/>
						</div>
						<div className="grid items-start gap-4 xl:grid-cols-[286px_minmax(0,1fr)]">
							<AccountGroupsRail
								groups={groups}
								accounts={accounts}
								selectedRows={selectedRows}
								activeGroup={groupFilter}
								onCreateGroup={createAccountGroup}
								onUpdateGroup={updateAccountGroup}
								onDeleteGroup={deleteAccountGroup}
								onFilterGroup={applyGroupFilter}
								onMoveSelectedToGroup={moveSelectedToGroup}
								onUnassignSelected={unassignSelected}
							/>
							<main className="min-w-0">
								<div className="sticky top-0 z-20 -mx-1 mb-3 rounded-lg border border-border bg-card px-3 pt-3 pb-2 shadow-sm">
									<AccountsFilterBar
										search={search}
										groupFilter={groupFilter}
										platform={platform}
										status={status}
										sort={sort}
										view={view}
										tags={allTags}
										tagFilter={tagFilter}
										groups={[]}
										onSearchChange={setSearch}
										onGroupFilterChange={applyGroupFilter}
										onPlatformChange={setPlatform}
										onStatusChange={setStatus}
										onSortChange={setSort}
										onViewChange={setView}
										onTagFilterChange={setTagFilter}
									/>
									<div className="flex items-center justify-between gap-3 text-[0.71875rem] font-medium uppercase tracking-[0.06em] text-muted-foreground tabular-nums">
										<span>
											{view === "list"
												? `Showing ${rangeStart}-${rangeEnd} of ${filtered.length}`
												: `Showing ${filtered.length} of ${totals.total}`}
										</span>
										{selected.size > 0 && (
											<span className="text-foreground">
												{selected.size} selected
											</span>
										)}
									</div>
								</div>

								{view === "list" ? (
									<AccountListView
										accounts={paginated}
										selected={selected}
										focusedIndex={focusedIndex}
										healthSignalsByAccount={healthSignalsByAccount}
										onToggleSelect={toggleSelect}
										onOpen={setOpenAccount}
										onFocusRow={setFocusedIndex}
										onPause={pauseAccount}
										onViewScheduler={viewScheduler}
										onViewAnalytics={viewAnalytics}
										onMoveGroup={(account) => {
											setSelected(new Set([account.id]));
											setMoveGroupSelection(account.groupId ?? null);
											setMoveGroupPickerOpen(true);
										}}
										onSync={(account) => void syncAccounts([account])}
										onHealthCheck={(account) =>
											void healthCheckAccounts([account])
										}
										onReconnect={reconnectAccount}
										onRemove={(account) => setPendingRemoval([account])}
										isLoading={isLoading}
									/>
								) : (
									<AccountMapView
										accounts={filtered}
										groups={groups}
										healthSignalsByAccount={healthSignalsByAccount}
										onOpen={setOpenAccount}
									/>
								)}
								{view === "list" && pageCount > 1 && (
									<Pagination
										page={safePage}
										pageCount={pageCount}
										onChange={setPage}
									/>
								)}
							</main>
						</div>
					</div>
				)}
			</NovaScreen>

			{selected.size > 0 && (
				<AccountBulkBar
					count={selected.size}
					tokenExpiringCount={selectedTokenExpiringRows.length}
					taggableCount={selectedTaggableRows.length}
					onClear={clearSelection}
					onBulkPause={bulkPause}
					onBulkReschedule={bulkReschedule}
					onBulkMoveGroup={() => {
						setMoveGroupSelection(groupFilter !== "all" ? groupFilter : null);
						setMoveGroupPickerOpen(true);
					}}
					onBulkRemove={() => setPendingRemoval(selectedRows)}
					onBulkSync={() => void bulkSync()}
					onBulkHealthCheck={() => void bulkHealthCheck()}
					onFixTokens={() => setReconnectOpen(true)}
					onAddTag={(tag) => void addTagToSelected(tag)}
				/>
			)}

			{openAccount && (
				<AccountDetailSlideOver
					account={openAccount}
					signals={healthSignalsByAccount.get(openAccount.id) ?? []}
					onSignalsRefresh={refreshSignals}
					onClose={() => setOpenAccount(null)}
					onViewInScheduler={() => {
						const target = openAccount;
						setOpenAccount(null);
						viewScheduler(target);
					}}
					onViewAnalytics={() => {
						const target = openAccount;
						setOpenAccount(null);
						viewAnalytics(target);
					}}
					onPause={() => {
						void pauseAccount(openAccount);
						setOpenAccount(null);
					}}
					onMoveGroup={() => {
						const target = openAccount;
						setOpenAccount(null);
						setSelected(new Set([target.id]));
						setMoveGroupSelection(target.groupId ?? null);
						setMoveGroupPickerOpen(true);
					}}
					onSync={() => void syncAccounts([openAccount])}
					onReconnect={() => reconnectAccount(openAccount)}
					onRemove={() => {
						setPendingRemoval([openAccount]);
						setOpenAccount(null);
					}}
				/>
			)}

			<AccountReconnectModal
				open={reconnectOpen}
				accounts={selectedTokenExpiringRows}
				onClose={() => setReconnectOpen(false)}
			/>
			<ConfirmDialog
				open={pendingRemoval !== null}
				onClose={() => {
					if (!removalBusy) setPendingRemoval(null);
				}}
				onConfirm={executeRemoval}
				title={`Remove ${pendingRemoval?.length ?? 0} account${(pendingRemoval?.length ?? 0) === 1 ? "" : "s"}?`}
				description="This disconnects them and stops all scheduled posting. You can reconnect any account later from Welcome."
				confirmLabel={removalBusy ? "Removing..." : "Remove"}
				destructive
				busy={removalBusy}
			/>
			<AccountMoveGroupModal
				open={moveGroupPickerOpen}
				count={selected.size}
				groups={groups}
				selection={moveGroupSelection}
				onSelectionChange={setMoveGroupSelection}
				onClose={() => {
					setMoveGroupPickerOpen(false);
					setMoveGroupSelection(null);
				}}
				onConfirm={() => void commitBulkMoveGroup()}
			/>
		</>
	);
}
