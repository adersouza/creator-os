/**
 * useInboxAssignments — unit tests for the inbox assignment management hook.
 *
 * Tests cover: loading assignments, assigning, unassigning,
 * getAssignment, isAssignedTo, and no-workspace guard.
 */

import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── Mocks ────────────────────────────────────────────────────────────────────

const mockGetSession = vi.fn();

vi.mock("@/services/supabase", () => ({
  supabase: {
    auth: {
      getSession: () => mockGetSession(),
    },
    channel: vi.fn().mockReturnValue({
      on: vi.fn().mockReturnThis(),
      subscribe: vi.fn().mockReturnThis(),
    }),
  },
}));

vi.mock("@/services/realtimeManager", () => ({
  subscribe: vi.fn((_key: string, _factory: unknown, _onReconnect: unknown) => {
    // Return a no-op unsubscribe function
    return () => {};
  }),
}));

const mockWorkspaceState = { currentWorkspace: { id: "ws-1", name: "Test Workspace" } };

vi.mock("@/stores/useWorkspaceStore", () => ({
  useWorkspaceStore: (selector: (s: typeof mockWorkspaceState) => unknown) =>
    selector(mockWorkspaceState),
}));

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

import { useInboxAssignments, type InboxAssignment } from "@/hooks/useInboxAssignments";

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });

  return function Wrapper({ children }: { children: ReactNode }) {
    return React.createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

const MOCK_SESSION = {
  data: {
    session: {
      access_token: "test-token-123",
    },
  },
};

const MOCK_ASSIGNMENT: InboxAssignment = {
  id: "assign-1",
  workspace_id: "ws-1",
  source: "threads",
  message_id: "msg-1",
  assigned_to: "user-a",
  assigned_by: "user-b",
  note: "Please handle this",
  assigned_at: "2026-04-15T10:00:00Z",
};

describe("useInboxAssignments", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetSession.mockResolvedValue(MOCK_SESSION);
    mockWorkspaceState.currentWorkspace = { id: "ws-1", name: "Test Workspace" };
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads assignments on mount when workspace exists", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ assignments: [MOCK_ASSIGNMENT] }),
    });

    const { result } = renderHook(() => useInboxAssignments(), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.assignments).toHaveLength(1);
    expect(result.current.assignments[0].id).toBe("assign-1");
  });

  it("getAssignment returns matching assignment by source and messageId", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ assignments: [MOCK_ASSIGNMENT] }),
    });

    const { result } = renderHook(() => useInboxAssignments(), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.assignments).toHaveLength(1);
    });

    const found = result.current.getAssignment("threads", "msg-1");
    expect(found).toBeDefined();
    expect(found?.assigned_to).toBe("user-a");

    const notFound = result.current.getAssignment("threads", "msg-999");
    expect(notFound).toBeUndefined();
  });

  it("isAssignedTo returns correct boolean", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ assignments: [MOCK_ASSIGNMENT] }),
    });

    const { result } = renderHook(() => useInboxAssignments(), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.assignments).toHaveLength(1);
    });

    expect(result.current.isAssignedTo("threads", "msg-1", "user-a")).toBe(true);
    expect(result.current.isAssignedTo("threads", "msg-1", "user-x")).toBe(false);
    expect(result.current.isAssignedTo("threads", "msg-999", "user-a")).toBe(false);
  });

  it("assign sends POST and updates local state", async () => {
    // Initial load
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ assignments: [] }),
    });

    const { result } = renderHook(() => useInboxAssignments(), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    // Assign call
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ assignment: MOCK_ASSIGNMENT }),
    });

    let success: boolean = false;
    await act(async () => {
      success = await result.current.assign("threads", "msg-1", "user-a", "Handle this");
    });

    expect(success).toBe(true);
    await waitFor(() => {
      expect(result.current.assignments).toHaveLength(1);
    });

    // Verify POST body
    const postCall = mockFetch.mock.calls[1];
    expect(postCall[0]).toBe("/api/inbox/assign");
    const postOpts = postCall[1];
    expect(postOpts.method).toBe("POST");
    const body = JSON.parse(postOpts.body);
    expect(body.workspaceId).toBe("ws-1");
    expect(body.source).toBe("threads");
    expect(body.messageId).toBe("msg-1");
    expect(body.assignedTo).toBe("user-a");
  });

  it("assign returns false on API failure", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ assignments: [] }),
    });

    const { result } = renderHook(() => useInboxAssignments(), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    mockFetch.mockResolvedValueOnce({ ok: false, json: async () => ({}) });

    let success: boolean = true;
    await act(async () => {
      success = await result.current.assign("threads", "msg-1", "user-a");
    });

    expect(success).toBe(false);
    expect(result.current.assignments).toHaveLength(0);
  });

  it("unassign sends DELETE and removes from local state", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ assignments: [MOCK_ASSIGNMENT] }),
    });

    const { result } = renderHook(() => useInboxAssignments(), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.assignments).toHaveLength(1);
    });

    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });

    let success: boolean = false;
    await act(async () => {
      success = await result.current.unassign("threads", "msg-1");
    });

    expect(success).toBe(true);
    await waitFor(() => {
      expect(result.current.assignments).toHaveLength(0);
    });
  });

  it("unassign returns false when workspace is missing", async () => {
    mockWorkspaceState.currentWorkspace = null as any;

    const { result } = renderHook(() => useInboxAssignments(), { wrapper: createWrapper() });

    let success: boolean = true;
    await act(async () => {
      success = await result.current.unassign("threads", "msg-1");
    });

    expect(success).toBe(false);
  });

  it("returns empty assignments when no workspace is set", async () => {
    mockWorkspaceState.currentWorkspace = null as any;

    const { result } = renderHook(() => useInboxAssignments(), { wrapper: createWrapper() });

    // No fetch should be made
    expect(mockFetch).not.toHaveBeenCalled();
    expect(result.current.assignments).toEqual([]);
  });
});
