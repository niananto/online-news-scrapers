-- Drop unused columns from youtube_videos table
-- Run this script to remove columns that are no longer needed

-- First drop indexes that depend on these columns
DROP INDEX IF EXISTS idx_youtube_videos_content_category;
DROP INDEX IF EXISTS idx_youtube_videos_sentiment_score;

-- Drop the unused columns
ALTER TABLE youtube_videos DROP COLUMN IF EXISTS published_at_text;
ALTER TABLE youtube_videos DROP COLUMN IF EXISTS duration_text;
ALTER TABLE youtube_videos DROP COLUMN IF EXISTS default_audio_language;
ALTER TABLE youtube_videos DROP COLUMN IF EXISTS default_language;
ALTER TABLE youtube_videos DROP COLUMN IF EXISTS language_detection_confidence;
ALTER TABLE youtube_videos DROP COLUMN IF EXISTS content_category;
ALTER TABLE youtube_videos DROP COLUMN IF EXISTS sentiment_score;

-- Confirm columns have been dropped
\d youtube_videos;