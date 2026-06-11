import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock supabase before importing the module under test
const mockGetUser = vi.fn();
vi.mock("../../api/_lib/supabase.js", () => ({
  getSupabase: () => ({
    auth: { getUser: mockGetUser },
  }),
}));

// Now import the function under test
const { getAuthUserOrError } = await import("../../api/_lib/apiResponse.js");

function mockRes() {
  const res: any = {};
  res.status = vi.fn().mockReturnValue(res);
  res.json = vi.fn().mockReturnValue(res);
  return res;
}

describe("getAuthUserOrError", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns user for valid Bearer token", async () => {
    mockGetUser.mockResolvedValue({
      data: { user: { id: "user-123", email: "test@example.com" } },
      error: null,
    });

    const req = { headers: { authorization: "Bearer valid-token-abc" } };
    const res = mockRes();

    const user = await getAuthUserOrError(req, res);
    expect(user).toEqual({ id: "user-123", email: "test@example.com" });
    expect(res.status).not.toHaveBeenCalled();
  });

  it("returns null and sends 401 when no Authorization header", async () => {
    const req = { headers: {} };
    const res = mockRes();

    const user = await getAuthUserOrError(req, res);
    expect(user).toBeNull();
    expect(res.status).toHaveBeenCalledWith(401);
  });

  it("returns null and sends 401 for malformed header (no Bearer prefix)", async () => {
    const req = { headers: { authorization: "Token abc123" } };
    const res = mockRes();

    const user = await getAuthUserOrError(req, res);
    expect(user).toBeNull();
    expect(res.status).toHaveBeenCalledWith(401);
  });

  it("rejects API keys on session-auth routes", async () => {
    const req = { headers: { authorization: "Bearer juno_ak_test_key" } };
    const res = mockRes();

    const user = await getAuthUserOrError(req, res);
    expect(user).toBeNull();
    expect(mockGetUser).not.toHaveBeenCalled();
    expect(res.status).toHaveBeenCalledWith(401);
  });

  it("returns null and sends 401 when supabase returns error (expired token)", async () => {
    mockGetUser.mockResolvedValue({
      data: { user: null },
      error: { message: "Token expired" },
    });

    const req = { headers: { authorization: "Bearer expired-token" } };
    const res = mockRes();

    const user = await getAuthUserOrError(req, res);
    expect(user).toBeNull();
    expect(res.status).toHaveBeenCalledWith(401);
  });

  it("returns null when supabase returns no user and no error", async () => {
    mockGetUser.mockResolvedValue({
      data: { user: null },
      error: null,
    });

    const req = { headers: { authorization: "Bearer invalid-token" } };
    const res = mockRes();

    const user = await getAuthUserOrError(req, res);
    expect(user).toBeNull();
    expect(res.status).toHaveBeenCalledWith(401);
  });
});
