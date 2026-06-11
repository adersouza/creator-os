/**
 * Unit tests for VAPID Key handler
 * (api/_lib/handlers/push/vapid-key.ts)
 *
 * Covers: GET returns key, missing env var, method validation,
 * cache headers, cache busting
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

// ---------------------------------------------------------------------------
// Mock fns
// ---------------------------------------------------------------------------

const mockApiError = vi.fn();
const mockApiSuccess = vi.fn();
const mockMethodNotAllowed = vi.fn();

// ---------------------------------------------------------------------------
// vi.mock()
// ---------------------------------------------------------------------------

vi.mock("@/api/_lib/apiResponse", () => ({
  apiError: (...args: unknown[]) => mockApiError(...args),
  apiSuccess: (...args: unknown[]) => mockApiSuccess(...args),
  methodNotAllowed: (res: any) => mockMethodNotAllowed(res),
}));

// ---------------------------------------------------------------------------
// Import module under test
// ---------------------------------------------------------------------------

import vapidKeyHandler from "@/api/_lib/handlers/push/vapid-key";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockReq(overrides: Record<string, unknown> = {}) {
  return {
    method: "GET",
    query: {},
    body: {},
    headers: {},
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("push/vapid-key handler", () => {
  const originalEnv = process.env.VAPID_PUBLIC_KEY;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    if (originalEnv !== undefined) {
      process.env.VAPID_PUBLIC_KEY = originalEnv;
    } else {
      delete process.env.VAPID_PUBLIC_KEY;
    }
  });

  // ── Method validation ─────────────────────────────────────────────────────

  it("rejects non-GET methods", async () => {
    const req = mockReq({ method: "POST" });
    const res = mockRes();
    await vapidKeyHandler(req as any, res as any);
    expect(mockMethodNotAllowed).toHaveBeenCalledWith(res);
  });

  it("rejects PUT method", async () => {
    const req = mockReq({ method: "PUT" });
    const res = mockRes();
    await vapidKeyHandler(req as any, res as any);
    expect(mockMethodNotAllowed).toHaveBeenCalledWith(res);
  });

  // ── Missing env var ───────────────────────────────────────────────────────

  it("returns 503 when VAPID_PUBLIC_KEY is not set", async () => {
    delete process.env.VAPID_PUBLIC_KEY;
    const req = mockReq();
    const res = mockRes();
    await vapidKeyHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 503, "Push notifications not configured");
  });

  // ── Happy path ────────────────────────────────────────────────────────────

  it("returns the VAPID public key", async () => {
    process.env.VAPID_PUBLIC_KEY = "test-vapid-key-123";
    const req = mockReq();
    const res = mockRes();
    await vapidKeyHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { key: "test-vapid-key-123" });
  });

  it("sets Cache-Control header to 5 minutes", async () => {
    process.env.VAPID_PUBLIC_KEY = "test-vapid-key";
    const req = mockReq();
    const res = mockRes();
    await vapidKeyHandler(req as any, res as any);
    expect(res.setHeader).toHaveBeenCalledWith("Cache-Control", "public, max-age=300");
  });

  // ── Cache busting ─────────────────────────────────────────────────────────

  it("sets no-store on cache bust", async () => {
    process.env.VAPID_PUBLIC_KEY = "test-vapid-key";
    const req = mockReq({ query: { bust: "" } });
    const res = mockRes();
    await vapidKeyHandler(req as any, res as any);
    expect(res.setHeader).toHaveBeenCalledWith("Cache-Control", "no-store");
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { key: "test-vapid-key" });
  });

  it("normal request does not set no-store", async () => {
    process.env.VAPID_PUBLIC_KEY = "test-vapid-key";
    const req = mockReq();
    const res = mockRes();
    await vapidKeyHandler(req as any, res as any);
    expect(res.setHeader).not.toHaveBeenCalledWith("Cache-Control", "no-store");
  });
});
