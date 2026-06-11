-- Cross-tenant RLS assertions — P0 #3 (security_compliance_2026.md)
--
-- Proves that user A cannot read/update/delete rows owned by user B across
-- the highest-risk tables. Each assertion raises on failure; the final raise
-- is a sentinel ('ALL_TESTS_PASSED') used to force transaction rollback so
-- the seeded test data never commits.
--
-- Coverage v1.2 (11 tables):
--   User-scoped:   posts, accounts, instagram_accounts, ai_config,
--                  account_analytics (via accounts FK),
--                  reports, smart_links
--   Workspace:     workspaces, workspace_members, auto_post_queue
--   Service-only:  recovery_codes (RLS on, no policies — zero visibility)
--
-- How to run:
--   A. Via MCP: wrap whole file in a single execute_sql call. A successful
--      run ends with error='ALL_TESTS_PASSED' (transaction rolled back).
--   B. Via `supabase db test` or pg_prove: convert DO block to pgtap
--      plan()/ok()/is() form. Covered by follow-up PR (Task #8).
--
-- Prereqs: pgtap extension enabled (migration 20260417_enable_pgtap).

DO $$
DECLARE
  alice_id    UUID := 'aaaaaaa1-1111-1111-1111-111111111111';
  bob_id      UUID := 'bbbbbbb1-1111-1111-1111-111111111111';
  alice_ws_id TEXT := 'ws-alice-' || gen_random_uuid()::text;
  bob_ws_id   TEXT := 'ws-bob-'   || gen_random_uuid()::text;
  alice_acct  TEXT;
  bob_acct    TEXT;
  alice_ig    UUID;
  bob_ig      UUID;
  observed    BIGINT;
  affected    BIGINT;
BEGIN
  ------------------------------------------------------------------
  -- SEED (service_role bypasses RLS)
  ------------------------------------------------------------------
  INSERT INTO auth.users (id, aud, role, email) VALUES
    (alice_id, 'authenticated', 'authenticated', 'alice-rlstest@test.local'),
    (bob_id,   'authenticated', 'authenticated', 'bob-rlstest@test.local')
  ON CONFLICT (id) DO NOTHING;
  -- on_auth_user_created trigger creates public.profiles rows automatically.

  -- posts
  INSERT INTO posts (user_id, content)
    VALUES (alice_id::text, 'rlstest alice post');
  INSERT INTO posts (user_id, content)
    VALUES (bob_id::text,   'rlstest bob post');

  -- accounts (Threads)
  INSERT INTO accounts (user_id, threads_user_id, username, threads_access_token_encrypted)
    VALUES (alice_id::text, 'threads-rlstest-alice', 'rlstest_alice', 'v2:fake-token-alice')
    RETURNING id INTO alice_acct;
  INSERT INTO accounts (user_id, threads_user_id, username, threads_access_token_encrypted)
    VALUES (bob_id::text, 'threads-rlstest-bob', 'rlstest_bob', 'v2:fake-token-bob')
    RETURNING id INTO bob_acct;

  -- instagram_accounts
  INSERT INTO instagram_accounts (user_id, instagram_user_id)
    VALUES (alice_id::text, 'ig-rlstest-alice')
    RETURNING id INTO alice_ig;
  INSERT INTO instagram_accounts (user_id, instagram_user_id)
    VALUES (bob_id::text, 'ig-rlstest-bob')
    RETURNING id INTO bob_ig;

  -- ai_config
  INSERT INTO ai_config (user_id) VALUES (alice_id::text);
  INSERT INTO ai_config (user_id) VALUES (bob_id::text);

  -- account_analytics (FKs accounts.id)
  INSERT INTO account_analytics (account_id, date)
    VALUES (alice_acct, CURRENT_DATE);
  INSERT INTO account_analytics (account_id, date)
    VALUES (bob_acct, CURRENT_DATE);

  -- workspaces + workspace_members
  INSERT INTO workspaces (id, name, owner_id)
    VALUES (alice_ws_id, 'alice workspace (rlstest)', alice_id::text);
  INSERT INTO workspaces (id, name, owner_id)
    VALUES (bob_ws_id,   'bob workspace (rlstest)',   bob_id::text);
  INSERT INTO workspace_members (workspace_id, user_id)
    VALUES (alice_ws_id, alice_id::text);
  INSERT INTO workspace_members (workspace_id, user_id)
    VALUES (bob_ws_id,   bob_id::text);

  -- auto_post_queue (workspace-scoped)
  INSERT INTO auto_post_queue (workspace_id, content, scheduled_for)
    VALUES (alice_ws_id, 'rlstest alice queued', now() + interval '1 day');
  INSERT INTO auto_post_queue (workspace_id, content, scheduled_for)
    VALUES (bob_ws_id,   'rlstest bob queued',   now() + interval '1 day');

  -- reports (user-owned, juno33 Reports page)
  INSERT INTO reports (user_id, name, type, cadence)
    VALUES (alice_id::text, 'rlstest alice report', 'scheduled', 'weekly');
  INSERT INTO reports (user_id, name, type, cadence)
    VALUES (bob_id::text,   'rlstest bob report',   'scheduled', 'weekly');

  -- smart_links (user-owned)
  INSERT INTO smart_links (user_id, code, target_url)
    VALUES (alice_id::text, 'rlstest-alice-' || gen_random_uuid()::text, 'https://example.com/a');
  INSERT INTO smart_links (user_id, code, target_url)
    VALUES (bob_id::text,   'rlstest-bob-'   || gen_random_uuid()::text, 'https://example.com/b');

  -- recovery_codes (service-role-only; RLS on with no policies)
  INSERT INTO recovery_codes (user_id, code_hash)
    VALUES (alice_id::text, 'scrypt$16384$8$1$aaaa$rlstestalice'),
           (bob_id::text,   'scrypt$16384$8$1$bbbb$rlstestbob');

  ------------------------------------------------------------------
  -- IMPERSONATE ALICE + run read-isolation checks
  ------------------------------------------------------------------
  PERFORM set_config(
    'request.jwt.claims',
    jsonb_build_object('sub', alice_id::text, 'role', 'authenticated')::text,
    true
  );
  EXECUTE 'SET LOCAL ROLE authenticated';

  -- posts
  SELECT COUNT(*) INTO observed FROM posts WHERE content LIKE 'rlstest%';
  IF observed <> 1 THEN
    RAISE EXCEPTION 'FAIL posts.SELECT: Alice saw % rlstest rows (expected 1)', observed;
  END IF;

  -- accounts
  SELECT COUNT(*) INTO observed FROM accounts WHERE username LIKE 'rlstest_%';
  IF observed <> 1 THEN
    RAISE EXCEPTION 'FAIL accounts.SELECT: Alice saw % rlstest accounts (expected 1)', observed;
  END IF;

  -- instagram_accounts
  SELECT COUNT(*) INTO observed FROM instagram_accounts WHERE instagram_user_id LIKE 'ig-rlstest-%';
  IF observed <> 1 THEN
    RAISE EXCEPTION 'FAIL instagram_accounts.SELECT: Alice saw % (expected 1)', observed;
  END IF;

  -- ai_config
  SELECT COUNT(*) INTO observed FROM ai_config WHERE user_id IN (alice_id::text, bob_id::text);
  IF observed <> 1 THEN
    RAISE EXCEPTION 'FAIL ai_config.SELECT: Alice saw % rlstest configs (expected 1)', observed;
  END IF;

  -- account_analytics (indirect via accounts join in RLS policy)
  SELECT COUNT(*) INTO observed FROM account_analytics
    WHERE account_id IN (alice_acct, bob_acct);
  IF observed <> 1 THEN
    RAISE EXCEPTION 'FAIL account_analytics.SELECT: Alice saw % (expected 1, hers only)', observed;
  END IF;

  -- workspaces (Alice can see her own + any she's a member of)
  SELECT COUNT(*) INTO observed FROM workspaces WHERE id IN (alice_ws_id, bob_ws_id);
  IF observed <> 1 THEN
    RAISE EXCEPTION 'FAIL workspaces.SELECT: Alice saw % rlstest workspaces (expected 1)', observed;
  END IF;

  -- workspace_members (sees own row + rows of workspaces she owns)
  SELECT COUNT(*) INTO observed FROM workspace_members
    WHERE workspace_id IN (alice_ws_id, bob_ws_id);
  IF observed <> 1 THEN
    RAISE EXCEPTION 'FAIL workspace_members.SELECT: Alice saw % members (expected 1)', observed;
  END IF;

  -- auto_post_queue (workspace-scoped)
  SELECT COUNT(*) INTO observed FROM auto_post_queue WHERE content LIKE 'rlstest%';
  IF observed <> 1 THEN
    RAISE EXCEPTION 'FAIL auto_post_queue.SELECT: Alice saw % (expected 1)', observed;
  END IF;

  -- reports
  SELECT COUNT(*) INTO observed FROM reports WHERE name LIKE 'rlstest%';
  IF observed <> 1 THEN
    RAISE EXCEPTION 'FAIL reports.SELECT: Alice saw % rlstest reports (expected 1)', observed;
  END IF;

  -- smart_links
  SELECT COUNT(*) INTO observed FROM smart_links WHERE code LIKE 'rlstest-%';
  IF observed <> 1 THEN
    RAISE EXCEPTION 'FAIL smart_links.SELECT: Alice saw % rlstest links (expected 1)', observed;
  END IF;

  -- recovery_codes — RLS on, no policies → zero visibility even for owner.
  -- Service role is the only legitimate reader; the backend endpoint holds that.
  SELECT COUNT(*) INTO observed FROM recovery_codes
    WHERE code_hash LIKE '%rlstest%';
  IF observed <> 0 THEN
    RAISE EXCEPTION 'FAIL recovery_codes.SELECT: Alice saw % rows (expected 0)', observed;
  END IF;

  ------------------------------------------------------------------
  -- ALICE attempts WRITE on BOB's rows — RLS should block/no-op
  ------------------------------------------------------------------

  -- UPDATE Bob's post → 0 rows affected
  WITH upd AS (
    UPDATE posts SET content = 'hijacked by alice'
      WHERE user_id = bob_id::text AND content = 'rlstest bob post'
      RETURNING 1
  )
  SELECT COUNT(*) INTO affected FROM upd;
  IF affected <> 0 THEN
    RAISE EXCEPTION 'FAIL posts.UPDATE: Alice modified % of Bobs rows', affected;
  END IF;

  -- DELETE Bob's post → 0 rows affected
  WITH del AS (
    DELETE FROM posts WHERE user_id = bob_id::text RETURNING 1
  )
  SELECT COUNT(*) INTO affected FROM del;
  IF affected <> 0 THEN
    RAISE EXCEPTION 'FAIL posts.DELETE: Alice deleted % of Bobs rows', affected;
  END IF;

  -- UPDATE Bob's account → 0 rows affected
  WITH upd AS (
    UPDATE accounts SET username = 'hijacked_alice'
      WHERE user_id = bob_id::text RETURNING 1
  )
  SELECT COUNT(*) INTO affected FROM upd;
  IF affected <> 0 THEN
    RAISE EXCEPTION 'FAIL accounts.UPDATE: Alice modified % of Bobs accounts', affected;
  END IF;

  -- INSERT with Bob's user_id as Alice → WITH CHECK should reject
  BEGIN
    INSERT INTO posts (user_id, content)
      VALUES (bob_id::text, 'rlstest alice impersonating bob');
    -- Count visible rows (if insert succeeded despite WITH CHECK, we'd see it)
    SELECT COUNT(*) INTO observed FROM posts
      WHERE content = 'rlstest alice impersonating bob';
    IF observed > 0 THEN
      RAISE EXCEPTION 'FAIL posts.INSERT: Alice inserted % posts as Bob', observed;
    END IF;
  EXCEPTION
    WHEN insufficient_privilege THEN
      NULL; -- expected — RLS WITH CHECK rejected
    WHEN check_violation THEN
      NULL; -- also acceptable
  END;

  -- UPDATE Bob's workspace as a non-member → 0 rows affected
  WITH upd AS (
    UPDATE workspaces SET name = 'hijacked' WHERE id = bob_ws_id RETURNING 1
  )
  SELECT COUNT(*) INTO affected FROM upd;
  IF affected <> 0 THEN
    RAISE EXCEPTION 'FAIL workspaces.UPDATE: Alice modified Bobs workspace (% rows)', affected;
  END IF;

  -- UPDATE Bob's auto_post_queue item → 0 rows affected
  WITH upd AS (
    UPDATE auto_post_queue SET content = 'hijacked'
      WHERE workspace_id = bob_ws_id RETURNING 1
  )
  SELECT COUNT(*) INTO affected FROM upd;
  IF affected <> 0 THEN
    RAISE EXCEPTION 'FAIL auto_post_queue.UPDATE: Alice modified Bobs queue (% rows)', affected;
  END IF;

  -- UPDATE Bob's report → 0 rows affected
  WITH upd AS (
    UPDATE reports SET name = 'hijacked'
      WHERE user_id = bob_id::text AND name = 'rlstest bob report' RETURNING 1
  )
  SELECT COUNT(*) INTO affected FROM upd;
  IF affected <> 0 THEN
    RAISE EXCEPTION 'FAIL reports.UPDATE: Alice modified % of Bobs reports', affected;
  END IF;

  -- DELETE Bob's smart_link → 0 rows affected
  WITH del AS (
    DELETE FROM smart_links
      WHERE user_id = bob_id::text AND code LIKE 'rlstest-bob-%' RETURNING 1
  )
  SELECT COUNT(*) INTO affected FROM del;
  IF affected <> 0 THEN
    RAISE EXCEPTION 'FAIL smart_links.DELETE: Alice deleted % of Bobs links', affected;
  END IF;

  -- INSERT report with Bob's user_id as Alice → WITH CHECK rejects
  BEGIN
    INSERT INTO reports (user_id, name, type, cadence)
      VALUES (bob_id::text, 'rlstest alice impersonating bob report', 'scheduled', 'weekly');
    SELECT COUNT(*) INTO observed FROM reports
      WHERE name = 'rlstest alice impersonating bob report';
    IF observed > 0 THEN
      RAISE EXCEPTION 'FAIL reports.INSERT: Alice inserted % reports as Bob', observed;
    END IF;
  EXCEPTION
    WHEN insufficient_privilege THEN NULL;
    WHEN check_violation THEN NULL;
  END;

  ------------------------------------------------------------------
  -- SWITCH TO BOB + verify mirrored isolation
  ------------------------------------------------------------------
  RESET ROLE;
  PERFORM set_config(
    'request.jwt.claims',
    jsonb_build_object('sub', bob_id::text, 'role', 'authenticated')::text,
    true
  );
  EXECUTE 'SET LOCAL ROLE authenticated';

  SELECT COUNT(*) INTO observed FROM posts WHERE content LIKE 'rlstest%';
  IF observed <> 1 THEN
    RAISE EXCEPTION 'FAIL posts.SELECT (Bob): saw % rlstest rows (expected 1)', observed;
  END IF;

  SELECT COUNT(*) INTO observed FROM accounts WHERE username LIKE 'rlstest_%';
  IF observed <> 1 THEN
    RAISE EXCEPTION 'FAIL accounts.SELECT (Bob): saw % (expected 1)', observed;
  END IF;

  SELECT COUNT(*) INTO observed FROM workspaces WHERE id IN (alice_ws_id, bob_ws_id);
  IF observed <> 1 THEN
    RAISE EXCEPTION 'FAIL workspaces.SELECT (Bob): saw % (expected 1)', observed;
  END IF;

  SELECT COUNT(*) INTO observed FROM reports WHERE name LIKE 'rlstest%';
  IF observed <> 1 THEN
    RAISE EXCEPTION 'FAIL reports.SELECT (Bob): saw % (expected 1)', observed;
  END IF;

  SELECT COUNT(*) INTO observed FROM smart_links WHERE code LIKE 'rlstest-%';
  IF observed <> 1 THEN
    RAISE EXCEPTION 'FAIL smart_links.SELECT (Bob): saw % (expected 1)', observed;
  END IF;

  ------------------------------------------------------------------
  -- ANON (unauthenticated) can see nothing
  ------------------------------------------------------------------
  RESET ROLE;
  PERFORM set_config(
    'request.jwt.claims',
    jsonb_build_object('role', 'anon')::text,
    true
  );
  EXECUTE 'SET LOCAL ROLE anon';

  SELECT COUNT(*) INTO observed FROM posts WHERE content LIKE 'rlstest%';
  IF observed <> 0 THEN
    RAISE EXCEPTION 'FAIL posts.SELECT (anon): saw % rows (expected 0)', observed;
  END IF;

  SELECT COUNT(*) INTO observed FROM accounts WHERE username LIKE 'rlstest_%';
  IF observed <> 0 THEN
    RAISE EXCEPTION 'FAIL accounts.SELECT (anon): saw % rows (expected 0)', observed;
  END IF;

  SELECT COUNT(*) INTO observed FROM workspaces WHERE id IN (alice_ws_id, bob_ws_id);
  IF observed <> 0 THEN
    RAISE EXCEPTION 'FAIL workspaces.SELECT (anon): saw % rows (expected 0)', observed;
  END IF;

  SELECT COUNT(*) INTO observed FROM reports WHERE name LIKE 'rlstest%';
  IF observed <> 0 THEN
    RAISE EXCEPTION 'FAIL reports.SELECT (anon): saw % rows (expected 0)', observed;
  END IF;

  SELECT COUNT(*) INTO observed FROM smart_links WHERE code LIKE 'rlstest-%';
  IF observed <> 0 THEN
    RAISE EXCEPTION 'FAIL smart_links.SELECT (anon): saw % rows (expected 0)', observed;
  END IF;

  ------------------------------------------------------------------
  -- All assertions passed. Force rollback so seed data never commits.
  ------------------------------------------------------------------
  RESET ROLE;
  RAISE EXCEPTION 'ALL_TESTS_PASSED';
END $$;
