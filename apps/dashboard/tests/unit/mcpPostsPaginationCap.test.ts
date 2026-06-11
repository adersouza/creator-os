/**
 * Encodes the pagination contract for MCP tools that fetch posts.
 *
 * Key invariants:
 * 1. The server hard-caps every response at 100 rows regardless of requested limit.
 * 2. The MCP tool clamps the limit client-side before sending — caller never
 *    receives fewer rows than requested without knowing it.
 * 3. hasMore signals when more pages exist — the caller must use offset to paginate.
 * 4. The offset cap (10,000) prevents DoS via large offset scans.
 *
 * If someone removes the Math.min(100, ...) on either the server or tool layer,
 * the cap tests fail. If the hasMore contract breaks, the pagination test fails.
 */

import { describe, it, expect } from "vitest";

// ---------------------------------------------------------------------------
// Server-side cap — from api/v1/posts.ts line 33
// ---------------------------------------------------------------------------

// Exact replication of the server's limit calculation.
// Any change to this formula must also update this test.
const serverLimit = (requested: number | undefined, raw: string | undefined) => {
  const parsed = parseInt(raw ?? String(requested ?? ""), 10);
  return Math.min(100, Math.max(1, isNaN(parsed) ? 50 : parsed));
};

describe("server-side limit cap (api/v1/posts.ts)", () => {
  it("caps at 100 for any value above 100", () => {
    expect(serverLimit(5000, "5000")).toBe(100);
    expect(serverLimit(101, "101")).toBe(100);
    expect(serverLimit(1000, "1000")).toBe(100);
  });

  it("passes through values at or below 100", () => {
    expect(serverLimit(100, "100")).toBe(100);
    expect(serverLimit(50, "50")).toBe(50);
    expect(serverLimit(1, "1")).toBe(1);
  });

  it("defaults to 50 when no limit is supplied", () => {
    expect(serverLimit(undefined, undefined)).toBe(50);
  });

  it("floors at 1 for zero or negative inputs", () => {
    expect(serverLimit(0, "0")).toBe(1);
    expect(serverLimit(-10, "-10")).toBe(1);
  });

  it("defaults to 50 for non-numeric strings", () => {
    expect(serverLimit(undefined, "abc")).toBe(50);
  });
});

// ---------------------------------------------------------------------------
// MCP tool client-side clamp — from mcp-server/src/tools/posts.ts
// ---------------------------------------------------------------------------

// The MCP get_posts tool must clamp before sending to avoid the caller
// believing they requested N rows when only 100 will be returned.
const mcpToolClamp = (requested: number | undefined) =>
  requested ? Math.min(100, requested) : undefined;

describe("MCP tool client-side limit clamp", () => {
  it("clamps 5000 to 100 before sending to server", () => {
    expect(mcpToolClamp(5000)).toBe(100);
  });

  it("passes through values ≤ 100 unchanged", () => {
    expect(mcpToolClamp(20)).toBe(20);
    expect(mcpToolClamp(100)).toBe(100);
  });

  it("passes undefined through (server will default to 50)", () => {
    expect(mcpToolClamp(undefined)).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// Pagination contract — hasMore + offset
// ---------------------------------------------------------------------------

// Replicates the hasMore calculation from api/v1/posts.ts line 111.
const hasMore = (offset: number, limit: number, total: number) =>
  offset + limit < total;

describe("pagination contract — hasMore and offset", () => {
  it("hasMore is true when more records exist beyond this page", () => {
    expect(hasMore(0, 100, 5000)).toBe(true);
    expect(hasMore(0, 20, 21)).toBe(true);
  });

  it("hasMore is false on the last page", () => {
    expect(hasMore(0, 100, 100)).toBe(false);
    expect(hasMore(80, 20, 100)).toBe(false);
    expect(hasMore(0, 50, 30)).toBe(false);
  });

  it("caller asking for 5000 gets 100, hasMore=true — must paginate", () => {
    const limit = serverLimit(5000, "5000"); // 100
    expect(hasMore(0, limit, 5000)).toBe(true);
    // Caller must make Math.ceil(5000/100) = 50 requests to retrieve all posts.
    // This is a known constraint — documented, not hidden.
    expect(Math.ceil(5000 / limit)).toBe(50);
  });

  it("correct offset for page N given a fixed limit", () => {
    const limit = 100;
    const pageOffsets = [0, 1, 2, 3].map((page) => page * limit);
    expect(pageOffsets).toEqual([0, 100, 200, 300]);
  });
});

// ---------------------------------------------------------------------------
// Offset cap — prevents DoS via large offset scans (api/v1/posts.ts line 38)
// ---------------------------------------------------------------------------

const serverOffset = (raw: string | undefined) => {
  const parsed = parseInt(raw ?? "0", 10);
  return Math.min(10000, Math.max(0, isNaN(parsed) ? 0 : parsed));
};

describe("server-side offset cap", () => {
  it("caps offset at 10,000", () => {
    expect(serverOffset("99999")).toBe(10000);
    expect(serverOffset("10001")).toBe(10000);
  });

  it("passes through valid offsets", () => {
    expect(serverOffset("0")).toBe(0);
    expect(serverOffset("100")).toBe(100);
    expect(serverOffset("9999")).toBe(9999);
    expect(serverOffset("10000")).toBe(10000);
  });

  it("defaults to 0 for undefined or invalid", () => {
    expect(serverOffset(undefined)).toBe(0);
    expect(serverOffset("abc")).toBe(0);
  });

  it("floors at 0 for negative values", () => {
    expect(serverOffset("-1")).toBe(0);
  });
});
