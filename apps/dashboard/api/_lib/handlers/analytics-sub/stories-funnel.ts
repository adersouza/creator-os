// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Stories funnel — per-frame retention curve across an IG Story sequence.
 *
 * GET /api/analytics?action=stories-funnel&periodDays=14
 *
 * Mockup: new-widgets-2026.html #4 ("Stories funnel · last sequence").
 *
 * Reads posts.ig_story_taps_forward / ig_story_taps_back / ig_story_exits /
 * ig_views — populated by the v25 navigation breakdown call now wired in
 * api/_lib/instagram/insights.ts (story navigation breakdown phase).
 *
 * Sequence definition: a "sequence" is one account's set of stories
 * published within a 24h sliding window. The dashboard wants the LAST
 * complete sequence — i.e. the most recent 24h burst of stories with at
 * least 2 frames. We return that one sequence by default.
 *
 * Per-frame metrics returned:
 *  - views (the impression count for that frame)
 *  - reach
 *  - taps_forward / taps_back / exits (the navigation breakdown)
 *  - retentionPct (views ÷ first-frame views) — drives the funnel curve
 *  - dropoffPct (1 - retention) — drives the drop-off label per frame
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "../../zodCompat.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";
import { getAccountIdsForContext } from "../../workspaceAccounts.js";

const QuerySchema = z.object({
	accountId: z.string().optional(),
	accountIds: z.string().optional(),
	periodDays: z.coerce.number().int().min(1).max(60).optional().default(14),
	minFrames: z.coerce.number().int().min(2).max(20).optional().default(2),
	workspaceId: z.string().optional(),
});

// biome-ignore lint/suspicious/noExplicitAny: posts columns aren't all in generated types
const db = (): any => getSupabase();

interface FrameRow {
	postId: string;
	publishedAt: string;
	views: number;
	reach: number;
	tapsForward: number;
	tapsBack: number;
	exits: number;
	replies: number;
	retentionPct: number;
	dropoffPct: number;
}

interface SequenceRow {
	accountId: string;
	username: string | null;
	startedAt: string;
	frameCount: number;
	frames: FrameRow[];
	totals: {
		views: number;
		reach: number;
		tapsForward: number;
		tapsBack: number;
		exits: number;
		replies: number;
	};
	completionPct: number;
	exitFramePeak: number | null; // 1-indexed frame where exits peaked
}

type RawStoryRow = {
	id: string;
	instagram_account_id: string;
	published_at: string;
	ig_views: number | null;
	ig_reach: number | null;
	ig_story_taps_forward: number | null;
	ig_story_taps_back: number | null;
	ig_story_exits: number | null;
	ig_story_replies: number | null;
};

const SEQUENCE_GAP_HOURS = 24;

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { accountId, accountIds, periodDays, minFrames, workspaceId } = parsed;

		// Resolve scope: explicit accountId, or every IG account in context.
		let candidateIds: string[] = [];
		if (accountIds) {
			candidateIds = accountIds.split(",").map((s) => s.trim()).filter(Boolean);
		} else if (accountId && accountId !== "ALL") {
			candidateIds = [accountId];
		} else {
			candidateIds = await getAccountIdsForContext(
				user.id,
				workspaceId ?? null,
				"instagram",
			);
		}

		// Always re-scope through the workspace allow-list.
		if (candidateIds.length > 0) {
			const allowed = new Set(
				await getAccountIdsForContext(
					user.id,
					workspaceId ?? null,
					"instagram",
				),
			);
			candidateIds = candidateIds.filter((id) => allowed.has(id));
		}

		if (candidateIds.length === 0) {
			return apiSuccess(res, { sequences: [], periodDays });
		}

		const cutoff = new Date(Date.now() - periodDays * 86_400_000).toISOString();

		const { data: rows, error } = await db()
			.from("posts")
			.select(
				"id, instagram_account_id, published_at, ig_views, ig_reach, ig_story_taps_forward, ig_story_taps_back, ig_story_exits, ig_story_replies",
			)
			.eq("user_id", user.id)
			.eq("status", "published")
			.eq("ig_media_type", "STORIES")
			.in("instagram_account_id", candidateIds)
			.gte("published_at", cutoff)
			.order("published_at", { ascending: true });

		if (error) {
			return apiError(res, 500, "Failed to load stories", {
				details: error.message,
			});
		}

		// Group rows into per-account chronological sequences. A sequence
		// breaks when the gap between consecutive stories from the same
		// account exceeds SEQUENCE_GAP_HOURS.
		const byAccount = new Map<string, RawStoryRow[]>();
		for (const r of (rows || []) as RawStoryRow[]) {
			const list = byAccount.get(r.instagram_account_id) ?? [];
			list.push(r);
			byAccount.set(r.instagram_account_id, list);
		}

		const sequences: SequenceRow[] = [];
		for (const [acctId, acctRows] of byAccount.entries()) {
			let current: RawStoryRow[] = [];
			const flush = () => {
				if (current.length >= minFrames) {
					sequences.push(buildSequence(acctId, current));
				}
				current = [];
			};
			for (const r of acctRows) {
				if (current.length === 0) {
					current.push(r);
					continue;
				}
				const last = current[current.length - 1];
				const gapH =
					(Date.parse(r.published_at) - Date.parse(last!.published_at)) /
					3_600_000;
				if (gapH > SEQUENCE_GAP_HOURS) {
					flush();
				}
				current.push(r);
			}
			flush();
		}

		// Hydrate usernames in one query.
		const acctIds = Array.from(new Set(sequences.map((s) => s.accountId)));
		const usernameById = new Map<string, string | null>();
		if (acctIds.length > 0) {
			const { data: accts } = await db()
				.from("instagram_accounts")
				.select("id, username")
				.in("id", acctIds);
			for (const a of (accts || []) as Array<{
				id: string;
				username: string | null;
			}>) {
				usernameById.set(a.id, a.username);
			}
		}
		for (const s of sequences) {
			s.username = usernameById.get(s.accountId) ?? null;
		}

		// Sort: most recent sequence first across all accounts. Tile usually
		// only renders the top one ("last sequence"); higher limits return
		// the full history for the analytics page.
		sequences.sort(
			(a, b) =>
				Date.parse(b.startedAt || "0") - Date.parse(a.startedAt || "0"),
		);

		return apiSuccess(res, {
			sequences,
			periodDays,
			notes: {
				framesField: "frames[].views from posts.ig_views",
				navigationField:
					"taps_forward / taps_back / exits from v25 navigation breakdown — populated by the navigation&breakdown=story_navigation_action_type call in api/_lib/instagram/insights.ts",
				sequenceGapHours: SEQUENCE_GAP_HOURS,
			},
		});
	},
);

function buildSequence(accountId: string, rows: RawStoryRow[]): SequenceRow {
	const firstViews = rows[0]?.ig_views || 0;

	const frames: FrameRow[] = rows.map((r) => {
		const views = r.ig_views || 0;
		const retention = firstViews > 0 ? views / firstViews : 0;
		return {
			postId: r.id,
			publishedAt: r.published_at,
			views,
			reach: r.ig_reach || 0,
			tapsForward: r.ig_story_taps_forward || 0,
			tapsBack: r.ig_story_taps_back || 0,
			exits: r.ig_story_exits || 0,
			replies: r.ig_story_replies || 0,
			retentionPct: Math.round(retention * 1000) / 10, // 0-100 with 1 decimal
			dropoffPct:
				Math.round((1 - retention) * 1000) / 10,
		};
	});

	const totals = frames.reduce(
		(acc, f) => {
			acc.views += f.views;
			acc.reach += f.reach;
			acc.tapsForward += f.tapsForward;
			acc.tapsBack += f.tapsBack;
			acc.exits += f.exits;
			acc.replies += f.replies;
			return acc;
		},
		{ views: 0, reach: 0, tapsForward: 0, tapsBack: 0, exits: 0, replies: 0 },
	);

	// Completion = views of last frame / views of first frame.
	const lastViews = frames[frames.length - 1]?.views ?? 0;
	const completionPct =
		firstViews > 0 ? Math.round((lastViews / firstViews) * 1000) / 10 : 0;

	// Exit-frame peak: which frame had the highest exit count? 1-indexed.
	let exitFramePeak: number | null = null;
	let maxExits = 0;
	frames.forEach((f, i) => {
		if (f.exits > maxExits) {
			maxExits = f.exits;
			exitFramePeak = i + 1;
		}
	});

	return {
		accountId,
		username: null, // hydrated by caller
		startedAt: rows[0]?.published_at ?? "",
		frameCount: frames.length,
		frames,
		totals,
		completionPct,
		exitFramePeak,
	};
}
