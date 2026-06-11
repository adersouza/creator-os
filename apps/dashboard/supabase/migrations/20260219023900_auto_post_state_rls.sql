-- Add RLS policies for auto_post_state
CREATE POLICY "Users can read own auto_post_state"
  ON public.auto_post_state FOR SELECT
  TO authenticated
  USING (
    EXISTS (SELECT 1 FROM public.accounts a WHERE a.id::text = auto_post_state.workspace_id AND a.user_id = auth.uid()::text)
  );

CREATE POLICY "Users can insert own auto_post_state"
  ON public.auto_post_state FOR INSERT
  TO authenticated
  WITH CHECK (
    EXISTS (SELECT 1 FROM public.accounts a WHERE a.id::text = auto_post_state.workspace_id AND a.user_id = auth.uid()::text)
  );

CREATE POLICY "Users can update own auto_post_state"
  ON public.auto_post_state FOR UPDATE
  TO authenticated
  USING (
    EXISTS (SELECT 1 FROM public.accounts a WHERE a.id::text = auto_post_state.workspace_id AND a.user_id = auth.uid()::text)
  )
  WITH CHECK (
    EXISTS (SELECT 1 FROM public.accounts a WHERE a.id::text = auto_post_state.workspace_id AND a.user_id = auth.uid()::text)
  );
