import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock tierGate directly to avoid internal cache persistence between tests
const mockGetUserTier = vi.fn();
vi.mock("../../api/_lib/tierGate.js", () => ({
  getUserTier: (...args: any[]) => mockGetUserTier(...args),
}));

// Mock redis
const mockPipeline = vi.fn();
vi.mock("../../api/_lib/redis.js", () => ({
  getRedis: () => ({
    pipeline: mockPipeline,
  }),
}));

// Mock logger
vi.mock("../../api/_lib/logger.js", () => ({
  logger: { error: vi.fn(), warn: vi.fn(), info: vi.fn(), debug: vi.fn() },
}));

const { checkAIRateLimit } = await import("../../api/_lib/aiRateLimit.js");

beforeEach(() => {
  vi.clearAllMocks();
  mockGetUserTier.mockResolvedValue("free");
});

function mockPipelineSuccess(count: number) {
  const pipe = {
    zremrangebyscore: vi.fn(),
    zadd: vi.fn(),
    zcard: vi.fn(),
    expire: vi.fn(),
    exec: vi.fn().mockResolvedValue([null, null, count, null]),
  };
  mockPipeline.mockReturnValue(pipe);
  return pipe;
}

describe("checkAIRateLimit", () => {
  it("allows request when under limit", async () => {
    mockPipelineSuccess(5); // 5 requests, free limit is 20

    const result = await checkAIRateLimit("user-1", "generate");
    expect(result.allowed).toBe(true);
    expect(result.remaining).toBe(15);
    expect(result.limit).toBe(20);
  });

  it("blocks request when at limit", async () => {
    mockPipelineSuccess(21); // over the 20 free limit

    const result = await checkAIRateLimit("user-1", "generate");
    expect(result.allowed).toBe(false);
    expect(result.remaining).toBe(0);
  });

  it("uses higher limit for pro tier", async () => {
    mockGetUserTier.mockResolvedValue("pro");
    mockPipelineSuccess(50); // 50 requests, pro limit is 100

    const result = await checkAIRateLimit("user-1", "generate");
    expect(result.allowed).toBe(true);
    expect(result.remaining).toBe(50);
    expect(result.limit).toBe(100);
  });

  it("fails closed on Redis error (blocks request)", async () => {
    const pipe = {
      zremrangebyscore: vi.fn(),
      zadd: vi.fn(),
      zcard: vi.fn(),
      expire: vi.fn(),
      exec: vi.fn().mockRejectedValue(new Error("Redis connection failed")),
    };
    mockPipeline.mockReturnValue(pipe);

    const result = await checkAIRateLimit("user-1", "generate");
    expect(result.allowed).toBe(false);
    expect(result.remaining).toBe(0);
  });

  it("defaults to free tier when profile lookup fails", async () => {
    mockGetUserTier.mockRejectedValue(new Error("DB error"));
    mockPipelineSuccess(5);

    const result = await checkAIRateLimit("user-1", "generate");
    expect(result.limit).toBe(20); // free tier default
  });
});
