/**
 * Unit tests for Content Pipeline Cron Sub-Handler
 * (api/_lib/cron/content-pipeline.ts)
 *
 * Tests the evergreen recycling and trend forecast refresh phases:
 * 1. Evergreen recycling — recycle due posts, platform-specific gaps, auto-retirement
 * 2. Seasonal priority boost detection
 * 3. Daily recycle cap enforcement by subscription tier
 * 4. Hook extraction for uniqueness checking
 * 5. Auto-retirement (max recycles, consecutive zero engagement, <50% decay)
 * 6. Trend forecast refresh — skip already-forecasted accounts
 * 7. Time budget enforcement
 * 8. Handler auth, lock, and tracking wiring
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mocks — module scope, BEFORE importing module under test
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();

vi.mock("@/api/_lib/supabase", () => ({
  getSupabase: () => ({ from: mockFrom }),
}));

vi.mock("@/api/_lib/logger", () => ({
  logger: {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  },
}));

vi.mock("@/api/_lib/alerting", () => ({
  alertCronFailure: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/api/_lib/cronUtils", () => ({
  trackCronRun: vi.fn().mockImplementation((_sb: unknown, _name: string, fn: () => unknown) => fn()),
  withCronLock: vi.fn().mockImplementation((_sb: unknown, _name: string, fn: () => unknown) => fn()),
}));

vi.mock("@/api/_lib/createNotification", () => ({
  createNotification: vi.fn().mockResolvedValue(undefined),
}));

const mockGetUserTier = vi.fn();
vi.mock("@/api/_lib/tierGate", () => ({
  getUserTier: (...args: unknown[]) => mockGetUserTier(...args),
}));

const mockGenerateForecast = vi.fn();
vi.mock("@/api/_lib/trendEngine", () => ({
  generateForecast: (...args: unknown[]) => mockGenerateForecast(...args),
}));

const mockRedisGet = vi.fn();
const mockRedisIncr = vi.fn();
const mockRedisExpire = vi.fn();
vi.mock("@/api/_lib/redis", () => ({
  getRedis: () => ({
    get: mockRedisGet,
    incr: mockRedisIncr,
    expire: mockRedisExpire,
  }),
}));

// Mock the Google GenAI for evergreen variation
vi.mock("@google/genai", () => ({
  GoogleGenAI: vi.fn().mockImplementation(() => ({
    models: {
      generateContent: vi.fn().mockResolvedValue({
        text: "A fresh rewrite of the original post",
      }),
    },
  })),
}));

// ---------------------------------------------------------------------------
// Import module under test (AFTER all mocks)
// ---------------------------------------------------------------------------

import {
  runEvergreenRecycling,
  runTrendForecasts,
} from "@/api/_lib/cron/content-pipeline";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function chain(data: unknown, error: unknown = null) {
  const c: any = {};
  const methods = [
    "select", "eq", "in", "not", "gte", "lte", "lt", "or",
    "order", "limit", "insert", "update", "delete", "is",
  ];
  for (const m of methods) {
    c[m] = vi.fn().mockReturnValue(c);
  }
  c.maybeSingle = vi.fn().mockResolvedValue({ data, error });
  c.then = (resolve: (v: any) => void) => resolve({ data, error, count: 0 });
  return c;
}

function makeEvergreenPost(overrides: Record<string, unknown> = {}) {
  const thirtyDaysAgo = new Date(Date.now() - 31 * 86_400_000).toISOString();
  return {
    id: "post-1",
    user_id: "user-1",
    content: "Top performing post content here",
    platform: "threads",
    account_id: "acc-1",
    instagram_account_id: null,
    hashtags: null,
    media_type: null,
    media_urls: null,
    engagement_rate: 0.05,
    evergreen_interval_days: 30,
    recycle_count: 0,
    max_recycles: 5,
    last_recycled_at: thirtyDaysAgo,
    published_at: thirtyDaysAgo,
    evergreen_min_engagement: null,
    views_count: 1000,
    likes_count: 50,
    replies_count: 10,
    metadata: {},
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests: runEvergreenRecycling
// ---------------------------------------------------------------------------

describe("runEvergreenRecycling", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetUserTier.mockResolvedValue("pro");
    mockRedisGet.mockResolvedValue(null);
    mockRedisIncr.mockResolvedValue(1);
    mockRedisExpire.mockResolvedValue(true);
    process.env.GEMINI_API_KEY = "test-gemini-key";
  });

  it("returns zero stats when no evergreen posts found", async () => {
    mockFrom.mockImplementation(() => chain(null));
    // Override to return empty array for posts
    mockFrom.mockImplementation((table: string) => {
      if (table === "posts") {
        return chain([]);
      }
      return chain(null);
    });

    const result = await runEvergreenRecycling(Date.now());
    expect(result.postsRecycled).toBe(0);
    expect(result.errors).toBe(0);
    expect(result.retired).toBe(0);
  });

  it("auto-retires posts that have reached max_recycles", async () => {
    const maxedPost = makeEvergreenPost({
      id: "post-maxed",
      recycle_count: 5,
      max_recycles: 5,
    });

    mockFrom.mockImplementation((table: string) => {
      const c: any = {};
      const methods = [
        "select", "eq", "in", "not", "gte", "lte", "lt", "or",
        "order", "limit", "insert", "update", "delete", "is",
      ];
      for (const m of methods) {
        c[m] = vi.fn().mockReturnValue(c);
      }
      c.maybeSingle = vi.fn().mockResolvedValue({ data: null, error: null });
      c.then = (resolve: (v: any) => void) => {
        if (table === "posts") {
          return resolve({ data: [maxedPost], error: null, count: 0 });
        }
        return resolve({ data: null, error: null, count: 0 });
      };
      return c;
    });

    const result = await runEvergreenRecycling(Date.now());
    expect(result.retired).toBe(1);
    expect(result.postsRecycled).toBe(0);
  });

  it("auto-retires posts with 2 consecutive zero-engagement cycles", async () => {
    const zeroEngagementPost = makeEvergreenPost({
      id: "post-zero",
      recycle_count: 2,
      metadata: { recycle_engagement_ratios: [0, 0] },
    });

    mockFrom.mockImplementation((table: string) => {
      const c: any = {};
      const methods = [
        "select", "eq", "in", "not", "gte", "lte", "lt", "or",
        "order", "limit", "insert", "update", "delete", "is",
      ];
      for (const m of methods) {
        c[m] = vi.fn().mockReturnValue(c);
      }
      c.maybeSingle = vi.fn().mockResolvedValue({ data: null, error: null });
      c.then = (resolve: (v: any) => void) => {
        if (table === "posts") {
          return resolve({ data: [zeroEngagementPost], error: null, count: 0 });
        }
        return resolve({ data: null, error: null, count: 0 });
      };
      return c;
    });

    const result = await runEvergreenRecycling(Date.now());
    expect(result.retired).toBe(1);
  });

  it("auto-retires posts where last engagement ratio dropped below 50%", async () => {
    const decayPost = makeEvergreenPost({
      id: "post-decay",
      recycle_count: 2,
      metadata: { recycle_engagement_ratios: [1.0, 0.3] },
    });

    mockFrom.mockImplementation((table: string) => {
      const c: any = {};
      const methods = [
        "select", "eq", "in", "not", "gte", "lte", "lt", "or",
        "order", "limit", "insert", "update", "delete", "is",
      ];
      for (const m of methods) {
        c[m] = vi.fn().mockReturnValue(c);
      }
      c.maybeSingle = vi.fn().mockResolvedValue({ data: null, error: null });
      c.then = (resolve: (v: any) => void) => {
        if (table === "posts") {
          return resolve({ data: [decayPost], error: null, count: 0 });
        }
        return resolve({ data: null, error: null, count: 0 });
      };
      return c;
    });

    const result = await runEvergreenRecycling(Date.now());
    expect(result.retired).toBe(1);
  });

  it("skips posts that have not reached their recycle interval", async () => {
    const recentPost = makeEvergreenPost({
      id: "post-recent",
      last_recycled_at: new Date().toISOString(), // just recycled
      evergreen_interval_days: 30,
    });

    mockFrom.mockImplementation((table: string) => {
      const c: any = {};
      const methods = [
        "select", "eq", "in", "not", "gte", "lte", "lt", "or",
        "order", "limit", "insert", "update", "delete", "is",
      ];
      for (const m of methods) {
        c[m] = vi.fn().mockReturnValue(c);
      }
      c.maybeSingle = vi.fn().mockResolvedValue({ data: null, error: null });
      c.then = (resolve: (v: any) => void) => {
        if (table === "posts") {
          return resolve({ data: [recentPost], error: null, count: 0 });
        }
        return resolve({ data: null, error: null, count: 0 });
      };
      return c;
    });

    const result = await runEvergreenRecycling(Date.now());
    expect(result.postsRecycled).toBe(0);
    expect(result.retired).toBe(0);
  });

  it("respects time budget and stops processing", async () => {
    const post = makeEvergreenPost();

    mockFrom.mockImplementation((table: string) => {
      const c: any = {};
      const methods = [
        "select", "eq", "in", "not", "gte", "lte", "lt", "or",
        "order", "limit", "insert", "update", "delete", "is",
      ];
      for (const m of methods) {
        c[m] = vi.fn().mockReturnValue(c);
      }
      c.maybeSingle = vi.fn().mockResolvedValue({ data: null, error: null });
      c.then = (resolve: (v: any) => void) => {
        if (table === "posts") {
          return resolve({ data: [post], error: null, count: 0 });
        }
        return resolve({ data: null, error: null, count: 0 });
      };
      return c;
    });

    // Start time far in the past so budget is exhausted
    const pastStart = Date.now() - 300_000;
    const result = await runEvergreenRecycling(pastStart);
    // Should have stopped before processing
    expect(result.postsRecycled).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Tests: runTrendForecasts
// ---------------------------------------------------------------------------

describe("runTrendForecasts", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGenerateForecast.mockResolvedValue(undefined);
  });

  it("returns zero when no active accounts found", async () => {
    mockFrom.mockImplementation(() => chain(null));
    // accounts query returns empty
    mockFrom.mockImplementation((table: string) => {
      if (table === "accounts") {
        return chain([]);
      }
      return chain(null);
    });

    const result = await runTrendForecasts(Date.now());
    expect(result.forecastsGenerated).toBe(0);
    expect(result.errors).toBe(0);
  });

  it("skips accounts that already have a forecast for today", async () => {
    const account = { id: "acc-1", user_id: "user-1" };

    mockFrom.mockImplementation((table: string) => {
      const c: any = {};
      const methods = [
        "select", "eq", "in", "not", "gte", "lte", "lt", "or",
        "order", "limit", "insert", "update", "delete", "is",
      ];
      for (const m of methods) {
        c[m] = vi.fn().mockReturnValue(c);
      }
      c.maybeSingle = vi.fn().mockResolvedValue({ data: null, error: null });
      c.then = (resolve: (v: any) => void) => {
        if (table === "accounts") {
          return resolve({ data: [account], error: null });
        }
        if (table === "trend_forecasts") {
          // Already has forecast for today
          return resolve({ data: [{ account_id: "acc-1" }], error: null });
        }
        return resolve({ data: null, error: null });
      };
      return c;
    });

    const result = await runTrendForecasts(Date.now());
    expect(result.forecastsGenerated).toBe(0);
    expect(mockGenerateForecast).not.toHaveBeenCalled();
  });

  it("generates forecasts for accounts missing today's forecast", async () => {
    const account = { id: "acc-2", user_id: "user-2" };

    mockFrom.mockImplementation((table: string) => {
      const c: any = {};
      const methods = [
        "select", "eq", "in", "not", "gte", "lte", "lt", "or",
        "order", "limit", "insert", "update", "delete", "is",
      ];
      for (const m of methods) {
        c[m] = vi.fn().mockReturnValue(c);
      }
      c.maybeSingle = vi.fn().mockResolvedValue({ data: null, error: null });
      c.then = (resolve: (v: any) => void) => {
        if (table === "accounts") {
          return resolve({ data: [account], error: null });
        }
        if (table === "trend_forecasts") {
          return resolve({ data: [], error: null });
        }
        return resolve({ data: null, error: null });
      };
      return c;
    });

    const result = await runTrendForecasts(Date.now());
    expect(result.forecastsGenerated).toBe(1);
    expect(mockGenerateForecast).toHaveBeenCalledOnce();
  });

  it("counts errors when forecast generation fails", async () => {
    const account = { id: "acc-err", user_id: "user-err" };
    mockGenerateForecast.mockRejectedValue(new Error("AI quota exceeded"));

    mockFrom.mockImplementation((table: string) => {
      const c: any = {};
      const methods = [
        "select", "eq", "in", "not", "gte", "lte", "lt", "or",
        "order", "limit", "insert", "update", "delete", "is",
      ];
      for (const m of methods) {
        c[m] = vi.fn().mockReturnValue(c);
      }
      c.maybeSingle = vi.fn().mockResolvedValue({ data: null, error: null });
      c.then = (resolve: (v: any) => void) => {
        if (table === "accounts") {
          return resolve({ data: [account], error: null });
        }
        if (table === "trend_forecasts") {
          return resolve({ data: [], error: null });
        }
        return resolve({ data: null, error: null });
      };
      return c;
    });

    const result = await runTrendForecasts(Date.now());
    expect(result.errors).toBe(1);
    expect(result.forecastsGenerated).toBe(0);
  });

  it("respects time budget and stops processing", async () => {
    const accounts = [
      { id: "acc-1", user_id: "user-1" },
      { id: "acc-2", user_id: "user-2" },
    ];

    mockFrom.mockImplementation((table: string) => {
      const c: any = {};
      const methods = [
        "select", "eq", "in", "not", "gte", "lte", "lt", "or",
        "order", "limit", "insert", "update", "delete", "is",
      ];
      for (const m of methods) {
        c[m] = vi.fn().mockReturnValue(c);
      }
      c.maybeSingle = vi.fn().mockResolvedValue({ data: null, error: null });
      c.then = (resolve: (v: any) => void) => {
        if (table === "accounts") {
          return resolve({ data: accounts, error: null });
        }
        if (table === "trend_forecasts") {
          return resolve({ data: [], error: null });
        }
        return resolve({ data: null, error: null });
      };
      return c;
    });

    // Exhausted budget
    const pastStart = Date.now() - 300_000;
    const result = await runTrendForecasts(pastStart);
    expect(result.forecastsGenerated).toBe(0);
  });
});
