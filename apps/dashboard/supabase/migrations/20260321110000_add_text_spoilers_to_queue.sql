-- Add text_spoilers column for Threads spoiler trick feature
-- Stores spoiler word metadata (word + which chars to hide)
-- Offsets are calculated at publish time to survive humanization transforms
ALTER TABLE auto_post_queue
ADD COLUMN IF NOT EXISTS text_spoilers JSONB DEFAULT NULL;

COMMENT ON COLUMN auto_post_queue.text_spoilers IS 'Spoiler word metadata: { word, charOffset, charLength }. Offsets calculated at publish time.';
