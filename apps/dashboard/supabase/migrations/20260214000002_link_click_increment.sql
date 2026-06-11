-- Migration: Atomic click counter increment for link items
-- Date: 2026-02-14
-- Purpose: SQL function to atomically increment click_count on link_items

CREATE OR REPLACE FUNCTION increment_link_click(p_link_id UUID)
RETURNS VOID AS $$
BEGIN
  UPDATE link_items
  SET click_count = click_count + 1
  WHERE id = p_link_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
