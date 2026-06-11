import * as webPush from "web-push";
import { logger } from "./logger.js";
import { getSupabaseAny } from "./supabase.js";

type PushSubscriptionRow = {
	id: string;
	endpoint: string;
	p256dh: string;
	auth: string;
};

export type WebPushPayload = {
	title: string;
	body: string;
	tag?: string | undefined;
	data?: Record<string, unknown> | undefined;
	requireInteraction?: boolean | undefined;
	icon?: string | undefined;
	badge?: string | undefined;
};

export type WebPushResult = {
	configured: boolean;
	attempted: number;
	sent: number;
	expired: number;
	failed: number;
};

const db = () => getSupabaseAny();

function vapidDetails() {
	const publicKey = process.env.VAPID_PUBLIC_KEY;
	const privateKey = process.env.VAPID_PRIVATE_KEY;
	if (!publicKey || !privateKey) return null;
	return {
		subject: process.env.VAPID_SUBJECT || "mailto:support@juno33.com",
		publicKey,
		privateKey,
	};
}

function statusCodeFromError(error: unknown): number | null {
	const record = error as { statusCode?: unknown; status?: unknown } | null;
	const value = record?.statusCode ?? record?.status;
	return typeof value === "number" ? value : null;
}

export async function sendWebPushToUser(
	userId: string,
	payload: WebPushPayload,
): Promise<WebPushResult> {
	const vapid = vapidDetails();
	if (!vapid) {
		logger.warn("[web-push] VAPID keys not configured", { userId });
		return { configured: false, attempted: 0, sent: 0, expired: 0, failed: 0 };
	}

	const { data, error } = (await db()
		.from("push_subscriptions")
		.select("id, endpoint, p256dh, auth")
		.eq("user_id", userId)) as {
		data: PushSubscriptionRow[] | null;
		error: { message?: string | undefined } | null;
	};

	if (error) {
		logger.warn("[web-push] Subscription lookup failed", {
			userId,
			error: error.message,
		});
		return { configured: true, attempted: 0, sent: 0, expired: 0, failed: 1 };
	}

	const subscriptions = data ?? [];
	let sent = 0;
	let expired = 0;
	let failed = 0;
	const expiredIds: string[] = [];
	const serializedPayload = JSON.stringify({
		icon: "/icon-192.png",
		badge: "/favicon.svg",
		...payload,
	});

	await Promise.all(
		subscriptions.map(async (subscription) => {
			try {
				await webPush.sendNotification(
					{
						endpoint: subscription.endpoint,
						keys: {
							p256dh: subscription.p256dh,
							auth: subscription.auth,
						},
					},
					serializedPayload,
					{ vapidDetails: vapid, TTL: 60 * 60 },
				);
				sent++;
				await db()
					.from("push_subscriptions")
					.update({ last_used_at: new Date().toISOString() })
					.eq("id", subscription.id);
			} catch (err) {
				const statusCode = statusCodeFromError(err);
				if (statusCode === 404 || statusCode === 410) {
					expired++;
					expiredIds.push(subscription.id);
					return;
				}
				failed++;
				logger.warn("[web-push] Send failed", {
					userId,
					subscriptionId: subscription.id,
					statusCode,
					error: String(err),
				});
			}
		}),
	);

	if (expiredIds.length > 0) {
		await db().from("push_subscriptions").delete().in("id", expiredIds);
	}

	return {
		configured: true,
		attempted: subscriptions.length,
		sent,
		expired,
		failed,
	};
}
