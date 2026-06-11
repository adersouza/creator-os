-- Fix circular RLS recursion between workspaces and workspace_members
-- The workspaces policy checks workspace_members, and vice versa.
-- This causes infinite recursion / timeout in PostgREST.
--
-- Solution: Create a SECURITY DEFINER function that bypasses RLS
-- to check membership, then use that in the policies.

-- Step 1: Create helper functions (bypasses RLS)
-- Note: workspace_members and workspaces use TEXT columns, not UUID
CREATE OR REPLACE FUNCTION public.is_workspace_member(p_workspace_id TEXT, p_user_id TEXT)
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.workspace_members
    WHERE workspace_id = p_workspace_id AND user_id = p_user_id
  );
$$;

CREATE OR REPLACE FUNCTION public.is_workspace_owner(p_workspace_id TEXT, p_user_id TEXT)
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.workspaces
    WHERE id = p_workspace_id AND owner_id = p_user_id
  );
$$;

-- Step 2: Drop old policies
DROP POLICY IF EXISTS "Workspace access for members" ON public.workspaces;
DROP POLICY IF EXISTS "Workspace members can view" ON public.workspace_members;

-- Step 3: Recreate policies using helper functions (no circular reference)
CREATE POLICY "Workspace access for members" ON public.workspaces FOR SELECT
  USING (owner_id = auth.uid()::TEXT OR public.is_workspace_member(id, auth.uid()::TEXT));

CREATE POLICY "Workspace members can view" ON public.workspace_members FOR SELECT
  USING (user_id = auth.uid()::TEXT OR public.is_workspace_owner(workspace_id, auth.uid()::TEXT));

-- Step 4: Grant execute permissions
GRANT EXECUTE ON FUNCTION public.is_workspace_member(TEXT, TEXT) TO authenticated;
GRANT EXECUTE ON FUNCTION public.is_workspace_member(TEXT, TEXT) TO anon;
GRANT EXECUTE ON FUNCTION public.is_workspace_owner(TEXT, TEXT) TO authenticated;
GRANT EXECUTE ON FUNCTION public.is_workspace_owner(TEXT, TEXT) TO anon;
