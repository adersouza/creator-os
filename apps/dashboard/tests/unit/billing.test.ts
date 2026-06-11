/**
 * Direct tests for getAccountLimit() from api/_lib/billing.ts
 *
 * The existing billing-downgrade-safeguards.test.ts simulates the billing logic
 * with local copies. This test imports the REAL getAccountLimit() function and
 * validates add-on slot behavior, tier edge cases, and boundary conditions.
 */

import { describe, expect, it } from "vitest";
import { getAccountLimit } from "@/api/_lib/billing";

describe("getAccountLimit", () => {
  // ── Base tier limits ────────────────────────────────────────────────────────

  it("free tier returns 1", () => {
    expect(getAccountLimit("free")).toBe(1);
  });

  it("pro tier returns 5 (no add-ons)", () => {
    expect(getAccountLimit("pro")).toBe(5);
  });

  it("empire tier returns Infinity", () => {
    expect(getAccountLimit("empire")).toBe(Infinity);
  });

  it("agency tier returns Infinity", () => {
    expect(getAccountLimit("agency")).toBe(Infinity);
  });

  it("unknown tier returns Infinity (safe default)", () => {
    expect(getAccountLimit("unknown_tier")).toBe(Infinity);
  });

  it("empty string tier returns Infinity", () => {
    expect(getAccountLimit("")).toBe(Infinity);
  });

  // ── Add-on slots ────────────────────────────────────────────────────────────

  it("pro tier with 1 add-on returns 6", () => {
    expect(getAccountLimit("pro", 1)).toBe(6);
  });

  it("pro tier with 3 add-ons returns 8", () => {
    expect(getAccountLimit("pro", 3)).toBe(8);
  });

  it("pro tier with 5 add-ons returns 10 (max add-on cap)", () => {
    expect(getAccountLimit("pro", 5)).toBe(10);
  });

  it("pro tier add-ons are capped at 5 (requesting 10 still yields 10)", () => {
    expect(getAccountLimit("pro", 10)).toBe(10);
  });

  it("pro tier add-ons are capped at 5 (requesting 100 still yields 10)", () => {
    expect(getAccountLimit("pro", 100)).toBe(10);
  });

  it("free tier ignores add-on slots (still returns 1)", () => {
    expect(getAccountLimit("free", 5)).toBe(1);
  });

  it("empire tier ignores add-on slots (still returns Infinity)", () => {
    expect(getAccountLimit("empire", 5)).toBe(Infinity);
  });

  // ── Default parameter ───────────────────────────────────────────────────────

  it("extraAccounts defaults to 0 when omitted", () => {
    expect(getAccountLimit("pro")).toBe(getAccountLimit("pro", 0));
  });

  // ── Boundary: zero add-ons explicitly ───────────────────────────────────────

  it("pro tier with 0 add-ons returns 5", () => {
    expect(getAccountLimit("pro", 0)).toBe(5);
  });
});
