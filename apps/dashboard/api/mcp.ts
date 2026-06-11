/**
 * MCP Streamable HTTP endpoint
 *
 * Exposes the canonical Juno33 MCP tool manifest over the Streamable HTTP transport so external
 * clients can connect without a local stdio process.
 *
 * Auth: Bearer <JWT or juno_ak_* API key> in Authorization header.
 * Each caller's token is forwarded to internal API calls via AsyncLocalStorage
 * (concurrency-safe on warm containers).
 */
import type { VercelRequest, VercelResponse } from "@vercel/node";

// ---------------------------------------------------------------------------
// Cached tool modules (stateless schemas + handlers, safe to reuse)
// ---------------------------------------------------------------------------

// biome-ignore lint/suspicious/noExplicitAny: dual-package SDK type conflict between root and mcp-server node_modules
type ToolRegistrar = (server: any) => void;
let cachedModules: ToolRegistrar[] | null = null;

type ToolModule = {
	register: ToolRegistrar;
};

type McpServerLike = {
	connect: (transport: unknown) => Promise<unknown> | unknown;
};

async function getToolModules(): Promise<ToolRegistrar[]> {
	if (cachedModules) return cachedModules;

	const { HOSTED_TOOL_MODULE_PATHS } = await importToolManifest();
	const mods = await Promise.all(
		HOSTED_TOOL_MODULE_PATHS.map((modulePath) => importToolModule(modulePath)),
	);

	cachedModules = mods.map((m) => m.register);
	return cachedModules;
}

async function importToolModule(modulePath: string): Promise<ToolModule> {
	return importGeneratedModule<ToolModule>(modulePath);
}

async function importToolManifest(): Promise<{ HOSTED_TOOL_MODULE_PATHS: readonly string[] }> {
	return importGeneratedModule<{ HOSTED_TOOL_MODULE_PATHS: readonly string[] }>(
		"../mcp-server/dist/toolModules.js",
	);
}

async function importMcpHelpers(): Promise<{ runWithAuthToken: unknown }> {
	return importGeneratedModule<{ runWithAuthToken: unknown }>(
		"../mcp-server/dist/helpers.js",
	);
}

async function importControlPlane(): Promise<{ installOperatorControlPlane: (server: unknown) => void }> {
	return importGeneratedModule<{ installOperatorControlPlane: (server: unknown) => void }>(
		"../mcp-server/dist/operatorControlPlane.js",
	);
}

async function importGeneratedModule<T>(modulePath: string): Promise<T> {
	return import(modulePath) as Promise<T>;
}

// ---------------------------------------------------------------------------
// Auth validation (mirrors getAuthUserOrError without res coupling)
// ---------------------------------------------------------------------------

async function validateToken(token: string): Promise<{ id: string } | null> {
	const { getPrivilegedSupabase, PRIVILEGED_DB_REASONS } = await import(
		"./_lib/privilegedDb.js"
	);
	const db = getPrivilegedSupabase(PRIVILEGED_DB_REASONS.hostedMcpAuth);

	if (token.startsWith("juno_ak_")) {
		// biome-ignore lint/style/useNodejsImportProtocol: Vercel requires bare "crypto"
		const { createHash } = await import("crypto");
		const keyHash = createHash("sha256").update(token).digest("hex");
		const { data, error } = await db
			.from("api_keys")
			.select("id, user_id, scopes, is_active, expires_at")
			.eq("key_hash", keyHash)
			.maybeSingle();
		if (error || !data || !data.is_active) return null;
		if (data.expires_at && new Date(data.expires_at) < new Date()) return null;
		if (!Array.isArray(data.scopes) || !data.scopes.includes("mcp")) {
			return null;
		}
		Promise.resolve(
			db
				.from("api_keys")
				.update({ last_used_at: new Date().toISOString() })
				.eq("id", data.id),
		).catch(() => {});
		return { id: data.user_id };
	}

	// JWT path
	const {
		data: { user },
		error,
	} = await db.auth.getUser(token);
	if (error || !user) return null;
	return { id: user.id };
}

// ---------------------------------------------------------------------------
// Handler
// ---------------------------------------------------------------------------

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const allowedOrigin =
		process.env.APP_URL ||
		(process.env.VERCEL_URL
			? `https://${process.env.VERCEL_URL}`
			: "https://juno33.com");
	if (req.method === "OPTIONS") {
		res.setHeader("Access-Control-Allow-Origin", allowedOrigin);
		res.setHeader("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS");
		res.setHeader(
			"Access-Control-Allow-Headers",
			"Content-Type, Authorization, Mcp-Session-Id",
		);
		return res.status(204).end();
	}

	// Stateless server — no SSE notification stream needed.
	// GET requests open long-lived SSE connections that hit the 60s timeout,
	// causing constant reconnects (~every 30s). Return 405 to stop the cycle.
	if (req.method === "GET") {
		res.setHeader("Access-Control-Allow-Origin", allowedOrigin);
		return res.status(405).json({
			jsonrpc: "2.0",
			error: {
				code: -32000,
				message: "SSE not supported — use POST for requests",
			},
		});
	}

	// Auth — Authorization header only. Query params leak credentials into logs and referrers.
	const authHeader = req.headers.authorization;
	const token = authHeader?.startsWith("Bearer ") ? authHeader.slice(7) : null;
	if (!token) {
		const { apiError } = await import("./_lib/apiResponse.js");
		return apiError(res, 401, "Missing auth: use Authorization header");
	}
	const user = await validateToken(token);
	if (!user) {
		const { apiError } = await import("./_lib/apiResponse.js");
		return apiError(res, 401, "Invalid or expired token");
	}

	// Lazy-import MCP SDK + helpers
	const { McpServer } = await import("@modelcontextprotocol/sdk/server/mcp.js");
	const { StreamableHTTPServerTransport } = await import(
		"@modelcontextprotocol/sdk/server/streamableHttp.js"
	);
	const helpers = await importMcpHelpers();
	const { installOperatorControlPlane } = await importControlPlane();

	// Create server + register tools
	const server = new McpServer({
		name: "juno33",
		version: "2.0.0",
	}) as unknown as McpServerLike;
	installOperatorControlPlane(server);
	const modules = await getToolModules();
	for (const register of modules) {
		register(server);
	}

	// Stateless transport — no session persistence between requests
	const transport = new StreamableHTTPServerTransport({});
	await server.connect(transport);

	// Handle the request inside the caller's auth context
	const runWithAuthToken = helpers.runWithAuthToken as (
		authToken: string,
		callback: () => Promise<unknown>,
	) => Promise<unknown>;
	await runWithAuthToken(token, () => transport.handleRequest(req, res, req.body));
}
