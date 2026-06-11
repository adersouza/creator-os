-- Fix duplicate index on account_daily_summary
DROP INDEX IF EXISTS public.account_daily_summary_date_idx1;
