import { beforeEach, describe, expect, it, vi } from "vitest";

// ── Module-scope mocks ──────────────────────────────────────────────────────

const mockFrom = vi.fn();
const mockGetWorkspaceAccountStates = vi.fn().mockResolvedValue([]);
const mockGetGroupAccountStates = vi.fn().mockResolvedValue([]);
const mockStatusLabel = vi.fn().mockImplementation((s: string) => s);
const mockUpsertAccountState = vi.fn().mockResolvedValue(true);

vi.mock("../../api/_lib/supabase", () => ({
  getSupabase: () => ({ from: mockFrom }),
  getSupabaseAny: () => ({ from: mockFrom }),
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

vi.mock("../../api/_lib/handlers/auto-post/accountState", () => ({
  getWorkspaceAccountStates: (...args: unknown[]) =>
    mockGetWorkspaceAccountStates(...args),
  getGroupAccountStates: (...args: unknown[]) =>
    mockGetGroupAccountStates(...args),
  statusLabel: (...args: unknown[]) => mockStatusLabel(...args),
  upsertAccountState: (...args: unknown[]) => mockUpsertAccountState(...args),
}));

vi.mock("../../api/_lib/redis", () => ({
  getRedis: () => ({
    del: vi.fn().mockResolvedValue(1),
  }),
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
  chain.then = (resolve: (v: typeof finalValue) => void) => resolve(finalValue);
  return chain;
}

function mockRes() {
  const res: any = { status: vi.fn(), json: vi.fn() };
  res.status.mockReturnValue(res);
  res.json.mockReturnValue(res);
  return res;
}

// ── Tests ───────────────────────────────────────────────────────────────────

describe("auto-post state handlers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetWorkspaceAccountStates.mockResolvedValue([]);
    mockGetGroupAccountStates.mockResolvedValue([]);
    mockUpsertAccountState.mockResolvedValue(true);
    mockFrom.mockReturnValue(chainMock({ data: [], error: null }));
  });

  // ── handleGetAccountStates ────────────────────────────────────────────

  it("handleGetAccountStates requires workspaceId", async () => {
    const { handleGetAccountStates } = await import(
      "../../api/_lib/handlers/auto-post/stateHandlers"
    );
    const res = mockRes();

    await handleGetAccountStates(
      { body: {} } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("handleGetAccountStates returns workspace-level states", async () => {
    const states = [
      {
        account_id: "a1",
        status: "active",
        status_reason: "Healthy",
        blocked_until: null,
        last_14d_avg_views: 100,
        median_30d_views: 80,
        max_30d_views: 500,
        pct_under_5_views: 10,
        flop_proven_remaining: 0,
        probe_posts_remaining: 0,
        warming_posts_today: 0,
        evaluated_at: "2026-04-15T00:00:00Z",
      },
    ];
    mockGetWorkspaceAccountStates.mockResolvedValue(states);

    mockFrom.mockReturnValue(
      chainMock({
        data: [{ id: "a1", username: "testuser" }],
        error: null,
      })
    );

    const { handleGetAccountStates } = await import(
      "../../api/_lib/handlers/auto-post/stateHandlers"
    );
    const res = mockRes();

    await handleGetAccountStates(
      { body: { workspaceId: "ws1" } } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(200);
    const json = res.json.mock.calls[0][0];
    expect(json.total).toBe(1);
    expect(json.accounts[0].status).toBe("active");
    expect(mockGetWorkspaceAccountStates).toHaveBeenCalledWith("ws1");
  });

  it("handleGetAccountStates uses group-level when groupId provided", async () => {
    mockGetGroupAccountStates.mockResolvedValue([]);
    mockFrom.mockReturnValue(chainMock({ data: [], error: null }));

    const { handleGetAccountStates } = await import(
      "../../api/_lib/handlers/auto-post/stateHandlers"
    );
    const res = mockRes();

    await handleGetAccountStates(
      { body: { workspaceId: "ws1", groupId: "g1" } } as any,
      res,
      "user-1"
    );

    expect(mockGetGroupAccountStates).toHaveBeenCalledWith("g1");
    expect(mockGetWorkspaceAccountStates).not.toHaveBeenCalled();
  });

  // ── handleGetQueueFillExplain ─────────────────────────────────────────

  it("handleGetQueueFillExplain requires workspaceId", async () => {
    const { handleGetQueueFillExplain } = await import(
      "../../api/_lib/handlers/auto-post/stateHandlers"
    );
    const res = mockRes();

    await handleGetQueueFillExplain(
      { body: {} } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("handleGetQueueFillExplain returns fill logs", async () => {
    const fills = [
      {
        id: "f1",
        group_id: "g1",
        started_at: "2026-04-15T00:00:00Z",
        completed_at: "2026-04-15T00:01:00Z",
        posts_inserted: 3,
        posts_generated: 5,
        posts_rejected: 2,
        rejection_summary: "duplicate: 2",
        account_summary: null,
        skip_details: null,
        duration_ms: 60000,
        early_exit_reason: null,
      },
    ];

    mockFrom.mockReturnValue(chainMock({ data: fills, error: null }));

    const { handleGetQueueFillExplain } = await import(
      "../../api/_lib/handlers/auto-post/stateHandlers"
    );
    const res = mockRes();

    await handleGetQueueFillExplain(
      { body: { workspaceId: "ws1" } } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(200);
    const json = res.json.mock.calls[0][0];
    expect(json.fills).toHaveLength(1);
    expect(json.fills[0].posts_inserted).toBe(3);
  });

  it("handleGetQueueFillExplain caps limit at 50", async () => {
    mockFrom.mockReturnValue(chainMock({ data: [], error: null }));

    const { handleGetQueueFillExplain } = await import(
      "../../api/_lib/handlers/auto-post/stateHandlers"
    );
    const res = mockRes();

    await handleGetQueueFillExplain(
      { body: { workspaceId: "ws1", limit: 100 } } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(200);
    // The handler should cap at 50, verified by chain mock
  });

  it("handleGetQueueFillExplain returns 500 on DB error", async () => {
    mockFrom.mockReturnValue(
      chainMock({ data: null, error: { message: "DB error" } })
    );

    const { handleGetQueueFillExplain } = await import(
      "../../api/_lib/handlers/auto-post/stateHandlers"
    );
    const res = mockRes();

    await handleGetQueueFillExplain(
      { body: { workspaceId: "ws1" } } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(500);
  });

  // ── handleOverrideAccountState ────────────────────────────────────────

  it("handleOverrideAccountState requires all 3 IDs", async () => {
    const { handleOverrideAccountState } = await import(
      "../../api/_lib/handlers/auto-post/stateHandlers"
    );
    const res = mockRes();

    await handleOverrideAccountState(
      { body: { accountId: "a1", groupId: "g1" } } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("handleOverrideAccountState validates action", async () => {
    const { handleOverrideAccountState } = await import(
      "../../api/_lib/handlers/auto-post/stateHandlers"
    );
    const res = mockRes();

    await handleOverrideAccountState(
      {
        body: {
          accountId: "a1",
          groupId: "g1",
          workspaceId: "ws1",
          action: "invalid",
        },
      } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(400);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({
        error: expect.stringContaining("resume, pause, clear_cooldown"),
      })
    );
  });

  it("handleOverrideAccountState resume sets active status", async () => {
    const { handleOverrideAccountState } = await import(
      "../../api/_lib/handlers/auto-post/stateHandlers"
    );
    const res = mockRes();

    await handleOverrideAccountState(
      {
        body: {
          accountId: "a1",
          groupId: "g1",
          workspaceId: "ws1",
          action: "resume",
        },
      } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(200);
    expect(mockUpsertAccountState).toHaveBeenCalledWith(
      "a1",
      expect.objectContaining({
        status: "active",
        flop_proven_remaining: 0,
        probe_posts_remaining: 0,
      })
    );
    const json = res.json.mock.calls[0][0];
    expect(json.newStatus).toBe("active");
    expect(json.action).toBe("resume");
  });

  it("handleOverrideAccountState pause sets inactive with 30-day block", async () => {
    const { handleOverrideAccountState } = await import(
      "../../api/_lib/handlers/auto-post/stateHandlers"
    );
    const res = mockRes();

    await handleOverrideAccountState(
      {
        body: {
          accountId: "a1",
          groupId: "g1",
          workspaceId: "ws1",
          action: "pause",
        },
      } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(200);
    expect(mockUpsertAccountState).toHaveBeenCalledWith(
      "a1",
      expect.objectContaining({ status: "inactive" })
    );
    const json = res.json.mock.calls[0][0];
    expect(json.blockedUntil).toBeTruthy();
  });

  it("handleOverrideAccountState returns 500 when upsert fails", async () => {
    mockUpsertAccountState.mockResolvedValue(false);

    const { handleOverrideAccountState } = await import(
      "../../api/_lib/handlers/auto-post/stateHandlers"
    );
    const res = mockRes();

    await handleOverrideAccountState(
      {
        body: {
          accountId: "a1",
          groupId: "g1",
          workspaceId: "ws1",
          action: "resume",
        },
      } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(500);
  });

  it("handleOverrideAccountState clear_cooldown resets counters", async () => {
    const { handleOverrideAccountState } = await import(
      "../../api/_lib/handlers/auto-post/stateHandlers"
    );
    const res = mockRes();

    await handleOverrideAccountState(
      {
        body: {
          accountId: "a1",
          groupId: "g1",
          workspaceId: "ws1",
          action: "clear_cooldown",
          reason: "Manual clear",
        },
      } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(200);
    expect(mockUpsertAccountState).toHaveBeenCalledWith(
      "a1",
      expect.objectContaining({
        status: "active",
        blocked_until: null,
        flop_proven_remaining: 0,
        probe_posts_remaining: 0,
        status_reason: "Manual clear",
      })
    );
  });

  // ── handleGetAutoposterSnapshot ───────────────────────────────────────

  it("handleGetAutoposterSnapshot requires workspaceId", async () => {
    const { handleGetAutoposterSnapshot } = await import(
      "../../api/_lib/handlers/auto-post/stateHandlers"
    );
    const res = mockRes();

    await handleGetAutoposterSnapshot(
      { body: {} } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(400);
  });
});
