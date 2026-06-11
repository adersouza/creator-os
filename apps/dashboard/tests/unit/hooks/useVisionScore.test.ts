/**
 * useVisionScore — unit tests for the vision AI scoring hook.
 *
 * Tests cover: successful scoring, caching via ref, error handling,
 * loading state management, and clearScore.
 */

import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

// ── Mocks ────────────────────────────────────────────────────────────────────

const mockGetSession = vi.fn();

vi.mock("@/services/supabase", () => ({
  supabase: {
    auth: {
      getSession: () => mockGetSession(),
    },
  },
}));

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

import { useVisionScore } from "@/src/hooks/useVisionScore";

const MOCK_SESSION = {
  data: {
    session: {
      access_token: "test-token-123",
    },
  },
};

const MOCK_SCORE = {
  score: 85,
  breakdown: {
    composition: 90,
    lighting: 80,
    color: 85,
    clarity: 88,
    engagement_potential: 82,
  },
  suggestions: ["Improve lighting contrast"],
  captionAngle: "Professional workspace setup",
  cached: false,
};

describe("useVisionScore", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetSession.mockResolvedValue(MOCK_SESSION);
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ data: MOCK_SCORE }),
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("starts with empty scores and loading state", () => {
    const { result } = renderHook(() => useVisionScore());

    expect(result.current.scores).toEqual({});
    expect(result.current.loading).toEqual({});
  });

  it("scoreImage returns score and updates state", async () => {
    const { result } = renderHook(() => useVisionScore());

    let score: unknown;
    await act(async () => {
      score = await result.current.scoreImage("https://img.example.com/photo.jpg", "threads");
    });

    expect(score).toEqual(MOCK_SCORE);
    expect(result.current.scores["https://img.example.com/photo.jpg"]).toEqual(MOCK_SCORE);
    expect(result.current.loading["https://img.example.com/photo.jpg"]).toBe(false);
  });

  it("scoreImage sends correct auth header and body", async () => {
    const { result } = renderHook(() => useVisionScore());

    await act(async () => {
      await result.current.scoreImage("https://img.example.com/photo.jpg", "instagram");
    });

    expect(mockFetch).toHaveBeenCalledWith("/api/ai/vision-score", {
      method: "POST",
      headers: {
        Authorization: "Bearer test-token-123",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        imageUrl: "https://img.example.com/photo.jpg",
        platform: "instagram",
      }),
    });
  });

  it("returns cached score from ref without re-fetching", async () => {
    const { result } = renderHook(() => useVisionScore());

    // First call — network
    await act(async () => {
      await result.current.scoreImage("https://img.example.com/photo.jpg", "threads");
    });

    expect(mockFetch).toHaveBeenCalledTimes(1);

    // Second call — should use ref cache, no additional fetch
    let cachedScore: unknown;
    await act(async () => {
      cachedScore = await result.current.scoreImage("https://img.example.com/photo.jpg", "threads");
    });

    expect(cachedScore).toEqual(MOCK_SCORE);
    expect(mockFetch).toHaveBeenCalledTimes(1); // no additional call
  });

  it("returns null on fetch failure", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({}),
    });

    const { result } = renderHook(() => useVisionScore());

    let score: unknown;
    await act(async () => {
      score = await result.current.scoreImage("https://img.example.com/fail.jpg", "threads");
    });

    expect(score).toBeNull();
    expect(result.current.loading["https://img.example.com/fail.jpg"]).toBe(false);
  });

  it("returns null when not authenticated", async () => {
    mockGetSession.mockResolvedValueOnce({
      data: { session: null },
    });

    const { result } = renderHook(() => useVisionScore());

    let score: unknown;
    await act(async () => {
      score = await result.current.scoreImage("https://img.example.com/noauth.jpg", "threads");
    });

    expect(score).toBeNull();
  });

  it("clearScore removes a specific image from scores", async () => {
    const { result } = renderHook(() => useVisionScore());

    await act(async () => {
      await result.current.scoreImage("https://img.example.com/photo.jpg", "threads");
    });

    expect(result.current.scores["https://img.example.com/photo.jpg"]).toEqual(MOCK_SCORE);

    act(() => {
      result.current.clearScore("https://img.example.com/photo.jpg");
    });

    expect(result.current.scores["https://img.example.com/photo.jpg"]).toBeUndefined();
  });

  it("sets loading true during scoring and false after", async () => {
    let resolvePromise!: (v: unknown) => void;
    mockFetch.mockReturnValueOnce(
      new Promise((resolve) => {
        resolvePromise = resolve;
      }),
    );

    const { result } = renderHook(() => useVisionScore());

    let scorePromise: Promise<unknown>;
    act(() => {
      scorePromise = result.current.scoreImage("https://img.example.com/loading.jpg", "threads");
    });

    // Loading should be true while in-flight
    expect(result.current.loading["https://img.example.com/loading.jpg"]).toBe(true);

    // Resolve the fetch
    await act(async () => {
      resolvePromise({
        ok: true,
        json: async () => ({ data: MOCK_SCORE }),
      });
      await scorePromise!;
    });

    expect(result.current.loading["https://img.example.com/loading.jpg"]).toBe(false);
  });
});
