/**
 * Team API Route
 * POST /api/team?action=send-invite-email
 * GET /api/team?action=invite-details&code=XXX
 * GET /api/team?action=team-stats&workspace_id=X&days=7|30|0&platform=threads|instagram
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
	apiError,
	apiSuccess,
	badRequest,
	methodNotAllowed,
	notFound,
	serverError,
	unauthorized,
} from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth, withCors } from "../../middleware.js";
import { enforceRouteRateLimit } from "../../routeRateLimit.js";
import { getSupabase } from "../../supabase.js";
import { requireMinTier } from "../../tierGate.js";
import {
	getWorkspaceAccess,
	verifyWorkspaceAccess,
	workspaceAccessHasRole,
} from "../../workspaceAccess.js";
import { z } from "../../zodCompat.js";

// ============================================================================
// Row / API Types
// ============================================================================

interface WorkspaceInviteRow {
	workspace_id: string;
}

interface WorkspaceMemberStatRow {
	user_id: string;
	display_name?: string | undefined;
	photo_url?: string | undefined;
}

interface AccountIdRow {
	id: string;
}

interface PostStatsRow {
	user_id: string;
	status: string;
	views_count: number;
	likes_count: number;
	replies_count: number;
}

interface WorkspaceInviteWithName {
	email?: string | undefined;
	role: string;
	workspace_id: string;
	workspaces: { name?: string | undefined } | null;
}

const SendInviteEmailSchema = z.object({
	workspaceName: z.string().min(1, "workspaceName is required"),
	inviteCode: z.string().min(1, "inviteCode is required"),
	recipientEmail: z.string().email("recipientEmail must be a valid email"),
	role: z.string().optional().default("member"),
});
// Create Supabase client lazily to avoid crashes at module load time

/** Escape HTML special characters to prevent injection in email body */
function escapeHtml(str: string): string {
	return str
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;")
		.replace(/'/g, "&#x27;");
}

// Generate invite email HTML template
function generateInviteEmailHtml(
	workspaceName: string,
	inviteCode: string,
	role: string,
	inviteUrl: string,
): string {
	return `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Team Invite</title>
</head>
<body style="margin:0; padding:0; background-color:#f4f4f5; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f4f5; padding:40px 20px;">
    <tr>
      <td align="center">
        <table width="100%" max-width="600" cellpadding="0" cellspacing="0" style="background-color:#ffffff; border-radius:12px; overflow:hidden; box-shadow:0 4px 6px rgba(0,0,0,0.1);">
          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg, #a855f7 0%, #7c3aed 100%); padding:32px 40px; text-align:center;">
              <h1 style="margin:0; color:#ffffff; font-size:24px; font-weight:700;">Juno33</h1>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td style="padding:40px;">
              <h2 style="margin:0 0 16px; color:#18181b; font-size:20px; font-weight:600;">You're Invited!</h2>
              <p style="margin:0 0 24px; color:#52525b; font-size:16px; line-height:1.6;">
                You've been invited to join <strong style="color:#18181b;">${escapeHtml(workspaceName)}</strong> as a <strong style="color:#a855f7;">${escapeHtml(role)}</strong>.
              </p>

              <!-- Invite Code Box -->
              <div style="background-color:#faf5ff; border:2px dashed #a855f7; border-radius:8px; padding:20px; text-align:center; margin-bottom:24px;">
                <p style="margin:0 0 8px; color:#6b21a8; font-size:14px; font-weight:500;">Your Invite Code</p>
                <p style="margin:0; color:#18181b; font-size:28px; font-weight:700; letter-spacing:2px; font-family:monospace;">${escapeHtml(inviteCode)}</p>
              </div>

              <!-- CTA Button -->
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center">
                    <a href="${escapeHtml(inviteUrl)}" style="display:inline-block; background:linear-gradient(135deg, #a855f7 0%, #7c3aed 100%); color:#ffffff; text-decoration:none; padding:14px 32px; border-radius:8px; font-size:16px; font-weight:600;">
                      Join Workspace
                    </a>
                  </td>
                </tr>
              </table>

              <p style="margin:24px 0 0; color:#71717a; font-size:14px; line-height:1.6;">
                Or copy this link to your browser:<br>
                <a href="${inviteUrl}" style="color:#a855f7; word-break:break-all;">${inviteUrl}</a>
              </p>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="background-color:#fafafa; padding:24px 40px; border-top:1px solid #e4e4e7;">
              <p style="margin:0; color:#a1a1aa; font-size:13px; text-align:center;">
                This invite expires in 14 days. If you didn't expect this invitation, you can safely ignore this email.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>`;
}

// Send invite email using Resend API
async function handleSendInviteEmail(
	req: VercelRequest,
	res: VercelResponse,
	userId?: string,
) {
	if (!userId) {
		return unauthorized(res, "Authentication required");
	}

	// Team invites require Pro tier or higher
	if (!(await requireMinTier(userId, "pro", res))) return;

	const parsed = SendInviteEmailSchema.safeParse(req.body);
	if (!parsed.success) {
		return badRequest(res, `Invalid input: ${parsed.error.issues[0]?.message}`);
	}

	const { workspaceName, inviteCode, recipientEmail, role } = parsed.data;

	// Verify the invite code exists and belongs to a workspace the user is a member of
	const { data: invite, error: inviteError } = await getSupabase()
		.from("workspace_invites")
		.select("workspace_id")
		.eq("code", inviteCode)
		.maybeSingle();

	if (inviteError || !invite) {
		return badRequest(res, "Invalid invite code");
	}

	const workspaceId = (invite as WorkspaceInviteRow).workspace_id;
	const workspaceAccess = await getWorkspaceAccess(
		getSupabase(),
		userId,
		workspaceId,
	);
	if (!workspaceAccessHasRole(workspaceAccess, ["owner", "admin"])) {
		return unauthorized(
			res,
			"You don't have permission to send invites for this workspace",
		);
	}

	// Server-side member limit enforcement (backstop for direct API calls)
	// Member limits by tier: free=1, pro=4, agency/empire=unlimited
	const BACKEND_MEMBER_LIMITS: Record<string, number> = { free: 1, pro: 4 };

	const { data: ownerProfile } = (await getSupabase()
		.from("profiles")
		.select("subscription_tier")
		.eq("id", userId)
		.maybeSingle()) as {
		data: { subscription_tier: string | null } | null;
		error: unknown;
	};

	const userTier = (ownerProfile?.subscription_tier || "free").toLowerCase();
	const memberLimit = BACKEND_MEMBER_LIMITS[userTier];

	if (memberLimit !== undefined) {
		const { count: memberCount } = await getSupabase()
			.from("workspace_members")
			.select("*", { count: "exact", head: true })
			.eq("workspace_id", workspaceId);

		if ((memberCount || 0) >= memberLimit) {
			const tierName = userTier.charAt(0).toUpperCase() + userTier.slice(1);
			return apiError(
				res,
				403,
				`Member limit reached. Your ${tierName} plan allows ${memberLimit} member(s). Upgrade to add more.`,
			);
		}
	}

	// Get the app URL for the invite link
	const appUrl = process.env.VERCEL_URL
		? `https://${process.env.VERCEL_URL}`
		: process.env.APP_URL || "https://juno33.com";

	const inviteUrl = `${appUrl}/join?code=${inviteCode}`;

	// Check if Resend API key is configured
	const resendApiKey = process.env.RESEND_API_KEY;

	if (!resendApiKey) {
		// No email service configured - log and return success with warning
		// This allows the invite to still be created, just without email notification
		logger.warn("Email service not configured — RESEND_API_KEY missing", {
			to: recipientEmail,
			workspace: workspaceName,
			role,
		});

		return apiSuccess(res, {
			message: "Invite created but email was not sent",
			emailSent: false,
			warning:
				"Email service not configured. Please share the invite code manually.",
		});
	}

	// Generate email HTML
	const emailHtml = generateInviteEmailHtml(
		workspaceName,
		inviteCode,
		role,
		inviteUrl,
	);

	try {
		// Send email via Resend REST API
		const response = await fetch("https://api.resend.com/emails", {
			method: "POST",
			headers: {
				Authorization: `Bearer ${resendApiKey}`,
				"Content-Type": "application/json",
			},
			signal: AbortSignal.timeout(15000),
			body: JSON.stringify({
				from: process.env.EMAIL_FROM || "Juno33 <noreply@juno33.com>",
				to: [recipientEmail],
				subject: `You've been invited to join ${workspaceName}`,
				html: emailHtml,
			}),
		});

		const result = await response.json();

		if (!response.ok) {
			logger.error("Failed to send invite email", { error: result.message });
			return apiSuccess(res, {
				message: "Invite created but email failed to send",
				emailSent: false,
				emailError: "Email delivery failed",
			});
		}

		logger.info("Invite email sent successfully", {
			to: recipientEmail,
			workspace: workspaceName,
			emailId: result.id,
		});

		return apiSuccess(res, {
			message: "Invite email sent successfully",
			emailSent: true,
			emailId: result.id,
		});
	} catch (error: unknown) {
		const message = error instanceof Error ? error.message : String(error);
		logger.error("Error sending invite email", { error: message });
		return apiSuccess(res, {
			message: "Invite created but email failed to send",
			emailSent: false,
			emailError: "Email delivery failed",
		});
	}
}

// Get invite details (public - no auth required, rate-limited by IP)
async function handleGetInviteDetails(req: VercelRequest, res: VercelResponse) {
	// Rate limit: 10 lookups per IP per hour (fail closed to prevent enumeration)
	const ip =
		(req.headers["x-forwarded-for"] as string)?.split(",")[0]?.trim() ||
		"unknown";
	const { checkRateLimit } = await import("../../rateLimiter.js");
	const rl = await checkRateLimit({
		key: `invite-details:${ip}`,
		limit: 10,
		windowSeconds: 3600,
		failMode: "closed",
	});
	if (!rl.allowed) {
		return apiError(res, 429, "Too many requests — try again later");
	}

	const code = req.query.code as string;

	if (!code) {
		return badRequest(res, "Invite code is required");
	}

	// Find the invite
	const { data: invite, error: inviteError } = (await getSupabase()
		.from("workspace_invites")
		.select("*, workspaces(name)")
		.eq("code", code)
		.eq("used", false)
		.gt("expires_at", new Date().toISOString())
		.maybeSingle()) as { data: WorkspaceInviteWithName | null; error: unknown };

	if (inviteError || !invite) {
		return notFound(res, "Invalid or expired invite code");
	}

	return apiSuccess(res, {
		invite: {
			email: invite.email || null,
			role: invite.role,
			workspaceName: invite.workspaces?.name || "Unknown Workspace",
			workspaceId: invite.workspace_id,
		},
	});
}

// Get team member stats (leaderboard)
async function handleTeamStats(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (req.method !== "GET") return methodNotAllowed(res);

	const workspaceId = req.query.workspace_id as string;
	const daysParam = req.query.days as string;

	if (!workspaceId) {
		return badRequest(res, "workspace_id is required");
	}

	const platform = req.query.platform as string | undefined;
	if (platform && platform !== "threads" && platform !== "instagram") {
		return badRequest(res, "platform must be 'threads' or 'instagram'");
	}

	const days = daysParam ? parseInt(daysParam, 10) : 30;
	if (Number.isNaN(days) || (days !== 0 && days !== 7 && days !== 30)) {
		return badRequest(res, "days must be 7, 30, or 0 (all time)");
	}

	const sb = getSupabase();

	// Verify user can access the workspace
	const hasWorkspaceAccess = await verifyWorkspaceAccess(
		sb,
		userId,
		workspaceId,
	);
	if (!hasWorkspaceAccess) {
		return unauthorized(res, "You are not a member of this workspace");
	}

	// Get workspace members with profile info
	const { data: wsMembers, error: wsMembersError } = await sb
		.from("workspace_members")
		.select("user_id, display_name, photo_url")
		.eq("workspace_id", workspaceId);

	if (wsMembersError) {
		logger.error("Failed to fetch workspace members", {
			error: String(wsMembersError),
		});
		return serverError(res, "Internal server error");
	}

	// Get all accounts belonging to the workspace members.
	// Threads accounts can be constrained by workspace_id directly.
	const memberUserIds = (
		(wsMembers as unknown as WorkspaceMemberStatRow[]) || []
	).map((m) => m.user_id);

	if (memberUserIds.length === 0) {
		return apiSuccess(res, { members: [] });
	}

	const [
		{ data: threadsAccounts, error: threadsAccountsError },
		{ data: igAccounts, error: igAccountsError },
	] = await Promise.all([
		// biome-ignore lint/suspicious/noExplicitAny: workspace_id exists in DB but may be missing from generated types
		(sb as any).from("accounts").select("id").eq("workspace_id", workspaceId),
		sb.from("instagram_accounts").select("id").in("user_id", memberUserIds),
	]);

	if (threadsAccountsError || igAccountsError) {
		logger.error("Failed to fetch workspace accounts", {
			threadsError: String(threadsAccountsError),
			instagramError: String(igAccountsError),
		});
		return serverError(res, "Internal server error");
	}

	const threadAccountIds = (threadsAccounts || []).map(
		(a: AccountIdRow) => a.id,
	);
	const igAccountIds = (igAccounts || []).map((a: AccountIdRow) => a.id);

	if (threadAccountIds.length === 0 && igAccountIds.length === 0) {
		return apiSuccess(res, { members: [] });
	}

	// Build date filter
	let postsQuery = sb
		.from("posts")
		.select("user_id, status, views_count, likes_count, replies_count")
		.order("created_at", { ascending: false });

	if (platform === "instagram") {
		if (igAccountIds.length === 0) {
			return apiSuccess(res, { members: [] });
		}
		postsQuery = postsQuery.in("instagram_account_id", igAccountIds);
	} else if (platform === "threads") {
		if (threadAccountIds.length === 0) {
			return apiSuccess(res, { members: [] });
		}
		postsQuery = postsQuery.in("account_id", threadAccountIds);
	} else {
		const clauses: string[] = [];
		if (threadAccountIds.length > 0) {
			clauses.push(`account_id.in.(${threadAccountIds.join(",")})`);
		}
		if (igAccountIds.length > 0) {
			clauses.push(`instagram_account_id.in.(${igAccountIds.join(",")})`);
		}
		if (clauses.length === 0) {
			return apiSuccess(res, { members: [] });
		}
		postsQuery = postsQuery.or(clauses.join(","));
	}

	if (platform) {
		postsQuery = postsQuery.eq("platform", platform);
	}

	if (days > 0) {
		const cutoff = new Date();
		cutoff.setDate(cutoff.getDate() - days);
		postsQuery = postsQuery.gte("created_at", cutoff.toISOString());
	}

	const { data: posts, error: postsError } = await postsQuery;

	if (postsError) {
		logger.error("Failed to fetch posts for team stats", {
			error: postsError.message ?? JSON.stringify(postsError),
		});
		return serverError(res, "Internal server error");
	}

	// Aggregate per user
	const statsMap = new Map<
		string,
		{
			posts_created: number;
			posts_published: number;
			total_likes: number;
			total_replies: number;
			total_views: number;
		}
	>();

	for (const post of (posts || []) as PostStatsRow[]) {
		const uid = post.user_id;
		if (!uid) continue;

		const existing = statsMap.get(uid) || {
			posts_created: 0,
			posts_published: 0,
			total_likes: 0,
			total_replies: 0,
			total_views: 0,
		};

		existing.posts_created++;
		if (post.status === "published") {
			existing.posts_published++;
		}
		existing.total_likes += post.likes_count || 0;
		existing.total_replies += post.replies_count || 0;
		existing.total_views += post.views_count || 0;

		statsMap.set(uid, existing);
	}

	// Build response — include all workspace members (even those with zero activity)
	const members = (
		(wsMembers as unknown as WorkspaceMemberStatRow[]) || []
	).map((m) => {
		const stats = statsMap.get(m.user_id) || {
			posts_created: 0,
			posts_published: 0,
			total_likes: 0,
			total_replies: 0,
			total_views: 0,
		};

		const totalEngagement = stats.total_likes + stats.total_replies;
		const engagementRate =
			stats.total_views > 0
				? Math.min(totalEngagement / stats.total_views, 1)
				: 0;

		return {
			user_id: m.user_id,
			name: m.display_name || "Unknown",
			avatar_url: m.photo_url || null,
			posts_created: stats.posts_created,
			posts_published: stats.posts_published,
			total_likes: stats.total_likes,
			total_replies: stats.total_replies,
			engagement_rate: Math.round(engagementRate * 10000) / 10000,
		};
	});

	return apiSuccess(res, { members });
}

// Authenticated handler for team actions
const authHandler = withAuth(async (req, res, user) => {
	const action = req.query.action as string;
	if (action === "send-invite-email") {
		const allowed = await enforceRouteRateLimit(res, {
			key: `team-invite:user:${user.id}:hour`,
			limit: 10,
			windowSeconds: 3600,
			failMode: "closed",
			message: "Too many team invite requests. Try again later.",
		});
		if (!allowed) return;
	}

	switch (action) {
		case "send-invite-email":
			if (req.method !== "POST") return methodNotAllowed(res);
			return handleSendInviteEmail(req, res, user.id);
		case "team-stats":
			return handleTeamStats(req, res, user.id);
		default:
			return badRequest(res, `Unknown action: ${action}`);
	}
});

export default withCors(async (req, res) => {
	const action = req.query.action as string;

	try {
		switch (action) {
			case "send-invite-email":
			case "team-stats":
				// Requires authentication
				return await authHandler(req, res);
			case "invite-details":
				if (req.method !== "GET") {
					return methodNotAllowed(res);
				}
				return handleGetInviteDetails(req, res);
			default:
				return badRequest(res, `Unknown action: ${action}`);
		}
	} catch (error: unknown) {
		logger.error("Team API error", { error: String(error) });
		return serverError(res, "Internal server error");
	}
});
