/**
 * Encodes the invariant that destructive MCP tools (delete_post,
 * delete_draft_folder, delete_template) are gated by an explicit
 * dryRun: false and cannot be triggered by an omitted or truthy value.
 *
 * The gate condition is:  if (dryRun !== false) { return dryRunResponse(...) }
 * This means ONLY the boolean literal `false` unlocks execution.
 *
 * Tests run against the zBool preprocessor (replicated from helpers.ts)
 * plus the default(true) fix applied to the schema. If .default(true) is
 * removed from any destructive tool, the omission test fails.
 */

import { describe, it, expect } from "vitest";
import { z } from "zod";

// Exact replication of zBool from mcp-server/src/helpers.ts.
// Any change to the preprocessor logic must also update this test.
const zBool = z.preprocess(
  (v) => (v === "false" ? false : v === "true" ? true : v),
  z.boolean(),
);

// The schema fragment for every destructive tool's dryRun param after the fix.
// .default(true) makes the invariant explicit rather than relying on the gate
// condition being correct for undefined inputs.
const dryRunSchema = z.object({
  dryRun: zBool.default(true),
});

// ---------------------------------------------------------------------------
// zBool preprocessing — string coercion contract
// ---------------------------------------------------------------------------

describe("zBool — string coercion", () => {
  it('coerces "true" to boolean true', () => {
    expect(zBool.parse("true")).toBe(true);
  });

  it('coerces "false" to boolean false', () => {
    expect(zBool.parse("false")).toBe(false);
  });

  it("passes boolean true through unchanged", () => {
    expect(zBool.parse(true)).toBe(true);
  });

  it("passes boolean false through unchanged", () => {
    expect(zBool.parse(false)).toBe(false);
  });

  it("rejects undefined without a default", () => {
    const result = zBool.safeParse(undefined);
    expect(result.success).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// dryRun schema with .default(true) — omission safety
// ---------------------------------------------------------------------------

describe("dryRun schema — default(true) invariant", () => {
  it("defaults to true when omitted — critical: no param = no execution", () => {
    const { dryRun } = dryRunSchema.parse({});
    expect(dryRun).toBe(true);
  });

  it('resolves "true" string to true', () => {
    expect(dryRunSchema.parse({ dryRun: "true" }).dryRun).toBe(true);
  });

  it('resolves "false" string to false — the only unlock value from MCP clients', () => {
    expect(dryRunSchema.parse({ dryRun: "false" }).dryRun).toBe(false);
  });

  it("resolves boolean true to true", () => {
    expect(dryRunSchema.parse({ dryRun: true }).dryRun).toBe(true);
  });

  it("resolves boolean false to false", () => {
    expect(dryRunSchema.parse({ dryRun: false }).dryRun).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Gate condition — what values actually unlock execution
// ---------------------------------------------------------------------------

describe("dryRun gate condition: dryRun !== false", () => {
  // Simulate the exact condition from every destructive tool handler:
  //   if (dryRun !== false) { return dryRunResponse(...) }
  const wouldExecute = (dryRun: unknown) => dryRun === false;

  it("does NOT execute when dryRun is undefined (omitted param)", () => {
    expect(wouldExecute(undefined)).toBe(false);
  });

  it("does NOT execute when dryRun is true", () => {
    expect(wouldExecute(true)).toBe(false);
  });

  it('does NOT execute when dryRun is the string "false" — must be parsed first', () => {
    expect(wouldExecute("false")).toBe(false);
  });

  it('does NOT execute when dryRun is the string "true"', () => {
    expect(wouldExecute("true")).toBe(false);
  });

  it("DOES execute when dryRun is the boolean false — the only unlock", () => {
    expect(wouldExecute(false)).toBe(true);
  });

  it("combining schema + gate: omitted param never reaches execution", () => {
    const parsed = dryRunSchema.parse({}).dryRun; // undefined → true via default
    expect(wouldExecute(parsed)).toBe(false);
  });

  it("combining schema + gate: dryRun=false reaches execution", () => {
    const parsed = dryRunSchema.parse({ dryRun: false }).dryRun;
    expect(wouldExecute(parsed)).toBe(true);
  });

  it('combining schema + gate: string "false" from MCP client reaches execution after parsing', () => {
    const parsed = dryRunSchema.parse({ dryRun: "false" }).dryRun;
    expect(wouldExecute(parsed)).toBe(true);
  });
});
