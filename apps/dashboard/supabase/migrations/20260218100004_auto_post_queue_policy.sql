-- auto_post_queue: Frontend queries this table via workspace_id
-- Add read policy so users can see their own workspace's queue

BEGIN;

CREATE POLICY "Users read own workspace queue"
  ON auto_post_queue FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM workspace_members wm
      WHERE wm.workspace_id = auto_post_queue.workspace_id
        AND wm.user_id = (SELECT auth.uid())::text
    )
  );

COMMIT;
