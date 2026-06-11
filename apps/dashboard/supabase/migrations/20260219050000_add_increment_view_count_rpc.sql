-- Atomic view count increment for link pages (avoids race conditions)
CREATE OR REPLACE FUNCTION increment_view_count(p_page_id UUID)
RETURNS VOID AS $$
BEGIN
  UPDATE link_pages
  SET view_count = COALESCE(view_count, 0) + 1
  WHERE id = p_page_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
