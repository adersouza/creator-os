ALTER TABLE posts ADD COLUMN IF NOT EXISTS avg_reply_response_mins numeric;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS reply_response_count integer DEFAULT 0;
