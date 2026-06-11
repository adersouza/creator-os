// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Team Service - Supabase operations for workspaces and team management
 */

import { subscribe } from "@/services/realtimeManager.js";
import {
	type ActivityAction,
	type ActivityLogEntry,
	type TeamRole,
	TIER_LIMITS,
	type Workspace,
	type WorkspaceInvite,
	type WorkspaceMember,
} from "../types/team.js";
import logger from "@/utils/logger";
import { supabase } from "./supabase.js";

// Helper to get current user ID for Supabase
const getSupabaseUserId = async (): Promise<string | null> => {
	const {
		data: { session },
	} = await supabase.auth.getSession();
	return session?.user?.id || null;
};

// Helper to get current user details for Supabase
const getSupabaseUserDetails = async (): Promise<{
	id: string;
	email: string;
	displayName: string;
} | null> => {
	const {
		data: { session },
	} = await supabase.auth.getSession();
	if (!session?.user) return null;
	return {
		id: session.user.id,
		email: session.user.email || "",
		displayName:
			session.user.user_metadata?.display_name ||
			session.user.email?.split("@")[0] ||
			"",
	};
};

// Generate unique invite code using cryptographically secure random values
const generateInviteCode = (): string => {
	const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789";
	const array = new Uint8Array(8);
	crypto.getRandomValues(array);
	let code = "";
	for (let i = 0; i < 8; i++) {
		code += chars.charAt(array[i]! % chars.length);
	}
	return code;
};

// ==================== WORKSPACE OPERATIONS ====================

export const createWorkspace = async (name: string): Promise<Workspace> => {
	const user = await getSupabaseUserDetails();
	if (!user) throw new Error("Not authenticated");

	// Create workspace
	const { data: workspace, error: workspaceError } = await supabase
		.from("workspaces")
		.insert({
			name,
			owner_id: user.id,
			tier: "free",
		})
		.select()
		.maybeSingle();

	if (workspaceError) throw workspaceError;
	if (!workspace) throw new Error("Failed to create workspace");

	// Add owner as member
	const { error: memberError } = await supabase
		.from("workspace_members")
		.insert({
			workspace_id: workspace.id,
			user_id: user.id,
			role: "owner",
			invited_by: user.id,
			display_name: user.displayName,
			email: user.email,
		});

	if (memberError) throw memberError;

	// Log activity
	await supabase.from("workspace_activity").insert({
		workspace_id: workspace.id,
		action: "workspace_created",
		user_id: user.id,
		user_name: user.displayName || user.email,
		details: { workspaceName: name },
		// biome-ignore lint/suspicious/noExplicitAny: Supabase insert type narrowing
	} as any);

	// Note: user_workspaces is a VIEW based on workspace_members
	// No need to insert separately - the workspace_members insert above handles it

	return {
		id: workspace.id,
		name: workspace.name,
		ownerId: workspace.owner_id,
		createdAt: new Date(workspace.created_at || Date.now()),
		subscriptionTier: (workspace.tier ||
			"free") as import("@/types/team.js").SubscriptionTier,
	};
};

export const getWorkspace = async (
	workspaceId: string,
): Promise<Workspace | null> => {
	const { data, error } = await supabase
		.from("workspaces")
		.select("*")
		.eq("id", workspaceId)
		.maybeSingle();

	if (error || !data) return null;

	// Convert subscription data if exists
	// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
	const dataAny = data as any;
	const subscription = dataAny.subscription
		? {
				...dataAny.subscription,
				trialEndAt: dataAny.subscription.trial_end_at
					? new Date(dataAny.subscription.trial_end_at)
					: undefined,
				currentPeriodStart: dataAny.subscription.current_period_start
					? new Date(dataAny.subscription.current_period_start)
					: undefined,
				currentPeriodEnd: dataAny.subscription.current_period_end
					? new Date(dataAny.subscription.current_period_end)
					: undefined,
				canceledAt: dataAny.subscription.canceled_at
					? new Date(dataAny.subscription.canceled_at)
					: undefined,
			}
		: null;

	return {
		id: dataAny.id,
		name: dataAny.name,
		ownerId: dataAny.owner_id,
		createdAt: new Date(dataAny.created_at),
		subscriptionTier: dataAny.tier || "free",
		subscription,
		memberCount: dataAny.member_count,
		accountCount: dataAny.account_count,
	};
};

export const getUserWorkspaces = async (): Promise<Workspace[]> => {
	const userId = await getSupabaseUserId();
	if (!userId) return [];

	// user_workspaces VIEW has 'id' (from workspaces table), not 'workspace_id'
	const { data: userWorkspaces, error } = await supabase
		.from("user_workspaces")
		.select("id")
		.eq("user_id", userId);

	if (error || !userWorkspaces) return [];

	const workspaces: Workspace[] = [];
	for (const uw of userWorkspaces) {
		const workspace = await getWorkspace(uw.id as string);
		if (workspace) {
			workspaces.push(workspace);
		}
	}

	return workspaces;
};

export const updateWorkspace = async (
	workspaceId: string,
	updates: Partial<Pick<Workspace, "name" | "subscriptionTier">>,
): Promise<void> => {
	const userId = await getSupabaseUserId();
	if (!userId) throw new Error("Not authenticated");

	// Only owner can update workspace settings
	const callerRole = await getMemberRole(workspaceId, userId);
	if (!callerRole || callerRole !== "owner") {
		throw new Error("Only the owner can update workspace settings");
	}

	// biome-ignore lint/suspicious/noExplicitAny: workspace updates are open-ended JSON
	const supabaseUpdates: Record<string, any> = {};
	if (updates.name) supabaseUpdates.name = updates.name;
	if (updates.subscriptionTier) supabaseUpdates.tier = updates.subscriptionTier;

	const { error } = await supabase
		.from("workspaces")
		.update(supabaseUpdates)
		.eq("id", workspaceId);

	if (error) throw error;

	await logActivity(workspaceId, "workspace_settings_updated", { updates });
};

export const deleteWorkspace = async (workspaceId: string): Promise<void> => {
	const userId = await getSupabaseUserId();
	if (!userId) throw new Error("Not authenticated");

	// Verify ownership
	const workspace = await getWorkspace(workspaceId);
	if (!workspace || workspace.ownerId !== userId) {
		throw new Error("Only the owner can delete a workspace");
	}

	// Remove all members (user_workspaces VIEW will reflect this automatically)
	await supabase
		.from("workspace_members")
		.delete()
		.eq("workspace_id", workspaceId);

	// Remove all invites
	await supabase
		.from("workspace_invites")
		.delete()
		.eq("workspace_id", workspaceId);

	// Remove all activity logs
	await supabase
		.from("workspace_activity")
		.delete()
		.eq("workspace_id", workspaceId);

	// Delete workspace
	const { error } = await supabase
		.from("workspaces")
		.delete()
		.eq("id", workspaceId);

	if (error) throw error;
};

// ==================== MEMBER OPERATIONS ====================

export const getWorkspaceMembers = async (
	workspaceId: string,
): Promise<WorkspaceMember[]> => {
	const { data, error } = await supabase
		.from("workspace_members")
		.select("*")
		.eq("workspace_id", workspaceId);

	if (error || !data) return [];

	// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
	return data.map((row: any) => ({
		userId: row.user_id,
		role: row.role,
		joinedAt: new Date(row.joined_at),
		invitedBy: row.invited_by,
		displayName: row.display_name || "",
		email: row.email || "",
		photoURL: row.photo_url || "",
	}));
};

export const getMemberRole = async (
	workspaceId: string,
	targetUserId?: string,
): Promise<TeamRole | null> => {
	const userId = targetUserId || (await getSupabaseUserId());
	if (!userId) return null;

	const { data, error } = await supabase
		.from("workspace_members")
		.select("role")
		.eq("workspace_id", workspaceId)
		.eq("user_id", userId)
		.maybeSingle();

	if (error || !data) return null;
	return data.role as TeamRole;
};

export const updateMemberRole = async (
	workspaceId: string,
	targetUserId: string,
	newRole: TeamRole,
): Promise<void> => {
	const userId = await getSupabaseUserId();
	if (!userId) throw new Error("Not authenticated");

	// Can't change to owner role directly
	if (newRole === "owner") {
		throw new Error("Use transferOwnership to change ownership");
	}

	// Verify caller has permission (must be owner or admin)
	const callerRole = await getMemberRole(workspaceId, userId);
	if (!callerRole || (callerRole !== "owner" && callerRole !== "admin")) {
		throw new Error("You don't have permission to change roles");
	}

	// Can't change your own role
	if (targetUserId === userId) {
		throw new Error("You cannot change your own role");
	}

	const { data: member, error: fetchError } = await supabase
		.from("workspace_members")
		.select("role, display_name, email")
		.eq("workspace_id", workspaceId)
		.eq("user_id", targetUserId)
		.maybeSingle();

	if (fetchError || !member) throw new Error("Member not found");

	if (member.role === "owner") {
		throw new Error("Cannot change owner role");
	}

	const { error: updateError } = await supabase
		.from("workspace_members")
		.update({ role: newRole })
		.eq("workspace_id", workspaceId)
		.eq("user_id", targetUserId);

	if (updateError) throw updateError;

	await logActivity(workspaceId, "member_role_changed", {
		targetUserId,
		targetUserName: member.display_name || member.email,
		previousRole: member.role,
		newRole,
	});
};

export const removeMember = async (
	workspaceId: string,
	targetUserId: string,
): Promise<void> => {
	const userId = await getSupabaseUserId();
	if (!userId) throw new Error("Not authenticated");

	// Verify caller has permission (must be owner or admin)
	const callerRole = await getMemberRole(workspaceId, userId);
	if (!callerRole || (callerRole !== "owner" && callerRole !== "admin")) {
		throw new Error("You don't have permission to remove members");
	}

	// Can't remove yourself (use leave workspace instead)
	if (targetUserId === userId) {
		throw new Error("You cannot remove yourself");
	}

	const { data: member, error: fetchError } = await supabase
		.from("workspace_members")
		.select("role, display_name, email")
		.eq("workspace_id", workspaceId)
		.eq("user_id", targetUserId)
		.maybeSingle();

	if (fetchError || !member) throw new Error("Member not found");

	if (member.role === "owner") {
		throw new Error("Cannot remove the owner");
	}

	// Remove from workspace members
	await supabase
		.from("workspace_members")
		.delete()
		.eq("workspace_id", workspaceId)
		.eq("user_id", targetUserId);

	// Note: user_workspaces VIEW automatically reflects workspace_members changes

	await logActivity(workspaceId, "member_removed", {
		removedUserId: targetUserId,
		removedUserName: member.display_name || member.email,
	});
};

export const transferOwnership = async (
	workspaceId: string,
	newOwnerId: string,
): Promise<void> => {
	const userId = await getSupabaseUserId();
	if (!userId) throw new Error("Not authenticated");

	const workspace = await getWorkspace(workspaceId);
	if (!workspace || workspace.ownerId !== userId) {
		throw new Error("Only the owner can transfer ownership");
	}

	const { data: newOwnerMember, error: fetchError } = await supabase
		.from("workspace_members")
		.select("display_name, email")
		.eq("workspace_id", workspaceId)
		.eq("user_id", newOwnerId)
		.maybeSingle();

	if (fetchError || !newOwnerMember) {
		throw new Error("New owner must be a member of the workspace");
	}

	// Update workspace owner
	await supabase
		.from("workspaces")
		.update({ owner_id: newOwnerId })
		.eq("id", workspaceId);

	// Update old owner to admin
	await supabase
		.from("workspace_members")
		.update({ role: "admin" })
		.eq("workspace_id", workspaceId)
		.eq("user_id", userId);

	// Update new owner role
	await supabase
		.from("workspace_members")
		.update({ role: "owner" })
		.eq("workspace_id", workspaceId)
		.eq("user_id", newOwnerId);

	// Note: user_workspaces VIEW automatically reflects workspace_members changes

	await logActivity(workspaceId, "ownership_transferred", {
		previousOwnerId: userId,
		newOwnerId,
		newOwnerName: newOwnerMember.display_name || newOwnerMember.email,
	});
};

// ==================== INVITE OPERATIONS ====================

export const createInvite = async (
	workspaceId: string,
	role: "admin" | "editor" = "editor",
	email?: string,
): Promise<WorkspaceInvite> => {
	const user = await getSupabaseUserDetails();
	if (!user) throw new Error("Not authenticated");

	// Verify caller has invite permission (must be owner or admin)
	const callerRole = await getMemberRole(workspaceId, user.id);
	if (!callerRole || (callerRole !== "owner" && callerRole !== "admin")) {
		throw new Error("You don't have permission to invite members");
	}

	// Admins cannot create admin invites (only owners can)
	if (callerRole === "admin" && role === "admin") {
		throw new Error("Only owners can invite admins");
	}

	// Check tier limits
	const workspace = await getWorkspace(workspaceId);
	if (!workspace) throw new Error("Workspace not found");

	const members = await getWorkspaceMembers(workspaceId);
	const tierLimit = TIER_LIMITS[workspace.subscriptionTier].maxMembers;

	if (members.length >= tierLimit) {
		throw new Error(`Team limit reached. Upgrade to add more members.`);
	}

	const code = generateInviteCode();
	const expiresAt = new Date();
	expiresAt.setDate(expiresAt.getDate() + 14); // 14 days expiry

	const { data: invite, error } = await supabase
		.from("workspace_invites")
		.insert({
			workspace_id: workspaceId,
			code,
			email,
			role,
			expires_at: expiresAt.toISOString(),
			created_by: user.id,
			used: false,
			// biome-ignore lint/suspicious/noExplicitAny: Supabase insert type narrowing
		} as any)
		.select()
		.maybeSingle();

	if (error) throw error;
	if (!invite) throw new Error("Failed to create invite");

	await logActivity(workspaceId, "invite_created", { email, role });

	// If email was provided, send the invite email via Vercel API
	let emailSent = false;
	if (email) {
		try {
			const {
				data: { session },
			} = await supabase.auth.getSession();
			const emailRes = await fetch("/api/team?action=send-invite-email", {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Authorization: `Bearer ${session?.access_token}`,
				},
				body: JSON.stringify({
					workspaceName: workspace.name,
					inviteCode: code,
					recipientEmail: email,
					role,
				}),
			});
			const emailJson = await emailRes.json().catch(() => ({}));
			emailSent = emailJson?.emailSent !== false;
		} catch (emailError) {
			logger.error("Failed to send invite email:", emailError);
			// Don't throw - invite was created, just email failed
		}
	}

	return {
		id: invite.id,
		code: invite.code || "",
		email: invite.email || "",
		role: invite.role as "admin" | "editor",
		expiresAt: new Date(invite.expires_at || Date.now()),
		createdBy: invite.created_by || "",
		createdAt: new Date(invite.created_at || Date.now()),
		used: invite.used ?? false,
		emailSent: email ? emailSent : undefined,
	};
};

export const getWorkspaceInvites = async (
	workspaceId: string,
): Promise<WorkspaceInvite[]> => {
	const { data, error } = await supabase
		.from("workspace_invites")
		.select("*")
		.eq("workspace_id", workspaceId)
		.eq("used", false)
		.gt("expires_at", new Date().toISOString());

	if (error || !data) return [];

	// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
	return data.map((row: any) => ({
		id: row.id,
		code: row.code,
		email: row.email,
		role: row.role,
		expiresAt: new Date(row.expires_at),
		createdBy: row.created_by,
		createdAt: new Date(row.created_at),
		used: row.used,
	}));
};

export const revokeInvite = async (
	workspaceId: string,
	inviteId: string,
): Promise<void> => {
	const userId = await getSupabaseUserId();
	if (!userId) throw new Error("Not authenticated");

	// Verify caller has permission (must be owner or admin)
	const callerRole = await getMemberRole(workspaceId, userId);
	if (!callerRole || (callerRole !== "owner" && callerRole !== "admin")) {
		throw new Error("You don't have permission to revoke invites");
	}

	const { error } = await supabase
		.from("workspace_invites")
		.delete()
		.eq("id", inviteId)
		.eq("workspace_id", workspaceId);

	if (error) throw error;

	await logActivity(workspaceId, "invite_revoked", { inviteId });
};

// Get invite details using API (bypasses security rules for non-members)
export const getInviteDetails = async (
	inviteCode: string,
): Promise<{
	email?: string | undefined;
	role: string;
	workspaceName: string;
	workspaceId: string;
} | null> => {
	try {
		const response = await fetch(
			`/api/team?action=invite-details&code=${inviteCode}`,
		);
		if (!response.ok) return null;

		const data = await response.json();
		if (data.success && data.invite) {
			return {
				email: data.invite.email || undefined,
				role: data.invite.role,
				workspaceName: data.invite.workspaceName,
				workspaceId: data.invite.workspaceId,
			};
		}
		return null;
	} catch (error) {
		logger.error("Failed to get invite details:", error);
		return null;
	}
};

export const joinWorkspaceWithCode = async (
	inviteCode: string,
): Promise<string> => {
	const user = await getSupabaseUserDetails();
	if (!user) throw new Error("Not authenticated");

	// Find the invite
	const { data: foundInvite, error: inviteError } = await supabase
		.from("workspace_invites")
		.select("*, workspaces(name)")
		.eq("code", inviteCode)
		.eq("used", false)
		.maybeSingle();

	if (inviteError || !foundInvite) {
		throw new Error("Invalid or expired invite code");
	}

	if (new Date(foundInvite.expires_at) < new Date()) {
		throw new Error("This invite has expired");
	}

	const foundWorkspaceId = foundInvite.workspace_id;

	// Check if already a member
	const { data: existingMember } = await supabase
		.from("workspace_members")
		.select("id")
		.eq("workspace_id", foundWorkspaceId)
		.eq("user_id", user.id)
		.maybeSingle();

	if (existingMember) {
		throw new Error("You are already a member of this workspace");
	}

	// Check tier limits
	const workspace = await getWorkspace(foundWorkspaceId);
	if (!workspace) throw new Error("Workspace not found");

	const members = await getWorkspaceMembers(foundWorkspaceId);
	const tierLimit = TIER_LIMITS[workspace.subscriptionTier].maxMembers;

	if (members.length >= tierLimit) {
		throw new Error("This workspace has reached its member limit");
	}

	// Add as member
	await supabase.from("workspace_members").insert({
		workspace_id: foundWorkspaceId,
		user_id: user.id,
		role: foundInvite.role,
		invited_by: foundInvite.created_by,
		display_name: user.displayName,
		email: user.email,
	});

	// Note: user_workspaces is a VIEW - workspace_members insert above handles it

	// Mark invite as used (if it's an email invite)
	if (foundInvite.email) {
		await supabase
			.from("workspace_invites")
			.update({ used: true, used_by: user.id })
			.eq("id", foundInvite.id);
	}

	await logActivity(foundWorkspaceId, "member_joined", {
		newMemberId: user.id,
		newMemberName: user.displayName || user.email,
		role: foundInvite.role,
	});

	return foundWorkspaceId;
};

// ==================== ACTIVITY LOG ====================

export const logActivity = async (
	workspaceId: string,
	action: ActivityAction,
	// biome-ignore lint/suspicious/noExplicitAny: activity details are open-ended JSON
	details?: Record<string, any>,
): Promise<void> => {
	const user = await getSupabaseUserDetails();
	if (!user) return;

	await supabase.from("workspace_activity").insert({
		workspace_id: workspaceId,
		action,
		user_id: user.id,
		user_name: user.displayName || user.email,
		details: details || {},
		// biome-ignore lint/suspicious/noExplicitAny: Supabase insert type narrowing
	} as any);
};

export const getActivityLog = async (
	workspaceId: string,
	limitCount: number = 50,
): Promise<ActivityLogEntry[]> => {
	const { data, error } = await supabase
		.from("workspace_activity")
		.select("*")
		.eq("workspace_id", workspaceId)
		.order("created_at", { ascending: false })
		.limit(limitCount);

	if (error || !data) return [];

	// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
	return data.map((row: any) => ({
		id: row.id,
		action: row.action,
		userId: row.user_id,
		userName: row.user_name,
		timestamp: new Date(row.created_at),
		details: row.details || {},
	})) as ActivityLogEntry[];
};

// Subscribe to activity updates
export const subscribeToActivity = (
	workspaceId: string,
	callback: (activities: ActivityLogEntry[]) => void,
) => {
	// Initial fetch
	const fetchActivities = async () => {
		const activities = await getActivityLog(workspaceId, 50);
		callback(activities);
	};

	fetchActivities();

	return subscribe(
		`workspace-activity:${workspaceId}`,
		() =>
			supabase
				.channel(`workspace-activity-${workspaceId}`)
				.on(
					"postgres_changes",
					{
						event: "*",
						schema: "public",
						table: "workspace_activity",
						filter: `workspace_id=eq.${workspaceId}`,
					},
					() => {
						fetchActivities();
					},
				)
				.subscribe(),
		fetchActivities,
	);
};

// ==================== HELPER EXPORTS ====================

export const teamService = {
	createWorkspace,
	getWorkspace,
	getUserWorkspaces,
	updateWorkspace,
	deleteWorkspace,
	getWorkspaceMembers,
	getMemberRole,
	updateMemberRole,
	removeMember,
	transferOwnership,
	createInvite,
	getWorkspaceInvites,
	getInviteDetails,
	revokeInvite,
	joinWorkspaceWithCode,
	logActivity,
	getActivityLog,
	subscribeToActivity,
};

export default teamService;
