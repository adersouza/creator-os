-- Migration: Add adaptation_angle and viral_formula columns to inspiration_ideas
-- This adds support for the Fresh Angle Variety feature and viral formula extraction

-- Add the adaptation_angle column
ALTER TABLE public.inspiration_ideas
ADD COLUMN IF NOT EXISTS adaptation_angle TEXT DEFAULT 'direct'
CHECK (adaptation_angle IN ('direct', 'counter', 'story', 'list', 'meme', 'question'));

-- Add the viral_formula column
ALTER TABLE public.inspiration_ideas
ADD COLUMN IF NOT EXISTS viral_formula TEXT;

-- Add index for filtering by angle
CREATE INDEX IF NOT EXISTS idx_inspiration_ideas_adaptation_angle
ON public.inspiration_ideas(adaptation_angle);

-- Done!
-- Run with: psql $DATABASE_URL -f supabase/migrate-add-adaptation-angle.sql
