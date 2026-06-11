import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock logger to suppress output during tests
vi.mock("../../api/_lib/logger.js", () => ({
  logger: {
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  },
}));

const { isPrivateIP, validateUrlNotPrivate } = await import(
  "../../api/_lib/ssrfProtection.js"
);

// ============================================================================
// isPrivateIP — IPv4 Private Ranges
// ============================================================================

describe("isPrivateIP — IPv4", () => {
  // Loopback (127.0.0.0/8)
  it("blocks 127.0.0.1 (loopback)", () => {
    expect(isPrivateIP("127.0.0.1")).toBe(true);
  });

  it("blocks 127.255.255.255 (loopback upper bound)", () => {
    expect(isPrivateIP("127.255.255.255")).toBe(true);
  });

  it("blocks 127.0.0.0 (loopback network)", () => {
    expect(isPrivateIP("127.0.0.0")).toBe(true);
  });

  // 10.0.0.0/8
  it("blocks 10.0.0.1 (RFC 1918)", () => {
    expect(isPrivateIP("10.0.0.1")).toBe(true);
  });

  it("blocks 10.255.255.255 (RFC 1918 upper bound)", () => {
    expect(isPrivateIP("10.255.255.255")).toBe(true);
  });

  // 172.16.0.0/12
  it("blocks 172.16.0.1 (RFC 1918)", () => {
    expect(isPrivateIP("172.16.0.1")).toBe(true);
  });

  it("blocks 172.31.255.255 (RFC 1918 upper bound)", () => {
    expect(isPrivateIP("172.31.255.255")).toBe(true);
  });

  it("allows 172.15.255.255 (just below private range)", () => {
    expect(isPrivateIP("172.15.255.255")).toBe(false);
  });

  it("allows 172.32.0.0 (just above private range)", () => {
    expect(isPrivateIP("172.32.0.0")).toBe(false);
  });

  // 192.168.0.0/16
  it("blocks 192.168.0.1 (RFC 1918)", () => {
    expect(isPrivateIP("192.168.0.1")).toBe(true);
  });

  it("blocks 192.168.255.255 (RFC 1918 upper bound)", () => {
    expect(isPrivateIP("192.168.255.255")).toBe(true);
  });

  it("allows 192.167.0.1 (not private)", () => {
    expect(isPrivateIP("192.167.0.1")).toBe(false);
  });

  // 169.254.0.0/16 — link-local (AWS metadata endpoint lives here)
  it("blocks 169.254.169.254 (cloud metadata endpoint)", () => {
    expect(isPrivateIP("169.254.169.254")).toBe(true);
  });

  it("blocks 169.254.0.1 (link-local)", () => {
    expect(isPrivateIP("169.254.0.1")).toBe(true);
  });

  // 0.0.0.0
  it("blocks 0.0.0.0 (unspecified)", () => {
    expect(isPrivateIP("0.0.0.0")).toBe(true);
  });

  // Public IPs — must be ALLOWED
  it("allows 8.8.8.8 (Google DNS)", () => {
    expect(isPrivateIP("8.8.8.8")).toBe(false);
  });

  it("allows 1.1.1.1 (Cloudflare DNS)", () => {
    expect(isPrivateIP("1.1.1.1")).toBe(false);
  });

  it("allows 93.184.216.34 (example.com)", () => {
    expect(isPrivateIP("93.184.216.34")).toBe(false);
  });

  it("allows 203.0.113.1 (public documentation range)", () => {
    expect(isPrivateIP("203.0.113.1")).toBe(false);
  });

  // Malformed IPs — should be blocked (treated as private)
  it("blocks malformed IP with 5 octets", () => {
    expect(isPrivateIP("1.2.3.4.5")).toBe(true);
  });

  it("blocks malformed IP with 3 octets", () => {
    expect(isPrivateIP("1.2.3")).toBe(true);
  });

  it("blocks IP with octet > 255", () => {
    expect(isPrivateIP("256.1.1.1")).toBe(true);
  });

  it("blocks IP with negative octet", () => {
    expect(isPrivateIP("10.-1.0.1")).toBe(true);
  });

  it("blocks IP with non-numeric octet", () => {
    expect(isPrivateIP("10.abc.0.1")).toBe(true);
  });

  it("blocks empty string", () => {
    expect(isPrivateIP("")).toBe(true);
  });
});

// ============================================================================
// isPrivateIP — IPv6
// ============================================================================

describe("isPrivateIP — IPv6", () => {
  it("blocks ::1 (loopback)", () => {
    expect(isPrivateIP("::1")).toBe(true);
  });

  it("blocks :: (unspecified)", () => {
    expect(isPrivateIP("::")).toBe(true);
  });

  it("blocks fc00:: (unique local)", () => {
    expect(isPrivateIP("fc00::1")).toBe(true);
  });

  it("blocks fd00:: (unique local)", () => {
    expect(isPrivateIP("fd12:3456::1")).toBe(true);
  });

  it("blocks fe80:: (link-local)", () => {
    expect(isPrivateIP("fe80::1")).toBe(true);
  });

  it("blocks uppercase IPv6 (case-insensitive)", () => {
    expect(isPrivateIP("FE80::1")).toBe(true);
  });

  it("blocks IPv4-mapped IPv6 with private IPv4 (::ffff:10.0.0.1)", () => {
    expect(isPrivateIP("::ffff:10.0.0.1")).toBe(true);
  });

  it("blocks IPv4-mapped IPv6 with loopback (::ffff:127.0.0.1)", () => {
    expect(isPrivateIP("::ffff:127.0.0.1")).toBe(true);
  });

  it("blocks IPv4-mapped IPv6 hex loopback (::ffff:7f00:0001)", () => {
    expect(isPrivateIP("::ffff:7f00:0001")).toBe(true);
  });

  it("blocks normalized IPv4-mapped IPv6 hex private range", () => {
    expect(isPrivateIP("0:0:0:0:0:ffff:0a00:0001")).toBe(true);
  });

  it("blocks IPv4-mapped IPv6 with metadata IP (::ffff:169.254.169.254)", () => {
    expect(isPrivateIP("::ffff:169.254.169.254")).toBe(true);
  });

  it("allows IPv4-mapped IPv6 with public IPv4 (::ffff:8.8.8.8)", () => {
    expect(isPrivateIP("::ffff:8.8.8.8")).toBe(false);
  });

  it("allows public IPv6 (2001:db8::1)", () => {
    expect(isPrivateIP("2001:db8::1")).toBe(false);
  });

  it("allows public IPv6 (2607:f8b0:4004:800::200e — Google)", () => {
    expect(isPrivateIP("2607:f8b0:4004:800::200e")).toBe(false);
  });
});

// ============================================================================
// validateUrlNotPrivate — URL validation
// ============================================================================

describe("validateUrlNotPrivate", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // Protocol filtering
  it("blocks ftp:// protocol", async () => {
    const result = await validateUrlNotPrivate("ftp://example.com/file");
    expect(result).toContain("Only HTTP(S)");
  });

  it("blocks file:// protocol", async () => {
    const result = await validateUrlNotPrivate("file:///etc/passwd");
    expect(result).toContain("Only HTTP(S)");
  });

  it("blocks javascript: protocol", async () => {
    // new URL("javascript:...") throws, which gets caught as URL validation failure
    const result = await validateUrlNotPrivate("javascript:alert(1)");
    expect(result).not.toBeNull();
  });

  // Localhost blocking
  it("blocks http://localhost", async () => {
    const result = await validateUrlNotPrivate("http://localhost/admin");
    expect(result).toContain("localhost");
  });

  it("blocks http://0.0.0.0", async () => {
    const result = await validateUrlNotPrivate("http://0.0.0.0/");
    expect(result).toContain("localhost");
  });

  it("blocks http://[::1]", async () => {
    const result = await validateUrlNotPrivate("http://[::1]/");
    expect(result).toContain("localhost");
  });

  // IP literal detection — private
  it("blocks http://127.0.0.1 (loopback literal)", async () => {
    const result = await validateUrlNotPrivate("http://127.0.0.1/secret");
    expect(result).toContain("private IP");
  });

  it("blocks http://10.0.0.1 (RFC 1918 literal)", async () => {
    const result = await validateUrlNotPrivate("http://10.0.0.1/internal");
    expect(result).toContain("private IP");
  });

  it("blocks http://192.168.1.1 (RFC 1918 literal)", async () => {
    const result = await validateUrlNotPrivate("http://192.168.1.1/router");
    expect(result).toContain("private IP");
  });

  it("blocks http://169.254.169.254 (cloud metadata)", async () => {
    const result = await validateUrlNotPrivate(
      "http://169.254.169.254/latest/meta-data/"
    );
    expect(result).toContain("private IP");
  });

  it("blocks IPv6 literal [fe80::1]", async () => {
    const result = await validateUrlNotPrivate("http://[fe80::1]/");
    expect(result).toContain("private IP");
  });

  it("blocks hex-form IPv4-mapped IPv6 [::ffff:7f00:1]", async () => {
    const result = await validateUrlNotPrivate("http://[::ffff:127.0.0.1]/");
    expect(result).toContain("private IP");
  });

  // IP literal — public (allowed)
  it("allows http://8.8.8.8 (public IP literal)", async () => {
    const result = await validateUrlNotPrivate("http://8.8.8.8/");
    expect(result).toBeNull();
  });

  it("allows IPv6 literal [2607:f8b0:4004:800::200e]", async () => {
    const result = await validateUrlNotPrivate(
      "http://[2607:f8b0:4004:800::200e]/"
    );
    expect(result).toBeNull();
  });

  // DNS resolution — mock dns to test rebinding protection
  it("blocks hostname that resolves to private IP (DNS rebinding)", async () => {
    // Mock DNS to return a private IP
    vi.doMock("node:dns", () => ({
      resolve4: (_hostname: string, cb: Function) =>
        cb(null, ["10.0.0.1"]),
      resolve6: (_hostname: string, cb: Function) =>
        cb(new Error("no AAAA"), null),
    }));

    // Re-import to pick up mock
    const { validateUrlNotPrivate: validate } = await import(
      "../../api/_lib/ssrfProtection.js"
    );
    const result = await validate("https://evil-rebind.example.com/steal");
    expect(result).toContain("private IP");

    vi.doUnmock("node:dns");
  });

  it("allows hostname that resolves to public IP", async () => {
    vi.doMock("node:dns", () => ({
      resolve4: (_hostname: string, cb: Function) =>
        cb(null, ["93.184.216.34"]),
      resolve6: (_hostname: string, cb: Function) =>
        cb(new Error("no AAAA"), null),
    }));

    const { validateUrlNotPrivate: validate } = await import(
      "../../api/_lib/ssrfProtection.js"
    );
    const result = await validate("https://example.com/page");
    expect(result).toBeNull();

    vi.doUnmock("node:dns");
  });

  it("blocks if any resolved IP is private (mixed results)", async () => {
    vi.doMock("node:dns", () => ({
      resolve4: (_hostname: string, cb: Function) =>
        cb(null, ["93.184.216.34", "10.0.0.1"]),
      resolve6: (_hostname: string, cb: Function) =>
        cb(new Error("no AAAA"), null),
    }));

    const { validateUrlNotPrivate: validate } = await import(
      "../../api/_lib/ssrfProtection.js"
    );
    const result = await validate("https://multi-a-record.example.com/");
    expect(result).toContain("private IP");

    vi.doUnmock("node:dns");
  });

  it("returns error when hostname cannot be resolved (no records)", async () => {
    vi.doMock("node:dns", () => ({
      resolve4: (_hostname: string, cb: Function) =>
        cb(new Error("NXDOMAIN"), null),
      resolve6: (_hostname: string, cb: Function) =>
        cb(new Error("NXDOMAIN"), null),
    }));

    const { validateUrlNotPrivate: validate } = await import(
      "../../api/_lib/ssrfProtection.js"
    );
    const result = await validate("https://nonexistent.invalid/");
    expect(result).toContain("Could not resolve");

    vi.doUnmock("node:dns");
  });

  // Malformed URLs
  it("returns error for completely invalid URL", async () => {
    const result = await validateUrlNotPrivate("not-a-url");
    expect(result).not.toBeNull();
  });

  it("returns error for empty string", async () => {
    const result = await validateUrlNotPrivate("");
    expect(result).not.toBeNull();
  });

  // Cloud metadata variations
  it("blocks metadata endpoint with path traversal", async () => {
    const result = await validateUrlNotPrivate(
      "http://169.254.169.254/latest/api/token"
    );
    expect(result).toContain("private IP");
  });

  it("blocks metadata endpoint on non-standard port", async () => {
    const result = await validateUrlNotPrivate("http://169.254.169.254:8080/");
    expect(result).toContain("private IP");
  });
});
