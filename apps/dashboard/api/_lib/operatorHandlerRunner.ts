import type { VercelRequest, VercelResponse } from "@vercel/node";
import { withIdempotency } from "./idempotency.js";

export type OperatorHandlerResult = {
	statusCode: number;
	body: unknown;
	headers: Record<string, string | number | readonly string[]>;
};

type OperatorHandler = (
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) => Promise<VercelResponse | undefined>;

type RunOperatorHandlerOptions = {
	baseReq: VercelRequest;
	userId: string;
	body: Record<string, unknown>;
	idempotencyKey: string;
	route: string;
	action: string;
	handler: OperatorHandler;
	query?: Record<string, unknown>;
	method?: string;
};

export async function runOperatorHandlerAction({
	baseReq,
	userId,
	body,
	idempotencyKey,
	route,
	action,
	handler,
	query,
	method = "POST",
}: RunOperatorHandlerOptions): Promise<OperatorHandlerResult> {
	const req = {
		...baseReq,
		method,
		body,
		query: {
			...(baseReq.query ?? {}),
			...(query ?? {}),
		},
		headers: {
			...(baseReq.headers ?? {}),
			"idempotency-key": idempotencyKey,
			"x-operator-intent-id": String(body.intent_id ?? ""),
		},
	} as unknown as VercelRequest;

	const captured = createCapturedResponse();

	await withIdempotency(
		req,
		captured.res,
		{
			userId,
			route,
			action,
			enabled: true,
			requireKey: true,
			failClosed: true,
		},
		async () => {
			const result = await handler(req, captured.res, userId);
			return result === undefined ? captured.res : result;
		},
	);

	return {
		statusCode: captured.statusCode,
		body: captured.body,
		headers: captured.headers,
	};
}

function createCapturedResponse(): {
	res: VercelResponse;
	statusCode: number;
	body: unknown;
	headers: Record<string, string | number | readonly string[]>;
} {
	const state = {
		statusCode: 200,
		body: undefined as unknown,
		headers: {} as Record<string, string | number | readonly string[]>,
	};

	const res = {
		status(statusCode: number) {
			state.statusCode = statusCode;
			return this;
		},
		json(body: unknown) {
			state.body = body;
			return this;
		},
		send(body: unknown) {
			state.body = body;
			return this;
		},
		end(body?: unknown) {
			if (body !== undefined) state.body = body;
			return this;
		},
		setHeader(name: string, value: string | number | readonly string[]) {
			state.headers[name.toLowerCase()] = value;
			return this;
		},
		getHeader(name: string) {
			return state.headers[name.toLowerCase()];
		},
		removeHeader(name: string) {
			delete state.headers[name.toLowerCase()];
			return this;
		},
	} as unknown as VercelResponse;

	return {
		res,
		get statusCode() {
			return state.statusCode;
		},
		get body() {
			return state.body;
		},
		get headers() {
			return state.headers;
		},
	};
}
