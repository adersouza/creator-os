-- Allow users to delete and update their own workspace's queue items
BEGIN;

CREATE POLICY "Users delete own workspace queue"
  ON auto_post_queue FOR DELETE
  USING (
    EXISTS (
      SELECT 1 FROM workspace_members wm
      WHERE wm.workspace_id = auto_post_queue.workspace_id
        AND wm.user_id = (SELECT auth.uid())::text
    )
  );

CREATE POLICY "Users update own workspace queue"
  ON auto_post_queue FOR UPDATE
  USING (
    EXISTS (
      SELECT 1 FROM workspace_members wm
      WHERE wm.workspace_id = auto_post_queue.workspace_id
        AND wm.user_id = (SELECT auth.uid())::text
    )
  );

CREATE POLICY "Users insert own workspace queue"
  ON auto_post_queue FOR INSERT
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM workspace_members wm
      WHERE wm.workspace_id = auto_post_queue.workspace_id
        AND wm.user_id = (SELECT auth.uid())::text
    )
  );

COMMIT;
