/**
 * Notification Delivery — simplified for single operator
 *
 * In-app notifications are already inserted into the DB before this runs.
 * This module only adds Discord alerts for critical events.
 * Push and email delivery removed — single operator doesn't need 3 channels.
 */

import { logger } from "./logger.js";

interface DeliveryParams {
	userId: string;
	type: string;
	title: string;
	message: string;
	data?: Record<string, unknown> | undefined;
}

/** Critical types that also fire a Discord alert */
const DISCORD_TYPES = new Set([
	"post_failed",
	"token_expiring",
	"token_reauth_needed",
	"account_disconnected",
	"account_suspended",
	"agent_circuit_breaker",
	"queue_low",
	"post_rate_limited",
]);

/**
 * Deliver notification via Discord (critical types only).
 * In-app notification is already in the DB — this is supplementary.
 * Fire-and-forget — never throws.
 */
export async function deliverNotification(
	params: DeliveryParams,
): Promise<void> {
	const { type, title, message, data } = params;

	if (!DISCORD_TYPES.has(type)) return;

	try {
		const { alert, AlertLevel } = await import("./alerting.js");
		const context = Object.fromEntries(
			Object.entries(data ?? {})
				.filter(([, value]) =>
					["string", "number", "boolean"].includes(typeof value),
				)
				.slice(0, 6),
		) as Record<string, string | number | boolean>;
		await alert(AlertLevel.WARN, title, {
			type,
			detail: message.slice(0, 500),
			...context,
		});
	} catch (err) {
		logger.warn("Discord notification failed", { type, error: String(err) });
	}
}
