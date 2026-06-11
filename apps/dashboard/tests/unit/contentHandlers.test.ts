import { beforeEach, describe, expect, it, vi } from "vitest";

// ── Module-scope mocks ──────────────────────────────────────────────────────

const mockFrom = vi.fn();
const mockVerifyWorkspaceAccess = vi.fn().mockResolvedValue(true);
const mockRequireMinTier = vi.fn().mockResolvedValue(true);

vi.mock("../../api/_lib/handlers/auto-post/route/routeHelpers", () => ({
  db: () => ({ from: mockFrom }),
  resolveWorkspaceId: vi.fn().mockResolvedValue("ws1"),
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

vi.mock("../../api/_lib/handlers/auto-post/queueState", () => ({
  retryQueueItem: vi.fn().mockResolvedValue(undefined),
}));

// ── Helpers ─────────────────────────────────────────────────────────────────

function chainMock(finalValue: { data?: unknown; error?: unknown }) {
  const chain: Record<string, any> = {};
  const methods = [
    "select", "eq", "in", "is", "not", "or", "gte", "lt", "lte",
    "maybeSingle", "single", "limit", "order", "update", "insert",
    "upsert", "delete", "filter",
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

describe("auto-post content handlers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockRequireMinTier.mockResolvedValue(true);
    mockVerifyWorkspaceAccess.mockResolvedValue(true);
  });

  // ── handleBulkUpdateGroupConfigs ──────────────────────────────────────

  it("handleBulkUpdateGroupConfigs updates multiple groups", async () => {
    mockFrom.mockReturnValue(chainMock({ data: null, error: null }));

    const { handleBulkUpdateGroupConfigs } = await import(
      "../../api/_lib/handlers/auto-post/route/contentHandlers"
    );
    const res = mockRes();

    await handleBulkUpdateGroupConfigs(
      {
        body: {
          workspaceId: "ws1",
          updates: [
            { groupId: "g1", enabled: true },
            { groupId: "g2", postsPerAccountPerDay: 3 },
          ],
        },
      } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(200);
    const json = res.json.mock.calls[0][0];
    expect(json.updated).toBe(2);
    expect(json.failed).toBe(0);
  });

  it("handleBulkUpdateGroupConfigs rejects empty updates", async () => {
    const { handleBulkUpdateGroupConfigs } = await import(
      "../../api/_lib/handlers/auto-post/route/contentHandlers"
    );
    const res = mockRes();

    await handleBulkUpdateGroupConfigs(
      { body: { workspaceId: "ws1", updates: [] } } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("handleBulkUpdateGroupConfigs rejects >30 updates", async () => {
    const { handleBulkUpdateGroupConfigs } = await import(
      "../../api/_lib/handlers/auto-post/route/contentHandlers"
    );
    const res = mockRes();

    const updates = Array.from({ length: 31 }, (_, i) => ({
      groupId: `g${i}`,
      enabled: true,
    }));

    await handleBulkUpdateGroupConfigs(
      { body: { workspaceId: "ws1", updates } } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("handleBulkUpdateGroupConfigs tracks missing groupId as failure", async () => {
    mockFrom.mockReturnValue(chainMock({ data: null, error: null }));

    const { handleBulkUpdateGroupConfigs } = await import(
      "../../api/_lib/handlers/auto-post/route/contentHandlers"
    );
    const res = mockRes();

    await handleBulkUpdateGroupConfigs(
      {
        body: {
          workspaceId: "ws1",
          updates: [{ enabled: true }], // missing groupId
        },
      } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(200);
    const json = res.json.mock.calls[0][0];
    expect(json.failed).toBe(1);
    expect(json.results[0].error).toBe("missing groupId");
  });

	// ── handleGetAccountBios ──────────────────────────────────────────────

	it("handleGetAccountBios returns enriched account bios", async () => {
		mockFrom.mockImplementation((table: string) => {
      if (table === "accounts") {
        return chainMock({
          data: [
            {
              id: "a1",
              username: "user1",
              biography: "hello world",
              followers_count: 100,
              is_active: true,
              is_retired: false,
              is_shadowbanned: false,
              needs_reauth: false,
            },
          ],
          error: null,
        });
      }
      if (table === "account_groups") {
        return chainMock({
          data: [{ id: "g1", name: "Group 1", account_ids: ["a1"] }],
          error: null,
        });
      }
      return chainMock({ data: [], error: null });
    });

    const { handleGetAccountBios } = await import(
      "../../api/_lib/handlers/auto-post/route/contentHandlers"
    );
    const res = mockRes();

    await handleGetAccountBios({} as any, res, "user-1");

    expect(res.status).toHaveBeenCalledWith(200);
    const json = res.json.mock.calls[0][0];
    expect(json.accounts[0].username).toBe("user1");
    expect(json.accounts[0].bio).toBe("hello world");
    expect(json.accounts[0].bio_length).toBe(11);
    expect(json.accounts[0].group).toBe("Group 1");
    expect(json.accounts[0].status).toBe("active");
  });

  it("handleGetAccountBios maps retired status correctly", async () => {
    mockFrom.mockImplementation((table: string) => {
      if (table === "accounts") {
        return chainMock({
          data: [
            {
              id: "a1",
              username: "user1",
              biography: null,
              followers_count: 0,
              is_active: false,
              is_retired: true,
              is_shadowbanned: false,
              needs_reauth: false,
            },
          ],
          error: null,
        });
      }
      return chainMock({ data: [], error: null });
    });

    const { handleGetAccountBios } = await import(
      "../../api/_lib/handlers/auto-post/route/contentHandlers"
    );
    const res = mockRes();

    await handleGetAccountBios({} as any, res, "user-1");

    const json = res.json.mock.calls[0][0];
    expect(json.accounts[0].status).toBe("retired");
    expect(json.accounts[0].bio).toBeNull();
    expect(json.accounts[0].bio_length).toBe(0);
  });

  // ── handleBulkSetContentStrategy ──────────────────────────────────────

  it("handleBulkSetContentStrategy merges with existing strategy", async () => {
    let updatedStrategy: any = null;

    const chain = chainMock({
      data: {
        id: "g1",
        content_strategy: { tone_notes: "existing", pillars: ["old"] },
      },
      error: null,
    });
    chain.update = vi.fn().mockImplementation((payload: any) => {
      updatedStrategy = payload;
      return chain;
    });

    mockFrom.mockReturnValue(chain);

    const { handleBulkSetContentStrategy } = await import(
      "../../api/_lib/handlers/auto-post/route/contentHandlers"
    );
    const res = mockRes();

    await handleBulkSetContentStrategy(
      {
        body: {
          strategies: [
            { groupId: "g1", pillars: ["new1", "new2"], weeklyTarget: 7 },
          ],
        },
      } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(200);
		const json = res.json.mock.calls[0][0];
		expect(json.updated).toBe(1);
		expect(updatedStrategy.content_strategy).toMatchObject({
			tone_notes: "existing",
			pillars: ["new1", "new2"],
			weekly_target: 7,
		});
	});

  it("handleBulkSetContentStrategy rejects empty strategies array", async () => {
    const { handleBulkSetContentStrategy } = await import(
      "../../api/_lib/handlers/auto-post/route/contentHandlers"
    );
    const res = mockRes();

    await handleBulkSetContentStrategy(
      { body: { strategies: [] } } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("handleBulkSetContentStrategy rejects >30 strategies", async () => {
    const { handleBulkSetContentStrategy } = await import(
      "../../api/_lib/handlers/auto-post/route/contentHandlers"
    );
    const res = mockRes();

    const strategies = Array.from({ length: 31 }, (_, i) => ({
      groupId: `g${i}`,
      pillars: [],
    }));

    await handleBulkSetContentStrategy(
      { body: { strategies } } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(400);
  });

  // ── handleGetVariants ─────────────────────────────────────────────────

  it("handleGetVariants requires postId", async () => {
    const { handleGetVariants } = await import(
      "../../api/_lib/handlers/auto-post/route/contentHandlers"
    );
    const res = mockRes();

    await handleGetVariants(
      { query: {}, body: {} } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("handleGetVariants returns variants and original", async () => {
    let callCount = 0;
    mockFrom.mockImplementation(() => {
      callCount++;
      if (callCount === 1) {
        // First query in handleGetVariants is the ORIGINAL post fetch.
        // Must include workspace_id so authorizeQueueRow can match against
        // the verifyWorkspaceAccess mock (returns true).
        return chainMock({
          data: {
            id: "p1",
            content: "original content",
            workspace_id: "ws1",
          },
          error: null,
        });
      }
      // Second query is the variants list.
      return chainMock({
        data: [{ id: "v1", content: "variant content" }],
        error: null,
      });
    });

    const { handleGetVariants } = await import(
      "../../api/_lib/handlers/auto-post/route/contentHandlers"
    );
    const res = mockRes();

    await handleGetVariants(
      { query: { postId: "p1" }, body: {} } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(200);
    const json = res.json.mock.calls[0][0];
    expect(json.original).toBeTruthy();
    expect(json.variants).toHaveLength(1);
  });

  // ── handlePromoteVariant ──────────────────────────────────────────────

  it("handlePromoteVariant requires variantId", async () => {
    const { handlePromoteVariant } = await import(
      "../../api/_lib/handlers/auto-post/route/contentHandlers"
    );
    const res = mockRes();

    await handlePromoteVariant(
      { body: {} } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("handlePromoteVariant rejects non-draft variant", async () => {
    mockFrom.mockReturnValue(
      chainMock({
        data: {
          id: "v1",
          content: "test",
          status: "published",
          source_type: "ai_variant",
          workspace_id: "ws1",
        },
        error: null,
      })
    );

    const { handlePromoteVariant } = await import(
      "../../api/_lib/handlers/auto-post/route/contentHandlers"
    );
    const res = mockRes();

    await handlePromoteVariant(
      { body: { variantId: "v1" } } as any,
      res,
      "user-1"
    );

    expect(res.status).toHaveBeenCalledWith(400);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({ error: expect.stringContaining("published") })
    );
  });
});
