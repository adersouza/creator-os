// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useEffect } from "react";
import { create } from "zustand";
import type { UsageStats } from "@/services/subscriptionService";
import { supabase } from "@/services/supabase";
import { logger } from "@/utils/logger";

// Lazy-load heavy services to keep them out of the main chunk
const getTeamService = () =>
	import("@/services/teamService").then((m) => m.teamService);
const getSubscriptionService = () =>
	import("@/services/subscriptionService").then((m) => m.subscriptionService);

import {
	getEffectiveAccountLimit,
	hasPermission,
	isInGracePeriod,
	isTrialActive,
	type Permission,
	type SubscriptionTier,
	type TeamRole,
	TIER_LIMITS,
	type Workspace,
	type WorkspaceMember,
	type WorkspaceSubscription,
} from "@/types/team";

// Re-export PERMISSIONS for consumers that imported from WorkspaceContext
export { PERMISSIONS } from "@/types/team";

// Migrate old localStorage keys
if (typeof window !== "undefined") {
	const oldWs = localStorage.getItem("threadsdash-current-workspace");
	if (oldWs && !localStorage.getItem("juno33-current-workspace")) {
		localStorage.setItem("juno33-current-workspace", oldWs);
		localStorage.removeItem("threadsdash-current-workspace");
	}
	const oldGrp = localStorage.getItem("threadsdash-selected-group");
	if (oldGrp && !localStorage.getItem("juno33-selected-group")) {
		localStorage.setItem("juno33-selected-group", oldGrp);
		localStorage.removeItem("threadsdash-selected-group");
	}
}

const WORKSPACE_STORAGE_KEY = "juno33-current-workspace";
const GROUP_FILTER_STORAGE_KEY = "juno33-selected-group";
const MULTI_ACCOUNT_STORAGE_KEY = "juno33-selected-account-ids";
const LAST_SYNC_STORAGE_KEY = "juno33-last-sync";
// Tracks which user owns the persisted localStorage state, so we can
// detect stale data from a previous user session on init.
const WORKSPACE_USER_KEY = "juno33-workspace-user";
let refreshWorkspacesInFlight: Promise<Workspace[]> | null = null;
const selectWorkspaceInFlight = new Map<string, Promise<void>>();

interface WorkspaceState {
	// State
	currentWorkspace: Workspace | null;
	currentRole: TeamRole | null;
	members: WorkspaceMember[];
	workspaces: Workspace[];
	subscription: WorkspaceSubscription | null;
	usageStats: UsageStats | null;
	selectedGroupId: string | null;
	selectedAccountIds: string[];
	lastSyncedAt: string | null;
	isLoading: boolean;
	isInitialized: boolean;

	// Internal version counter for cancelling stale selectWorkspace calls
	_selectVersion: number;

	// Computed getters
	isTrialing: boolean;
	trialDaysRemaining: number;
	isInGrace: boolean;

	// Actions
	selectWorkspace: (workspaceId: string) => Promise<void>;
	createWorkspace: (name: string) => Promise<Workspace>;
	refreshWorkspaces: () => Promise<Workspace[]>;
	refreshMembers: () => Promise<void>;
	refreshUsageStats: () => Promise<void>;
	can: (permission: Permission) => boolean;
	canManageUser: (targetRole: TeamRole) => boolean;
	canAddAccount: () => Promise<{
		allowed: boolean;
		reason?: string | undefined;
		upsellTier?: SubscriptionTier | undefined;
	}>;
	canInviteMember: () => Promise<{
		allowed: boolean;
		reason?: string | undefined;
		upsellTier?: SubscriptionTier | undefined;
	}>;
	getEffectiveLimit: (type: "accounts" | "members") => number;
	setSelectedGroupId: (groupId: string | null) => void;
	setSelectedAccountIds: (ids: string[]) => void;
	toggleAccountSelection: (id: string) => void;
	setLastSyncedAt: (iso: string) => void;
	reset: () => void;
}

// Helper to compute derived subscription fields
function computeSubscriptionDerived(
	subscription: WorkspaceSubscription | null,
) {
	return {
		isTrialing: subscription ? isTrialActive(subscription) : false,
		isInGrace: subscription ? isInGracePeriod(subscription) : false,
		trialDaysRemaining: subscription?.trialEndAt
			? Math.max(
					0,
					Math.ceil(
						(new Date(subscription.trialEndAt).getTime() - Date.now()) /
							(1000 * 60 * 60 * 24),
					),
				)
			: 0,
	};
}

// Safely convert a potential Firestore Timestamp / string / Date to a Date
function toDate(value: unknown): Date | undefined {
	if (!value) return undefined;
	if (value instanceof Date) return value;
	if (
		typeof value === "object" &&
		value !== null &&
		"toDate" in value &&
		typeof (value as { toDate: unknown }).toDate === "function"
	) {
		return (value as { toDate: () => Date }).toDate();
	}
	if (typeof value === "string") return new Date(value);
	return undefined;
}

// Helper to convert raw subscription timestamps to Dates
function convertSubscriptionDates(
	rawSub: WorkspaceSubscription | null | undefined,
): WorkspaceSubscription | null {
	if (!rawSub) return null;
	return {
		...rawSub,
		trialEndAt: toDate(rawSub.trialEndAt),
		currentPeriodStart: toDate(rawSub.currentPeriodStart),
		currentPeriodEnd: toDate(rawSub.currentPeriodEnd),
		canceledAt: toDate(rawSub.canceledAt),
	};
}

const initialState = {
	currentWorkspace: null,
	currentRole: null,
	members: [],
	workspaces: [],
	subscription: null,
	usageStats: null,
	selectedGroupId:
		typeof window !== "undefined"
			? localStorage.getItem(GROUP_FILTER_STORAGE_KEY)
			: null,
	selectedAccountIds:
		typeof window !== "undefined"
			? (() => {
					try {
						const stored = localStorage.getItem(MULTI_ACCOUNT_STORAGE_KEY);
						return stored ? JSON.parse(stored) : [];
					} catch {
						return [];
					}
				})()
			: [],
	lastSyncedAt:
		typeof window !== "undefined"
			? localStorage.getItem(LAST_SYNC_STORAGE_KEY)
			: null,
	isLoading: true,
	isInitialized: false,
	_selectVersion: 0,
	isTrialing: false,
	trialDaysRemaining: 0,
	isInGrace: false,
};

export const useWorkspaceStore = create<WorkspaceState>()((set, get) => ({
	...initialState,

	setSelectedGroupId: (groupId: string | null) => {
		set({ selectedGroupId: groupId });
		if (groupId) {
			localStorage.setItem(GROUP_FILTER_STORAGE_KEY, groupId);
		} else {
			localStorage.removeItem(GROUP_FILTER_STORAGE_KEY);
		}
	},

	setSelectedAccountIds: (ids: string[]) => {
		set({ selectedAccountIds: ids });
		if (ids.length > 0) {
			localStorage.setItem(MULTI_ACCOUNT_STORAGE_KEY, JSON.stringify(ids));
		} else {
			localStorage.removeItem(MULTI_ACCOUNT_STORAGE_KEY);
		}
	},

	toggleAccountSelection: (id: string) => {
		const { selectedAccountIds } = get();
		const next = selectedAccountIds.includes(id)
			? selectedAccountIds.filter((x) => x !== id)
			: [...selectedAccountIds, id];
		set({ selectedAccountIds: next });
		if (next.length > 0) {
			localStorage.setItem(MULTI_ACCOUNT_STORAGE_KEY, JSON.stringify(next));
		} else {
			localStorage.removeItem(MULTI_ACCOUNT_STORAGE_KEY);
		}
	},

	setLastSyncedAt: (iso: string) => {
		set({ lastSyncedAt: iso });
		localStorage.setItem(LAST_SYNC_STORAGE_KEY, iso);
	},

	refreshWorkspaces: async () => {
		if (refreshWorkspacesInFlight) return refreshWorkspacesInFlight;
		refreshWorkspacesInFlight = (async () => {
		try {
			const userWorkspaces = await (await getTeamService()).getUserWorkspaces();
			set({ workspaces: userWorkspaces });
			return userWorkspaces;
		} catch (error) {
			logger.error("Failed to load workspaces:", error);
			return [];
		} finally {
			refreshWorkspacesInFlight = null;
		}
		})();
		return refreshWorkspacesInFlight;
	},

	refreshMembers: async () => {
		const { currentWorkspace } = get();
		if (!currentWorkspace) return;
		try {
			const workspaceMembers = await (
				await getTeamService()
			).getWorkspaceMembers(currentWorkspace.id);
			set({ members: workspaceMembers });
		} catch (error) {
			logger.error("Failed to load members:", error);
		}
	},

	refreshUsageStats: async () => {
		const { currentWorkspace } = get();
		if (!currentWorkspace) return;
		try {
			const stats = await (await getSubscriptionService()).getUsageStats(
				currentWorkspace.id,
			);
			set({ usageStats: stats });
		} catch (error) {
			logger.error("Failed to load usage stats:", error);
		}
	},

	selectWorkspace: async (workspaceId: string) => {
		const existing = selectWorkspaceInFlight.get(workspaceId);
		if (existing) return existing;
		const request = (async () => {
		// Increment version to cancel any in-flight previous selection
		const myVersion = ++get()._selectVersion;
		set({ _selectVersion: myVersion, isLoading: true });
		try {
			const teamService = await getTeamService();
			const workspace =
				get().workspaces.find((candidate) => candidate.id === workspaceId) ??
				(await teamService.getWorkspace(workspaceId));
			if (myVersion !== get()._selectVersion) return; // Superseded

			if (workspace) {
				const workspaceMembers = await teamService.getWorkspaceMembers(workspaceId);
				if (myVersion !== get()._selectVersion) return; // Superseded
				const {
					data: { session },
				} = await supabase.auth.getSession();
				if (myVersion !== get()._selectVersion) return; // Superseded
				const role =
					workspaceMembers.find((member) => member.userId === session?.user.id)
						?.role ?? null;
				const subscription = convertSubscriptionDates(workspace.subscription);

				set({
					currentWorkspace: workspace,
					currentRole: role,
					subscription,
					...computeSubscriptionDerived(subscription),
					members: workspaceMembers,
				});

				localStorage.setItem(WORKSPACE_STORAGE_KEY, workspaceId);

				// Load usage stats
				try {
					const stats = await (await getSubscriptionService()).getUsageStats(
						workspaceId,
						{ workspace, memberCount: workspaceMembers.length },
					);
					if (myVersion !== get()._selectVersion) return; // Superseded
					set({ usageStats: stats });
				} catch (e) {
					logger.error("Failed to load initial usage stats:", e);
				}
			}
		} catch (error) {
			logger.error("Failed to select workspace:", error);
			if (myVersion === get()._selectVersion) {
				set({
					currentWorkspace: null,
					currentRole: null,
					members: [],
					subscription: null,
					usageStats: null,
					isTrialing: false,
					trialDaysRemaining: 0,
					isInGrace: false,
				});
			}
		} finally {
			// Only clear loading if this is still the latest request
			if (myVersion === get()._selectVersion) {
				set({ isLoading: false });
			}
		}
		})();
		selectWorkspaceInFlight.set(workspaceId, request);
		try {
			await request;
		} finally {
			if (selectWorkspaceInFlight.get(workspaceId) === request) {
				selectWorkspaceInFlight.delete(workspaceId);
			}
		}
	},

	createWorkspace: async (name: string): Promise<Workspace> => {
		const workspace = await (await getTeamService()).createWorkspace(name);
		await get().refreshWorkspaces();
		await get().selectWorkspace(workspace.id);
		return workspace;
	},

	can: (permission: Permission): boolean => {
		const { currentRole } = get();
		if (!currentRole) return false;
		return hasPermission(currentRole, permission);
	},

	canManageUser: (targetRole: TeamRole): boolean => {
		const { currentRole } = get();
		if (!currentRole) return false;
		const roleHierarchy: Record<TeamRole, number> = {
			owner: 3,
			admin: 2,
			editor: 1,
		};
		return roleHierarchy[currentRole] > roleHierarchy[targetRole];
	},

	canAddAccount: async () => {
		const { currentWorkspace } = get();
		if (!currentWorkspace)
			return { allowed: false, reason: "No workspace selected" };
		return (await getSubscriptionService()).canAddAccount(currentWorkspace.id);
	},

	canInviteMember: async () => {
		const { currentWorkspace } = get();
		if (!currentWorkspace)
			return { allowed: false, reason: "No workspace selected" };
		return (await getSubscriptionService()).canInviteMember(
			currentWorkspace.id,
		);
	},

	getEffectiveLimit: (type: "accounts" | "members"): number => {
		const { currentWorkspace, subscription } = get();
		const tier = currentWorkspace?.subscriptionTier || "free";
		const addOns = subscription?.addOnsCount || 0;

		if (type === "accounts") {
			return getEffectiveAccountLimit(tier, addOns);
		}
		return TIER_LIMITS[tier].maxMembers;
	},

	reset: () => {
		set({
			currentWorkspace: null,
			currentRole: null,
			members: [],
			workspaces: [],
			subscription: null,
			usageStats: null,
			selectedGroupId: null,
			selectedAccountIds: [],
			lastSyncedAt: null,
			isLoading: false,
			isInitialized: true,
			_selectVersion: 0,
			isTrialing: false,
			trialDaysRemaining: 0,
			isInGrace: false,
		});
		localStorage.removeItem(GROUP_FILTER_STORAGE_KEY);
		localStorage.removeItem(MULTI_ACCOUNT_STORAGE_KEY);
		localStorage.removeItem(LAST_SYNC_STORAGE_KEY);
		localStorage.removeItem(WORKSPACE_USER_KEY);
	},
}));

// Init hook -- call once in App.tsx
export function useWorkspaceInit() {
	useEffect(() => {
		let mounted = true;
		let authSubscription: { unsubscribe: () => void } | null = null;
		let authStateReceived = false;

		const initializeWorkspace = async (userId: string | null) => {
			if (!mounted) return;
			const { refreshWorkspaces, selectWorkspace, createWorkspace, reset } =
				useWorkspaceStore.getState();

			if (userId) {
				// If the stored workspace data belongs to a different user, clear it
				// to prevent stale group/account selections leaking across sessions.
				const previousUser = localStorage.getItem(WORKSPACE_USER_KEY);
				if (previousUser && previousUser !== userId) {
					localStorage.removeItem(WORKSPACE_STORAGE_KEY);
					localStorage.removeItem(GROUP_FILTER_STORAGE_KEY);
					localStorage.removeItem(MULTI_ACCOUNT_STORAGE_KEY);
					useWorkspaceStore.setState({
						selectedGroupId: null,
						selectedAccountIds: [],
					});
				}
				localStorage.setItem(WORKSPACE_USER_KEY, userId);

				useWorkspaceStore.setState({ isLoading: true });
				try {
					const userWorkspaces = await refreshWorkspaces();

					if (!mounted) return;

					// Try to restore last selected workspace
					const savedWorkspaceId = localStorage.getItem(WORKSPACE_STORAGE_KEY);

					if (
						savedWorkspaceId &&
						userWorkspaces.some((w) => w.id === savedWorkspaceId)
					) {
						await selectWorkspace(savedWorkspaceId);
					} else if (userWorkspaces.length > 0) {
						// Prefer a workspace with a paid subscription over free ones
						const paidWorkspace = userWorkspaces.find(
							(w) => w.subscriptionTier && w.subscriptionTier !== "free",
						);
						const workspaceToSelect = paidWorkspace || userWorkspaces[0];
						await selectWorkspace(workspaceToSelect!.id);
					} else {
						// No workspaces - create default one
						await createWorkspace("My Workspace");
					}
				} catch (error) {
					logger.error("Failed to initialize workspace:", error);
				} finally {
					if (mounted) {
						useWorkspaceStore.setState({
							isLoading: false,
							isInitialized: true,
						});
					}
				}
			} else {
				reset();
			}
		};

		// Listen for Supabase auth changes
		// IMPORTANT: Do NOT use async callback - it breaks Supabase client after tab switching
		// See: https://github.com/orgs/supabase/discussions/17612
		const {
			data: { subscription },
		} = supabase.auth.onAuthStateChange((event, session) => {
			if (!mounted) return;
			logger.log("Supabase auth state changed:", event);
			// Fire and forget - don't await to avoid breaking Supabase client
			authStateReceived = true;
			initializeWorkspace(session?.user?.id || null);
		});
		authSubscription = subscription;

		// Fallback: check current session if onAuthStateChange hasn't fired yet
		// (avoids double-initialization race on page refresh)
		supabase.auth
			.getSession()
			.then(({ data: { session } }) => {
				if (mounted && !authStateReceived) {
					initializeWorkspace(session?.user?.id || null);
				}
			})
			.catch((error) => {
				logger.error("Failed to get session:", error);
				if (mounted) {
					useWorkspaceStore.setState({
						isLoading: false,
						isInitialized: true,
					});
				}
			});

		return () => {
			mounted = false;
			authSubscription?.unsubscribe();
		};
	}, []);
}
