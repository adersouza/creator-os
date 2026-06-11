import * as crypto from "node:crypto";
import { decrypt, needsUpgrade } from "./encryption.js";
import { logger } from "./logger.js";
import { validateUrlNotPrivate } from "./ssrfProtection.js";
import { getSupabase } from "./supabase.js";

// #620: Decrypt webhook secret, falling back to plaintext for legacy entries.
// Tracked failures help spot corrupted ciphertexts (key rotation regression)
// vs legitimate plaintext-from-old-rows.
function decryptSecret(secret: string): string {
  try {
    return decrypt(secret);
  } catch (err) {
    if (secret.startsWith("v2:") || needsUpgrade(secret)) {
      logger.error("[webhookDispatcher] encrypted secret decrypt failed", {
        error: String(err),
      });
      throw err;
    }
    logger.warn(
      "[webhookDispatcher] secret decrypt failed, using plaintext fallback",
      { error: String(err) },
    );
    return secret;
  }
}

function buildSignedHeaders(
  event: string,
  payload: string,
  secret?: string,
  deliveryId: string = crypto.randomUUID(),
): Record<string, string> {
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Juno33-Event": event,
    "X-Juno33-Timestamp": timestamp,
    "X-Juno33-Delivery-Id": deliveryId,
  };

  if (secret) {
    const decrypted = decryptSecret(secret);
    headers["X-Juno33-Signature-256"] =
      "sha256=" +
      crypto.createHmac("sha256", decrypted).update(payload).digest("hex");
    headers["X-Juno33-Signature-V2"] =
      "v2=" +
      crypto
        .createHmac("sha256", decrypted)
        .update(`${timestamp}.${deliveryId}.${payload}`)
        .digest("hex");
  }

  return headers;
}

type WebhookEvent =
  | "post.published"
  | "post.scheduled"
  | "sync.completed"
  | "quickwin.solved"
  | "ces.milestone"
  | "analytics.updated";

const USER_WEBHOOK_EVENT_MAP: Partial<Record<WebhookEvent, string>> = {
  "post.published": "post_published",
};

/**
 * Dispatch outgoing webhook events to user-subscribed URLs.
 *
 * - Free tier: fire-and-forget (best effort, no retry)
 * - Pro/Empire: queued to `webhook_deliveries` table with 3-attempt retry
 */
export async function dispatchWebhook(
  userId: string,
  event: WebhookEvent,
  data: Record<string, unknown>,
) {
  try {
    await dispatchUserWebhook(userId, event, data);

    const { data: webhooks, error } = await getSupabase()
      .from("webhook_subscriptions")
      .select("id, url, secret, events")
      .eq("user_id", userId)
      .eq("active", true);

    if (error) {
      logger.warn("Webhook subscriptions query failed (table may not exist)", {
        error: String(error),
      });
      return;
    }

    if (!webhooks?.length) return;

    const matching = webhooks.filter((w: { events?: string[] | undefined }) =>
      w.events?.includes(event),
    );
    if (matching.length === 0) return;

    // Check user tier to decide delivery mode
    const { getUserTier } = await import("./tierGate.js");
    const tier = await getUserTier(userId);
    const useReliableDelivery =
      tier === "pro" || tier === "empire" || tier === "agency";

    for (const webhook of matching) {
      const payloadObj = {
        event,
        timestamp: new Date().toISOString(),
        data,
      };
      const payload = JSON.stringify(payloadObj);

      if (useReliableDelivery) {
        // Queue for reliable delivery with retries
        await queueWebhookDelivery(webhook.id, userId, event, payloadObj);
      } else {
        // Fire and forget for free tier — don't block the main flow
        deliverWebhookNow(
          { ...webhook, secret: webhook.secret ?? undefined },
          event,
          payload,
        );
      }
    }
  } catch (err) {
    logger.error("Webhook dispatch error", {
      userId,
      event,
      error: String(err),
    });
  }
}

async function dispatchUserWebhook(
  userId: string,
  event: WebhookEvent,
  data: Record<string, unknown>,
) {
  const mappedEvent = USER_WEBHOOK_EVENT_MAP[event];
  if (!mappedEvent) return;
  const { data: webhooks, error } = await getSupabase()
    .from("user_webhooks" as never)
    .select("id, url, secret, events")
    .eq("user_id", userId)
    .eq("is_active", true);
  if (error || !webhooks?.length) return;

  const matching = (
    webhooks as Array<{
      id: string;
      url: string;
      secret: string;
      events?: string[] | undefined;
    }>
  ).filter((webhook) => webhook.events?.includes(mappedEvent));
  if (matching.length === 0) return;

  const payload = JSON.stringify({
    event: mappedEvent,
    timestamp: new Date().toISOString(),
    data,
  });
  for (const webhook of matching) {
    deliverWebhookNow(webhook, mappedEvent, payload);
    await getSupabase()
      .from("user_webhooks" as never)
      .update({ last_triggered_at: new Date().toISOString() } as never)
      .eq("id", webhook.id);
  }
}

/**
 * Queue a webhook delivery for reliable processing with retries.
 */
async function queueWebhookDelivery(
  subscriptionId: string,
  userId: string,
  event: WebhookEvent,
  payload: Record<string, unknown>,
): Promise<void> {
  try {
    await getSupabase()
      .from("webhook_deliveries")
      .insert({
        subscription_id: subscriptionId,
        user_id: userId,
        event,
        payload,
        status: "pending",
        next_retry_at: new Date().toISOString(),
        // biome-ignore lint/suspicious/noExplicitAny: custom event field not in generated Supabase types
      } as any);
  } catch (err) {
    logger.error("Failed to queue webhook delivery", {
      subscriptionId,
      event,
      error: String(err),
    });
    // Fall back to fire-and-forget if queue insert fails
    try {
      const { data: webhook } = await getSupabase()
        .from("webhook_subscriptions")
        .select("id, url, secret")
        .eq("id", subscriptionId)
        .maybeSingle();
      if (webhook) {
        deliverWebhookNow(
          { ...webhook, secret: webhook.secret ?? undefined },
          event,
          JSON.stringify({
            event,
            timestamp: new Date().toISOString(),
            data: payload,
          }),
        );
      }
    } catch {
      // Best effort exhausted
    }
  }
}

/**
 * Immediately deliver a webhook (fire-and-forget).
 */
function deliverWebhookNow(
  webhook: { id: string; url: string; secret?: string | undefined },
  event: string,
  payload: string,
): void {
  let headers: Record<string, string>;
  try {
    headers = buildSignedHeaders(event, payload, webhook.secret);
  } catch (err) {
    logger.error("Webhook delivery skipped: secret decrypt failed", {
      webhookId: webhook.id,
      error: String(err),
    });
    return;
  }

  // #616: SSRF protection — validate webhook URL before dispatching
  validateUrlNotPrivate(webhook.url)
    .then((ssrfError) => {
      if (ssrfError) {
        logger.warn("Webhook blocked by SSRF protection", {
          webhookId: webhook.id,
          reason: ssrfError,
        });
        return;
      }
      return fetch(webhook.url, {
        method: "POST",
        headers,
        body: payload,
        signal: AbortSignal.timeout(15000),
      }).then(async (response) => {
        if (response.ok) return;
        const responseBody = await response.text().catch(() => "");
        logger.warn("Webhook delivery returned non-2xx", {
          webhookId: webhook.id,
          status: response.status,
          body: responseBody.slice(0, 500),
        });
      });
    })
    .catch((err) =>
      logger.error("Webhook delivery failed", {
        webhookId: webhook.id,
        error: String(err),
      }),
    );
}

/**
 * Process pending webhook deliveries with retry logic.
 * Called by the webhook-processor cron or a dedicated cron.
 *
 * Retry schedule: attempt 1 = immediate, attempt 2 = 1min, attempt 3 = 5min.
 * After max attempts, mark as dead_letter.
 */
export async function processWebhookDeliveries(): Promise<number> {
  const now = new Date().toISOString();
  let processed = 0;

  const { data: deliveries, error } = await getSupabase()
    .from("webhook_deliveries")
    .select("id, subscription_id, event, payload, attempts, max_attempts")
    .in("status", ["pending", "failed"])
    .lte("next_retry_at", now)
    .order("created_at", { ascending: true })
    .limit(100);

  if (error || !deliveries?.length) return 0;

  for (const delivery of deliveries) {
    try {
      // Fetch the subscription details
      const { data: webhook } = await getSupabase()
        .from("webhook_subscriptions")
        .select("url, secret, active")
        .eq("id", delivery.subscription_id)
        .maybeSingle();

      if (!webhook?.active) {
        // Subscription deleted or deactivated — mark as dead letter
        await getSupabase()
          .from("webhook_deliveries")
          .update({ status: "dead_letter", last_attempt_at: now })
          .eq("id", delivery.id);
        processed++;
        continue;
      }

      const payload = JSON.stringify(delivery.payload);
      const headers = buildSignedHeaders(
        delivery.event,
        payload,
        webhook.secret ?? undefined,
        delivery.id,
      );

      // #616: SSRF protection on queued deliveries too
      const ssrfError = await validateUrlNotPrivate(webhook.url);
      if (ssrfError) {
        await getSupabase()
          .from("webhook_deliveries")
          .update({
            status: "dead_letter",
            last_attempt_at: now,
            last_error: `SSRF blocked: ${ssrfError}`,
          })
          .eq("id", delivery.id);
        processed++;
        continue;
      }

      const response = await fetch(webhook.url, {
        method: "POST",
        headers,
        body: payload,
        signal: AbortSignal.timeout(15000),
      });

      const newAttempts = delivery.attempts + 1;

      if (response.ok) {
        await getSupabase()
          .from("webhook_deliveries")
          .update({
            status: "delivered",
            attempts: newAttempts,
            last_attempt_at: now,
            delivered_at: now,
          })
          .eq("id", delivery.id);
      } else if (response.status < 500) {
        // Client errors are terminal, but not successful. Keep them visible.
        const responseBody = await response.text().catch(() => "");
        await getSupabase()
          .from("webhook_deliveries")
          .update({
            status: "dead_letter",
            attempts: newAttempts,
            last_attempt_at: now,
            last_error: `HTTP ${response.status}${responseBody ? `: ${responseBody.slice(0, 500)}` : ""}`,
          })
          .eq("id", delivery.id);
      } else if (newAttempts >= delivery.max_attempts) {
        // Max retries exhausted
        await getSupabase()
          .from("webhook_deliveries")
          .update({
            status: "dead_letter",
            attempts: newAttempts,
            last_attempt_at: now,
            last_error: `HTTP ${response.status}`,
          })
          .eq("id", delivery.id);
      } else {
        // Schedule retry with exponential backoff (1min, 5min)
        const backoffMs = newAttempts === 1 ? 60_000 : 300_000;
        await getSupabase()
          .from("webhook_deliveries")
          .update({
            status: "failed",
            attempts: newAttempts,
            last_attempt_at: now,
            next_retry_at: new Date(Date.now() + backoffMs).toISOString(),
            last_error: `HTTP ${response.status}`,
          })
          .eq("id", delivery.id);
      }

      processed++;
    } catch (err) {
      const newAttempts = delivery.attempts + 1;
      const errMsg = err instanceof Error ? err.message : String(err);

      if (newAttempts >= delivery.max_attempts) {
        await getSupabase()
          .from("webhook_deliveries")
          .update({
            status: "dead_letter",
            attempts: newAttempts,
            last_attempt_at: now,
            last_error: errMsg,
          })
          .eq("id", delivery.id);
      } else {
        const backoffMs = newAttempts === 1 ? 60_000 : 300_000;
        await getSupabase()
          .from("webhook_deliveries")
          .update({
            status: "failed",
            attempts: newAttempts,
            last_attempt_at: now,
            next_retry_at: new Date(Date.now() + backoffMs).toISOString(),
            last_error: errMsg,
          })
          .eq("id", delivery.id);
      }
      processed++;
    }
  }

  if (processed > 0) {
    logger.info("[webhookDispatcher] Processed queued deliveries", {
      processed,
    });
  }

  return processed;
}
