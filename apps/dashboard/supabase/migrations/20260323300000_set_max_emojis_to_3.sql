-- Set content_filter_max_emojis to 3 (was 2 or NULL).
-- Competitors use 2-3 emoji. The old value of 2 combined with the
-- broken emoji counter (counting skin tone modifiers as separate emoji)
-- was rejecting valid posts like "🤌🏼🤌🏼🤌🏼" (3 visible, counted as 6).

UPDATE auto_post_config
SET content_filter_max_emojis = 3
WHERE content_filter_max_emojis IS NULL OR content_filter_max_emojis < 3;
