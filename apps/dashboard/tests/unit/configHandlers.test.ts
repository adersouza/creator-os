import { beforeEach, describe, expect, it, vi } from "vitest";

// ── Module-scope mocks ──────────────────────────────────────────────────────

const mockFrom = vi.fn();
const mockVerifyWorkspaceAccess = vi.fn().mockResolvedValue(true);
const mockVerifyWorkspaceWriteAccess = vi.fn().mockResolvedValue(true);
const mockVerifyGroupBelongsToWorkspace = vi.fn().mockResolvedValue(true);
const mockVerifyAccountBelongsToGroup = vi.fn().mockResolvedValue(true);
const mockResolveWorkspaceId = vi.fn().mockResolvedValue("ws1");
const mockRequireMinTier = vi.fn().mockResolvedValue(true);

vi.mock("../../api/_lib/handlers/auto-post/route/routeHelpers", () => ({
  db: () => ({ from: mockFrom }),
  resolveWorkspaceId: (...args: unknown[]) => mockResolveWorkspaceId(...args),
  verifyWorkspaceAccess: (...args: unknown[]) => mockVerifyWorkspaceAccess(...args),
  verifyWorkspaceWriteAccess: (...args: unknown[]) => mockVerifyWorkspaceWriteAccess(...args),
  verifyGroupBelongsToWorkspace: (...args: unknown[]) => mockVerifyGroupBelongsToWorkspace(...args),
  verifyAccountBelongsToGroup: (...args: unknown[]) => mockVerifyAccountBelongsToGroup(...args),
}));

vi.mock("../../api/_lib/tierGate", () => ({
  requireMinTier: (...args: unknown[]) => mockRequireMinTier(...args),
}));

vi.mock("../../api/_lib/apiResponse", () => ({
  apiError: (res: any, status: number, error: string) =>
    res.status(status).json({ error }),
  apiSuccess: (res: any, data?: Record<string, unknown>) =>
    res.status(200).json({ success: true, ...data }),
}));

vi.mock("../../api/_lib/logger", () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

vi.mock("../../api/_lib/supabase", () => ({
  getSupabase: () => ({ from: mockFrom }),
  getSupabaseAny: () => ({ from: mockFrom }),
}));

vi.mock("../../api/_lib/ssrfProtection", () => ({
  validateUrlNotPrivate: vi.fn().mockResolvedValue(null),
}));

vi.mock("../../api/_lib/validation", () => ({
  parseBodyOrError: (_res: any, _schema: any, body: any) => body,
  AutoPostConfigSchema: {},
  AutoPostGroupConfigInnerSchema: {
    partial: () => ({
      safeParse: (data: any) => ({ success: true, data }),
    }),
  },
  WorkspaceConfigSchema: {},
}));

vi.mock("../../api/_lib/handlers/auto-post/queueState", () => ({
  cancelQueueItemsByIds: vi.fn().mockResolvedValue(undefined),
}));

// ── Helpers ─────────────────────────────────────────────────────────────────

function chainMock(finalValue: { data?: unknown; error?: unknown; count?: number }) {
  const chain: Record<string, any> = {};
  const methods = [
    "select", "eq", "in", "not", "or", "gte", "lt", "lte",
    "maybeSingle", "single", "limit", "order", "update", "insert", "upsert", "delete",
    "filter",
  ];
  for (const m of methods) {
    if (m === "maybeSingle" || m === "single") {
      chain[m] = vi.fn().mockResolvedValue(finalValue);
    } else {
      chain[m] = vi.fn().mockReturnValue(chain);
    }
  }
  chain.then = (resolve: (v: unknown) => unknown) =>
    Promise.resolve(finalValue).then(resolve);
  return chain;
}

function mockRes() {
  const res: any = { status: vi.fn(), json: vi.fn() };
  res.status.mockReturnValue(res);
  res.json.mockReturnValue(res);
  return res;
}

// ── Tests ───────────────────────────────────────────────────────────────────

describe("auto-post config handlers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockRequireMinTier.mockResolvedValue(true);
    mockVerifyWorkspaceAccess.mockResolvedValue(true);
    mockVerifyWorkspaceWriteAccess.mockResolvedValue(true);
    mockVerifyGroupBelongsToWorkspace.mockResolvedValue(true);
    mockVerifyAccountBelongsToGroup.mockResolvedValue(true);
    mockResolveWorkspaceId.mockResolvedValue("ws1");
  });

  // ── handleGetGroupConfigs ───────────────────────────────────────────────

  it("handleGetGroupConfigs returns configs for workspace", async () => {
    const configs = [
      { group_id: "g1", enabled: true },
      { group_id: "g2", enabled: false },
    ];

    mockFrom.mockReturnValue(chainMock({ data: configs, error: null }));

    const { handleGetGroupConfigs } = await import(
      "../../api/_lib/handlers/auto-post/route/configHandlers"
    );
    const res = mockRes();

    await handleGetGroupConfigs(
      { body: { workspaceId: "ws1" } } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(200);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({ configs })
    );
  });

  it("handleGetGroupConfigs returns 500 on DB error", async () => {
    mockFrom.mockReturnValue(
      chainMock({ data: null, error: "DB failure" })
    );

    const { handleGetGroupConfigs } = await import(
      "../../api/_lib/handlers/auto-post/route/configHandlers"
    );
    const res = mockRes();

    await handleGetGroupConfigs(
      { body: { workspaceId: "ws1" } } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(500);
  });

  it("handleGetGroupConfigs blocks non-empire tier", async () => {
    mockRequireMinTier.mockResolvedValue(false);

    const { handleGetGroupConfigs } = await import(
      "../../api/_lib/handlers/auto-post/route/configHandlers"
    );
    const res = mockRes();

    await handleGetGroupConfigs(
      { body: { workspaceId: "ws1" } } as any,
      res,
      "user-free"
    );

    // Handler returns early without setting status (tier gate does it)
    expect(mockFrom).not.toHaveBeenCalled();
  });

  // ── handleDeleteGroupConfig ─────────────────────────────────────────────

  it("handleDeleteGroupConfig deletes config and returns success", async () => {
    mockFrom.mockReturnValue(chainMock({ data: null, error: null }));

    const { handleDeleteGroupConfig } = await import(
      "../../api/_lib/handlers/auto-post/route/configHandlers"
    );
    const res = mockRes();

    await handleDeleteGroupConfig(
      { body: { workspaceId: "ws1", groupId: "g1" } } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(200);
  });

  it("handleDeleteGroupConfig rejects missing params", async () => {
    const { handleDeleteGroupConfig } = await import(
      "../../api/_lib/handlers/auto-post/route/configHandlers"
    );
    const res = mockRes();

    await handleDeleteGroupConfig(
      { body: { workspaceId: "ws1" } } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(400);
  });

  // ── handleGetWorkspaceConfig ────────────────────────────────────────────

  it("handleGetWorkspaceConfig masks discord_webhook_url", async () => {
    mockFrom.mockReturnValue(
      chainMock({
        data: {
          workspace_id: "ws1",
          is_enabled: true,
          discord_webhook_url: "https://discord.com/api/webhooks/secret",
        },
        error: null,
      })
    );

    const { handleGetWorkspaceConfig } = await import(
      "../../api/_lib/handlers/auto-post/route/configHandlers"
    );
    const res = mockRes();

    await handleGetWorkspaceConfig(
      { body: { workspaceId: "ws1" } } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(200);
    const jsonCall = res.json.mock.calls[0][0];
    expect(jsonCall.config.discord_webhook_url).toBe("configured");
  });

  it("handleGetWorkspaceConfig returns 404 when not found", async () => {
    mockFrom.mockReturnValue(chainMock({ data: null, error: null }));

    const { handleGetWorkspaceConfig } = await import(
      "../../api/_lib/handlers/auto-post/route/configHandlers"
    );
    const res = mockRes();

    await handleGetWorkspaceConfig(
      { body: { workspaceId: "ws1" } } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(404);
  });

  // ── handleGetAccountOverrides ───────────────────────────────────────────

  it("handleGetAccountOverrides returns overrides", async () => {
    const overrides = [{ id: "o1", account_id: "a1", overrides: {} }];
    mockFrom.mockReturnValue(chainMock({ data: overrides, error: null }));

    const { handleGetAccountOverrides } = await import(
      "../../api/_lib/handlers/auto-post/route/configHandlers"
    );
    const res = mockRes();

    await handleGetAccountOverrides(
      { body: { workspaceId: "ws1" } } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(200);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({ overrides })
    );
  });

  it("handleGetAccountOverrides requires workspaceId", async () => {
    const { handleGetAccountOverrides } = await import(
      "../../api/_lib/handlers/auto-post/route/configHandlers"
    );
    const res = mockRes();

    await handleGetAccountOverrides(
      { body: {} } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(400);
  });

  // ── handleDeleteAccountOverride ─────────────────────────────────────────

  it("handleDeleteAccountOverride dry-run returns preview", async () => {
    mockFrom.mockReturnValue(
      chainMock({ data: { id: "o1", overrides: { enabled: true } }, error: null })
    );

    const { handleDeleteAccountOverride } = await import(
      "../../api/_lib/handlers/auto-post/route/configHandlers"
    );
    const res = mockRes();

    await handleDeleteAccountOverride(
      {
        body: {
          workspaceId: "ws1",
          groupId: "g1",
          accountId: "a1",
          dryRun: true,
        },
      } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(200);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({ dryRun: true })
    );
  });

  it("handleDeleteAccountOverride requires all 3 IDs", async () => {
    const { handleDeleteAccountOverride } = await import(
      "../../api/_lib/handlers/auto-post/route/configHandlers"
    );
    const res = mockRes();

    await handleDeleteAccountOverride(
      { body: { workspaceId: "ws1", groupId: "g1" } } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(400);
  });
});
