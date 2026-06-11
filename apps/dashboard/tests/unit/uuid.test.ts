/**
 * randomUUID utility tests
 *
 * Validates:
 * 1. Returns a valid RFC 4122 v4 UUID string
 * 2. Output is unique across many calls (collision resistance)
 * 3. Falls back gracefully when crypto.randomUUID is unavailable (Safari <15.4)
 * 4. Fallback path produces valid UUIDs via getRandomValues
 */

import { describe, expect, it } from "vitest";
import { randomUUID } from "@/src/lib/uuid";

const UUID_REGEX =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe("randomUUID", () => {
  it("returns a valid RFC 4122 v4 UUID", () => {
    const id = randomUUID();
    expect(id).toMatch(UUID_REGEX);
  });

  it("produces unique values across 1000 calls", () => {
    const ids = new Set(Array.from({ length: 1000 }, () => randomUUID()));
    expect(ids.size).toBe(1000);
  });

  it("falls back via getRandomValues when randomUUID is unavailable", () => {
    const original = crypto.randomUUID;
    // Simulate Safari 14 / Chrome 91 — getRandomValues present, randomUUID absent
    Object.defineProperty(crypto, "randomUUID", {
      value: undefined,
      configurable: true,
    });

    try {
      const id = randomUUID();
      expect(id).toMatch(UUID_REGEX);
    } finally {
      Object.defineProperty(crypto, "randomUUID", {
        value: original,
        configurable: true,
      });
    }
  });

  it("fallback still produces unique values", () => {
    const original = crypto.randomUUID;
    Object.defineProperty(crypto, "randomUUID", {
      value: undefined,
      configurable: true,
    });

    try {
      const ids = new Set(Array.from({ length: 200 }, () => randomUUID()));
      expect(ids.size).toBe(200);
    } finally {
      Object.defineProperty(crypto, "randomUUID", {
        value: original,
        configurable: true,
      });
    }
  });

  it("version nibble is always 4", () => {
    for (let i = 0; i < 50; i++) {
      const id = randomUUID();
      expect(id[14]).toBe("4");
    }
  });

  it("variant nibble is always 8, 9, a, or b", () => {
    for (let i = 0; i < 50; i++) {
      const id = randomUUID();
      expect(["8", "9", "a", "b"]).toContain(id[19]);
    }
  });
});
