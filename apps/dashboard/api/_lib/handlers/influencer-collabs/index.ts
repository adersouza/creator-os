/**
 * Influencer Collaboration Manager — CRUD + ROI + Leaderboard
 *
 * Actions via query param:
 *   list, get, create, update, delete, link-post, unlink-post, roi, leaderboard
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import type { Database } from "../../../../types/supabase.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { requireMinTier } from "../../tierGate.js";
import { z, zEnum } from "../../zodCompat.js";

const CollabSchema = z.object({
	partner_handle: z.string().min(1).max(200),
	partner_platform: zEnum(["instagram", "threads"]).default("instagram"),
	partner_avatar_url: z.string().url().optional().nullable(),
	partner_follower_count: z.number().int().optional().nullable(),
	collab_type: zEnum([
		"post",
		"story",
		"reel",
		"giveaway",
		"takeover",
		"affiliate",
		"shoutout",
		"collab_post",
		"story_feature",
		"ugc",
		"other",
	]).default("post"),
	status: zEnum([
		"contacted",
		"negotiating",
		"agreed",
		"active",
		"completed",
		"declined",
	]).default("contacted"),
	cost_cents: z.number().int().min(0).default(0),
	cost_type: zEnum(["flat", "per_post", "revenue_share", "barter"]).default(
		"flat",
	),
	revenue_share_pct: z.number().min(0).max(100).optional().nullable(),
	notes: z.string().max(2000).optional().nullable(),
	outreach_template: z.string().max(5000).optional().nullable(),
	start_date: z.string().optional().nullable(),
	end_date: z.string().optional().nullable(),
	workspace_id: z.string().optional().nullable(),
});

type InfluencerCollabInsert =
	Database["public"]["Tables"]["influencer_collabs"]["Insert"];
type InfluencerCollabUpdate =
	Database["public"]["Tables"]["influencer_collabs"]["Update"];

async function computeROI(
	db: ReturnType<typeof getSupabase>,
	collabId: string,
	userId: string,
) {
	// Get linked posts
	const { data: links } = await db
		.from("influencer_collab_posts")
		.select("post_id, is_partner_post")
		.eq("collab_id", collabId);

	if (!links?.length) {
		return {
			totalReach: 0,
			totalLikes: 0,
			totalComments: 0,
			totalSaves: 0,
			totalEngagement: 0,
			costDollars: 0,
			costPerEngagement: 0,
			costPerReach: 0,
			linkedPostCount: 0,
		};
	}

	const postIds = (
		links as { post_id: string; is_partner_post: boolean | null }[]
	).map((l) => l.post_id);
	// #689: Filter posts by user_id to prevent IDOR in ROI computation
	const { data: posts } = await db
		.from("posts")
		.select("id, views_count, likes_count, replies_count, ig_saved")
		.in("id", postIds)
		.eq("user_id", userId);

	interface LinkedPost {
		id: string;
		views_count?: number | undefined;
		likes_count?: number | undefined;
		replies_count?: number | undefined;
		ig_saved?: number | undefined;
	}
	const linkedPosts: LinkedPost[] = (posts || []) as unknown as LinkedPost[];
	const totalReach = linkedPosts.reduce(
		(s: number, p: LinkedPost) => s + (p.views_count || 0),
		0,
	);
	const totalLikes = linkedPosts.reduce(
		(s: number, p: LinkedPost) => s + (p.likes_count || 0),
		0,
	);
	const totalComments = linkedPosts.reduce(
		(s: number, p: LinkedPost) => s + (p.replies_count || 0),
		0,
	);
	const totalSaves = linkedPosts.reduce(
		(s: number, p: LinkedPost) => s + (p.ig_saved || 0),
		0,
	);
	const totalEngagement = totalLikes + totalComments + totalSaves;

	// Get cost
	const { data: collab } = await db
		.from("influencer_collabs")
		.select("cost_cents")
		.eq("id", collabId)
		.eq("user_id", userId)
		.maybeSingle();

	const costDollars = (collab?.cost_cents || 0) / 100;
	const costPerEngagement =
		totalEngagement > 0 && costDollars > 0 ? costDollars / totalEngagement : 0;
	const costPerReach =
		totalReach > 0 && costDollars > 0 ? (costDollars / totalReach) * 1000 : 0;

	return {
		totalReach,
		totalLikes,
		totalComments,
		totalSaves,
		totalEngagement,
		costDollars,
		costPerEngagement: Math.round(costPerEngagement * 100) / 100,
		costPerReach: Math.round(costPerReach * 100) / 100,
		linkedPostCount: linkedPosts.length,
	};
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		// Influencer collaborations require Empire tier
		if (!(await requireMinTier(user.id, "empire", res))) return;

		const db = getSupabase();
		const action =
			(req.query.action as string) ||
			(req.method === "GET" ? "list" : "create");

		// --- LIST ---
		if (req.method === "GET" && action === "list") {
			let query = db
				.from("influencer_collabs")
				.select("*")
				.eq("user_id", user.id)
				.order("created_at", { ascending: false });

			const status = req.query.status as string;
			if (status) query = query.eq("status", status);

			const { data, error } = await query.limit(200);
			if (error) return apiError(res, 500, "Failed to load collabs");
			return apiSuccess(res, { collabs: data || [] });
		}

		// --- GET (single with ROI) ---
		if (req.method === "GET" && action === "get") {
			const id = req.query.id as string;
			if (!id) return apiError(res, 400, "id required");

			const { data: collab, error } = await db
				.from("influencer_collabs")
				.select("*")
				.eq("id", id)
				.eq("user_id", user.id)
				.maybeSingle();

			if (error || !collab) return apiError(res, 404, "Collab not found");

			const { data: linkedPosts } = await db
				.from("influencer_collab_posts")
				.select("post_id, is_partner_post, created_at")
				.eq("collab_id", id);

			const roi = await computeROI(db, id, user.id);
			return apiSuccess(res, { collab, linkedPosts: linkedPosts || [], roi });
		}

		// --- ROI ---
		if (req.method === "GET" && action === "roi") {
			const id = req.query.id as string;
			if (!id) return apiError(res, 400, "id required");

			// Verify ownership
			const { data: check } = await db
				.from("influencer_collabs")
				.select("id")
				.eq("id", id)
				.eq("user_id", user.id)
				.maybeSingle();
			if (!check) return apiError(res, 404, "Collab not found");

			const roi = await computeROI(db, id, user.id);
			return apiSuccess(res, { roi });
		}

		// --- LEADERBOARD ---
		if (req.method === "GET" && action === "leaderboard") {
			const { data: collabs } = await db
				.from("influencer_collabs")
				.select("*")
				.eq("user_id", user.id)
				.in("status", ["active", "completed"]);

			const leaderboard: Array<Record<string, unknown>> = [];
			for (const collab of collabs || []) {
				const roi = await computeROI(db, collab.id, user.id);
				leaderboard.push({ ...collab, roi });
			}

			// Sort by total engagement descending
			leaderboard.sort(
				(a, b) =>
					(b.roi as { totalEngagement: number }).totalEngagement -
					(a.roi as { totalEngagement: number }).totalEngagement,
			);
			return apiSuccess(res, { leaderboard: leaderboard.slice(0, 20) });
		}

		// --- CREATE ---
		if (req.method === "POST" && action === "create") {
			const parsed = CollabSchema.safeParse(req.body);
			if (!parsed.success)
				return apiError(
					res,
					400,
					parsed.error.issues[0]?.message || "Invalid input",
				);

			// #565: Enforce character limit on notes field
			if (parsed.data.notes && parsed.data.notes.length > 2000) {
				return apiError(res, 400, "Notes must be 2000 characters or fewer");
			}

			// #563: Check for duplicate influencer — same partner_handle for the same user
			const { data: existingCollab } = await db
				.from("influencer_collabs")
				.select("id, partner_handle, status")
				.eq("user_id", user.id)
				.eq("partner_handle", parsed.data.partner_handle)
				.maybeSingle();

			if (existingCollab) {
				return apiError(
					res,
					409,
					`A collaboration with @${parsed.data.partner_handle} already exists (status: ${existingCollab.status}). Use the existing collab or delete it first.`,
				);
			}

			const collabInsert: InfluencerCollabInsert = {
				user_id: user.id,
				partner_handle: parsed.data.partner_handle,
				partner_platform: parsed.data.partner_platform,
				collab_type: parsed.data.collab_type,
				status: parsed.data.status,
				cost_cents: parsed.data.cost_cents,
				cost_type: parsed.data.cost_type,
			};
			if (parsed.data.partner_avatar_url !== undefined) {
				collabInsert.partner_avatar_url = parsed.data.partner_avatar_url;
			}
			if (parsed.data.partner_follower_count !== undefined) {
				collabInsert.partner_follower_count =
					parsed.data.partner_follower_count;
			}
			if (parsed.data.revenue_share_pct !== undefined) {
				collabInsert.revenue_share_pct = parsed.data.revenue_share_pct;
			}
			if (parsed.data.notes !== undefined)
				collabInsert.notes = parsed.data.notes;
			if (parsed.data.outreach_template !== undefined) {
				collabInsert.outreach_template = parsed.data.outreach_template;
			}
			if (parsed.data.start_date !== undefined) {
				collabInsert.start_date = parsed.data.start_date;
			}
			if (parsed.data.end_date !== undefined) {
				collabInsert.end_date = parsed.data.end_date;
			}
			if (parsed.data.workspace_id !== undefined) {
				collabInsert.workspace_id = parsed.data.workspace_id;
			}

			const { data, error } = await db
				.from("influencer_collabs")
				.insert(collabInsert)
				.select()
				.maybeSingle();

			if (error) return apiError(res, 500, "Failed to create collab");
			return apiSuccess(res, { collab: data });
		}

		// --- UPDATE ---
		if (req.method === "PUT" && action === "update") {
			const id = req.query.id as string;
			if (!id) return apiError(res, 400, "id required");

			const parsed = CollabSchema.partial().safeParse(req.body);
			if (!parsed.success)
				return apiError(
					res,
					400,
					parsed.error.issues[0]?.message || "Invalid input",
				);

			// #565: Enforce character limit on notes field
			if (parsed.data.notes && parsed.data.notes.length > 2000) {
				return apiError(res, 400, "Notes must be 2000 characters or fewer");
			}

			const collabUpdate: InfluencerCollabUpdate = {
				updated_at: new Date().toISOString(),
			};
			if (parsed.data.partner_handle !== undefined) {
				collabUpdate.partner_handle = parsed.data.partner_handle;
			}
			if (parsed.data.partner_platform !== undefined) {
				collabUpdate.partner_platform = parsed.data.partner_platform;
			}
			if (parsed.data.partner_avatar_url !== undefined) {
				collabUpdate.partner_avatar_url = parsed.data.partner_avatar_url;
			}
			if (parsed.data.partner_follower_count !== undefined) {
				collabUpdate.partner_follower_count =
					parsed.data.partner_follower_count;
			}
			if (parsed.data.collab_type !== undefined) {
				collabUpdate.collab_type = parsed.data.collab_type;
			}
			if (parsed.data.status !== undefined)
				collabUpdate.status = parsed.data.status;
			if (parsed.data.cost_cents !== undefined) {
				collabUpdate.cost_cents = parsed.data.cost_cents;
			}
			if (parsed.data.cost_type !== undefined) {
				collabUpdate.cost_type = parsed.data.cost_type;
			}
			if (parsed.data.revenue_share_pct !== undefined) {
				collabUpdate.revenue_share_pct = parsed.data.revenue_share_pct;
			}
			if (parsed.data.notes !== undefined)
				collabUpdate.notes = parsed.data.notes;
			if (parsed.data.outreach_template !== undefined) {
				collabUpdate.outreach_template = parsed.data.outreach_template;
			}
			if (parsed.data.start_date !== undefined) {
				collabUpdate.start_date = parsed.data.start_date;
			}
			if (parsed.data.end_date !== undefined) {
				collabUpdate.end_date = parsed.data.end_date;
			}
			if (parsed.data.workspace_id !== undefined) {
				collabUpdate.workspace_id = parsed.data.workspace_id;
			}

			const { data, error } = await db
				.from("influencer_collabs")
				.update(collabUpdate)
				.eq("id", id)
				.eq("user_id", user.id)
				.select()
				.maybeSingle();

			if (error) return apiError(res, 500, "Failed to update collab");
			if (!data) return apiError(res, 404, "Collab not found");
			return apiSuccess(res, { collab: data });
		}

		// --- DELETE ---
		if (req.method === "DELETE" && action === "delete") {
			const id = req.query.id as string;
			if (!id) return apiError(res, 400, "id required");

			// Verify ownership
			const { data: ownedCollab } = await db
				.from("influencer_collabs")
				.select("id")
				.eq("id", id)
				.eq("user_id", user.id)
				.maybeSingle();
			if (!ownedCollab) return apiError(res, 403, "Not authorized");

			const { error } = await db
				.from("influencer_collabs")
				.delete()
				.eq("id", id)
				.eq("user_id", user.id);

			if (error) {
				return apiError(res, 500, "Failed to delete collab");
			}
			return apiSuccess(res, { deleted: true });
		}

		// --- LINK POST ---
		if (req.method === "POST" && action === "link-post") {
			const { collab_id, post_id, is_partner_post } = req.body || {};
			if (!collab_id || !post_id)
				return apiError(res, 400, "collab_id and post_id required");

			// Verify ownership
			const { data: check } = await db
				.from("influencer_collabs")
				.select("id")
				.eq("id", collab_id)
				.eq("user_id", user.id)
				.maybeSingle();
			if (!check) return apiError(res, 404, "Collab not found");

			const { data: ownedPost } = await db
				.from("posts")
				.select("id")
				.eq("id", post_id)
				.eq("user_id", user.id)
				.maybeSingle();
			if (!ownedPost) return apiError(res, 404, "Post not found");

			const { data, error } = await db
				.from("influencer_collab_posts")
				.insert({ collab_id, post_id, is_partner_post: !!is_partner_post })
				.select()
				.maybeSingle();

			if (error) return apiError(res, 500, "Failed to link post");
			return apiSuccess(res, { link: data });
		}

		// --- UNLINK POST ---
		if (req.method === "DELETE" && action === "unlink-post") {
			const { collab_id, post_id } = req.body || {};
			if (!collab_id || !post_id)
				return apiError(res, 400, "collab_id and post_id required");

			// Verify ownership
			const { data: collab } = await db
				.from("influencer_collabs")
				.select("id")
				.eq("id", collab_id)
				.eq("user_id", user.id)
				.maybeSingle();
			if (!collab) return apiError(res, 403, "Not authorized");

			const { error, count } = await db
				.from("influencer_collab_posts")
				.delete({ count: "exact" })
				.eq("collab_id", collab_id)
				.eq("post_id", post_id);

			if (error) return apiError(res, 500, "Failed to unlink post");
			if (!count) return apiError(res, 404, "Link not found");
			return apiSuccess(res, { unlinked: true });
		}

		return apiError(res, 405, "Method not allowed");
	},
);
