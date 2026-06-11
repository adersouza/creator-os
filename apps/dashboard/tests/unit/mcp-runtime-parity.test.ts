import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  HOSTED_TOOL_MODULE_PATHS,
  LOCAL_TOOL_MODULES,
  TOOL_MODULE_NAMES,
} from "../../mcp-server/src/toolModules";
import {
  getOperatorActionManifest,
  installOperatorControlPlane,
  WRITE_TOOLS,
} from "../../mcp-server/src/operatorControlPlane";

type ToolHandler = (...args: unknown[]) => Promise<unknown> | unknown;

interface ToolRegistration {
  name: string;
  description: string;
  schema: Record<string, unknown>;
  handler: ToolHandler;
}

class FakeMcpServer {
  registrations: ToolRegistration[] = [];

  tool(...args: unknown[]) {
    const name = String(args[0]);
    const description = typeof args[1] === "string" ? args[1] : "";
    const schema = args[2] && typeof args[2] === "object" && !Array.isArray(args[2])
      ? args[2] as Record<string, unknown>
      : {};
    const handler = args.findLast((arg) => typeof arg === "function") as ToolHandler | undefined;

    if (!handler) throw new Error(`Missing handler for ${name}`);
    this.registrations.push({ name, description, schema, handler });
  }
}

function registerLocalRuntime() {
  const server = new FakeMcpServer();
  installOperatorControlPlane(server as never);
  for (const register of LOCAL_TOOL_MODULES) {
    register(server as never);
  }
  return server;
}

function responseText(value: unknown): string {
  if (!value || typeof value !== "object") return "";
  const content = (value as { content?: Array<{ text?: string }> }).content;
  return content?.find((part) => part.text)?.text ?? "";
}

describe("MCP runtime parity", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ok: true }), { status: 200 })));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps hosted module paths in lockstep with local runtime modules", () => {
    expect(LOCAL_TOOL_MODULES).toHaveLength(TOOL_MODULE_NAMES.length);
    expect(HOSTED_TOOL_MODULE_PATHS).toEqual(
      TOOL_MODULE_NAMES.map((name) => `../mcp-server/dist/tools/${name}.js`),
    );
  });

  it("registers the local MCP runtime through the shared control plane", () => {
    const server = registerLocalRuntime();
    const toolNames = server.registrations.map((registration) => registration.name);

    expect(toolNames.length).toBeGreaterThan(100);
    expect(new Set(toolNames).size).toBe(toolNames.length);
    expect(toolNames).toContain("get_posts");
    expect(toolNames).toContain("publish_threads_post");
    expect(toolNames).toContain("schedule_instagram_post");
    expect(toolNames).toContain("request_operator_approval");
    expect(toolNames).toContain("execute_operator_action");
  });

  it("injects dry-run and approval controls into write tools only", () => {
    const server = registerLocalRuntime();

    const readTool = server.registrations.find((registration) => registration.name === "get_posts");
    const publishTool = server.registrations.find((registration) => registration.name === "publish_threads_post");
    const replyTool = server.registrations.find((registration) => registration.name === "reply_to_ig_comment");
    const deleteTool = server.registrations.find((registration) => registration.name === "delete_post");

    expect(readTool?.schema).not.toHaveProperty("dryRun");
    expect(readTool?.schema).not.toHaveProperty("approvalId");

    for (const writeTool of [publishTool, replyTool, deleteTool]) {
      expect(writeTool?.schema).toHaveProperty("dryRun");
      expect(writeTool?.schema).toHaveProperty("approvalId");
    }
  });

  it("defaults write handlers to dry-run without calling the underlying API", async () => {
    const fetchSpy = vi.mocked(fetch);
    const server = registerLocalRuntime();
    const publishTool = server.registrations.find((registration) => registration.name === "publish_threads_post");

    expect(publishTool).toBeDefined();
    const response = await publishTool?.handler({
      accountId: "acct_123",
      content: "Launch caption",
    });

    const text = responseText(response);
    expect(text).toContain('"dryRun": true');
    expect(text).toContain("Would execute publish_threads_post");
    expect(text).toContain('"accountId": "acct_123"');
    expect(text).not.toContain("approvalId");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy.mock.calls[0]?.[0]).toBe("https://juno33.com/api/agent/log");
  });

  it("exposes every write tool in the operator action manifest", () => {
    const manifest = getOperatorActionManifest();
    const manifestNames = new Set(manifest.map((entry) => entry.toolName));

    for (const toolName of WRITE_TOOLS) {
      expect(manifestNames.has(toolName)).toBe(true);
    }

    expect(manifest.find((entry) => entry.toolName === "publish_threads_post")).toMatchObject({
      riskLevel: "critical",
      sideEffectType: "external_publish",
      requiresApproval: true,
      requiresIdempotencyKey: true,
      supportsDryRun: true,
      hostedAvailable: true,
      rollbackSupport: "compensating_action",
      compensationActionName: "delete_post",
      compensationRequiresApproval: true,
    });

    expect(manifest.find((entry) => entry.toolName === "delete_post")).toMatchObject({
      rollbackSupport: "none",
      compensationRequiresApproval: true,
    });

    expect(manifest.find((entry) => entry.toolName === "upsert_workspace_config")).toMatchObject({
      rollbackSupport: "delete_or_revert",
      compensationRequiresApproval: true,
    });
  });
});
