-- Migration 005: Auth & RBAC hardening
-- Adds user account lifecycle columns. Passwords are migrated to bcrypt hashes
-- at runtime by the ingestion service (bootstrap_passwords), which also hashes
-- the plaintext demo passwords seeded in 004 on first startup.

ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT true;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(150);

CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active);
