import "dotenv/config";
import { createClient } from "@supabase/supabase-js";
import { decrypt } from "../api/_lib/encryption.ts";
const FB_LOGIN_WEBHOOK_FIELDS = "feed,comments,live_comments,mentions,messages,message_reactions,messaging_postbacks,messaging_seen,messaging_referral,messaging_optins,message_edit";
// NOTE (WEBHOOK-3): story_insights webhook events are only available for Facebook Login accounts,
// not Instagram Login. If story_insights is needed, the account must use the Facebook Login flow.
const IG_LOGIN_WEBHOOK_FIELDS = "comments,live_comments,mentions,messages,message_reactions,messaging_postbacks,messaging_seen,messaging_referral,messaging_optins,messaging_handover,standby,message_edit";

async function subscribePageToWebhooks(
  pageId: string,
  pageAccessToken: string,
): Promise<{ success: boolean; error?: string }> {
  try {
    const subscribeUrl = `https://graph.facebook.com/v25.0/${pageId}/subscribed_apps`;
    const response = await fetch(subscribeUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        subscribed_fields: FB_LOGIN_WEBHOOK_FIELDS,
        access_token: pageAccessToken,
      }),
      signal: AbortSignal.timeout(15000),
    });

    const data = await response.json();

    if (!response.ok || data.error) {
      return {
        success: false,
        error: data.error?.message || "Subscription failed",
      };
    }

    return { success: true };
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : String(error) };
  }
}

async function subscribeInstagramUserToWebhooks(
  instagramUserId: string,
  instagramAccessToken: string,
): Promise<{ success: boolean; error?: string }> {
  try {
    const subscribeUrl = `https://graph.instagram.com/v25.0/${instagramUserId}/subscribed_apps`;
    const response = await fetch(subscribeUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        subscribed_fields: IG_LOGIN_WEBHOOK_FIELDS,
        access_token: instagramAccessToken,
      }),
      signal: AbortSignal.timeout(15000),
    });

    const data = await response.json();

    if (!response.ok || data.error) {
      return {
        success: false,
        error: data.error?.message || "Subscription failed",
      };
    }

    return { success: true };
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : String(error) };
  }
}

type InstagramAccountRecord = {
  id: string;
  login_type: "instagram" | "facebook" | null;
  instagram_user_id: string | null;
  instagram_access_token_encrypted: string | null;
  facebook_page_id: string | null;
  facebook_page_access_token_encrypted: string | null;
};

async function main() {
  const supabaseUrl = process.env.SUPABASE_URL;
  const supabaseServiceKey =
    process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.SUPABASE_SERVICE_KEY;

  if (!supabaseUrl || !supabaseServiceKey) {
    throw new Error(
      "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured to resubscribe webhooks.",
    );
  }

  const supabase = createClient(supabaseUrl, supabaseServiceKey);

  const { data: accounts, error } = await supabase
    .from("instagram_accounts")
    .select(
      "id, login_type, instagram_user_id, instagram_access_token_encrypted, facebook_page_id, facebook_page_access_token_encrypted",
    );

  if (error) {
    throw error;
  }

  if (!accounts || accounts.length === 0) {
    console.log("No Instagram accounts found — nothing to resubscribe.");
    return;
  }

  let success = 0;
  let failed = 0;

  for (const account of accounts as InstagramAccountRecord[]) {
    const loginType = account.login_type || "instagram";

    try {
      if (loginType === "facebook") {
        if (!account.facebook_page_id || !account.facebook_page_access_token_encrypted) {
          throw new Error("Missing Facebook Page credentials");
        }
        const pageToken = decrypt(account.facebook_page_access_token_encrypted);
        const result = await subscribePageToWebhooks(account.facebook_page_id, pageToken);
        if (!result.success) {
          throw new Error(result.error || "Subscription failed");
        }
      } else {
        if (!account.instagram_user_id || !account.instagram_access_token_encrypted) {
          throw new Error("Missing Instagram token");
        }
        const igToken = decrypt(account.instagram_access_token_encrypted);
        const result = await subscribeInstagramUserToWebhooks(
          account.instagram_user_id,
          igToken,
        );
        if (!result.success) {
          throw new Error(result.error || "Subscription failed");
        }
      }
      success++;
      console.log(
        `[resubscribe] ✅ ${account.id} (${loginType}) resubscribed successfully`,
      );
    } catch (err) {
      failed++;
      console.warn(
        `[resubscribe] ⚠️ ${account.id} (${loginType}) failed: ${
          err instanceof Error ? err.message : String(err)
        }`,
      );
    }
  }

  console.log(
    `[resubscribe] Completed. Success: ${success}, Failed: ${failed}, Total: ${accounts.length}`,
  );
}

main().catch((err) => {
  console.error("[resubscribe] Fatal error", err);
  process.exit(1);
});
