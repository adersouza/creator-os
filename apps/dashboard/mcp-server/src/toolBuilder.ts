/**
 * Tool builder that enforces MCP tool conventions.
 *
 * Instead of hand-rolling `server.tool(name, description, schema, handler)` with
 * inconsistent param types, dryRun defaults, and response shapes, tools go through
 * this builder which:
 *
 *  - Auto-adds `limit`/`offset` params for paginated tools
 *  - Auto-adds `dryRun` with `.default(true)` for destructive tools
 *  - Provides a shared `platform` enum (never z.string())
 *  - Routes all responses through `respond()`/`success()`/`error()`
 *  - Registers each tool in a global registry for the validation test
 *  - Centralizes timeout selection
 */

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z, type ZodRawShape } from "zod";
import {
  api,
  respond,
  success,
  error,
  dryRunResponse,
  zBool,
  zNum,
  AI_TIMEOUT,
  logAgentAction,
  deriveAgentActionReason,
  type ToolRegistrar,
} from "./helpers.js";
import { checkRateLimit, recordSuccess } from "./rateLimiter.js";

// ---------------------------------------------------------------------------
// Shared schema fragments (use these instead of hand-writing)
// ---------------------------------------------------------------------------

/** Standard platform enum — never use z.string() for platform params. */
export const platformEnum = z.enum(["threads", "instagram"]);

/** Platform enum with "all" option for cross-platform queries. */
export const platformAllEnum = z.enum(["threads", "instagram", "all"]);

// ---------------------------------------------------------------------------
// Pagination
// ---------------------------------------------------------------------------

export interface PaginationConfig {
  defaultLimit?: number; // default: 50
  maxLimit?: number;     // default: 100
}

const DEFAULT_PAGINATION: Required<PaginationConfig> = {
  defaultLimit: 50,
  maxLimit: 100,
};

/** Schema fields auto-added for paginated tools. */
function paginationParams(config: PaginationConfig = {}) {
  const { defaultLimit, maxLimit } = { ...DEFAULT_PAGINATION, ...config };
  return {
    limit: zNum.optional().describe(`Max items to return (default: ${defaultLimit}, max: ${maxLimit})`),
    offset: zNum.optional().describe("Pagination offset (default: 0). Increment by limit for next page."),
  };
}

/** Clamp limit/offset values and build URLSearchParams entries. */
export function paginationQuery(
  limit: number | undefined,
  offset: number | undefined,
  config: PaginationConfig = {},
): { limit: number; offset: number } {
  const { defaultLimit, maxLimit } = { ...DEFAULT_PAGINATION, ...config };
  return {
    limit: Math.min(maxLimit, Math.max(1, limit ?? defaultLimit)),
    offset: Math.min(10_000, Math.max(0, offset ?? 0)),
  };
}

// ---------------------------------------------------------------------------
// Dry-run
// ---------------------------------------------------------------------------

/** Schema field auto-added for destructive tools. */
function dryRunParam() {
  return {
    dryRun: zBool.default(true).describe(
      "Preview without executing (default: true). Must be explicitly set to false to execute."
    ),
  };
}

// ---------------------------------------------------------------------------
// Timeout presets
// ---------------------------------------------------------------------------

export const Timeouts = {
  default: 15_000,
  ai: AI_TIMEOUT,       // 30s
  bulk: 60_000,          // 1min
  heavyBulk: 120_000,   // 2min
  report: 30_000,
} as const;

export type TimeoutPreset = keyof typeof Timeouts;

// ---------------------------------------------------------------------------
// Tool registry (for validation test)
// ---------------------------------------------------------------------------

export interface RegisteredToolMeta {
  name: string;
  description: string;
  module: string;
  paginated: boolean;
  destructive: boolean;
  timeout: number;
  paramNames: string[];
}

const _registry: RegisteredToolMeta[] = [];

/** Read-only snapshot of all registered tools — used by the validation test. */
export function getToolRegistry(): readonly RegisteredToolMeta[] {
  return _registry;
}

// ---------------------------------------------------------------------------
// Builder
// ---------------------------------------------------------------------------

export interface ToolDef<P extends ZodRawShape> {
  /** Tool name (snake_case). */
  name: string;
  /** One-line description. Can include [TAG] prefix. */
  description: string;
  /** Zod param schema (the object shape passed to server.tool). */
  params: P;
  /** Add limit/offset pagination params. */
  paginated?: boolean | PaginationConfig;
  /** Add dryRun param with default=true. */
  destructive?: boolean;
  /** Timeout preset or raw ms. */
  timeout?: TimeoutPreset | number;
}

/**
 * Creates a typed tool definition factory bound to a module name.
 *
 * Usage:
 * ```ts
 * const define = toolModule("analytics");
 *
 * define(server, {
 *   name: "get_analytics",
 *   description: "Get single account analytics",
 *   params: { accountId: z.string().describe("Account ID") },
 *   paginated: true,
 * }, async ({ accountId, limit, offset }) => {
 *   const p = paginationQuery(limit, offset);
 *   return respond(await api(`/v1/analytics?account_id=${accountId}&limit=${p.limit}&offset=${p.offset}`));
 * });
 * ```
 */
export function toolModule(moduleName: string) {
  /**
   * Define and register a tool with enforced conventions.
   *
   * The handler receives all params (including auto-added pagination/dryRun)
   * as a flat object. TypeScript infers the base params from `def.params`;
   * auto-added fields (`limit`, `offset`, `dryRun`) are typed loosely to
   * avoid deep generic gymnastics with Zod's conditional types.
   */
  return function define<P extends ZodRawShape>(
    server: McpServer,
    def: ToolDef<P>,
    handler: (
      params: Record<string, unknown>,
    ) => Promise<ReturnType<typeof success>>,
  ) {
    // Merge auto-params
    let schema: ZodRawShape = { ...def.params };
    if (def.paginated) {
      const config = typeof def.paginated === "object" ? def.paginated : undefined;
      schema = { ...schema, ...paginationParams(config) };
    }
    if (def.destructive) {
      schema = { ...schema, ...dryRunParam() };
    }

    const timeoutMs = typeof def.timeout === "number"
      ? def.timeout
      : Timeouts[def.timeout ?? "default"];

    // Register for validation
    _registry.push({
      name: def.name,
      description: def.description,
      module: moduleName,
      paginated: !!def.paginated,
      destructive: !!def.destructive,
      timeout: timeoutMs,
      paramNames: Object.keys(schema),
    });

    // Register with MCP server — wrapped with rate limiting + error boundary
    const toolName = def.name;
    // biome-ignore lint/suspicious/noExplicitAny: MCP SDK handler type mismatch with our wrapper signature
    const wrappedHandler = (async (params: Record<string, unknown>) => {
      if (def.destructive && params.dryRun !== false) {
        const { dryRun: _dryRun, ...preview } = params;
        return dryRunResponse(`Would execute ${toolName}`, preview);
      }

      // Rate limit check
      const rateCheck = checkRateLimit();
      if (rateCheck) {
        return error({
          code: "rate_limit",
          message: rateCheck.reason,
          status: 429,
          retryAfterMs: rateCheck.waitMs,
        });
      }

      const start = Date.now();
      try {
        const result = await handler(params);
        logAgentAction(
          toolName,
          params,
          result,
          Date.now() - start,
          deriveAgentActionReason(toolName, params, result),
        );
        recordSuccess();
        return result;
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        const result = {
          ok: false,
          error: { code: "server_error", message, status: 500 },
        } as const;
        logAgentAction(
          toolName,
          params,
          result,
          Date.now() - start,
          deriveAgentActionReason(toolName, params, result),
        );
        return error({
          code: "server_error",
          message: `Tool "${toolName}" crashed: ${message}`,
          status: 500,
        });
      }
    }) as any;
    wrappedHandler.__agentLoggingInstalled = true;
    server.tool(toolName, def.description, schema, wrappedHandler);
  };
}

// Re-export helpers so tool files can import everything from one place
export { z, api, respond, success, error, dryRunResponse, zBool, zNum, AI_TIMEOUT };
export type { ToolRegistrar };
