// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Middleware wrappers for Vercel API routes
 *
 * withCors()  — adds CORS headers + OPTIONS handling
 * withAuth()  — CORS + Bearer auth + error boundary + Sentry
 * withCron()  — cron secret auth + error boundary + Sentry
 */

import * as Sentry from "@sentry/node";
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, getAuthUserOrError, verifyCronAuth } from "./apiResponse.js";
import { createDbContext, type DbContext } from "./dbContext.js";
import { validateEnv } from "./envValidation.js";
import { logger } from "./logger.js";
import { getOrCreateRequestId } from "./requestId.js";

const ALLOWED_ORIGIN =
	process.env.APP_URL ||
	(process.env.VERCEL_URL
		? `https://${process.env.VERCEL_URL}`
		: "https://juno33.com");

/**
 * Pro Hardening Middleware
 * Ensures environment is valid, initializes tracing, and catches all errors.
 */
export function withProHardening(
	handler: (
		req: VercelRequest,
		res: VercelResponse,
	) => Promise<VercelResponse | undefined>,
) {
	return async (req: VercelRequest, res: VercelResponse) => {
		const requestId = getOrCreateRequestId(req, res);
		try {
			// 1. Fail Fast: Validate Environment
			validateEnv();

			// 2. Distributed Tracing
			return Sentry.continueTrace(
				{
					sentryTrace: (req.headers["sentry-trace"] as string) || "",
					baggage: (req.headers.baggage as string) || "",
				},
				async () => {
					return Sentry.startSpan(
						{
							name: `${req.method} ${req.url?.split("?")[0] || "unknown"}`,
							op: "http.server",
						},
						async () => {
							return handler(req, res);
						},
					);
				},
			);
		} catch (error) {
			logger.error("[Hardening] Fatal Error", {
				requestId,
				error: String(error),
			});
			return apiError(
				res,
				500,
				"Internal Server Error",
				{ details: error instanceof Error ? error.message : String(error) },
			);
		}
	};
}

/**
 * Wrap a handler with CORS headers.
 * Automatically responds to OPTIONS preflight.
 */
export function withCors(
	handler: (
		req: VercelRequest,
		res: VercelResponse,
	) => Promise<VercelResponse | undefined>,
) {
	return async (req: VercelRequest, res: VercelResponse) => {
		res.setHeader("Access-Control-Allow-Origin", ALLOWED_ORIGIN);
		res.setHeader(
			"Access-Control-Allow-Methods",
			"GET,OPTIONS,POST,PUT,DELETE",
		);
		res.setHeader(
			"Access-Control-Allow-Headers",
			"Content-Type, Authorization, sentry-trace, baggage, X-Agent-Session, X-Request-Id, Idempotency-Key, Prefer",
		);
		if (req.method === "OPTIONS") return res.status(200).end();
		return handler(req, res);
	};
}

/**
 * Wrap a handler with CORS + Bearer auth + error boundary.
 * Sends 401 if auth fails. Catches unhandled errors, reports to Sentry, returns 500.
 */
export function withAuth(
	handler: (
		req: VercelRequest,
		res: VercelResponse,
		user: { id: string; email?: string | undefined },
	) => Promise<VercelResponse | undefined>,
) {
	return withProHardening(
		withCors(async (req, res) => {
			const user = await getAuthUserOrError(req, res);
			if (!user) return; // 401 already sent
			const requestId = getOrCreateRequestId(req, res);
			const routeUrl = new URL(req.url ?? "/", "https://x");
			const route = routeUrl.pathname;
			const action = routeUrl.searchParams.get("action") ?? undefined;
			Sentry.setUser({ id: user.id });
			Sentry.setTags({
				request_id: requestId,
				route,
				method: req.method ?? "UNKNOWN",
				vercel_env: process.env.VERCEL_ENV ?? process.env.NODE_ENV ?? "unknown",
				release: process.env.VERCEL_GIT_COMMIT_SHA ?? "dev",
			});

			// ── Agent safety: kill switch + session limit + approval gate + circuit breaker ──
			// Detects agent requests via API key (juno_ak_*) OR X-Agent-Session header.
			// This ensures safety applies even if MCP uses JWT auth instead of API key.
			const token = req.headers.authorization?.slice(7) ?? "";
			const agentSessionId = req.headers["x-agent-session"] as
				| string
				| undefined;
			const isAgent = token.startsWith("juno_ak_") || !!agentSessionId;
			const reqPath = req.url?.split("?")[0] ?? "";

			if (isAgent && req.method !== "GET" && req.method !== "OPTIONS") {
				const isUnpauseCall =
					req.method === "PATCH" && reqPath.endsWith("/agent/settings");

				if (!isUnpauseCall) {
					const { getSupabase } = await import("./supabase.js");

					// 1. Kill switch — hard block on all agent writes
					// biome-ignore lint/suspicious/noExplicitAny: agent_paused not in generated types
					const { data: profile } = await (getSupabase() as any)
						.from("profiles")
						.select("agent_paused")
						.eq("id", user.id)
						.maybeSingle();
					if (profile?.agent_paused) {
						return apiError(res, 503, "Agent paused by user", {
							code: "AGENT_PAUSED",
						});
					}

					// 2. Session call limit (429 — does NOT trip breaker, just caps this session)
					if (agentSessionId) {
						try {
							const { checkSessionCallLimit } = await import(
								"./agentCircuitBreaker.js"
							);
							const sc = await checkSessionCallLimit(user.id, agentSessionId);
							if (!sc.allowed) {
								return apiError(
									res,
									429,
									`Session call limit exceeded (${sc.count}/${sc.limit}). Start a new session.`,
									{ code: "SESSION_LIMIT_EXCEEDED" },
								);
							}
						} catch {
							// Fail open
						}
					}

					// 3. Approval gate — block publish/schedule if a pending approval exists
					//    (agent requested approval but didn't wait for user decision)
					//    Interactive use (no pending approvals) is NOT blocked.
					try {
						const actionParam = new URL(
							req.url ?? "/",
							"https://x",
						).searchParams.get("action");
						const isPublishAction =
							reqPath.endsWith("/posts") &&
							["publish", "schedule", "bulk-schedule-groups"].includes(
								actionParam ?? "",
							);

						if (isPublishAction) {
							// biome-ignore lint/suspicious/noExplicitAny: agent_approvals not in generated types
							let query = (getSupabase() as any)
								.from("agent_approvals")
								.select("id", { count: "exact", head: true })
								.eq("user_id", user.id)
								.eq("status", "pending")
								.gt("expires_at", new Date().toISOString());

							if (agentSessionId) {
								query = query.eq("session_id", agentSessionId);
							}

							const { count } = await query;
							if (count && count > 0) {
								return apiError(
									res,
									403,
									"Approval pending — wait for user decision before publishing",
									{ code: "APPROVAL_PENDING" },
								);
							}
						}
					} catch {
						// Fail open — don't block on approval check failure
					}

					// 4. Circuit breaker — track call and auto-pause on anomalous behavior
					try {
						const { checkAndRecord, trip, computeParamsHash } = await import(
							"./agentCircuitBreaker.js"
						);
						const toolHash = computeParamsHash(
							reqPath,
							req.url ?? "",
							req.method ?? "POST",
						);
						// Pre-handler check: counts call against hourly + dedup limits
						// only. The success arg is irrelevant here — recordOutcome
						// below tracks actual result against the consecutive-failure
						// streak counter.
						const reason = await checkAndRecord(
							user.id,
							reqPath,
							toolHash,
							true,
						);
						if (reason) {
							await trip(user.id, reason);
							return apiError(res, 503, `Agent auto-paused: ${reason.detail}`, {
								code: "CIRCUIT_BREAKER_TRIPPED",
							});
						}
					} catch {
						// Circuit breaker failure must never block requests
					}
				}
			}

			const start = Date.now();
			const result = await handler(req, res, user);
			const duration = Date.now() - start;
			const status = res.statusCode || 200;
			logger.info("API request completed", {
				requestId,
				route,
				action,
				method: req.method,
				userId: user.id,
				status,
				duration,
				release: process.env.VERCEL_GIT_COMMIT_SHA ?? "dev",
				environment: process.env.VERCEL_ENV ?? process.env.NODE_ENV ?? "unknown",
			});
			// Post-handler outcome recording — the consecutive-failure streak
			// only ticks if the handler responded with 4xx/5xx. Was previously
			// dead because checkAndRecord always passed success=true.
			if (
				isAgent &&
				req.method !== "GET" &&
				req.method !== "OPTIONS" &&
				reqPath !== "/admin/agent-pause" &&
				reqPath !== "/admin/agent-status"
			) {
				try {
					const { recordOutcome, trip } = await import(
						"./agentCircuitBreaker.js"
					);
					const success = status < 400;
					const reason = await recordOutcome(user.id, reqPath, success);
					if (reason) await trip(user.id, reason);
				} catch {
					// Non-blocking
				}
			}
			if (duration > 3000) {
				Sentry.captureMessage("Slow API response", {
					level: "warning",
					extra: { requestId, route, action, method: req.method, status, duration },
				});
				logger.warn("Slow API response", {
					requestId,
					url: route,
					action,
					method: req.method,
					status,
					duration,
				});
			}
			return result;
		}),
	);
}

/**
 * Authenticated route wrapper that provides a user-scoped Supabase client for
 * RLS-protected CRUD plus explicit admin clients for privileged branches.
 */
export function withAuthDb(
	handler: (
		req: VercelRequest,
		res: VercelResponse,
		context: DbContext,
	) => Promise<VercelResponse | undefined>,
) {
	return withAuth(async (req, res, user) => {
		const context = createDbContext(req, user);
		return handler(req, res, context);
	});
}

/**
 * Decode JWT payload claims without signature verification.
 * Safe because the JWT was already validated by getAuthUserOrError upstream
 * (Supabase's GoTrue verified the signature before we got here).
 * Returns null on malformed tokens.
 */
function decodeJwtClaims(
	token: string,
): { aal?: string | undefined; role?: string | undefined; sub?: string | undefined } | null {
	try {
		const parts = token.split(".");
		if (parts.length !== 3) return null;
		const normalized = parts[1]!.replace(/-/g, "+").replace(/_/g, "/");
		const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
		const payload = JSON.parse(Buffer.from(padded, "base64").toString("utf8"));
		return {
			aal: typeof payload.aal === "string" ? payload.aal : undefined,
			role: typeof payload.role === "string" ? payload.role : undefined,
			sub: typeof payload.sub === "string" ? payload.sub : undefined,
		};
	} catch {
		return null;
	}
}

/**
 * Step-up check for sensitive user-scope actions.
 *
 * Call inside a withAuth handler before performing a destructive or
 * credential-sensitive operation (account deletion, billing cancel, API
 * key mint, etc.). Returns the 403 response on rejection — the caller
 * short-circuits — or null to continue.
 *
 * Policy:
 *   AAL2 session                        → pass (user just verified TOTP)
 *   AAL1 + no verified factor on file   → pass (user hasn't opted into MFA;
 *                                          enforcing here would be a silent
 *                                          lockout with no remediation path)
 *   AAL1 + verified factor on file      → 403 MFA_STEP_UP_REQUIRED
 *                                          (frontend prompts re-auth)
 *
 * This is stricter than withAuth and lighter than withAdminRole.
 */
export async function requireStepUp(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
): Promise<VercelResponse | null> {
	const token = req.headers.authorization?.slice(7) ?? "";
	const claims = decodeJwtClaims(token);
	const aal = claims?.aal ?? "aal1";
	if (aal === "aal2") return null;

	const { getSupabase } = await import("./supabase.js");
	const supabase = getSupabase();
	const { data: factorsData } = await supabase.auth.admin.mfa.listFactors({
		userId,
	});
	const hasVerifiedFactor = (factorsData?.factors ?? []).some(
		(f) => f.status === "verified",
	);
	if (!hasVerifiedFactor) return null;

	return apiError(
		res,
		403,
		"MFA step-up required. Re-authenticate with your authenticator app.",
		{ code: "MFA_STEP_UP_REQUIRED" },
	);
}

/**
 * Wrap a handler with CORS + Bearer auth + platform-admin role check + MFA gate.
 *
 * Identification: checks PLATFORM_ADMIN_IDS env var (comma-separated user IDs).
 *
 * MFA enforcement (P0 #5 from security_compliance_2026.md):
 * When REQUIRE_ADMIN_MFA env var is truthy, requires the caller's JWT to carry
 * aal = "aal2" — i.e. the session has completed an MFA challenge. Returns 403
 * with code MFA_ENROLLMENT_REQUIRED (no factors enrolled) or MFA_STEP_UP_REQUIRED
 * (factors enrolled but session is aal1) so the frontend can route the user to
 * either Settings → Security or a re-auth prompt.
 *
 * Operational rollout:
 *   1. Enroll TOTP for every admin via Settings → Security
 *   2. Set REQUIRE_ADMIN_MFA=1 in Vercel prod env
 *   3. Redeploy. Admins without aal2 will get 403 until they re-authenticate.
 *
 * Usage: export default withAdminRole(async (req, res, user) => { ... })
 */
export function withAdminRole(
	handler: (
		req: VercelRequest,
		res: VercelResponse,
		user: { id: string; email?: string | undefined },
	) => Promise<VercelResponse | undefined>,
) {
	return withAuth(async (req, res, user) => {
		const adminIdsEnv = process.env.PLATFORM_ADMIN_IDS;
		if (!adminIdsEnv) {
			logger.warn(
				"[withAdminRole] PLATFORM_ADMIN_IDS env var is not set — all admin requests will 403",
			);
			return apiError(res, 403, "Admin access required");
		}

		const adminIds = adminIdsEnv
			.split(",")
			.map((id) => id.trim())
			.filter(Boolean);
		if (!adminIds.includes(user.id)) {
			return apiError(res, 403, "Admin access required");
		}

		const requireMfa = /^(1|true|yes)$/i.test(
			process.env.REQUIRE_ADMIN_MFA ?? "",
		);
		if (!requireMfa) {
			return handler(req, res, user);
		}

		const token = req.headers.authorization?.slice(7) ?? "";
		const claims = decodeJwtClaims(token);
		const aal = claims?.aal ?? "aal1";
		if (aal === "aal2") {
			return handler(req, res, user);
		}

		// Distinguish enrollment vs step-up so the frontend can pick the right UX.
		const { getSupabase } = await import("./supabase.js");
		const supabase = getSupabase();
		const { data: factorsData } = await supabase.auth.admin.mfa.listFactors({
			userId: user.id,
		});
		const hasVerifiedFactor = (factorsData?.factors ?? []).some(
			(f) => f.status === "verified",
		);

		if (!hasVerifiedFactor) {
			return apiError(
				res,
				403,
				"MFA enrollment required. Set up TOTP in Settings → Security before accessing admin endpoints.",
				{ code: "MFA_ENROLLMENT_REQUIRED" },
			);
		}
		return apiError(
			res,
			403,
			"MFA step-up required. Re-authenticate with your authenticator app.",
			{ code: "MFA_STEP_UP_REQUIRED" },
		);
	});
}

/**
 * Wrap a handler with cron secret auth + error boundary.
 * Sends 401 if CRON_SECRET doesn't match. Catches unhandled errors, reports to Sentry.
 * Also sends Discord alerts on failures.
 */
export function withCron(
	handler: (
		req: VercelRequest,
		res: VercelResponse,
	) => Promise<VercelResponse | undefined>,
) {
	return withProHardening(async (req, res) => {
		// Block cron execution in preview/staging deployments to prevent
		// preview branches from running crons against production data
		const vercelEnv = process.env.VERCEL_ENV;
		if (vercelEnv && vercelEnv !== "production") {
			return res.status(200).json({
				skipped: true,
				reason: `Crons disabled in ${vercelEnv} environment`,
			});
		}

		if (!verifyCronAuth(req, res)) return;
		const startTime = Date.now();
		const requestId = getOrCreateRequestId(req, res);
		const route = new URL(req.url ?? "/", "https://x").pathname;
		Sentry.setTags({
			request_id: requestId,
			route,
			method: req.method ?? "UNKNOWN",
			vercel_env: process.env.VERCEL_ENV ?? process.env.NODE_ENV ?? "unknown",
			release: process.env.VERCEL_GIT_COMMIT_SHA ?? "dev",
		});

		try {
			const result = await handler(req, res);
			const durationMs = Date.now() - startTime;
			logger.info("Cron request completed", {
				requestId,
				route,
				method: req.method,
				status: res.statusCode || 200,
				duration: durationMs,
				release: process.env.VERCEL_GIT_COMMIT_SHA ?? "dev",
				environment: process.env.VERCEL_ENV ?? process.env.NODE_ENV ?? "unknown",
			});
			return result;
		} catch (error) {
			const durationMs = Date.now() - startTime;
			logger.error("[withCron] Unhandled error", {
				requestId,
				error: String(error),
				url: req.url,
				durationMs,
			});

			try {
				const { captureServerException } = await import("./sentryServer.js");
				await captureServerException(error, {
					middleware: "withCron",
					url: req.url,
					requestId,
				});
			} catch (sentryErr) {
				logger.error("[withCron] Sentry reporting failed", {
					error: String(sentryErr),
				});
			}

			// Send Discord alert (fire-and-forget)
			try {
				const { alertCronFailure } = await import("./alerting.js");
				const jobName =
					req.url?.replace(/^\/api\/cron\//, "").split("?")[0] || "unknown";
				alertCronFailure(
					jobName,
					error instanceof Error ? error.message : String(error),
					durationMs,
				);
			} catch (alertErr) {
				logger.error("[withCron] Alert sending failed", {
					error: String(alertErr),
				});
			}
			throw error; // Let withProHardening handle the final response
		}
	});
}
