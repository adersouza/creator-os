import * as crypto from "node:crypto";
import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
  apiError,
  apiSuccess,
  badRequest,
  methodNotAllowed,
} from "../../apiResponse.js";
import { decrypt, encrypt } from "../../encryption.js";
import { withAuthDb } from "../../middleware.js";
import { validateUrlNotPrivate } from "../../ssrfProtection.js";
import { z, zEnum } from "../../zodCompat.js";

const EVENTS = [
  "post_published",
  "post_failed",
  "account_reconnect_needed",
  "report_sent",
] as const;

const CreateWebhookSchema = z.object({
  url: z.string().url(),
  events: z.array(zEnum(EVENTS)).min(1),
});

function signature(secret: string, payload: string): string {
  return `sha256=${crypto.createHmac("sha256", secret).update(payload).digest("hex")}`;
}

function signedHeaders(
  secret: string,
  payload: string,
  event: string,
): Record<string, string> {
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const deliveryId = crypto.randomUUID();
  return {
    "X-Juno33-Event": event,
    "X-Juno33-Timestamp": timestamp,
    "X-Juno33-Delivery-Id": deliveryId,
    "X-Juno33-Signature-256": signature(secret, payload),
    "X-Juno33-Signature-V2": `v2=${crypto
      .createHmac("sha256", secret)
      .update(`${timestamp}.${deliveryId}.${payload}`)
      .digest("hex")}`,
  };
}

async function sendTest(url: string, secret: string) {
  const payload = JSON.stringify({
    event: "test",
    timestamp: new Date().toISOString(),
    data: { message: "Test event from Juno33" },
  });
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Juno33-Event": "test",
      ...signedHeaders(secret, payload, "test"),
    },
    body: payload,
    signal: AbortSignal.timeout(10000),
  });
  return { status: response.status, ok: response.ok };
}

export default withAuthDb(
  async (req: VercelRequest, res: VercelResponse, context) => {
    const { user, userDb } = context;

    if (req.method === "GET") {
      const { data, error } = await userDb
        .from("user_webhooks")
        .select("id, url, events, is_active, last_triggered_at, created_at")
        .eq("user_id", user.id)
        .order("created_at", { ascending: false });
      if (error) return apiError(res, 500, "Failed to load webhooks");
      return apiSuccess(res, { webhooks: data ?? [] });
    }

    if (req.method === "POST") {
      if (req.body?.mode === "test") {
        const id = String(req.body.id ?? "");
        if (!id) return badRequest(res, "id is required");
        const { data: webhook, error } = await userDb
          .from("user_webhooks")
          .select("id, url, secret")
          .eq("id", id)
          .eq("user_id", user.id)
          .maybeSingle();
        if (error) return apiError(res, 500, "Failed to load webhook");
        if (!webhook) return apiError(res, 404, "Webhook not found");
        const ssrfError = await validateUrlNotPrivate(webhook.url);
        if (ssrfError) return apiError(res, 400, "Invalid webhook URL");
        try {
          // secret may be encrypted (new) or plaintext (legacy) — try decrypt with fallback
          let plaintextSecret = webhook.secret as string;
          try {
            plaintextSecret = decrypt(webhook.secret as string);
          } catch {
            // legacy plaintext entry — use as-is
          }
          const result = await sendTest(webhook.url, plaintextSecret);
          await userDb
            .from("user_webhooks")
            .update({ last_triggered_at: new Date().toISOString() })
            .eq("id", id)
            .eq("user_id", user.id);
          return apiSuccess(res, result);
        } catch {
          return apiError(res, 400, "Failed to reach webhook URL");
        }
      }

      const parsed = CreateWebhookSchema.safeParse(req.body);
      if (!parsed.success)
        return apiError(
          res,
          400,
          parsed.error.issues[0]?.message || "Invalid webhook",
        );
      const ssrfError = await validateUrlNotPrivate(parsed.data.url);
      if (ssrfError) return apiError(res, 400, "Invalid webhook URL");
      const secret = crypto.randomBytes(24).toString("hex");
      const { data, error } = await userDb
        .from("user_webhooks")
        .insert({
          user_id: user.id,
          url: parsed.data.url,
          events: parsed.data.events,
          secret: encrypt(secret),
          is_active: true,
        })
        .select("id, url, events, is_active, last_triggered_at, created_at")
        .maybeSingle();
      if (error) return apiError(res, 500, "Failed to create webhook");
      return apiSuccess(res, { webhook: data, secret });
    }

    if (req.method === "DELETE") {
      const id = String(req.body?.id ?? "");
      if (!id) return badRequest(res, "id is required");
      const { error, count } = await userDb
        .from("user_webhooks")
        .delete({ count: "exact" })
        .eq("id", id)
        .eq("user_id", user.id);
      if (error) return apiError(res, 500, "Failed to delete webhook");
      if (!count) return apiError(res, 404, "Webhook not found");
      return apiSuccess(res, { deleted: true });
    }

    return methodNotAllowed(res);
  },
);
