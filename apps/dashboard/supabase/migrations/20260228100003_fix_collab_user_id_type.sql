-- #558: influencer_collabs.user_id should be TEXT (per architecture), not UUID
-- Core IDs in this codebase are TEXT, not UUID

DO $$
BEGIN
  -- Only alter if the column exists and is uuid type
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'influencer_collabs'
    AND column_name = 'user_id'
    AND data_type = 'uuid'
  ) THEN
    ALTER TABLE influencer_collabs ALTER COLUMN user_id TYPE text USING user_id::text;
  END IF;
END $$;
