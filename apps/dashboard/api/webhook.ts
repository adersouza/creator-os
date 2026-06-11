/**
 * Stripe Webhook Handler
 * POST /api/webhook
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { buffer } from "micro";
import type Stripe from "stripe";
import { apiError, apiSuccess } from "./_lib/apiResponse.js";
import { logger } from "./_lib/logger.js";
import {
	getPrivilegedSupabase,
	PRIVILEGED_DB_REASONS,
} from "./_lib/privilegedDb.js";
import { getStripe } from "./_lib/stripeClient.js";

export const config = {
	api: {
		bodyParser: false,
	},
};

const db = () => getPrivilegedSupabase(PRIVILEGED_DB_REASONS.stripeWebhook);

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	if (!process.env.STRIPE_SECRET_KEY) {
		logger.error("STRIPE_SECRET_KEY is not configured — rejecting webhook");
		return apiError(res, 500, "Stripe configuration missing");
	}

	const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET || "";
	if (!webhookSecret) {
		logger.error("STRIPE_WEBHOOK_SECRET is not configured — rejecting webhook");
		return apiError(res, 500, "Webhook not configured");
	}

	let event: Stripe.Event;
	let stripe: Stripe;

	try {
		const buf = await buffer(req);
		const sig = req.headers["stripe-signature"] as string;
		if (!sig) {
			return apiError(res, 400, "Missing stripe-signature header");
		}
		stripe = getStripe();
		event = stripe.webhooks.constructEvent(buf, sig, webhookSecret);
	} catch (err: unknown) {
		logger.error("Webhook signature verification failed", {
			error: err instanceof Error ? err.message : String(err),
		});
		return apiError(res, 400, "Webhook signature verification failed");
	}

	// Atomic idempotency claim using the PRIMARY KEY constraint as the lock.
	// INSERT wins the race for the first delivery; all concurrent duplicates
	// hit a unique constraint violation and are handled separately.
	// This eliminates the read-then-write TOCTOU that allowed double-processing.
	const STALE_LOCK_MS = 5 * 60 * 1000; // 5 min > max Vercel function duration (60s)

	const { error: claimError } = await db()
		.from("stripe_processed_events")
		.insert({
			event_id: event.id,
			event_type: event.type,
			status: "processing",
			claimed_at: new Date().toISOString(),
		});

	if (claimError) {
		// Primary key conflict: another invocation has (or had) this event.
		const { data: existing } = await db()
			.from("stripe_processed_events")
			.select("status, claimed_at")
			.eq("event_id", event.id)
			.maybeSingle();

		if (existing?.status === "completed") {
			logger.info("[webhook] Duplicate Stripe event (completed), skipping", {
				eventId: event.id,
				type: event.type,
			});
			return apiSuccess(res, { received: true, duplicate: true });
		}

		// status === "processing": either a concurrent live delivery or a stale
		// lock left by a Vercel function that timed out / crashed.
		const lockAge = existing?.claimed_at
			? Date.now() - new Date(existing.claimed_at).getTime()
			: Infinity;

		if (lockAge < STALE_LOCK_MS) {
			// Fresh lock — another instance is actively handling this event right now.
			// Return 200 so Stripe does not retry; that other instance will finish.
			logger.info("[webhook] Concurrent event delivery, deferring to owner", {
				eventId: event.id,
				type: event.type,
			});
			return apiSuccess(res, { received: true, deferred: true });
		}

		// Stale lock — previous handler crashed. Re-claim by updating claimed_at.
		// The .eq("status","processing") guard prevents stomping a completed row
		// that was written between the SELECT and this UPDATE.
		const { error: reclaimError } = await db()
			.from("stripe_processed_events")
			.update({ claimed_at: new Date().toISOString() })
			.eq("event_id", event.id)
			.eq("status", "processing");

		if (reclaimError) {
			// Lost the re-claim race to another Stripe retry; bail out safely.
			logger.info("[webhook] Lost re-claim race for stale event, skipping", {
				eventId: event.id,
			});
			return apiSuccess(res, { received: true, deferred: true });
		}

		logger.info("[webhook] Re-claimed stale processing lock for retry", {
			eventId: event.id,
			lockAgeMs: lockAge,
		});
	}

	// Probabilistic inline cleanup (~1% of requests) as safety net for
	// stripe_processed_events growth if daily-maintenance cron fails.
	if (Math.random() < 0.01) {
		const cutoff72h = new Date(Date.now() - 72 * 60 * 60 * 1000).toISOString();
		void db()
			.from("stripe_processed_events")
			.delete()
			.lt("processed_at", cutoff72h)
			.then(() => {});
	}

	try {
		const { STRIPE_EVENT_HANDLER_MAP } = await import("./_lib/handlers/webhook/stripeEvents.js");
		const eventHandler = STRIPE_EVENT_HANDLER_MAP[event.type];
		if (eventHandler) {
			await eventHandler(event, { stripe, supabase: db(), logger });
		} else {
			logger.info("[webhook] Unhandled Stripe event type", {
				eventType: event.type,
				eventId: event.id,
			});
		}

		// Mark as completed after successful processing.
		// NON-CRITICAL: If this fails, the event may be reprocessed on Stripe retry,
		// but the handler is idempotent so that's safe.
		const { error: completeErr } = await db()
			.from("stripe_processed_events")
			.update({ status: "completed", processed_at: new Date().toISOString() })
			.eq("event_id", event.id);

		if (completeErr) {
			logger.warn("[webhook] Non-critical: failed to mark event as completed", {
				eventId: event.id,
				error: completeErr.message,
			});
		}

		return apiSuccess(res, { received: true });
	} catch (error: unknown) {
		logger.error("Webhook handler error", {
			error: String(error),
			eventId: event.id,
			eventType: event.type,
		});
		// Leave status as "processing" so Stripe's retry can re-deliver
		return apiError(res, 500, "Internal server error");
	}
}
