/**
 * useInboxAssignments — manage inbox item assignments for the workspace.
 *
 * Loads assignments on mount, provides assign/unassign actions,
 * and listens for realtime updates via Supabase postgres_changes.
 */

import { useCallback, useEffect, useMemo } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { subscribe } from '@/services/realtimeManager';
import { supabase } from '@/services/supabase';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';

import { apiUrl } from '@/lib/apiUrl';

export interface InboxAssignment {
  id: string;
  workspace_id: string;
  source: string;
  message_id: string;
  assigned_to: string;
  assigned_by: string;
  note: string | null;
  assigned_at: string;
  assignee?: {
            id: string;
            display_name: string | null;
            avatar_url: string | null;
          } | undefined;
}

export interface UseInboxAssignmentsReturn {
  assignments: InboxAssignment[];
  loading: boolean;
  hasError: boolean;
  /** Get assignment for a specific message */
  getAssignment: (source: string, messageId: string) => InboxAssignment | undefined;
  /** Assign an inbox item to a team member */
  assign: (source: string, messageId: string, assignedTo: string, note?: string) => Promise<boolean>;
  /** Unassign an inbox item */
  unassign: (source: string, messageId: string) => Promise<boolean>;
  /** Filter: only messages assigned to a user */
  isAssignedTo: (source: string, messageId: string, userId: string) => boolean;
}

export function useInboxAssignments(): UseInboxAssignmentsReturn {
  const workspace = useWorkspaceStore((s) => s.currentWorkspace);
  const workspaceId = workspace?.id ?? null;
  const qc = useQueryClient();
  const queryKey = useMemo(
    () => ['inboxAssignments', workspaceId] as const,
    [workspaceId],
  );

  const { data, isPending, isError } = useQuery({
    queryKey,
    enabled: !!workspaceId,
    queryFn: async (): Promise<InboxAssignment[]> => {
      if (!workspaceId) return [];
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.access_token) throw new Error('Not authenticated');

      const res = await fetch(
        apiUrl(`/api/inbox/assign?workspaceId=${encodeURIComponent(workspaceId)}`),
        { headers: { Authorization: `Bearer ${session.access_token}` } },
      );
      if (!res.ok) throw new Error(`Inbox assignments request failed (${res.status})`);
      const json = await res.json();
      return json.assignments ?? [];
    },
  });

  const assignments = data ?? [];

  useEffect(() => {
    if (!workspaceId) return;
    const key = `inbox-assignments:${workspaceId}`;
    const unsub = subscribe(
      key,
      () =>
        supabase
          .channel(key)
          .on(
            'postgres_changes',
            {
              event: '*',
              schema: 'public',
              table: 'inbox_assignments',
              filter: `workspace_id=eq.${workspaceId}`,
            },
            () => {
              qc.invalidateQueries({ queryKey });
            },
          )
          .subscribe(),
      () => {
        qc.invalidateQueries({ queryKey });
      },
    );

    return () => {
      unsub();
    };
  }, [workspaceId, qc, queryKey]);

  const getAssignment = useCallback(
    (source: string, messageId: string) =>
      assignments.find((a) => a.source === source && a.message_id === messageId),
    [assignments],
  );

  const assign = useCallback(
    async (source: string, messageId: string, assignedTo: string, note?: string): Promise<boolean> => {
      if (!workspaceId) return false;
      try {
        const { data: { session } } = await supabase.auth.getSession();
        if (!session?.access_token) return false;

        const res = await fetch(apiUrl('/api/inbox/assign'), {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${session.access_token}`,
          },
          body: JSON.stringify({ workspaceId, source, messageId, assignedTo, note }),
        });
        if (!res.ok) return false;
        const json = await res.json();
        if (json.assignment) {
          qc.setQueryData<InboxAssignment[]>(queryKey, (prev) => {
            const filtered = (prev ?? []).filter(
              (a) => !(a.source === source && a.message_id === messageId),
            );
            return [...filtered, json.assignment];
          });
        }
        return true;
      } catch {
        return false;
      }
    },
    [workspaceId, qc, queryKey],
  );

  const unassign = useCallback(
    async (source: string, messageId: string): Promise<boolean> => {
      if (!workspaceId) return false;
      try {
        const { data: { session } } = await supabase.auth.getSession();
        if (!session?.access_token) return false;

        const res = await fetch(apiUrl('/api/inbox/assign'), {
          method: 'DELETE',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${session.access_token}`,
          },
          body: JSON.stringify({ workspaceId, source, messageId }),
        });
        if (!res.ok) return false;
        qc.setQueryData<InboxAssignment[]>(queryKey, (prev) =>
          (prev ?? []).filter((a) => !(a.source === source && a.message_id === messageId)),
        );
        return true;
      } catch {
        return false;
      }
    },
    [workspaceId, qc, queryKey],
  );

  const isAssignedTo = useCallback(
    (source: string, messageId: string, userId: string) => {
      const a = assignments.find((a) => a.source === source && a.message_id === messageId);
      return a?.assigned_to === userId;
    },
    [assignments],
  );

  return {
    assignments,
    loading: !!workspaceId && isPending,
    hasError: !!workspaceId && isError,
    getAssignment,
    assign,
    unassign,
    isAssignedTo,
  };
}
