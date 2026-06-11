import { beforeEach, describe, expect, it, vi } from "vitest";

// ── Module-scope mocks ──────────────────────────────────────────────────────

const mockFrom = vi.fn();
const mockVerifyWorkspaceAccess = vi.fn().mockResolvedValue(true);
const mockRequireMinTier = vi.fn().mockResolvedValue(true);
const mockGetRedis = vi.fn();
const mockGetPostMetricsLazy = vi.fn();
const mockGetUserCurrentEngagementJob = vi.fn().mockResolvedValue(null);
const mockQueueEngagementSyncJob = vi.fn();

vi.mock("../../api/_lib/handlers/auto-post/route/routeHelpers", () => ({
  db: () => ({ from: mockFrom }),
  resolveWorkspaceId: vi.fn().mockResolvedValue("ws1"),
  verifyWorkspaceAccess: (...args: unknown[]) => mockVerifyWorkspaceAccess(...args),
  verifyGroupBelongsToWorkspace: vi.fn().mockResolvedValue(true),
  getPostMetricsLazy: (...args: unknown[]) => mockGetPostMetricsLazy(...args),
  getUserCurrentEngagementJob: (...args: unknown[]) => mockGetUserCurrentEngagementJob(...args),
  queueEngagementSyncJob: (...args: unknown[]) => mockQueueEngagementSyncJob(...args),
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

vi.mock("../../api/_lib/redis", () => ({
  getRedis: () => mockGetRedis(),
}));

// ── Helpers ─────────────────────────────────────────────────────────────────

function chainMock(finalValue: { data?: unknown; error?: unknown }) {
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
  return chain;
}

function mockRes() {
  const res: any = { status: vi.fn(), json: vi.fn() };
  res.status.mockReturnValue(res);
  res.json.mockReturnValue(res);
  return res;
}

// ── Tests ───────────────────────────────────────────────────────────────────

describe("auto-post engagement handlers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockRequireMinTier.mockResolvedValue(true);
    mockVerifyWorkspaceAccess.mockResolvedValue(true);
  });

  // ── handleLogActivity ─────────────────────────────────────────────────

  it("handleLogActivity inserts activity and returns it", async () => {
    const activity = {
      id: "act-1",
      workspace_id: "ws1",
      activity_type: "post_published",
    };

    mockFrom.mockReturnValue(chainMock({ data: activity, error: null }));

    const { handleLogActivity } = await import(
      "../../api/_lib/handlers/auto-post/route/engagementHandlers"
    );
    const res = mockRes();

    await handleLogActivity(
      {
        body: {
          workspaceId: "ws1",
          activityType: "post_published",
          accountHandle: "testuser",
          message: "Published post #1",
        },
      } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(200);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({ activity })
    );
  });

  it("handleLogActivity requires workspaceId", async () => {
    const { handleLogActivity } = await import(
      "../../api/_lib/handlers/auto-post/route/engagementHandlers"
    );
    const res = mockRes();

    await handleLogActivity(
      { body: { activityType: "test" } } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("handleLogActivity requires activityType", async () => {
    const { handleLogActivity } = await import(
      "../../api/_lib/handlers/auto-post/route/engagementHandlers"
    );
    const res = mockRes();

    await handleLogActivity(
      { body: { workspaceId: "ws1" } } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("handleLogActivity returns 500 on insert error", async () => {
    mockFrom.mockReturnValue(
      chainMock({
        data: null,
        error: { code: "42P01", message: "relation does not exist", hint: null },
      })
    );

    const { handleLogActivity } = await import(
      "../../api/_lib/handlers/auto-post/route/engagementHandlers"
    );
    const res = mockRes();

    await handleLogActivity(
      {
        body: { workspaceId: "ws1", activityType: "test" },
      } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(500);
  });

  // ── handleFetchEngagement ─────────────────────────────────────────────

  it("handleFetchEngagement requires postId", async () => {
    const { handleFetchEngagement } = await import(
      "../../api/_lib/handlers/auto-post/route/engagementHandlers"
    );
    const res = mockRes();

    await handleFetchEngagement(
      { body: {} } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("handleFetchEngagement returns 404 when post not found", async () => {
    mockFrom.mockReturnValue(chainMock({ data: null, error: null }));

    const { handleFetchEngagement } = await import(
      "../../api/_lib/handlers/auto-post/route/engagementHandlers"
    );
    const res = mockRes();

    await handleFetchEngagement(
      { body: { postId: "non-existent" } } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(404);
  });

  it("handleFetchEngagement returns 403 when account_id is null", async () => {
    // First call (auto_post_queue) returns post with null account_id
    mockFrom.mockReturnValue(
      chainMock({
        data: {
          id: "p1",
          threads_post_id: "tp1",
          account_id: null,
          accounts: null,
        },
        error: null,
      })
    );

    const { handleFetchEngagement } = await import(
      "../../api/_lib/handlers/auto-post/route/engagementHandlers"
    );
    const res = mockRes();

    await handleFetchEngagement(
      { body: { postId: "p1" } } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(403);
  });

  // ── handleSyncEngagement ──────────────────────────────────────────────

  it("handleSyncEngagement requires workspaceId", async () => {
    const { handleSyncEngagement } = await import(
      "../../api/_lib/handlers/auto-post/route/engagementHandlers"
    );
    const res = mockRes();

    await handleSyncEngagement(
      { body: {} } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(400);
  });
});
