/**
 * MCP Server Enterprise Tests
 *
 * Validates:
 * 1. Rate limiter module exists with required exports
 * 2. Tool builder wraps handlers with error boundary + rate limiting
 * 3. API helper tracks 429s for backoff
 * 4. All tool modules are registered
 */

import { readFileSync } from "fs";
import { join } from "path";
import { describe, expect, it } from "vitest";

const HELPERS = join(__dirname, "../../mcp-server/src/helpers.ts");
const TOOL_BUILDER = join(__dirname, "../../mcp-server/src/toolBuilder.ts");
const RATE_LIMITER = join(__dirname, "../../mcp-server/src/rateLimiter.ts");
const INDEX = join(__dirname, "../../mcp-server/src/index.ts");
const TOOL_MODULES = join(__dirname, "../../mcp-server/src/toolModules.ts");

const helpersCode = readFileSync(HELPERS, "utf-8");
const toolBuilderCode = readFileSync(TOOL_BUILDER, "utf-8");
const rateLimiterCode = readFileSync(RATE_LIMITER, "utf-8");
const indexCode = readFileSync(INDEX, "utf-8");
const toolModulesCode = readFileSync(TOOL_MODULES, "utf-8");

describe("MCP Rate Limiter", () => {
	it("must export checkRateLimit function", () => {
		expect(rateLimiterCode).toContain("export function checkRateLimit");
	});

	it("must export recordRateLimit function", () => {
		expect(rateLimiterCode).toContain("export function recordRateLimit");
	});

	it("must export recordSuccess function", () => {
		expect(rateLimiterCode).toContain("export function recordSuccess");
	});

	it("must implement sliding window with max calls per minute", () => {
		expect(rateLimiterCode).toContain("MAX_CALLS_PER_MINUTE");
		expect(rateLimiterCode).toContain("callTimestamps");
	});

	it("must implement exponential backoff on 429s", () => {
		expect(rateLimiterCode).toContain("consecutive429s");
		expect(rateLimiterCode).toContain("backoffUntil");
		expect(rateLimiterCode).toMatch(/Math\.pow|2\s*\*\*/);
	});
});

describe("MCP Tool Builder — Error Boundary", () => {
	it("must import rate limiter", () => {
		expect(toolBuilderCode).toContain("checkRateLimit");
		expect(toolBuilderCode).toContain("./rateLimiter.js");
	});

	it("must wrap handlers with try/catch", () => {
		expect(toolBuilderCode).toContain("try {");
		expect(toolBuilderCode).toContain("catch (err");
	});

	it("must return structured error on handler crash (not throw)", () => {
		expect(toolBuilderCode).toContain("Tool \"${toolName}\" crashed");
		expect(toolBuilderCode).toContain('code: "server_error"');
	});

	it("must check rate limit before executing handler", () => {
		// checkRateLimit must appear before handler() call
		const checkIdx = toolBuilderCode.indexOf("checkRateLimit()");
		const handlerIdx = toolBuilderCode.indexOf("await handler(params)");
		expect(checkIdx).toBeGreaterThan(-1);
		expect(handlerIdx).toBeGreaterThan(-1);
		expect(checkIdx).toBeLessThan(handlerIdx);
	});

	it("must call recordSuccess on successful handler execution", () => {
		expect(toolBuilderCode).toContain("recordSuccess()");
	});

	it("must log crashes via logAgentAction", () => {
		expect(toolBuilderCode).toContain("logAgentAction");
	});
});

describe("MCP API Helper — 429 Tracking", () => {
	it("must import rate limiter functions", () => {
		expect(helpersCode).toContain("recordRateLimit");
		expect(helpersCode).toContain("recordSuccess");
		expect(helpersCode).toContain("./rateLimiter.js");
	});

	it("must call recordRateLimit on 429 responses", () => {
		expect(helpersCode).toContain("res.status === 429");
		expect(helpersCode).toContain("recordRateLimit(retryAfterMs)");
	});

	it("must call recordSuccess on successful responses", () => {
		// recordSuccess must appear in the success path (after !res.ok block)
		const successIdx = helpersCode.indexOf("recordSuccess()");
		const returnOkIdx = helpersCode.indexOf('return { ok: true, data: data as T }');
		expect(successIdx).toBeGreaterThan(-1);
		expect(returnOkIdx).toBeGreaterThan(-1);
		expect(successIdx).toBeLessThan(returnOkIdx);
	});
});

describe("MCP Server — Module Registration", () => {
	it("must register all 24 tool modules", () => {
		const moduleImports = toolModulesCode.match(/import \{ register as \w+ \}/g) || [];
		expect(moduleImports.length).toBeGreaterThanOrEqual(24);
	});

	it("must have auth check at startup", () => {
		expect(indexCode).toContain("AUTH_TOKEN");
		expect(indexCode).toContain("process.exit(1)");
	});

	it("must have global error handler for main()", () => {
		expect(indexCode).toContain("main().catch");
	});
});
