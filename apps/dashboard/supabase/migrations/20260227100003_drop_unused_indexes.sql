-- Drop indexes with no matching query pattern in the codebase.
-- Unused indexes slow down writes without benefiting reads.
-- Can be recreated if needed when admin features are built.

-- audit_logs: INSERT-only table, never queried by SELECT
DROP INDEX IF EXISTS idx_audit_logs_user_created;
DROP INDEX IF EXISTS idx_audit_logs_resource;
DROP INDEX IF EXISTS idx_audit_logs_action;

-- api_usage: accessed only via increment_api_usage() RPC, never queried directly
DROP INDEX IF EXISTS idx_api_usage_user_period;

-- creator_events: queries filter by (user_id, account_id) but never by event_type
DROP INDEX IF EXISTS idx_creator_events_type_date;
