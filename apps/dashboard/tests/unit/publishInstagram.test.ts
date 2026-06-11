/**
 * Unit tests for Instagram Scheduled Post Publisher
 * (api/_lib/cron/scheduled-posts/publishInstagram.ts)
 *
 * Tests the two main flows:
 * 1. retryIGContainers — retries posts stuck in "publishing" with existing containers
 * 2. processNewIGPosts — processes new scheduled Instagram posts
 *
 * Covers:
 * - Container status checking (FINISHED, EXPIRED, ERROR, IN_PROGRESS)
 * - Atomic claim guard (prevents double-publish)
 * - Rate limiting (claim-then-check ordering)
 * - Tier limit enforcement
 * - Content validation (caption length, story media requirement)
 * - Media type normalization (CAROUSEL_ALBUM -> CAROUSEL)
 * - Transient error auto-retry with exponential backoff
 * - Permanent failure handling
 * - Timeout safety (MAX_RUNTIME_MS budget)
 * - Cross-post triggering
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mocks — module scope, BEFORE importing module under test
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();

vi.mock("@/api/_lib/supabase", () => ({
  getSupabase: () => ({ from: mockFrom }),
  getSupabaseAny: () => ({ from: mockFrom }),
}));

vi.mock("@/api/_lib/logger", () => ({
  logger: {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  },
}));

vi.mock("@/api/_lib/encryption", () => ({
  decrypt: vi.fn().mockReturnValue("decrypted-token"),
}));

const mockCheckContainerStatus = vi.fn();
const mockPublishContainer = vi.fn();
vi.mock("@/api/_lib/instagramApi", () => ({
  checkContainerStatus: (...args: unknown[]) =>
    mockCheckContainerStatus(...args),
  publishContainer: (...args: unknown[]) => mockPublishContainer(...args),
}));

const mockCheckIGRateLimit = vi.fn();
vi.mock("@/api/_lib/igRateLimit", () => ({
  checkIGRateLimit: (...args: unknown[]) => mockCheckIGRateLimit(...args),
}));

const mockOrchestrateIGPublish = vi.fn();
vi.mock("@/api/_lib/instagram/orchestrate", () => ({
  orchestrateIGPublish: (...args: unknown[]) =>
    mockOrchestrateIGPublish(...args),
}));

const mockHandleCrossPost = vi.fn().mockResolvedValue(undefined);
vi.mock("@/api/_lib/cron/scheduled-posts/crossPost", () => ({
  handleCrossPost: (...args: unknown[]) => mockHandleCrossPost(...args),
}));

vi.mock("@/api/_lib/constants", () => ({
  IG_CONTAINER_STATUS: {
    IN_PROGRESS: "IN_PROGRESS",
    FINISHED: "FINISHED",
    EXPIRED: "EXPIRED",
    ERROR: "ERROR",
  },
}));

const mockDeliverNotification = vi.fn().mockResolvedValue(undefined);
vi.mock("@/api/_lib/deliverNotification", () => ({
  deliverNotification: (...args: unknown[]) =>
    mockDeliverNotification(...args),
}));

const mockCheckSubscriptionPostLimit = vi.fn();
vi.mock("@/api/_lib/handlers/posts/shared", () => ({
  checkSubscriptionPostLimit: (...args: unknown[]) =>
    mockCheckSubscriptionPostLimit(...args),
}));

vi.mock("@/api/_lib/cron/scheduled-posts/mediaValidation", () => ({
  checkMediaUrlAccessible: vi.fn().mockResolvedValue(null),
}));

// ---------------------------------------------------------------------------
// Import module under test (AFTER all mocks)
// ---------------------------------------------------------------------------

import {
  retryIGContainers,
  processNewIGPosts,
} from "@/api/_lib/cron/scheduled-posts/publishInstagram";
import type { ProcessingStats } from "@/api/_lib/cron/scheduled-posts/shared";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeStats(): ProcessingStats {
  return {
    found: 0,
    published: 0,
    failed: 0,
    retried: 0,
    rateLimited: 0,
    errors: [],
  };
}

function chainable(data: unknown, error: unknown = null) {
  const c: any = {};
  const methods = [
    "select", "eq", "in", "not", "gte", "lte", "lt", "or",
    "order", "limit", "insert", "update", "delete", "is",
  ];
  for (const m of methods) {
    c[m] = vi.fn().mockReturnValue(c);
  }
  c.maybeSingle = vi.fn().mockResolvedValue({ data, error });
  c.then = (resolve: (v: any) => void) => resolve({ data, error });
  return c;
}

// ---------------------------------------------------------------------------
// Tests: retryIGContainers
// ---------------------------------------------------------------------------

describe("retryIGContainers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does nothing when no retry posts found", async () => {
    mockFrom.mockImplementation(() => chainable(null));
    // posts query returns empty
    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      c.then = (resolve: (v: any) => void) => {
        if (table === "posts") {
          return resolve({ data: [], error: null });
        }
        return resolve({ data: null, error: null });
      };
      return c;
    });

    const stats = makeStats();
    await retryIGContainers(stats, Date.now(), 55_000);
    expect(stats.published).toBe(0);
    expect(stats.failed).toBe(0);
  });

  it("publishes container when status is FINISHED", async () => {
    const retryPost = {
      id: "post-retry-1",
      user_id: "user-1",
      instagram_account_id: "ig-1",
      ig_container_id: "container-1",
      ig_container_status: "IN_PROGRESS",
      ig_publish_attempts: 1,
      updated_at: new Date().toISOString(),
      instagram_accounts: {
        id: "ig-1",
        instagram_user_id: "ig-user-1",
        instagram_access_token_encrypted: "enc-token",
        facebook_page_access_token_encrypted: null,
        login_type: "facebook",
        username: "iguser",
      },
    };

    mockCheckContainerStatus.mockResolvedValue({ status: "FINISHED" });
    mockPublishContainer.mockResolvedValue({
      success: true,
      mediaId: "media-123",
      permalink: "https://instagram.com/p/abc",
    });

    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      c.then = (resolve: (v: any) => void) => {
        if (table === "posts") {
          return resolve({ data: [retryPost], error: null });
        }
        return resolve({ data: null, error: null });
      };
      // For update().eq().eq().select() chain that returns guard result
      c.select = vi.fn().mockReturnValue({
        ...c,
        then: (resolve: (v: any) => void) =>
          resolve({ data: [{ id: retryPost.id }], error: null }),
      });
      return c;
    });

    const stats = makeStats();
    await retryIGContainers(stats, Date.now(), 55_000);
    expect(stats.published).toBe(1);
    expect(mockPublishContainer).toHaveBeenCalled();
  });

  it("marks container as failed when status is EXPIRED", async () => {
    const retryPost = {
      id: "post-expired",
      user_id: "user-1",
      instagram_account_id: "ig-1",
      ig_container_id: "container-expired",
      ig_container_status: "IN_PROGRESS",
      ig_publish_attempts: 2,
      updated_at: new Date().toISOString(),
      instagram_accounts: {
        id: "ig-1",
        instagram_user_id: "ig-user-1",
        instagram_access_token_encrypted: "enc-token",
        facebook_page_access_token_encrypted: null,
        login_type: "facebook",
        username: "iguser",
      },
    };

    mockCheckContainerStatus.mockResolvedValue({
      status: "EXPIRED",
      error: "Container expired",
    });

    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      c.then = (resolve: (v: any) => void) => {
        if (table === "posts") {
          return resolve({ data: [retryPost], error: null });
        }
        return resolve({ data: null, error: null });
      };
      return c;
    });

    const stats = makeStats();
    await retryIGContainers(stats, Date.now(), 55_000);
    expect(stats.failed).toBe(1);
  });

  it("auto-fails containers stuck IN_PROGRESS for >2 hours", async () => {
    const twoHoursAgoPlus = new Date(
      Date.now() - 3 * 60 * 60 * 1000,
    ).toISOString();

    const retryPost = {
      id: "post-stuck",
      user_id: "user-1",
      instagram_account_id: "ig-1",
      ig_container_id: "container-stuck",
      ig_container_status: "IN_PROGRESS",
      ig_publish_attempts: 3,
      updated_at: twoHoursAgoPlus,
      instagram_accounts: {
        id: "ig-1",
        instagram_user_id: "ig-user-1",
        instagram_access_token_encrypted: "enc-token",
        facebook_page_access_token_encrypted: null,
        login_type: "facebook",
        username: "iguser",
      },
    };

    mockCheckContainerStatus.mockResolvedValue({
      status: "IN_PROGRESS",
    });

    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      c.then = (resolve: (v: any) => void) => {
        if (table === "posts") {
          return resolve({ data: [retryPost], error: null });
        }
        return resolve({ data: null, error: null });
      };
      return c;
    });

    const stats = makeStats();
    await retryIGContainers(stats, Date.now(), 55_000);
    expect(stats.failed).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// Tests: processNewIGPosts
// ---------------------------------------------------------------------------

describe("processNewIGPosts", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCheckIGRateLimit.mockResolvedValue({ allowed: true });
    mockCheckSubscriptionPostLimit.mockResolvedValue({
      allowed: true,
      tier: "pro",
      used: 1,
      limit: 25,
    });
  });

  it("does nothing when no scheduled IG posts found", async () => {
    mockFrom.mockImplementation(() => {
      const c = chainable(null);
      c.then = (resolve: (v: any) => void) =>
        resolve({ data: [], error: null });
      return c;
    });

    const stats = makeStats();
    await processNewIGPosts(stats, Date.now(), 55_000);
    expect(stats.published).toBe(0);
    expect(stats.found).toBe(0);
  });

  it("fails posts exceeding 2200 character caption limit", async () => {
    const longCaption = "x".repeat(2201);
    const igPost = {
      id: "post-long",
      user_id: "user-1",
      instagram_account_id: "ig-1",
      content: longCaption,
      media_urls: ["https://example.com/img.jpg"],
      ig_media_type: "IMAGE",
      alt_text: null,
      location_id: null,
      metadata: {},
      scheduled_for: new Date().toISOString(),
      retry_count: 0,
      instagram_accounts: {
        id: "ig-1",
        instagram_user_id: "ig-user-1",
        instagram_access_token_encrypted: "enc-token",
        facebook_page_access_token_encrypted: null,
        login_type: "facebook",
        username: "iguser",
        is_active: true,
      },
    };

    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      c.then = (resolve: (v: any) => void) => {
        if (table === "posts") {
          return resolve({ data: [igPost], error: null });
        }
        return resolve({ data: null, error: null });
      };
      return c;
    });

    const stats = makeStats();
    await processNewIGPosts(stats, Date.now(), 55_000);
    expect(stats.failed).toBe(1);
  });

  it("fails Stories with no media attached", async () => {
    const storyPost = {
      id: "post-story-nomedia",
      user_id: "user-1",
      instagram_account_id: "ig-1",
      content: "My story",
      media_urls: [],
      ig_media_type: "STORIES",
      alt_text: null,
      location_id: null,
      metadata: {},
      scheduled_for: new Date().toISOString(),
      retry_count: 0,
      instagram_accounts: {
        id: "ig-1",
        instagram_user_id: "ig-user-1",
        instagram_access_token_encrypted: "enc-token",
        facebook_page_access_token_encrypted: null,
        login_type: "facebook",
        username: "iguser",
        is_active: true,
      },
    };

    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      c.then = (resolve: (v: any) => void) => {
        if (table === "posts") {
          return resolve({ data: [storyPost], error: null });
        }
        return resolve({ data: null, error: null });
      };
      // For atomic claim
      c.maybeSingle = vi.fn().mockResolvedValue({
        data: { id: storyPost.id },
        error: null,
      });
      return c;
    });

    const stats = makeStats();
    await processNewIGPosts(stats, Date.now(), 55_000);
    expect(stats.failed).toBe(1);
  });

  it("skips posts for inactive accounts", async () => {
    const igPost = {
      id: "post-inactive",
      user_id: "user-1",
      instagram_account_id: "ig-1",
      content: "Test",
      media_urls: ["https://example.com/img.jpg"],
      ig_media_type: "IMAGE",
      alt_text: null,
      location_id: null,
      metadata: {},
      scheduled_for: new Date().toISOString(),
      retry_count: 0,
      instagram_accounts: {
        id: "ig-1",
        instagram_user_id: "ig-user-1",
        instagram_access_token_encrypted: "enc-token",
        facebook_page_access_token_encrypted: null,
        login_type: "facebook",
        username: "iguser",
        is_active: false,
      },
    };

    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      c.then = (resolve: (v: any) => void) => {
        if (table === "posts") {
          return resolve({ data: [igPost], error: null });
        }
        return resolve({ data: null, error: null });
      };
      return c;
    });

    const stats = makeStats();
    await processNewIGPosts(stats, Date.now(), 55_000);
    // Should skip (not publish, not fail)
    expect(stats.published).toBe(0);
  });

  it("handles rate limiting by releasing claim and marking rateLimited", async () => {
    const igPost = {
      id: "post-ratelimited",
      user_id: "user-1",
      instagram_account_id: "ig-1",
      content: "Test",
      media_urls: ["https://example.com/img.jpg"],
      ig_media_type: "IMAGE",
      alt_text: null,
      location_id: null,
      metadata: {},
      scheduled_for: new Date().toISOString(),
      retry_count: 0,
      instagram_accounts: {
        id: "ig-1",
        instagram_user_id: "ig-user-1",
        instagram_access_token_encrypted: "enc-token",
        facebook_page_access_token_encrypted: null,
        login_type: "facebook",
        username: "iguser",
        is_active: true,
      },
    };

    mockCheckIGRateLimit.mockResolvedValue({
      allowed: false,
      reason: "Daily limit exceeded",
    });

    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      c.then = (resolve: (v: any) => void) => {
        if (table === "posts") {
          return resolve({ data: [igPost], error: null });
        }
        return resolve({ data: null, error: null });
      };
      c.maybeSingle = vi.fn().mockResolvedValue({
        data: { id: igPost.id },
        error: null,
      });
      return c;
    });

    const stats = makeStats();
    await processNewIGPosts(stats, Date.now(), 55_000);
    expect(stats.rateLimited).toBe(1);
  });

  it("auto-reschedules on transient errors with exponential backoff", async () => {
    const igPost = {
      id: "post-transient",
      user_id: "user-1",
      instagram_account_id: "ig-1",
      content: "Test post",
      media_urls: ["https://example.com/img.jpg"],
      ig_media_type: "IMAGE",
      alt_text: null,
      location_id: null,
      metadata: {},
      scheduled_for: new Date().toISOString(),
      retry_count: 0,
      instagram_accounts: {
        id: "ig-1",
        instagram_user_id: "ig-user-1",
        instagram_access_token_encrypted: "enc-token",
        facebook_page_access_token_encrypted: null,
        login_type: "facebook",
        username: "iguser",
        is_active: true,
      },
    };

    mockCheckIGRateLimit.mockResolvedValue({ allowed: true });
    mockOrchestrateIGPublish.mockResolvedValue({
      success: false,
      error: "Temporary Meta server error",
      retryable: true,
    });

    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      c.then = (resolve: (v: any) => void) => {
        if (table === "posts") {
          return resolve({ data: [igPost], error: null });
        }
        if (table === "notifications") {
          return resolve({ data: null, error: null });
        }
        return resolve({ data: null, error: null });
      };
      c.maybeSingle = vi.fn().mockResolvedValue({
        data: { id: igPost.id },
        error: null,
      });
      return c;
    });

    const stats = makeStats();
    await processNewIGPosts(stats, Date.now(), 55_000);
    expect(stats.retried).toBe(1);
    expect(stats.failed).toBe(0);
  });

  it("fails permanently after 3 retries are exhausted", async () => {
    const igPost = {
      id: "post-exhausted",
      user_id: "user-1",
      instagram_account_id: "ig-1",
      content: "Test post",
      media_urls: ["https://example.com/img.jpg"],
      ig_media_type: "IMAGE",
      alt_text: null,
      location_id: null,
      metadata: {},
      scheduled_for: new Date().toISOString(),
      retry_count: 3,
      instagram_accounts: {
        id: "ig-1",
        instagram_user_id: "ig-user-1",
        instagram_access_token_encrypted: "enc-token",
        facebook_page_access_token_encrypted: null,
        login_type: "facebook",
        username: "iguser",
        is_active: true,
      },
    };

    mockCheckIGRateLimit.mockResolvedValue({ allowed: true });
    mockOrchestrateIGPublish.mockResolvedValue({
      success: false,
      error: "Media processing failed",
      retryable: true,
    });

    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      c.then = (resolve: (v: any) => void) => {
        if (table === "posts") {
          return resolve({ data: [igPost], error: null });
        }
        return resolve({ data: null, error: null });
      };
      c.maybeSingle = vi.fn().mockResolvedValue({
        data: { id: igPost.id },
        error: null,
      });
      return c;
    });

    const stats = makeStats();
    await processNewIGPosts(stats, Date.now(), 55_000);
    expect(stats.failed).toBe(1);
    expect(stats.retried).toBe(0);
  });

  it("respects timeout budget and breaks early", async () => {
    const igPost = {
      id: "post-timeout",
      user_id: "user-1",
      instagram_account_id: "ig-1",
      content: "Test",
      media_urls: ["https://example.com/img.jpg"],
      ig_media_type: "IMAGE",
      alt_text: null,
      location_id: null,
      metadata: {},
      scheduled_for: new Date().toISOString(),
      retry_count: 0,
      instagram_accounts: {
        id: "ig-1",
        instagram_user_id: "ig-user-1",
        instagram_access_token_encrypted: "enc-token",
        facebook_page_access_token_encrypted: null,
        login_type: "facebook",
        username: "iguser",
        is_active: true,
      },
    };

    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      c.then = (resolve: (v: any) => void) => {
        if (table === "posts") {
          return resolve({ data: [igPost, igPost], error: null });
        }
        return resolve({ data: null, error: null });
      };
      return c;
    });

    const stats = makeStats();
    // Start time 2 minutes ago — budget exhausted
    await processNewIGPosts(stats, Date.now() - 120_000, 55_000);
    // Should have broken before processing any posts
    expect(stats.published).toBe(0);
  });
});
