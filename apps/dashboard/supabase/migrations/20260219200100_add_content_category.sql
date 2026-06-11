ALTER TABLE posts ADD COLUMN IF NOT EXISTS content_category text;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS content_category_confidence numeric;
