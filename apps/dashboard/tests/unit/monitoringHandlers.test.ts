import { beforeEach, describe, expect, it, vi } from "vitest";

// ── Module-scope mocks ──────────────────────────────────────────────────────

const mockFrom = vi.fn();
const mockVerifyWorkspaceAccess = vi.fn().mockResolvedValue(true);
const mockResolveWorkspaceId = vi.fn().mockResolvedValue("ws1");
const mockRequireMinTier = vi.fn().mockResolvedValue(true);

vi.mock("../../api/_lib/handlers/auto-post/route/routeHelpers", () => ({
  db: () => ({ from: mockFrom }),
  resolveWorkspaceId: (...args: unknown[]) => mockResolveWorkspaceId(...args),
  verifyWorkspaceAccess: (...args: unknown[]) => mockVerifyWorkspaceAccess(...args),
  verifyGroupBelongsToWorkspace: vi.fn().mockResolvedValue(true),
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

vi.mock("../../api/_lib/encryption", () => ({
  decrypt: (val: string) => `decrypted_${val}`,
}));

// ── Helpers ─────────────────────────────────────────────────────────────────

function chainMock(finalValue: { data?: unknown; error?: unknown; count?: number }) {
  const chain: Record<string, any> = {};
  const methods = [
    "select", "eq", "in", "not", "or", "gte", "lt", "lte",
    "maybeSingle", "single", "limit", "order", "update", "insert",
    "upsert", "delete",
  ];
  for (const m of methods) {
    if (m === "maybeSingle" || m === "single") {
      chain[m] = vi.fn().mockResolvedValue(finalValue);
    } else {
      chain[m] = vi.fn().mockReturnValue(chain);
    }
  }
  chain.then = (resolve: (value: typeof finalValue) => void) => resolve(finalValue);
  return chain;
}

function mockRes() {
  const res: any = { status: vi.fn(), json: vi.fn() };
  res.status.mockReturnValue(res);
  res.json.mockReturnValue(res);
  return res;
}

// ── Tests ───────────────────────────────────────────────────────────────────

describe("auto-post monitoring handlers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockRequireMinTier.mockResolvedValue(true);
    mockVerifyWorkspaceAccess.mockResolvedValue(true);
    mockResolveWorkspaceId.mockResolvedValue("ws1");
  });

  // ── handleToggleAutoReply ─────────────────────────────────────────────

  it("handleToggleAutoReply updates group config", async () => {
    mockFrom.mockReturnValue(chainMock({ data: null, error: null }));

    const { handleToggleAutoReply } = await import(
      "../../api/_lib/handlers/auto-post/route/monitoringHandlers"
    );
    const res = mockRes();

    await handleToggleAutoReply(
      {
        body: {
          workspaceId: "ws1",
          groupId: "g1",
          config: { enable_auto_reply: true },
        },
      } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(200);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({ updated: true })
    );
  });

  it("handleToggleAutoReply requires workspaceId and groupId", async () => {
    const { handleToggleAutoReply } = await import(
      "../../api/_lib/handlers/auto-post/route/monitoringHandlers"
    );
    const res = mockRes();

    await handleToggleAutoReply(
      { body: { workspaceId: "ws1" } } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("handleToggleAutoReply validates daily_limit range", async () => {
    const { handleToggleAutoReply } = await import(
      "../../api/_lib/handlers/auto-post/route/monitoringHandlers"
    );
    const res = mockRes();

    await handleToggleAutoReply(
      {
        body: {
          workspaceId: "ws1",
          groupId: "g1",
          config: { auto_reply_daily_limit: 100 },
        },
      } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(400);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({
        error: expect.stringContaining("auto_reply_daily_limit"),
      })
    );
  });

  it("handleToggleAutoReply validates ratio range 0-1", async () => {
    const { handleToggleAutoReply } = await import(
      "../../api/_lib/handlers/auto-post/route/monitoringHandlers"
    );
    const res = mockRes();

    await handleToggleAutoReply(
      {
        body: {
          workspaceId: "ws1",
          groupId: "g1",
          config: { auto_reply_ratio: 1.5 },
        },
      } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(400);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({
        error: expect.stringContaining("auto_reply_ratio"),
      })
    );
  });

  it("handleToggleAutoReply validates trigger_count range", async () => {
    const { handleToggleAutoReply } = await import(
      "../../api/_lib/handlers/auto-post/route/monitoringHandlers"
    );
    const res = mockRes();

    await handleToggleAutoReply(
      {
        body: {
          workspaceId: "ws1",
          groupId: "g1",
          config: { auto_reply_trigger_count: 0 },
        },
      } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("handleToggleAutoReply validates window_hours range", async () => {
    const { handleToggleAutoReply } = await import(
      "../../api/_lib/handlers/auto-post/route/monitoringHandlers"
    );
    const res = mockRes();

    await handleToggleAutoReply(
      {
        body: {
          workspaceId: "ws1",
          groupId: "g1",
          config: { auto_reply_window_hours: 200 },
        },
      } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("handleToggleAutoReply rejects empty config", async () => {
    const { handleToggleAutoReply } = await import(
      "../../api/_lib/handlers/auto-post/route/monitoringHandlers"
    );
    const res = mockRes();

    await handleToggleAutoReply(
      {
        body: {
          workspaceId: "ws1",
          groupId: "g1",
          config: {},
        },
      } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(400);
  });

  // ── handleGetAutoReplyQueue ───────────────────────────────────────────

  it("handleGetAutoReplyQueue returns queue items", async () => {
    const queueItems = [
      { id: "ar1", status: "pending", content: "reply text" },
    ];
    mockFrom.mockReturnValue(chainMock({ data: queueItems, error: null }));

    const { handleGetAutoReplyQueue } = await import(
      "../../api/_lib/handlers/auto-post/route/monitoringHandlers"
    );
    const res = mockRes();

    await handleGetAutoReplyQueue(
      { body: { workspaceId: "ws1" }, query: {} } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(200);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({ queue: queueItems })
    );
  });

  // ── handleGetPublishLog ───────────────────────────────────────────────

  it("handleGetPublishLog returns empty when no published items", async () => {
    mockFrom.mockReturnValue(chainMock({ data: [], error: null }));

    const { handleGetPublishLog } = await import(
      "../../api/_lib/handlers/auto-post/route/monitoringHandlers"
    );
    const res = mockRes();

    await handleGetPublishLog(
      { body: { workspaceId: "ws1" }, query: {} } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(200);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({ posts: [], total: 0 })
    );
  });

  // ── handleGetAccountHealth ────────────────────────────────────────────

  it("handleGetAccountHealth returns 404 when workspace not found", async () => {
    // First call: workspace lookup returns null
    mockFrom.mockReturnValue(chainMock({ data: null, error: null }));

    const { handleGetAccountHealth } = await import(
      "../../api/_lib/handlers/auto-post/route/monitoringHandlers"
    );
    const res = mockRes();

    await handleGetAccountHealth(
      { body: { workspaceId: "ws1" }, query: {} } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(404);
  });
});
