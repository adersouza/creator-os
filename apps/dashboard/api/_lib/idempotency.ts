import * as crypto from "node:crypto";
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError } from "./apiResponse.js";
import { logger } from "./logger.js";
import { getSupabaseAny } from "./supabase.js";

const IDEMPOTENCY_HEADER = "idempotency-key";
const IDEMPOTENCY_TTL_HOURS = 24;

type IdempotencyReplay = {
	status: "completed" | "processing" | "failed";
	payload_hash: string;
	response_status: number | null;
	response_body: unknown;
};

type IdempotencyState =
	| { mode: "none" }
	| { mode: "handled" }
	| {
			mode: "claimed";
			key: string;
			payloadHash: string;
			capturedStatus: number;
			capturedBody: unknown;
			restore: () => void;
	  };

export async function withIdempotency(
	req: VercelRequest,
	res: VercelResponse,
	options: {
		userId: string;
		route: string;
		action: string;
		enabled: boolean;
		requireKey?: boolean;
		failClosed?: boolean;
	},
	handler: () => Promise<VercelResponse | undefined>,
): Promise<VercelResponse | undefined> {
	if (!options.enabled) return handler();

	const state = await beginIdempotency(req, res, options);
	if (state.mode === "handled") return;
	if (state.mode === "none") return handler();

	try {
		const result = await handler();
		await completeIdempotency(options, state, "completed");
		return result;
	} catch (error) {
		await completeIdempotency(options, state, "failed");
		throw error;
	} finally {
		state.restore();
	}
}

async function beginIdempotency(
	req: VercelRequest,
	res: VercelResponse,
	options: {
		userId: string;
		route: string;
		action: string;
		requireKey?: boolean;
		failClosed?: boolean;
	},
): Promise<IdempotencyState> {
	const key = readIdempotencyKey(req);
	if (!key) {
		if (options.requireKey) {
			apiError(res, 428, "Idempotency-Key header is required", {
				code: "IDEMPOTENCY_KEY_REQUIRED",
			});
			return { mode: "handled" };
		}
		return { mode: "none" };
	}
	if (key.length > 128 || !/^[\w:.-]+$/.test(key)) {
		apiError(res, 400, "Invalid Idempotency-Key header", {
			code: "INVALID_IDEMPOTENCY_KEY",
		});
		return { mode: "handled" };
	}

	const payloadHash = hashPayload(req.body ?? {});
	const db = getSupabaseAny();
	const row = {
		user_id: options.userId,
		route: options.route,
		action: options.action,
		idempotency_key: key,
		payload_hash: payloadHash,
		status: "processing",
		expires_at: new Date(
			Date.now() + IDEMPOTENCY_TTL_HOURS * 60 * 60 * 1000,
		).toISOString(),
	};

	const { error: insertError } = await db.from("api_idempotency_keys").insert(row);
	if (!insertError) return captureResponse(res, key, payloadHash);

	if (!isDuplicateError(insertError)) {
		if (options.failClosed) {
			logger.warn("[idempotency] unavailable, rejecting side-effect request", {
				route: options.route,
				action: options.action,
				error: String(insertError?.message ?? insertError),
			});
			apiError(res, 503, "Could not reserve request idempotency. Please retry.", {
				code: "IDEMPOTENCY_UNAVAILABLE",
			});
			return { mode: "handled" };
		}
		logger.warn("[idempotency] unavailable, proceeding without claim", {
			route: options.route,
			action: options.action,
			error: String(insertError?.message ?? insertError),
		});
		return { mode: "none" };
	}

	const { data: existing, error: loadError } = await db
		.from("api_idempotency_keys")
		.select("status, payload_hash, response_status, response_body")
		.eq("user_id", options.userId)
		.eq("route", options.route)
		.eq("action", options.action)
		.eq("idempotency_key", key)
		.maybeSingle();

	if (loadError || !existing) {
		apiError(res, 409, "Duplicate request is still being processed", {
			code: "IDEMPOTENCY_IN_PROGRESS",
		});
		return { mode: "handled" };
	}

	const replay = existing as IdempotencyReplay;
	if (replay.payload_hash !== payloadHash) {
		apiError(res, 409, "Idempotency key was already used with a different payload", {
			code: "IDEMPOTENCY_PAYLOAD_MISMATCH",
		});
		return { mode: "handled" };
	}

	if (replay.status === "completed" && replay.response_body) {
		res.setHeader("x-idempotent-replay", "true");
		return {
			mode: res.status(replay.response_status || 200).json(replay.response_body)
				? "handled"
				: "handled",
		};
	}

	apiError(res, 409, "Duplicate request is still being processed", {
		code: "IDEMPOTENCY_IN_PROGRESS",
	});
	return { mode: "handled" };
}

function captureResponse(
	res: VercelResponse,
	key: string,
	payloadHash: string,
): IdempotencyState {
	const originalStatus = res.status.bind(res);
	const originalJson = res.json.bind(res);
	const state = {
		mode: "claimed" as const,
		key,
		payloadHash,
		capturedStatus: 200,
		capturedBody: undefined as unknown,
		restore: () => {
			res.status = originalStatus;
			res.json = originalJson;
		},
	};

	res.status = ((statusCode: number) => {
		state.capturedStatus = statusCode;
		return originalStatus(statusCode);
	}) as typeof res.status;

	res.json = ((body: unknown) => {
		state.capturedBody = body;
		return originalJson(body);
	}) as typeof res.json;

	return state;
}

async function completeIdempotency(
	options: { userId: string; route: string; action: string },
	state: Extract<IdempotencyState, { mode: "claimed" }>,
	status: "completed" | "failed",
) {
	try {
		await getSupabaseAny()
			.from("api_idempotency_keys")
			.update({
				status,
				response_status: state.capturedStatus,
				response_body: state.capturedBody ?? null,
				completed_at: new Date().toISOString(),
			})
			.eq("user_id", options.userId)
			.eq("route", options.route)
			.eq("action", options.action)
			.eq("idempotency_key", state.key)
			.eq("payload_hash", state.payloadHash);
	} catch (error) {
		logger.warn("[idempotency] failed to complete claim", {
			route: options.route,
			action: options.action,
			error: String(error),
		});
	}
}

function readIdempotencyKey(req: VercelRequest): string | null {
	const value = req.headers[IDEMPOTENCY_HEADER] ?? req.headers["Idempotency-Key"];
	if (Array.isArray(value)) return value[0] ?? null;
	return typeof value === "string" && value.trim() ? value.trim() : null;
}

function hashPayload(payload: unknown): string {
	return crypto
		.createHash("sha256")
		.update(stableStringify(payload))
		.digest("hex");
}

function stableStringify(value: unknown): string {
	if (value === null || typeof value !== "object") return JSON.stringify(value);
	if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
	const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) =>
		a.localeCompare(b),
	);
	return `{${entries
		.map(([key, child]) => `${JSON.stringify(key)}:${stableStringify(child)}`)
		.join(",")}}`;
}

function isDuplicateError(error: unknown): boolean {
	return (
		typeof error === "object" &&
		error !== null &&
		"code" in error &&
		(error as { code?: string }).code === "23505"
	);
}
