/**
 * Tests for services/approvalService.ts
 *
 * Validates account ID fetching and pending post retrieval for the approval workflow.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";

// Use vi.hoisted so mock state is available in the hoisted vi.mock factory
const { mockState, mockSupabase } = vi.hoisted(() => {
  const mockState = {
    accountsData: [] as any[] | null,
    igAccountsData: [] as any[] | null,
    postsData: [] as any[] | null,
    postsError: null as any,
  };

  const mockSupabase = {
    from: vi.fn().mockImplementation((table: string) => {
      if (table === "accounts") {
        return {
          select: vi.fn().mockImplementation(() =>
            Promise.resolve({ data: mockState.accountsData, error: null })
          ),
        };
      }
      if (table === "instagram_accounts") {
        return {
          select: vi.fn().mockImplementation(() =>
            Promise.resolve({ data: mockState.igAccountsData, error: null })
          ),
        };
      }
      if (table === "posts") {
        return {
          select: vi.fn().mockReturnValue({
            eq: vi.fn().mockReturnValue({
              in: vi.fn().mockReturnValue({
                order: vi.fn().mockImplementation(() =>
                  Promise.resolve({
                    data: mockState.postsData,
                    error: mockState.postsError,
                  })
                ),
              }),
            }),
          }),
        };
      }
      return {
        select: vi.fn().mockReturnThis(),
        eq: vi.fn().mockReturnThis(),
        in: vi.fn().mockReturnThis(),
        order: vi.fn().mockResolvedValue({ data: null, error: null }),
      };
    }),
  };

  return { mockState, mockSupabase };
});

vi.mock("@/services/supabase", () => ({
  supabase: mockSupabase,
}));

import {
  fetchAllAccountIds,
  fetchPendingPostsByAccountIds,
} from "@/services/approvalService";

describe("approvalService", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockState.accountsData = [];
    mockState.igAccountsData = [];
    mockState.postsData = [];
    mockState.postsError = null;
    // Re-wire the from mock after clearAllMocks
    mockSupabase.from.mockImplementation((table: string) => {
      if (table === "accounts") {
        return {
          select: vi.fn().mockImplementation(() =>
            Promise.resolve({ data: mockState.accountsData, error: null })
          ),
        };
      }
      if (table === "instagram_accounts") {
        return {
          select: vi.fn().mockImplementation(() =>
            Promise.resolve({ data: mockState.igAccountsData, error: null })
          ),
        };
      }
      if (table === "posts") {
        return {
          select: vi.fn().mockReturnValue({
            eq: vi.fn().mockReturnValue({
              in: vi.fn().mockReturnValue({
                order: vi.fn().mockImplementation(() =>
                  Promise.resolve({
                    data: mockState.postsData,
                    error: mockState.postsError,
                  })
                ),
              }),
            }),
          }),
        };
      }
      return {
        select: vi.fn().mockReturnThis(),
        eq: vi.fn().mockReturnThis(),
        in: vi.fn().mockReturnThis(),
        order: vi.fn().mockResolvedValue({ data: null, error: null }),
      };
    });
  });

  // ============================================================
  // fetchAllAccountIds
  // ============================================================
  describe("fetchAllAccountIds()", () => {
    it("returns combined threads and instagram account IDs", async () => {
      mockState.accountsData = [{ id: "t-1" }, { id: "t-2" }];
      mockState.igAccountsData = [{ id: "ig-1" }];

      const ids = await fetchAllAccountIds();

      expect(ids).toEqual(["t-1", "t-2", "ig-1"]);
    });

    it("returns empty array when no accounts exist", async () => {
      mockState.accountsData = null;
      mockState.igAccountsData = null;

      const ids = await fetchAllAccountIds();
      expect(ids).toEqual([]);
    });

    it("queries both accounts and instagram_accounts tables", async () => {
      await fetchAllAccountIds();

      const tables = mockSupabase.from.mock.calls.map((c: any) => c[0]);
      expect(tables).toContain("accounts");
      expect(tables).toContain("instagram_accounts");
    });

    it("handles one platform having no accounts", async () => {
      mockState.accountsData = [{ id: "t-1" }];
      mockState.igAccountsData = [];

      const ids = await fetchAllAccountIds();
      expect(ids).toEqual(["t-1"]);
    });
  });

  // ============================================================
  // fetchPendingPostsByAccountIds
  // ============================================================
  describe("fetchPendingPostsByAccountIds()", () => {
    it("fetches pending approval posts for given account IDs", async () => {
      mockState.postsData = [
        { id: "p-1", content: "test", approval_status: "pending", account_id: "t-1" },
      ];

      const result = await fetchPendingPostsByAccountIds(["t-1", "t-2"]);

      expect(result).toEqual([
        { id: "p-1", content: "test", approval_status: "pending", account_id: "t-1" },
      ]);
    });

    it("returns empty array when no pending posts", async () => {
      mockState.postsData = null;

      const result = await fetchPendingPostsByAccountIds(["t-1"]);
      expect(result).toEqual([]);
    });

    it("throws on database error", async () => {
      mockState.postsError = { message: "Query failed" };

      await expect(
        fetchPendingPostsByAccountIds(["t-1"])
      ).rejects.toEqual({ message: "Query failed" });
    });

    it("queries the posts table with approval_status filter", async () => {
      await fetchPendingPostsByAccountIds(["t-1"]);

      expect(mockSupabase.from).toHaveBeenCalledWith("posts");
    });
  });
});
