-- Add cover_url column to media_folders for user-selected folder cover photos
ALTER TABLE media_folders ADD COLUMN IF NOT EXISTS cover_url TEXT DEFAULT NULL;
