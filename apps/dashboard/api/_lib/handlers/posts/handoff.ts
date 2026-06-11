import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess, methodNotAllowed } from "../../apiResponse.js";
import { getSupabaseAny } from "../../supabase.js";
import { z } from "../../zodCompat.js";

const db = () => getSupabaseAny();

const HandoffEventSchema = z.object({
	postId: z.string().min(1),
	event: z.enum([
		"opened",
		"caption_copied",
		"media_downloaded",
		"media_shared",
		"completed",
	]),
});

const HandoffFollowUpSchema = z.object({
	postId: z.string().min(1),
	instagramUrl: z.string().max(240).optional(),
	notes: z.string().max(500).optional(),
});

type HandoffEvent =
	| "opened"
	| "caption_copied"
	| "media_downloaded"
	| "media_shared"
	| "completed";

const eventUpdates: Record<
	HandoffEvent,
	{ status: string; column: string }
> = {
	opened: { status: "opened", column: "handoff_opened_at" },
	caption_copied: { status: "caption_copied", column: "caption_copied_at" },
	media_downloaded: { status: "media_downloaded", column: "media_downloaded_at" },
	media_shared: { status: "media_shared", column: "media_shared_at" },
	completed: { status: "completed", column: "manual_publish_confirmed_at" },
};

export async function handleHandoff(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (req.method !== "GET") return methodNotAllowed(res);
	const postId = typeof req.query.postId === "string" ? req.query.postId : "";
	if (!postId) return apiError(res, 400, "postId is required");

	const { data: post, error } = await db()
		.from("posts")
		.select(
			`
			id,
			content,
			media_urls,
			media_type,
			ig_media_type,
			status,
			scheduled_for,
			published_at,
			handoff_status,
			notification_sent_at,
			handoff_opened_at,
			caption_copied_at,
			media_downloaded_at,
			media_shared_at,
			manual_publish_confirmed_at,
			reminder_count,
			metadata,
			instagram_accounts(username)
		`,
		)
		.eq("id", postId)
		.eq("user_id", userId)
		.eq("platform", "instagram")
		.eq("publish_mode", "notify")
		.maybeSingle();

	if (error) return apiError(res, 500, "Failed to load handoff post");
	if (!post) return apiError(res, 404, "Handoff post not found");

	const joined = (post as Record<string, unknown>).instagram_accounts as
		| { username?: string | null }
		| { username?: string | null }[]
		| null;
	const account = Array.isArray(joined) ? joined[0] : joined;

	return apiSuccess(res, {
		post: {
			id: post.id,
			content: post.content,
			mediaUrls: post.media_urls || [],
			mediaType: post.media_type,
			igMediaType: post.ig_media_type,
			status: post.status,
			scheduledFor: post.scheduled_for,
			publishedAt: post.published_at,
			handoffStatus: post.handoff_status,
			notificationSentAt: post.notification_sent_at,
			handoffOpenedAt: post.handoff_opened_at,
			captionCopiedAt: post.caption_copied_at,
			mediaDownloadedAt: post.media_downloaded_at,
			mediaSharedAt: post.media_shared_at,
			manualPublishConfirmedAt: post.manual_publish_confirmed_at,
			reminderCount: post.reminder_count,
			accountUsername: account?.username || null,
			followUp:
				post.metadata && typeof post.metadata === "object"
					? (post.metadata as Record<string, unknown>).post_publish_follow_up || null
					: null,
		},
	});
}

export async function handleHandoffEvent(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (req.method !== "POST") return methodNotAllowed(res);
	const parsed = HandoffEventSchema.safeParse(req.body);
	if (!parsed.success) return apiError(res, 400, "Invalid handoff event");

	const { postId, event } = parsed.data as { postId: string; event: HandoffEvent };
	const eventUpdate = eventUpdates[event];
	const now = new Date().toISOString();

	const { data: post, error: fetchError } = await db()
		.from("posts")
		.select("id, metadata, status")
		.eq("id", postId)
		.eq("user_id", userId)
		.eq("platform", "instagram")
		.eq("publish_mode", "notify")
		.maybeSingle();

	if (fetchError) return apiError(res, 500, "Failed to load handoff post");
	if (!post) return apiError(res, 404, "Handoff post not found");
	if (post.status === "published" && event !== "completed") {
		return apiSuccess(res, { postId, event, handoffStatus: "completed" });
	}

	const updates: Record<string, unknown> = {
		handoff_status: eventUpdate.status,
		[eventUpdate.column]: now,
		updated_at: now,
	};

	if (event === "completed") {
		updates.status = "published";
		updates.published_at = now;
		updates.metadata = {
			...((post.metadata as Record<string, unknown> | null) || {}),
			manual_publish: true,
			manual_publish_confirmed_at: now,
		};
	}

	const { error } = await db()
		.from("posts")
		.update(updates)
		.eq("id", postId)
		.eq("user_id", userId)
		.eq("platform", "instagram")
		.eq("publish_mode", "notify");

	if (error) return apiError(res, 500, "Failed to update handoff event");
	return apiSuccess(res, { postId, event, handoffStatus: eventUpdate.status });
}

export async function handleHandoffFollowUp(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (req.method !== "POST") return methodNotAllowed(res);
	const parsed = HandoffFollowUpSchema.safeParse(req.body);
	if (!parsed.success) return apiError(res, 400, "Invalid handoff follow-up");

	const { postId, instagramUrl, notes } = parsed.data;
	const { data: post, error: fetchError } = await db()
		.from("posts")
		.select("id, metadata")
		.eq("id", postId)
		.eq("user_id", userId)
		.eq("platform", "instagram")
		.eq("publish_mode", "notify")
		.maybeSingle();

	if (fetchError) return apiError(res, 500, "Failed to load handoff post");
	if (!post) return apiError(res, 404, "Handoff post not found");

	const savedAt = new Date().toISOString();
	const followUp = {
		...(instagramUrl ? { instagramUrl: instagramUrl.slice(0, 240) } : {}),
		...(notes ? { notes: notes.slice(0, 500) } : {}),
		savedAt,
	};
	const metadata = {
		...((post.metadata as Record<string, unknown> | null) || {}),
		post_publish_follow_up: followUp,
	};

	const { error } = await db()
		.from("posts")
		.update({ metadata, updated_at: savedAt })
		.eq("id", postId)
		.eq("user_id", userId)
		.eq("platform", "instagram")
		.eq("publish_mode", "notify");

	if (error) return apiError(res, 500, "Failed to save handoff follow-up");
	return apiSuccess(res, { postId, followUp });
}
