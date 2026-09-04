-- Migration 004: MineIQ v2 Schema Enhancements (Audit Logs, Structured Data, Domain Validation, Vector Storage, RBAC Users)

-- 1. Create audit_logs table for security and compliance tracking
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id VARCHAR(100) NOT NULL,
    user_role VARCHAR(50) NOT NULL,
    action VARCHAR(100) NOT NULL,
    document_id UUID,
    service VARCHAR(50) NOT NULL,
    result VARCHAR(50) NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    ip_address VARCHAR(45)
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_document_id ON audit_logs(document_id);

-- 2. Create structured_data table for extracted domain metrics
CREATE TABLE IF NOT EXISTS structured_data (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    mine_name VARCHAR(150),
    subsidiary VARCHAR(50),
    report_year INT,
    production_target_mt NUMERIC(10, 2),
    actual_production_mt NUMERIC(10, 2),
    dispatch_mt NUMERIC(10, 2),
    overburden_mcum NUMERIC(10, 2),
    unit VARCHAR(20) DEFAULT 'MT',
    raw_json JSONB DEFAULT '{}'::jsonb,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_structured_data_doc ON structured_data(document_id);
CREATE INDEX IF NOT EXISTS idx_structured_data_subsidiary ON structured_data(subsidiary);

-- 3. Create domain_validations table for anomaly & cross-document consistency checks
CREATE TABLE IF NOT EXISTS domain_validations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    check_type VARCHAR(50) NOT NULL, -- 'format', 'garbled', 'duplicate', 'inconsistency'
    severity VARCHAR(20) NOT NULL, -- 'info', 'warning', 'critical'
    message TEXT NOT NULL,
    competing_doc_id UUID REFERENCES documents(id) ON DELETE SET NULL,
    details JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_domain_validations_doc ON domain_validations(document_id);

-- 4. Create vector_chunks table for semantic retrieval & RAG
CREATE TABLE IF NOT EXISTS vector_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding FLOAT8[], -- Vector embedding array
    subsidiary VARCHAR(50),
    doc_type VARCHAR(100),
    topic VARCHAR(100),
    access_roles VARCHAR(100)[] DEFAULT ARRAY['ADMIN', 'MINISTRY_OFFICER', 'CMPDI_OFFICER'],
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_vector_chunks_doc ON vector_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_vector_chunks_subsidiary ON vector_chunks(subsidiary);

-- 5. Create system_metrics table for performance & ROI tracking
CREATE TABLE IF NOT EXISTS system_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    upload_time_ms INT,
    ocr_time_ms INT,
    validation_time_ms INT,
    classification_time_ms INT,
    report_gen_time_ms INT,
    vector_embed_time_ms INT,
    total_time_ms INT,
    manual_baseline_minutes NUMERIC(10, 2) DEFAULT 180.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 6. Create users table for RBAC authentication
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(100) NOT NULL,
    role VARCHAR(50) NOT NULL, -- 'ADMIN', 'MINISTRY_OFFICER', 'CMPDI_OFFICER', 'SUBSIDIARY_OFFICER', 'ANALYST', 'AUDITOR', 'VIEWER'
    assigned_subsidiary VARCHAR(50), -- Nullable for global roles, mandatory for SUBSIDIARY_OFFICER
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Seed Demo Users
INSERT INTO users (username, password_hash, full_name, role, assigned_subsidiary)
VALUES 
('admin', 'admin123', 'System Administrator', 'ADMIN', NULL),
('ministry_officer', 'ministry123', 'Ministry of Coal Officer', 'MINISTRY_OFFICER', NULL),
('cmpdi_officer', 'cmpdi123', 'CMPDI Nodal Officer', 'CMPDI_OFFICER', 'CMPDI'),
('mcl_officer', 'mcl123', 'MCL Subsidiary Officer', 'SUBSIDIARY_OFFICER', 'MCL'),
('ecl_officer', 'ecl123', 'ECL Subsidiary Officer', 'SUBSIDIARY_OFFICER', 'ECL'),
('auditor_user', 'audit123', 'Compliance Auditor', 'AUDITOR', NULL),
('viewer_user', 'view123', 'Public Relations Viewer', 'VIEWER', NULL)
ON CONFLICT (username) DO NOTHING;
