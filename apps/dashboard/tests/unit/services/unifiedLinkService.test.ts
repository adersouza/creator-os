/**
 * Tests for services/unifiedLinkService.ts
 *
 * Validates ROI metric aggregation, platform split calculation,
 * fallback behavior on errors, and unified link creation.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";

// Mock Supabase with table-aware responses
let roiData: any[] | null = [];
let roiError: any = null;
let platformData: any[] | null = [];
let insertError: any = null;

const mockSupabase = {
  from: vi.fn().mockImplementation((table: string) => {
    if (table === "unified_link_roi") {
      return {
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockResolvedValue({ data: roiData, error: roiError }),
        }),
      };
    }
    if (table === "smart_links") {
      return {
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockResolvedValue({ data: platformData, error: null }),
        }),
      };
    }
    if (table === "unified_links") {
      return {
        insert: vi.fn().mockResolvedValue({ error: insertError }),
      };
    }
    return {
      select: vi.fn().mockReturnThis(),
      eq: vi.fn().mockResolvedValue({ data: null, error: null }),
    };
  }),
};

vi.mock("@/services/api/shared", () => ({
  getSupabaseAny: () => mockSupabase,
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

import { unifiedLinkService } from "@/services/unifiedLinkService";

describe("unifiedLinkService", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    roiData = [];
    roiError = null;
    platformData = [];
    insertError = null;
  });

  // ============================================================
  // getROISummary
  // ============================================================
  describe("getROISummary()", () => {
    it("aggregates ROI data correctly", async () => {
      roiData = [
        { page_views: 100, total_redirect_clicks: 20, estimated_revenue: 50 },
        { page_views: 200, total_redirect_clicks: 30, estimated_revenue: 75 },
      ];

      const result = await unifiedLinkService.getROISummary("user-1");

      expect(result.totalClicks).toBe(50);
      expect(result.totalRevenue).toBe(125);
      expect(result.avgEPC).toBeCloseTo(2.5); // 125/50
      expect(result.funnel.impressions).toBe(300); // 100+200
      expect(result.funnel.clicks).toBe(50);
    });

    it("calculates platform split with weighted estimation", async () => {
      platformData = [
        { click_count: 100, threads_redirect_url: "https://threads.net/...", ig_redirect_url: "https://instagram.com/..." },
        { click_count: 50, threads_redirect_url: "https://threads.net/...", ig_redirect_url: null },
      ];

      const result = await unifiedLinkService.getROISummary("user-1");

      // Link 1: threads = 100 * 0.4 = 40, ig = 100 * 0.6 = 60
      // Link 2: threads = 50 * 0.4 = 20, ig = 0 (no ig url)
      expect(result.platformSplit.threads).toBe(60); // 40 + 20
      expect(result.platformSplit.instagram).toBe(60); // only link 1
    });

    it("calculates conversions at 3% floor", async () => {
      roiData = [
        { page_views: 1000, total_redirect_clicks: 100, estimated_revenue: 0 },
      ];

      const result = await unifiedLinkService.getROISummary("user-1");
      expect(result.funnel.conversions).toBe(3); // 100 * 0.03
    });

    it("handles zero clicks without division error", async () => {
      roiData = [
        { page_views: 100, total_redirect_clicks: 0, estimated_revenue: 0 },
      ];

      const result = await unifiedLinkService.getROISummary("user-1");
      expect(result.avgEPC).toBe(0);
    });

    it("handles null values in ROI data", async () => {
      roiData = [
        { page_views: null, total_redirect_clicks: null, estimated_revenue: null },
      ];

      const result = await unifiedLinkService.getROISummary("user-1");
      expect(result.totalClicks).toBe(0);
      expect(result.totalRevenue).toBe(0);
      expect(result.funnel.impressions).toBe(0);
    });

    it("returns fallback metrics on database error", async () => {
      roiError = { message: "DB timeout" };

      const result = await unifiedLinkService.getROISummary("user-1");

      expect(result).toEqual({
        totalClicks: 0,
        totalRevenue: 0,
        avgEPC: 0,
        platformSplit: { threads: 0, instagram: 0 },
        funnel: { impressions: 0, clicks: 0, conversions: 0 },
      });
    });

    it("handles empty data gracefully", async () => {
      roiData = [];
      platformData = [];

      const result = await unifiedLinkService.getROISummary("user-1");

      expect(result.totalClicks).toBe(0);
      expect(result.totalRevenue).toBe(0);
    });
  });

  // ============================================================
  // createUnifiedLink
  // ============================================================
  describe("createUnifiedLink()", () => {
    it("inserts unified link with correct params", async () => {
      await unifiedLinkService.createUnifiedLink({
        userId: "user-1",
        workspaceId: "ws-1",
        name: "My Link",
        type: "smart_link",
        sourceId: "src-1",
      });

      expect(mockSupabase.from).toHaveBeenCalledWith("unified_links");
    });

    it("throws on insert error", async () => {
      insertError = { message: "Constraint violation" };

      await expect(
        unifiedLinkService.createUnifiedLink({
          userId: "user-1",
          workspaceId: null,
          name: "Test",
          type: "bio_link",
          sourceId: "src-2",
        })
      ).rejects.toEqual({ message: "Constraint violation" });
    });
  });

  // ============================================================
  // getFallbackMetrics
  // ============================================================
  describe("getFallbackMetrics()", () => {
    it("returns all-zero structure", () => {
      const result = unifiedLinkService.getFallbackMetrics();
      expect(result.totalClicks).toBe(0);
      expect(result.totalRevenue).toBe(0);
      expect(result.avgEPC).toBe(0);
      expect(result.platformSplit.threads).toBe(0);
      expect(result.platformSplit.instagram).toBe(0);
      expect(result.funnel.impressions).toBe(0);
      expect(result.funnel.clicks).toBe(0);
      expect(result.funnel.conversions).toBe(0);
    });
  });
});
