-- Resolve Supabase advisor `auth_rls_initplan` warnings for recently added
-- operator, eval, Campaign Factory, proofing, quarantine, and account DNA
-- policies. The predicates intentionally match the live policies, with
-- auth.uid() wrapped as an initplan and anonymous access made explicitly out
-- of scope via TO authenticated.

DO $$
DECLARE
  policy_record record;
  create_statement text;
BEGIN
  FOR policy_record IN
    SELECT *
    FROM (
      VALUES
        (
          'account_content_arcs',
          'account_content_arcs_workspace_read',
          'SELECT',
          'EXISTS (
            SELECT 1
            FROM public.workspace_members wm
            WHERE wm.workspace_id = account_content_arcs.workspace_id
              AND wm.user_id = (select auth.uid())::text
          )',
          NULL
        ),
        (
          'account_dna',
          'Workspace members can read account DNA',
          'SELECT',
          'EXISTS (
            SELECT 1
            FROM public.workspace_members wm
            WHERE wm.workspace_id = account_dna.workspace_id
              AND wm.user_id = (select auth.uid())::text
          )',
          NULL
        ),
        (
          'account_dna_examples',
          'Workspace members can read account DNA examples',
          'SELECT',
          'EXISTS (
            SELECT 1
            FROM public.workspace_members wm
            WHERE wm.workspace_id = account_dna_examples.workspace_id
              AND wm.user_id = (select auth.uid())::text
          )',
          NULL
        ),
        (
          'account_dna_rules',
          'Workspace members can read account DNA rules',
          'SELECT',
          'EXISTS (
            SELECT 1
            FROM public.workspace_members wm
            WHERE wm.workspace_id = account_dna_rules.workspace_id
              AND wm.user_id = (select auth.uid())::text
          )',
          NULL
        ),
        (
          'account_uniqueness_metrics',
          'Workspace members can read uniqueness metrics',
          'SELECT',
          'EXISTS (
            SELECT 1
            FROM public.workspace_members wm
            WHERE wm.workspace_id = account_uniqueness_metrics.workspace_id
              AND wm.user_id = (select auth.uid())::text
          )',
          NULL
        ),
        (
          'agent_action_intents',
          'Users can read own agent action intents',
          'SELECT',
          '(select auth.uid()) = user_id',
          NULL
        ),
        (
          'ai_eval_snapshots',
          'Users insert own AI eval snapshots',
          'INSERT',
          NULL,
          '(select auth.uid()) = user_id'
        ),
        (
          'ai_eval_snapshots',
          'Users read own AI eval snapshots',
          'SELECT',
          '(select auth.uid()) = user_id',
          NULL
        ),
        (
          'arc_beats',
          'arc_beats_workspace_read',
          'SELECT',
          'EXISTS (
            SELECT 1
            FROM public.workspace_members wm
            WHERE wm.workspace_id = arc_beats.workspace_id
              AND wm.user_id = (select auth.uid())::text
          )',
          NULL
        ),
        (
          'campaign_factory_audio_events',
          'Users insert own Campaign Factory audio events',
          'INSERT',
          NULL,
          '(select auth.uid())::text = user_id'
        ),
        (
          'campaign_factory_audio_events',
          'Users read own Campaign Factory audio events',
          'SELECT',
          '(select auth.uid())::text = user_id',
          NULL
        ),
        (
          'manager_cycles',
          'Users manage own manager cycles',
          'ALL',
          '(select auth.uid()) = user_id',
          '(select auth.uid()) = user_id'
        ),
        (
          'manager_decisions',
          'Users manage own manager decisions',
          'ALL',
          '(select auth.uid()) = user_id',
          '(select auth.uid()) = user_id'
        ),
        (
          'manager_goals',
          'Users manage own manager goals',
          'ALL',
          '(select auth.uid()) = user_id',
          '(select auth.uid()) = user_id'
        ),
        (
          'manager_plan_items',
          'Users manage own manager plan items',
          'ALL',
          '(select auth.uid()) = user_id',
          '(select auth.uid()) = user_id'
        ),
        (
          'manager_plans',
          'Users manage own manager plans',
          'ALL',
          '(select auth.uid()) = user_id',
          '(select auth.uid()) = user_id'
        ),
        (
          'operator_tasks',
          'Users manage own operator tasks',
          'ALL',
          '(select auth.uid()) = user_id',
          '(select auth.uid()) = user_id'
        ),
        (
          'proof_runs',
          'Users insert own proof runs',
          'INSERT',
          NULL,
          '(select auth.uid())::text = user_id'
        ),
        (
          'proof_runs',
          'Users read own proof runs',
          'SELECT',
          '(select auth.uid())::text = user_id',
          NULL
        ),
        (
          'proof_runs',
          'Users update own proof runs',
          'UPDATE',
          '(select auth.uid())::text = user_id',
          '(select auth.uid())::text = user_id'
        ),
        (
          'quarantined_assets',
          'Users insert own quarantined assets',
          'INSERT',
          NULL,
          '(select auth.uid())::text = user_id'
        ),
        (
          'quarantined_assets',
          'Users read own quarantined assets',
          'SELECT',
          '(select auth.uid())::text = user_id',
          NULL
        ),
        (
          'quarantined_assets',
          'Users update own quarantined assets',
          'UPDATE',
          '(select auth.uid())::text = user_id',
          '(select auth.uid())::text = user_id'
        )
    ) AS policies(table_name, policy_name, command_name, using_sql, check_sql)
  LOOP
    IF to_regclass(format('public.%I', policy_record.table_name)) IS NULL THEN
      CONTINUE;
    END IF;

    EXECUTE format(
      'DROP POLICY IF EXISTS %I ON public.%I',
      policy_record.policy_name,
      policy_record.table_name
    );

    create_statement := format(
      'CREATE POLICY %I ON public.%I FOR %s TO authenticated',
      policy_record.policy_name,
      policy_record.table_name,
      policy_record.command_name
    );

    IF policy_record.using_sql IS NOT NULL THEN
      create_statement := create_statement || ' USING (' || policy_record.using_sql || ')';
    END IF;

    IF policy_record.check_sql IS NOT NULL THEN
      create_statement := create_statement || ' WITH CHECK (' || policy_record.check_sql || ')';
    END IF;

    EXECUTE create_statement;
  END LOOP;
END $$;
