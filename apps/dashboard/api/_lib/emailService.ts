/**
 * Email Service — Resend wrapper for all transactional emails
 */

const FROM_DEFAULT = "Juno33 <noreply@juno33.com>";
const FROM_REPORTS = "Juno33 <reports@juno33.com>";

export interface EmailAttachment {
	filename: string;
	/** Base64-encoded file contents (no data: prefix) */
	content: string;
}

async function sendEmail(
	to: string,
	subject: string,
	html: string,
	from: string = FROM_DEFAULT,
	attachments?: EmailAttachment[],
): Promise<{ success: boolean; error?: string | undefined }> {
	const apiKey = process.env.RESEND_API_KEY;
	if (!apiKey)
		return { success: false, error: "RESEND_API_KEY not configured" };

	try {
		const payload: Record<string, unknown> = {
			from,
			to: [to],
			subject,
			html,
		};
		if (attachments && attachments.length > 0) {
			payload.attachments = attachments;
		}
		const response = await fetch("https://api.resend.com/emails", {
			method: "POST",
			headers: {
				Authorization: `Bearer ${apiKey}`,
				"Content-Type": "application/json",
			},
			body: JSON.stringify(payload),
			signal: AbortSignal.timeout(15000),
		});

		if (!response.ok) {
			const err = await response.text();
			return { success: false, error: err };
		}
		return { success: true };
	} catch (err: unknown) {
		return {
			success: false,
			error: err instanceof Error ? err.message : String(err),
		};
	}
}

// ─── Template Wrapper ───────────────────────────────────────────────────────

function wrap(body: string): string {
	return `<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0b0b0d;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;margin:0 auto;padding:40px 24px">
    <tr><td>
      <div style="text-align:center;margin-bottom:32px">
        <span style="font-size:20px;font-weight:700;color:#f4f4f5;letter-spacing:0.02em">Juno33</span>
      </div>
      ${body}
      <div style="text-align:center;margin-top:40px;padding-top:24px;border-top:1px solid rgba(255,255,255,0.06)">
        <span style="font-size:12px;color:rgba(255,255,255,0.3)">Juno33 — Threads & Instagram Analytics</span>
      </div>
    </td></tr>
  </table>
</body>
</html>`;
}

// ─── Email Types ─────────────────────────────────────────────────────────────

export async function sendWelcomeEmail(
	to: string,
	displayName: string,
): Promise<{ success: boolean; error?: string | undefined }> {
	const html = wrap(`
    <h1 style="color:#f4f4f5;font-size:28px;font-weight:700;margin:0 0 16px">Welcome${displayName ? `, ${displayName}` : ""}!</h1>
    <p style="color:rgba(255,255,255,0.6);font-size:15px;line-height:1.6;margin:0 0 24px">
      You're in. Juno33 is your command center for Threads and Instagram growth.
    </p>
    <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:24px;margin-bottom:24px">
      <p style="color:rgba(255,255,255,0.5);font-size:13px;margin:0 0 12px;text-transform:uppercase;letter-spacing:0.15em;font-weight:600">Get Started</p>
      <p style="color:rgba(255,255,255,0.6);font-size:14px;line-height:1.6;margin:0">
        <strong style="color:#f4f4f5">1.</strong> Connect your Threads account<br>
        <strong style="color:#f4f4f5">2.</strong> Connect Instagram (optional)<br>
        <strong style="color:#f4f4f5">3.</strong> Start posting & tracking growth
      </p>
    </div>
    <div style="text-align:center">
      <a href="${process.env.APP_URL || "https://juno33.com"}/dashboard" 
         style="display:inline-block;background:#f4f4f5;color:#09090b;padding:12px 32px;border-radius:12px;font-weight:700;font-size:14px;text-decoration:none">
        Open Dashboard →
      </a>
    </div>
  `);
	return sendEmail(to, "Welcome to Juno33 🚀", html);
}

export async function sendSubscriptionConfirmation(
	to: string,
	tier: "pro" | "agency" | "empire",
	interval: "monthly" | "yearly",
): Promise<{ success: boolean; error?: string | undefined }> {
	const tierName =
		tier === "empire" ? "Empire" : tier === "agency" ? "Agency" : "Pro";
	const features =
		tier === "empire"
			? "Unlimited accounts, auto-poster, AI studio, team collaboration"
			: tier === "agency"
				? "Team workspaces, approvals, analytics, and AI studio"
			: "Up to 5 accounts, auto-poster, AI studio";

	const html = wrap(`
    <h1 style="color:#f4f4f5;font-size:28px;font-weight:700;margin:0 0 16px">You're on ${tierName}!</h1>
    <p style="color:rgba(255,255,255,0.6);font-size:15px;line-height:1.6;margin:0 0 24px">
      Your ${tierName} ${interval} subscription is now active.
    </p>
    <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:24px;margin-bottom:24px">
      <p style="color:rgba(255,255,255,0.5);font-size:13px;margin:0 0 8px;text-transform:uppercase;letter-spacing:0.15em;font-weight:600">${tierName} Plan</p>
      <p style="color:rgba(255,255,255,0.6);font-size:14px;line-height:1.6;margin:0">${features}</p>
    </div>
    <div style="text-align:center">
      <a href="${process.env.APP_URL || "https://juno33.com"}/settings" 
         style="display:inline-block;background:#f4f4f5;color:#09090b;padding:12px 32px;border-radius:12px;font-weight:700;font-size:14px;text-decoration:none">
        Manage Subscription
      </a>
    </div>
  `);
	return sendEmail(to, `Welcome to Juno33 ${tierName} ✨`, html);
}

export async function sendSubscriptionCancelled(
	to: string,
	endsAt: string,
): Promise<{ success: boolean; error?: string | undefined }> {
	const html = wrap(`
    <h1 style="color:#f4f4f5;font-size:28px;font-weight:700;margin:0 0 16px">Subscription Cancelled</h1>
    <p style="color:rgba(255,255,255,0.6);font-size:15px;line-height:1.6;margin:0 0 24px">
      Your subscription has been cancelled. You'll retain access until <strong style="color:#f4f4f5">${endsAt}</strong>.
    </p>
    <p style="color:rgba(255,255,255,0.4);font-size:14px;line-height:1.6;margin:0 0 24px">
      Changed your mind? You can resubscribe anytime from your settings.
    </p>
    <div style="text-align:center">
      <a href="${process.env.APP_URL || "https://juno33.com"}/settings" 
         style="display:inline-block;background:rgba(255,255,255,0.08);color:#f4f4f5;padding:12px 32px;border-radius:12px;font-weight:700;font-size:14px;text-decoration:none;border:1px solid rgba(255,255,255,0.1)">
        Resubscribe
      </a>
    </div>
  `);
	return sendEmail(to, "Your Juno33 subscription has been cancelled", html);
}

export async function sendPaymentFailed(
	to: string,
	attemptCount: number,
): Promise<{ success: boolean; error?: string | undefined }> {
	const html = wrap(`
    <h1 style="color:#f4f4f5;font-size:28px;font-weight:700;margin:0 0 16px">Payment Failed</h1>
    <p style="color:rgba(255,255,255,0.6);font-size:15px;line-height:1.6;margin:0 0 24px">
      We couldn't process your payment${attemptCount > 1 ? ` (attempt ${attemptCount})` : ""}. Please update your payment method to keep your account active.
    </p>
    <div style="text-align:center">
      <a href="${process.env.APP_URL || "https://juno33.com"}/settings" 
         style="display:inline-block;background:#f4f4f5;color:#09090b;padding:12px 32px;border-radius:12px;font-weight:700;font-size:14px;text-decoration:none">
        Update Payment →
      </a>
    </div>
  `);
	return sendEmail(to, "⚠️ Payment failed — action needed", html);
}

export async function sendTrialEndingSoon(
	to: string,
	daysLeft: number,
): Promise<{ success: boolean; error?: string | undefined }> {
	const html = wrap(`
    <h1 style="color:#f4f4f5;font-size:28px;font-weight:700;margin:0 0 16px">Trial ending in ${daysLeft} day${daysLeft !== 1 ? "s" : ""}</h1>
    <p style="color:rgba(255,255,255,0.6);font-size:15px;line-height:1.6;margin:0 0 24px">
      Your free trial is almost up. Subscribe now to keep your data and features.
    </p>
    <div style="text-align:center">
      <a href="${process.env.APP_URL || "https://juno33.com"}/settings" 
         style="display:inline-block;background:#f4f4f5;color:#09090b;padding:12px 32px;border-radius:12px;font-weight:700;font-size:14px;text-decoration:none">
        Choose a Plan →
      </a>
    </div>
  `);
	return sendEmail(to, `Your trial ends in ${daysLeft} days`, html);
}

// Keep backward compat
export async function sendReportEmail(
	to: string,
	subject: string,
	htmlContent: string,
	attachments?: EmailAttachment[],
): Promise<{ success: boolean; error?: string | undefined }> {
	return sendEmail(to, subject, htmlContent, FROM_REPORTS, attachments);
}
