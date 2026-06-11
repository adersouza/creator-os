ALTER TABLE posts ADD COLUMN IF NOT EXISTS quote_chain_depth integer DEFAULT 0;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS quoted_by_count integer DEFAULT 0;
