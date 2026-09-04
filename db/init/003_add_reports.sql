-- Migration 003: Add reports table, failure_reason, and update enum types

-- Ensure enum values exist
ALTER TYPE document_status_enum ADD VALUE IF NOT EXISTS 'flagged';
ALTER TYPE document_status_enum ADD VALUE IF NOT EXISTS 'failed';

-- Ensure all document columns exist
ALTER TABLE documents ADD COLUMN IF NOT EXISTS extracted_text TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS flag_reason TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS failure_reason TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_duplicate BOOLEAN DEFAULT false;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS topic_area VARCHAR(200);

-- Create reports table
CREATE TABLE IF NOT EXISTS reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    report_text TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Index for document_id lookups in reports table
CREATE INDEX IF NOT EXISTS idx_reports_document_id ON reports(document_id);
