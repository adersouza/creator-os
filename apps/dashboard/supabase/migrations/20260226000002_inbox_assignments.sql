-- ============================================
-- INBOX ASSIGNMENTS (Team collaboration)
-- ============================================
-- Tracks which team member is assigned to each inbox item.
-- Uses (source, message_id) composite key so we don't modify 4 separate tables.

CREATE TABLE IF NOT EXISTS public.inbox_assignments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id TEXT NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  source TEXT NOT NULL CHECK (source IN ('threads_reply', 'threads_mention', 'ig_comment', 'ig_mention', 'ig_dm')),
  message_id TEXT NOT NULL,
  assigned_to TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  assigned_by TEXT NOT NULL REFERENCES public.profiles(id),
  note TEXT,
  assigned_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(workspace_id, source, message_id)
);

CREATE INDEX IF NOT EXISTS idx_inbox_assignments_workspace ON public.inbox_assignments(workspace_id);
CREATE INDEX IF NOT EXISTS idx_inbox_assignments_assignee ON public.inbox_assignments(assigned_to);
CREATE INDEX IF NOT EXISTS idx_inbox_assignments_lookup ON public.inbox_assignments(source, message_id);

ALTER TABLE public.inbox_assignments ENABLE ROW LEVEL SECURITY;

-- Workspace members can read assignments in their workspace
CREATE POLICY "Workspace members can view inbox assignments"
  ON public.inbox_assignments FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM public.workspace_members wm
      WHERE wm.workspace_id = inbox_assignments.workspace_id
      AND wm.user_id = auth.uid()::text
    )
  );

-- Admins and owners can assign/reassign
CREATE POLICY "Workspace admins can manage inbox assignments"
  ON public.inbox_assignments FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM public.workspace_members wm
      WHERE wm.workspace_id = inbox_assignments.workspace_id
      AND wm.user_id = auth.uid()::text
      AND wm.role IN ('owner', 'admin')
    )
  );

-- Members can assign to themselves (self-assign)
CREATE POLICY "Members can self-assign inbox items"
  ON public.inbox_assignments FOR INSERT
  WITH CHECK (
    assigned_to = auth.uid()::text
    AND EXISTS (
      SELECT 1 FROM public.workspace_members wm
      WHERE wm.workspace_id = inbox_assignments.workspace_id
      AND wm.user_id = auth.uid()::text
    )
  );

-- Members can unassign themselves
CREATE POLICY "Members can unassign themselves"
  ON public.inbox_assignments FOR DELETE
  USING (
    assigned_to = auth.uid()::text
    AND EXISTS (
      SELECT 1 FROM public.workspace_members wm
      WHERE wm.workspace_id = inbox_assignments.workspace_id
      AND wm.user_id = auth.uid()::text
    )
  );
