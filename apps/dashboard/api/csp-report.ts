import type { VercelRequest, VercelResponse } from "@vercel/node";
import { logger, scrubSensitive } from "./_lib/logger.js";
import { enforceRouteRateLimit, getClientIp } from "./_lib/routeRateLimit.js";
import { captureServerMessage } from "./_lib/sentryServer.js";

type NormalizedReport = Record<string, unknown>;

function pickField(
	source: Record<string, unknown>,
	...keys: string[]
): unknown {
	for (const key of keys) {
		const value = source[key];
		if (value !== undefined && value !== null && value !== "") return value;
	}
	return undefined;
}

function normalizeSingle(raw: Record<string, unknown>): NormalizedReport {
	return {
		documentUri: pickField(raw, "documentURL", "document-uri", "documentUri"),
		referrer: pickField(raw, "referrer"),
		blockedUri: pickField(raw, "blockedURL", "blocked-uri", "blockedUri"),
		violatedDirective: pickField(
			raw,
			"violatedDirective",
			"violated-directive",
		),
		effectiveDirective: pickField(
			raw,
			"effectiveDirective",
			"effective-directive",
		),
		originalPolicy: pickField(raw, "originalPolicy", "original-policy"),
		disposition: pickField(raw, "disposition"),
		statusCode: pickField(raw, "statusCode", "status-code"),
		sourceFile: pickField(raw, "sourceFile", "source-file"),
		lineNumber: pickField(raw, "lineNumber", "line-number"),
		columnNumber: pickField(raw, "columnNumber", "column-number"),
		userAgent: pickField(raw, "userAgent", "user-agent"),
		sample: pickField(raw, "sample"),
	};
}

function extractReports(body: unknown): NormalizedReport[] {
	if (!body) return [];

	if (Array.isArray(body)) {
		return body
			.map((entry) => {
				if (!entry || typeof entry !== "object") return null;
				const record = entry as Record<string, unknown>;
				if (record.type !== undefined && record.type !== "csp-violation") {
					return null;
				}
				const inner =
					record.body && typeof record.body === "object"
						? (record.body as Record<string, unknown>)
						: record;
				return normalizeSingle(inner);
			})
			.filter((r): r is NormalizedReport => r !== null);
	}

	if (typeof body === "object") {
		const record = body as Record<string, unknown>;
		const inner =
			record["csp-report"] && typeof record["csp-report"] === "object"
				? (record["csp-report"] as Record<string, unknown>)
				: record;
		return [normalizeSingle(inner)];
	}

	return [];
}

async function readRawBody(req: VercelRequest): Promise<string> {
	if (typeof req.body === "string") return req.body;
	const chunks: Buffer[] = [];
	for await (const chunk of req as AsyncIterable<Buffer | string>) {
		chunks.push(typeof chunk === "string" ? Buffer.from(chunk) : chunk);
	}
	return Buffer.concat(chunks).toString("utf8");
}

async function parseBody(req: VercelRequest): Promise<unknown> {
	if (req.body !== undefined && req.body !== null && req.body !== "") {
		if (typeof req.body === "string") {
			try {
				return JSON.parse(req.body);
			} catch {
				return req.body;
			}
		}
		return req.body;
	}
	const raw = await readRawBody(req);
	if (!raw) return null;
	try {
		return JSON.parse(raw);
	} catch {
		return raw;
	}
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method === "OPTIONS") {
		res.setHeader("Allow", "POST, OPTIONS");
		return res.status(204).end();
	}

	if (req.method !== "POST") {
		res.setHeader("Allow", "POST, OPTIONS");
		return res.status(405).json({ error: "Method not allowed" });
	}

	const allowed = await enforceRouteRateLimit(res, {
		key: `csp-report:${getClientIp(req)}`,
		limit: 60,
		windowSeconds: 60,
		failMode: "open",
		message: "Rate limit exceeded",
	});
	if (!allowed) return;

	const body = await parseBody(req);
	const reports = extractReports(body);
	const contentType = req.headers["content-type"] ?? null;
	const userAgent = req.headers["user-agent"] ?? null;

	if (reports.length === 0) {
		logger.warn("[csp] Violation report — unparseable", {
			contentType,
			userAgent,
			rawType: typeof body,
		});
		await captureServerMessage(
			"CSP violation report — unparseable",
			{ contentType, userAgent, rawType: typeof body },
			"warning",
		);
		return res.status(204).end();
	}

	for (const report of reports) {
		const scrubbed = scrubSensitive({ ...report, contentType, userAgent });
		logger.warn("[csp] Violation report", { report: scrubbed });
		await captureServerMessage(
			"CSP violation report",
			{ report: scrubbed },
			"warning",
		);
	}

	return res.status(204).end();
}
