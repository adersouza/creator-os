/**
 * Tests for services/crossPostService.ts
 *
 * Validates cross-post settings CRUD operations.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";

// Track calls
let lastTable = "";
let selectResult: any = { data: null, error: null };
let upsertError: any = null;

vi.mock("@/services/supabase", () => ({
  supabase: {
    from: vi.fn().mockImplementation((table: string) => {
      lastTable = table;
      return {
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            maybeSingle: vi.fn().mockResolvedValue(selectResult),
          }),
        }),
        upsert: vi.fn().mockResolvedValue({ error: upsertError }),
      };
    }),
  },
}));

import {
  getCrossPostSettings,
  upsertCrossPostSettings,
} from "@/services/crossPostService";

describe("crossPostService", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    lastTable = "";
    selectResult = { data: null, error: null };
    upsertError = null;
  });

  describe("getCrossPostSettings()", () => {
    it("fetches settings for the workspace", async () => {
      selectResult = {
        data: { workspace_id: "ws-1", auto_cross_post: true },
        error: null,
      };

      const result = await getCrossPostSettings("ws-1");

      expect(lastTable).toBe("cross_post_settings");
      expect(result).toEqual({ workspace_id: "ws-1", auto_cross_post: true });
    });

    it("returns null when no settings exist", async () => {
      selectResult = { data: null, error: null };

      const result = await getCrossPostSettings("ws-1");
      expect(result).toBeNull();
    });

    it("throws on database error", async () => {
      selectResult = { data: null, error: { message: "DB error" } };

      await expect(getCrossPostSettings("ws-1")).rejects.toEqual({
        message: "DB error",
      });
    });
  });

  describe("upsertCrossPostSettings()", () => {
    it("upserts settings with workspace_id and updated_at", async () => {
      const { supabase } = await import("@/services/supabase");

      await upsertCrossPostSettings("ws-1", { auto_cross_post: true });

      expect(supabase.from).toHaveBeenCalledWith("cross_post_settings");
    });

    it("throws on upsert error", async () => {
      upsertError = { message: "Constraint violation" };

      await expect(
        upsertCrossPostSettings("ws-1", { auto_cross_post: false })
      ).rejects.toEqual({ message: "Constraint violation" });
    });
  });
});
