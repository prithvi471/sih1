-- Migration 006: Parliamentary Question Copilot
-- Registers PQs, per-subsidiary response tasks, and generated draft responses.

CREATE TABLE IF NOT EXISTS parliamentary_questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pq_number VARCHAR(50) UNIQUE,
    question_text TEXT NOT NULL,
    house VARCHAR(50),                       -- 'Lok Sabha' / 'Rajya Sabha'
    member_name VARCHAR(150),
    ministry VARCHAR(150) DEFAULT 'Ministry of Coal',
    received_date DATE DEFAULT CURRENT_DATE,
    due_date DATE,
    subsidiaries VARCHAR(50)[] DEFAULT ARRAY[]::VARCHAR(50)[],
    metrics VARCHAR(50)[] DEFAULT ARRAY[]::VARCHAR(50)[],
    topics VARCHAR(100)[] DEFAULT ARRAY[]::VARCHAR(100)[],
    period_from INT,
    period_to INT,
    status VARCHAR(30) NOT NULL DEFAULT 'REGISTERED', -- REGISTERED, ANALYZED, DRAFTED, PENDING_APPROVAL, APPROVED, REJECTED
    analysis JSONB DEFAULT '{}'::jsonb,
    created_by VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pq_status ON parliamentary_questions(status);
CREATE INDEX IF NOT EXISTS idx_pq_due ON parliamentary_questions(due_date);

-- One task per subsidiary involved in a PQ (multi-subsidiary compilation).
CREATE TABLE IF NOT EXISTS pq_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pq_id UUID REFERENCES parliamentary_questions(id) ON DELETE CASCADE,
    subsidiary VARCHAR(50) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'OPEN', -- OPEN, IN_PROGRESS, SUBMITTED
    assigned_user VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (pq_id, subsidiary)
);

CREATE INDEX IF NOT EXISTS idx_pq_tasks_pq ON pq_tasks(pq_id);

-- Generated draft responses (versioned; latest by generated_at).
CREATE TABLE IF NOT EXISTS parliamentary_responses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pq_id UUID REFERENCES parliamentary_questions(id) ON DELETE CASCADE,
    draft_text TEXT NOT NULL,
    sources JSONB DEFAULT '[]'::jsonb,
    data_table JSONB DEFAULT '[]'::jsonb,
    discrepancies JSONB DEFAULT '[]'::jsonb,
    status VARCHAR(30) NOT NULL DEFAULT 'DRAFT', -- DRAFT, PENDING_APPROVAL, APPROVED, REJECTED
    generated_by VARCHAR(100),
    approved_by VARCHAR(100),
    approved_at TIMESTAMPTZ,
    review_note TEXT,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pq_responses_pq ON parliamentary_responses(pq_id);
