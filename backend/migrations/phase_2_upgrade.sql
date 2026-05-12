-- Phase 2 schema migration — run if you have existing v1.5 data.
-- For fresh installs, Base.metadata.create_all will pick up these columns
-- automatically on first startup; you don't need to run this.

-- Add Phase 2 columns to search_history
ALTER TABLE search_history
    ADD COLUMN IF NOT EXISTS input_type VARCHAR(32) NOT NULL DEFAULT 'youtube',
    ALTER COLUMN input_url DROP NOT NULL,
    ALTER COLUMN content_id DROP NOT NULL;

-- Backfill input_type for existing rows (all v1.5 data is YouTube)
UPDATE search_history SET input_type = 'youtube' WHERE input_type IS NULL;

-- Add Phase 2 OCR columns to extracted_clues
ALTER TABLE extracted_clues
    ADD COLUMN IF NOT EXISTS ocr_text JSON,
    ADD COLUMN IF NOT EXISTS ocr_full_text TEXT,
    ADD COLUMN IF NOT EXISTS ocr_confidence FLOAT,
    ADD COLUMN IF NOT EXISTS ocr_backend VARCHAR(32);
