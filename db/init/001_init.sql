-- Database Initialization Schema for MineIQ

-- Custom Enum Types
CREATE TYPE source_type_enum AS ENUM ('pdf', 'spreadsheet', 'image', 'archive');
CREATE TYPE document_status_enum AS ENUM ('uploaded', 'ocr_pending', 'ocr_done', 'validated', 'classified', 'failed');

-- Documents Table
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    original_filename VARCHAR(255) NOT NULL,
    s3_key VARCHAR(512) NOT NULL,
    source_type source_type_enum NOT NULL,
    idempotency_key VARCHAR(64) UNIQUE NOT NULL,
    status document_status_enum NOT NULL DEFAULT 'uploaded',
    doc_type VARCHAR(100),
    subsidiary VARCHAR(100),
    urgency VARCHAR(50),
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for frequent query paths
CREATE INDEX IF NOT EXISTS idx_documents_idempotency_key ON documents(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
