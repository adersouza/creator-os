import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess, methodNotAllowed } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { z } from "../../zodCompat.js";

const ALLOWED_EVENTS = new Set([
	"composer_opened",
	"composer_media_upload_success",
	"composer_media_upload_failure",
	"composer_readiness_fix_clicked",
	"composer_schedule_success",
	"composer_schedule_failure",
	"composer_notify_push_state",
	"handoff_opened",
	"handoff_completed",
	"web_vitals",
	"first_post_wizard_opened",
	"first_post_wizard_step_completed",
	"account_readiness_action_clicked",
	"pwa_setup_step_completed",
	"calendar_command_used",
	"post_publish_followup_saved",
	"empty_state_cta_clicked",
]);

const BLOCKED_KEYS = /caption|content|text|body|url|media|token|secret|email/i;

const ClientEventSchema = z.object({
	event: z.string().min(1).max(80),
	route: z.string().max(160).optional(),
	properties: z.record(z.unknown()).optional(),
});

function hasBlockedPropertyKey(input: Record<string, unknown> | undefined) {
	return Object.keys(input ?? {}).some((key) => BLOCKED_KEYS.test(key));
}

function sanitizeProperties(input: Record<string, unknown> | undefined) {
	const output: Record<string, unknown> = {};
	for (const [key, value] of Object.entries(input ?? {})) {
		if (BLOCKED_KEYS.test(key)) continue;
		if (
			typeof value === "string" ||
			typeof value === "number" ||
			typeof value === "boolean" ||
			value === null
		) {
			output[key] = typeof value === "string" ? value.slice(0, 120) : value;
		}
	}
	return output;
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "POST") return methodNotAllowed(res);

		const parsed = ClientEventSchema.safeParse(req.body);
		if (!parsed.success) return apiError(res, 400, "Invalid telemetry event");
		if (!ALLOWED_EVENTS.has(parsed.data.event)) {
			return apiError(res, 400, "Unsupported telemetry event");
		}
		if (hasBlockedPropertyKey(parsed.data.properties)) {
			return apiError(res, 400, "Telemetry properties cannot include content fields");
		}

		const rl = await checkRateLimit({
			key: `client-telemetry:${user.id}`,
			limit: 120,
			windowSeconds: 60,
			failMode: "open",
		});
		if (!rl.allowed) return apiError(res, 429, "Too many telemetry events");

		logger.info("[client-telemetry]", {
			userId: user.id,
			event: parsed.data.event,
			route: parsed.data.route?.slice(0, 160) ?? null,
			properties: sanitizeProperties(parsed.data.properties),
		});

		return apiSuccess(res, { accepted: true });
	},
);
