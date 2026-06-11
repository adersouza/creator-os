-- Fix for ThreadsDashboard Migration
-- Run this in Supabase SQL Editor to fix:
-- 1. Create user_workspaces VIEW (if not exists)
-- 2. Add missing columns to workspaces table

-- ============================================
-- CREATE USER_WORKSPACES VIEW
-- ============================================
-- This view joins workspace data with membership
-- Code queries this to get user's workspaces

CREATE OR REPLACE VIEW public.user_workspaces AS
SELECT
  w.id,
  w.name,
  w.tier,
  w.settings,
  w.owner_id,
  w.created_at,
  wm.user_id,
  wm.role
FROM public.workspaces w
INNER JOIN public.workspace_members wm ON w.id = wm.workspace_id;

-- Grant access to the view
GRANT SELECT ON public.user_workspaces TO authenticated;
GRANT SELECT ON public.user_workspaces TO anon;

-- ============================================
-- ADD MISSING COLUMNS TO WORKSPACES (if needed)
-- ============================================
-- Some code might expect these columns to exist

ALTER TABLE public.workspaces
ADD COLUMN IF NOT EXISTS max_members INTEGER DEFAULT 4;

ALTER TABLE public.workspaces
ADD COLUMN IF NOT EXISTS max_accounts INTEGER DEFAULT 5;

ALTER TABLE public.workspaces
ADD COLUMN IF NOT EXISTS subscription JSONB;

ALTER TABLE public.workspaces
ADD COLUMN IF NOT EXISTS account_count INTEGER DEFAULT 0;

ALTER TABLE public.workspaces
ADD COLUMN IF NOT EXISTS member_count INTEGER DEFAULT 1;

-- ============================================
-- ADD MISSING COLUMNS TO WORKSPACE_MEMBERS (if needed)
-- ============================================

ALTER TABLE public.workspace_members
ADD COLUMN IF NOT EXISTS display_name TEXT;

ALTER TABLE public.workspace_members
ADD COLUMN IF NOT EXISTS email TEXT;

ALTER TABLE public.workspace_members
ADD COLUMN IF NOT EXISTS photo_url TEXT;

-- ============================================
-- ADD MISSING COLUMNS TO WORKSPACE_INVITES (if needed)
-- ============================================

ALTER TABLE public.workspace_invites
ADD COLUMN IF NOT EXISTS code TEXT;

ALTER TABLE public.workspace_invites
ADD COLUMN IF NOT EXISTS used BOOLEAN DEFAULT FALSE;

ALTER TABLE public.workspace_invites
ADD COLUMN IF NOT EXISTS used_by UUID REFERENCES public.profiles(id);

ALTER TABLE public.workspace_invites
ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES public.profiles(id);

-- ============================================
-- ADD MISSING COLUMNS TO WORKSPACE_ACTIVITY (if needed)
-- ============================================

ALTER TABLE public.workspace_activity
ADD COLUMN IF NOT EXISTS action TEXT;

ALTER TABLE public.workspace_activity
ADD COLUMN IF NOT EXISTS user_name TEXT;

ALTER TABLE public.workspace_activity
ADD COLUMN IF NOT EXISTS details JSONB;

-- ============================================
-- DONE
-- ============================================
