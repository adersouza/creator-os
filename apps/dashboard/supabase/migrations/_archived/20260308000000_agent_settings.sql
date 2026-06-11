-- Agent Settings: kill switch for autonomous agent writes
-- Adds agent_paused flag to profiles table.
-- When true, API key (agent) writes return 503 "Agent paused by user".

ALTER TABLE profiles
  ADD COLUMN IF NOT EXISTS agent_paused BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN profiles.agent_paused IS
  'When true, MCP agent API key writes are blocked with 503. User-controlled kill switch.';
