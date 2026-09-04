-- Migration 002: Add anomaly flags, duplicates, extracted_text and topic_area to documents table

-- Add 'flagged' status to document_status_enum if it doesn't already exist
ALTER TYPE document_status_enum ADD VALUE IF NOT EXISTS 'flagged';

-- Add new columns to documents table
ALTER TABLE documents ADD COLUMN IF NOT EXISTS extracted_text TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS flag_reason TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_duplicate BOOLEAN DEFAULT false;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS topic_area VARCHAR(200);
