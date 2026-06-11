-- Enable pgtap extension for RLS test suite (supabase/tests/*).
-- pgtap is stateless (just SQL functions) — safe in production.
-- Schema 'extensions' matches Supabase convention for pgcrypto/uuid-ossp.
CREATE EXTENSION IF NOT EXISTS pgtap WITH SCHEMA extensions;
