-- Separate column migrations allow the existing runner to retry partial upgrades.
ALTER TABLE lesson_logs ADD COLUMN original_filename TEXT;
