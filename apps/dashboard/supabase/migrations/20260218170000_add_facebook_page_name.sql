-- Add facebook_page_name to instagram_accounts for pages_show_list permission display
ALTER TABLE instagram_accounts ADD COLUMN IF NOT EXISTS facebook_page_name TEXT;
