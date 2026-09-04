import os
import io
import re
import json
import uuid
import time
import hashlib
import logging
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, UploadFile, File, HTTPException, Header, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
import boto3
from botocore.client import Config
import httpx
import pika
import sys

# Add parent directory for shared auth module
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from auth import (
    create_jwt_token, decode_jwt_token, get_current_user, verify_document_access,
    log_audit_event, hash_password, verify_password, is_hashed, require_permission,
    has_permission, ROLES, ROLE_PERMISSIONS, ALL_PERMISSIONS,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ingestion-service")

app = FastAPI(
    title="MineIQ Ingestion & Secure Gateway Service",
    description="Ingestion, document management, authentication, RBAC authorization, and pipeline orchestration for CIL/CMPDI AI platform."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration from environment
DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "mineiq_docs")
DB_USER = os.getenv("DB_USER", "mineiq")
DB_PASSWORD = os.getenv("DB_PASSWORD", "mineiq_pass")

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ROOT_USER", os.getenv("MINIO_ACCESS_KEY", "minioadmin"))
MINIO_SECRET_KEY = os.getenv("MINIO_ROOT_PASSWORD", os.getenv("MINIO_SECRET_KEY", "minioadmin"))
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "raw-files")

OCR_SERVICE_URL = os.getenv("OCR_SERVICE_URL", "http://ocr-service:8000")
VALIDATION_SERVICE_URL = os.getenv("VALIDATION_SERVICE_URL", "http://validation-service:8000")
CLASSIFICATION_SERVICE_URL = os.getenv("CLASSIFICATION_SERVICE_URL", "http://classification-service:8000")
RAG_SERVICE_URL = os.getenv("RAG_SERVICE_URL", "http://rag-service:8000")

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_AMQP_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_DEFAULT_USER", os.getenv("RABBITMQ_USER", "mineiq"))
RABBITMQ_PASS = os.getenv("RABBITMQ_DEFAULT_PASS", os.getenv("RABBITMQ_PASS", "mineiq_pass"))


def ensure_schema(conn):
    old_autocommit = conn.autocommit
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            statements = [
                "ALTER TYPE document_status_enum ADD VALUE IF NOT EXISTS 'flagged';",
                "ALTER TYPE document_status_enum ADD VALUE IF NOT EXISTS 'failed';",
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS extracted_text TEXT;",
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS flag_reason TEXT;",
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS failure_reason TEXT;",
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_duplicate BOOLEAN DEFAULT false;",
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS topic_area VARCHAR(200);",
                """
                CREATE TABLE IF NOT EXISTS reports (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
                    report_text TEXT NOT NULL,
                    generated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """,
                """
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
                """,
                """
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
                """,
                """
                CREATE TABLE IF NOT EXISTS domain_validations (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
                    check_type VARCHAR(50) NOT NULL,
                    severity VARCHAR(20) NOT NULL,
                    message TEXT NOT NULL,
                    competing_doc_id UUID REFERENCES documents(id) ON DELETE SET NULL,
                    details JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS vector_chunks (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
                    chunk_index INT NOT NULL,
                    chunk_text TEXT NOT NULL,
                    embedding FLOAT8[],
                    subsidiary VARCHAR(50),
                    doc_type VARCHAR(100),
                    topic VARCHAR(100),
                    access_roles VARCHAR(100)[] DEFAULT ARRAY['ADMIN', 'MINISTRY_OFFICER', 'CMPDI_OFFICER'],
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS system_metrics (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
                    ocr_time_ms INT,
                    validation_time_ms INT,
                    classification_time_ms INT,
                    vector_embed_time_ms INT,
                    total_time_ms INT,
                    manual_baseline_minutes NUMERIC(10, 2) DEFAULT 180.0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS users (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    username VARCHAR(50) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    full_name VARCHAR(100) NOT NULL,
                    role VARCHAR(50) NOT NULL,
                    assigned_subsidiary VARCHAR(50),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """,
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT true;",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login TIMESTAMPTZ;",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(150);",
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS version INT DEFAULT 1;",
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS supersedes_document_id UUID;",
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS uploaded_by VARCHAR(100);",
                "ALTER TYPE document_status_enum ADD VALUE IF NOT EXISTS 'flagged';",
                "ALTER TYPE document_status_enum ADD VALUE IF NOT EXISTS 'failed';",
                "ALTER TYPE document_status_enum ADD VALUE IF NOT EXISTS 'awaiting_signoff';",
                """
                CREATE TABLE IF NOT EXISTS subsidiary_source_config (
                    subsidiary_name VARCHAR(50) PRIMARY KEY,
                    ingestion_method VARCHAR(50) NOT NULL,
                    connection_status VARCHAR(50) NOT NULL,
                    last_sync TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """,
                """
                INSERT INTO subsidiary_source_config (subsidiary_name, ingestion_method, connection_status)
                VALUES 
                ('CMPDI', 'api', 'active'),
                ('MCL', 'shared_drive', 'active'),
                ('ECL', 'shared_drive', 'active'),
                ('WCL', 'api', 'active'),
                ('BCCL', 'api', 'pending'),
                ('SECL', 'shared_drive', 'pending'),
                ('CCL', 'email', 'planned'),
                ('NCL', 'email', 'planned')
                ON CONFLICT (subsidiary_name) DO NOTHING;
                """,
                """
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
                """
            ]
            for stmt in statements:
                try:
                    cur.execute(stmt)
                except Exception as e:
                    logger.debug(f"Schema notice: {str(e)}")
    finally:
        conn.autocommit = old_autocommit


_passwords_bootstrapped = False


def bootstrap_passwords(conn):
    """Hash any legacy plaintext passwords once per process (idempotent)."""
    global _passwords_bootstrapped
    if _passwords_bootstrapped:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, password_hash FROM users;")
            rows = cur.fetchall()
            upgraded = 0
            for row in rows:
                if not is_hashed(row["password_hash"]):
                    cur.execute(
                        "UPDATE users SET password_hash = %s WHERE id = %s;",
                        (hash_password(row["password_hash"]), row["id"]),
                    )
                    upgraded += 1
            conn.commit()
            if upgraded:
                logger.info(f"Hashed {upgraded} legacy plaintext password(s) with bcrypt.")
        _passwords_bootstrapped = True
    except Exception as e:
        logger.warning(f"Password bootstrap notice: {str(e)}")


def get_db_connection():
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            cursor_factory=RealDictCursor
        )
        ensure_schema(conn)
        bootstrap_passwords(conn)
        return conn
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database connection error: {str(e)}"
        )


def get_s3_client():
    return boto3.client(
        's3',
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=Config(signature_version='s3v4'),
        region_name='us-east-1'
    )


# Fanout exchange so every worker (report / triage / topic) receives every
# classified event on its own queue, instead of competing for one shared queue.
CLASSIFIED_EXCHANGE = "document.classified.fanout"


def publish_to_rabbitmq(queue_name: str, payload: dict):
    try:
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
        parameters = pika.ConnectionParameters(
            host=RABBITMQ_HOST,
            port=RABBITMQ_PORT,
            credentials=credentials
        )
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        channel.exchange_declare(exchange=CLASSIFIED_EXCHANGE, exchange_type="fanout", durable=True)
        channel.basic_publish(
            exchange=CLASSIFIED_EXCHANGE,
            routing_key='',
            body=json.dumps(payload),
            properties=pika.BasicProperties(delivery_mode=2)
        )
        connection.close()
        logger.info(f"Published classified event to fanout '{CLASSIFIED_EXCHANGE}' for doc_id={payload.get('document_id')}")
    except Exception as e:
        logger.error(f"Failed to publish RabbitMQ message: {str(e)}")
        raise


def determine_source_type(filename: str) -> str:
    ext = filename.lower().split('.')[-1] if '.' in filename else ''
    if ext in ['pdf']:
        return 'pdf'
    elif ext in ['xls', 'xlsx', 'csv', 'tsv']:
        return 'spreadsheet'
    elif ext in ['png', 'jpg', 'jpeg', 'tiff', 'tif', 'bmp', 'webp']:
        return 'image'
    elif ext in ['zip', 'tar', 'gz', 'rar', '7z', 'bz2']:
        return 'archive'
    return 'pdf'


class LoginRequest(BaseModel):
    username: str
    password: str


@app.get("/health")
def health():
    return {"status": "ok"}


# Authentication Endpoints
@app.post("/auth/login")
def login(payload: LoginRequest):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, password_hash, full_name, role, assigned_subsidiary, COALESCE(is_active, true) AS is_active FROM users WHERE username = %s;",
                (payload.username,)
            )
            user = cur.fetchone()
            if not user or not verify_password(payload.password, user["password_hash"]):
                log_audit_event(conn, payload.username, "UNKNOWN", "LOGIN", "ingestion-service", "FAILED_CREDENTIALS")
                raise HTTPException(status_code=401, detail="Invalid username or password")

            if not user["is_active"]:
                log_audit_event(conn, user["username"], user["role"], "LOGIN", "ingestion-service", "ACCOUNT_DISABLED")
                raise HTTPException(status_code=403, detail="Account is disabled")

            # Transparent upgrade: if the stored password was still plaintext,
            # replace it with a bcrypt hash now that we have the cleartext.
            if not is_hashed(user["password_hash"]):
                try:
                    cur.execute("UPDATE users SET password_hash = %s WHERE id = %s;",
                                (hash_password(payload.password), user["id"]))
                except Exception:
                    pass
            cur.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = %s;", (user["id"],))
            conn.commit()

            token = create_jwt_token(
                username=user["username"],
                role=user["role"],
                full_name=user["full_name"],
                assigned_subsidiary=user["assigned_subsidiary"]
            )

            log_audit_event(conn, user["username"], user["role"], "LOGIN", "ingestion-service", "SUCCESS")
            return {
                "access_token": token,
                "token_type": "bearer",
                "user": {
                    "username": user["username"],
                    "full_name": user["full_name"],
                    "role": user["role"],
                    "assigned_subsidiary": user["assigned_subsidiary"]
                }
            }
    finally:
        conn.close()


@app.get("/auth/me")
def get_me(authorization: Optional[str] = Header(None)):
    user = get_current_user(authorization)
    perms = ROLE_PERMISSIONS.get(user.get("role"), set())
    user["permissions"] = ["*"] if "*" in perms else sorted(perms)
    return user


# ---------------------------------------------------------------------------
# RBAC: roles / permissions catalogue and user administration API.
# ---------------------------------------------------------------------------
@app.get("/auth/roles")
def list_roles(user: dict = Depends(require_permission("users.read"))):
    return {
        "roles": [
            {"role": r, "permissions": ["*"] if "*" in ROLE_PERMISSIONS.get(r, set()) else sorted(ROLE_PERMISSIONS.get(r, set()))}
            for r in ROLES
        ],
        "all_permissions": ALL_PERMISSIONS,
    }


class CreateUserRequest(BaseModel):
    username: str
    password: str
    full_name: str
    role: str
    assigned_subsidiary: Optional[str] = None
    email: Optional[str] = None


class UpdateUserRequest(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    assigned_subsidiary: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None
    email: Optional[str] = None


def _serialize_user(u: dict) -> dict:
    return {
        "id": str(u["id"]),
        "username": u["username"],
        "full_name": u["full_name"],
        "role": u["role"],
        "assigned_subsidiary": u.get("assigned_subsidiary"),
        "email": u.get("email"),
        "is_active": u.get("is_active", True),
        "last_login": u["last_login"].isoformat() if u.get("last_login") else None,
        "created_at": u["created_at"].isoformat() if u.get("created_at") else None,
    }


@app.get("/auth/users")
def list_users(user: dict = Depends(require_permission("users.read"))):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, full_name, role, assigned_subsidiary, email, "
                "COALESCE(is_active, true) AS is_active, last_login, created_at "
                "FROM users ORDER BY created_at ASC;"
            )
            return [_serialize_user(u) for u in cur.fetchall()]
    finally:
        conn.close()


@app.post("/auth/users", status_code=201)
def create_user(payload: CreateUserRequest, admin: dict = Depends(require_permission("users.write"))):
    if payload.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of {ROLES}")
    if payload.role == "SUBSIDIARY_OFFICER" and not payload.assigned_subsidiary:
        raise HTTPException(status_code=400, detail="SUBSIDIARY_OFFICER requires assigned_subsidiary")
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE username = %s;", (payload.username,))
            if cur.fetchone():
                raise HTTPException(status_code=409, detail="Username already exists")
            cur.execute(
                """
                INSERT INTO users (username, password_hash, full_name, role, assigned_subsidiary, email, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, true)
                RETURNING id, username, full_name, role, assigned_subsidiary, email, is_active, last_login, created_at;
                """,
                (payload.username, hash_password(payload.password), payload.full_name,
                 payload.role, payload.assigned_subsidiary, payload.email),
            )
            new_user = cur.fetchone()
            conn.commit()
            log_audit_event(conn, admin["username"], admin["role"], "USER_CREATED", "ingestion-service", "SUCCESS",
                            metadata={"new_user": payload.username, "role": payload.role})
            return _serialize_user(new_user)
    except HTTPException:
        conn.rollback(); raise
    finally:
        conn.close()


@app.patch("/auth/users/{user_id}")
def update_user(user_id: str, payload: UpdateUserRequest, admin: dict = Depends(require_permission("users.write"))):
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user id")
    if payload.role is not None and payload.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of {ROLES}")

    fields, values = [], []
    if payload.full_name is not None: fields.append("full_name = %s"); values.append(payload.full_name)
    if payload.role is not None: fields.append("role = %s"); values.append(payload.role)
    if payload.assigned_subsidiary is not None: fields.append("assigned_subsidiary = %s"); values.append(payload.assigned_subsidiary)
    if payload.is_active is not None: fields.append("is_active = %s"); values.append(payload.is_active)
    if payload.email is not None: fields.append("email = %s"); values.append(payload.email)
    if payload.password is not None:
        if len(payload.password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        fields.append("password_hash = %s"); values.append(hash_password(payload.password))
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Guard: don't let an admin disable/demote the last active admin.
            if payload.is_active is False or (payload.role and payload.role != "ADMIN"):
                cur.execute("SELECT role, COALESCE(is_active,true) AS is_active FROM users WHERE id = %s;", (str(uid),))
                target = cur.fetchone()
                if target and target["role"] == "ADMIN":
                    cur.execute("SELECT COUNT(*)::int AS n FROM users WHERE role='ADMIN' AND COALESCE(is_active,true)=true;")
                    if cur.fetchone()["n"] <= 1:
                        raise HTTPException(status_code=400, detail="Cannot disable or demote the last active admin")

            values.append(str(uid))
            cur.execute(
                f"UPDATE users SET {', '.join(fields)} WHERE id = %s "
                "RETURNING id, username, full_name, role, assigned_subsidiary, email, "
                "COALESCE(is_active, true) AS is_active, last_login, created_at;",
                tuple(values),
            )
            updated = cur.fetchone()
            if not updated:
                raise HTTPException(status_code=404, detail="User not found")
            conn.commit()
            log_audit_event(conn, admin["username"], admin["role"], "USER_UPDATED", "ingestion-service", "SUCCESS",
                            metadata={"user_id": str(uid), "fields": [f.split(" =")[0] for f in fields]})
            return _serialize_user(updated)
    except HTTPException:
        conn.rollback(); raise
    finally:
        conn.close()


@app.delete("/auth/users/{user_id}")
def delete_user(user_id: str, admin: dict = Depends(require_permission("users.write"))):
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user id")
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT username, role FROM users WHERE id = %s;", (str(uid),))
            target = cur.fetchone()
            if not target:
                raise HTTPException(status_code=404, detail="User not found")
            if target["username"] == admin["username"]:
                raise HTTPException(status_code=400, detail="You cannot delete your own account")
            if target["role"] == "ADMIN":
                cur.execute("SELECT COUNT(*)::int AS n FROM users WHERE role='ADMIN';")
                if cur.fetchone()["n"] <= 1:
                    raise HTTPException(status_code=400, detail="Cannot delete the last admin")
            cur.execute("DELETE FROM users WHERE id = %s;", (str(uid),))
            conn.commit()
            log_audit_event(conn, admin["username"], admin["role"], "USER_DELETED", "ingestion-service", "SUCCESS",
                            metadata={"deleted_user": target["username"]})
            return {"status": "deleted", "username": target["username"]}
    except HTTPException:
        conn.rollback(); raise
    finally:
        conn.close()


# Document Upload Endpoint
@app.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    authorization: Optional[str] = Header(None)
):
    user = get_current_user(authorization)
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename required")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="File content is empty")

    idempotency_key = hashlib.sha256(contents).hexdigest()

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, s3_key, status, original_filename FROM documents WHERE idempotency_key = %s;",
                (idempotency_key,)
            )
            existing_doc = cur.fetchone()
            if existing_doc:
                log_audit_event(conn, user["username"], user["role"], "DOCUMENT_UPLOADED", "ingestion-service", "DUPLICATE_IDEMPOTENCY", document_id=str(existing_doc["id"]))
                return {
                    "id": str(existing_doc["id"]),
                    "s3_key": existing_doc["s3_key"],
                    "status": existing_doc["status"],
                    "original_filename": existing_doc["original_filename"],
                    "is_duplicate": True
                }

            doc_id = str(uuid.uuid4())
            object_name = f"{doc_id}/{file.filename}"
            s3_key = f"{MINIO_BUCKET}/{object_name}"
            source_type = determine_source_type(file.filename)

            s3_client = get_s3_client()
            s3_client.upload_fileobj(
                io.BytesIO(contents),
                MINIO_BUCKET,
                object_name
            )

            # Versioning: a new upload with the SAME filename but DIFFERENT
            # content (not a SHA duplicate) is treated as the next version and
            # links back to the most recent prior version. Original files stay
            # immutable — each version is its own object in MinIO.
            cur.execute(
                """
                SELECT id, version FROM documents
                WHERE original_filename = %s
                ORDER BY version DESC, uploaded_at DESC LIMIT 1;
                """,
                (file.filename,)
            )
            prior = cur.fetchone()
            version = (prior["version"] + 1) if prior and prior.get("version") else (2 if prior else 1)
            supersedes = str(prior["id"]) if prior else None

            cur.execute(
                """
                INSERT INTO documents (id, original_filename, s3_key, source_type, idempotency_key, status,
                                       version, supersedes_document_id, uploaded_by)
                VALUES (%s, %s, %s, %s, %s, 'uploaded', %s, %s, %s)
                RETURNING id, s3_key, status, version;
                """,
                (doc_id, file.filename, s3_key, source_type, idempotency_key,
                 version, supersedes, user["username"])
            )
            new_doc = cur.fetchone()
            conn.commit()

            log_audit_event(conn, user["username"], user["role"], "DOCUMENT_UPLOADED", "ingestion-service", "SUCCESS",
                            document_id=doc_id, metadata={"filename": file.filename, "size": len(contents),
                                                          "version": version, "supersedes": supersedes})

            return {
                "id": str(new_doc["id"]),
                "s3_key": new_doc["s3_key"],
                "status": new_doc["status"],
                "version": new_doc["version"],
                "supersedes_document_id": supersedes,
            }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Upload processing failed: {str(e)}")
    finally:
        conn.close()


@app.get("/documents")
def list_documents(
    subsidiary: Optional[str] = None,
    doc_type: Optional[str] = None,
    status_filter: Optional[str] = None,
    authorization: Optional[str] = Header(None)
):
    user = get_current_user(authorization)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            query = """
                SELECT id, original_filename, s3_key, source_type, status, doc_type, 
                       subsidiary, urgency, topic_area, flag_reason, is_duplicate, uploaded_at, updated_at
                FROM documents
                WHERE 1=1
            """
            params = []
            if subsidiary:
                query += " AND UPPER(subsidiary) = %s"
                params.append(subsidiary.upper())
            if doc_type:
                query += " AND doc_type = %s"
                params.append(doc_type)
            if status_filter:
                query += " AND status = %s::document_status_enum"
                params.append(status_filter)

            query += " ORDER BY uploaded_at DESC LIMIT 100;"
            cur.execute(query, tuple(params))
            docs = cur.fetchall()

            authorized_docs = []
            for d in docs:
                if verify_document_access(user, d.get("subsidiary")):
                    d["id"] = str(d["id"])
                    if d.get("uploaded_at"):
                        d["uploaded_at"] = d["uploaded_at"].isoformat()
                    if d.get("updated_at"):
                        d["updated_at"] = d["updated_at"].isoformat()
                    authorized_docs.append(d)

            return authorized_docs
    finally:
        conn.close()


@app.get("/documents/{document_id}")
def get_document(
    document_id: str,
    authorization: Optional[str] = Header(None)
):
    user = get_current_user(authorization)
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid document UUID format")

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.id, d.original_filename, d.s3_key, d.source_type, d.idempotency_key, 
                       d.status, d.doc_type, d.subsidiary, d.urgency, d.topic_area, d.extracted_text,
                       d.flag_reason, d.failure_reason, d.is_duplicate, d.uploaded_at, d.updated_at,
                       d.version, d.supersedes_document_id, d.uploaded_by,
                       s.mine_name, s.report_year, s.production_target_mt, s.actual_production_mt,
                       s.dispatch_mt, s.overburden_mcum
                FROM documents d
                LEFT JOIN structured_data s ON d.id = s.document_id
                WHERE d.id = %s
                ORDER BY s.actual_production_mt DESC NULLS LAST
                LIMIT 1;
                """,
                (str(doc_uuid),)
            )
            doc = cur.fetchone()
            if not doc:
                raise HTTPException(status_code=404, detail="Document not found")

            # Server-side RBAC Authorization check
            if not verify_document_access(user, doc.get("subsidiary")):
                log_audit_event(conn, user["username"], user["role"], "UNAUTHORIZED_ACCESS_ATTEMPT", "ingestion-service", "DENIED", document_id=document_id)
                raise HTTPException(status_code=403, detail=f"Forbidden: Your role '{user['role']}' is not authorized to view documents for subsidiary '{doc.get('subsidiary')}'")

            doc["id"] = str(doc["id"])
            if doc.get("supersedes_document_id"):
                doc["supersedes_document_id"] = str(doc["supersedes_document_id"])
            if doc.get("uploaded_at"):
                doc["uploaded_at"] = doc["uploaded_at"].isoformat()
            if doc.get("updated_at"):
                doc["updated_at"] = doc["updated_at"].isoformat()

            # Retrieve domain validation warnings
            cur.execute("SELECT check_type, severity, message, details FROM domain_validations WHERE document_id = %s;", (str(doc_uuid),))
            validations = cur.fetchall()
            doc["validations"] = validations or []

            # Full set of structured rows (one per mine/data-row) for this document.
            cur.execute(
                """
                SELECT mine_name, subsidiary, report_year, production_target_mt,
                       actual_production_mt, dispatch_mt, overburden_mcum, unit
                FROM structured_data WHERE document_id = %s
                ORDER BY actual_production_mt DESC NULLS LAST;
                """,
                (str(doc_uuid),)
            )
            doc["structured_records"] = cur.fetchall() or []

            log_audit_event(conn, user["username"], user["role"], "DOCUMENT_VIEWED", "ingestion-service", "SUCCESS", document_id=document_id)
            return doc
    finally:
        conn.close()


@app.get("/documents/{document_id}/lineage")
def get_document_lineage(document_id: str, authorization: Optional[str] = Header(None)):
    """Return the full version chain (oldest -> newest) for a document."""
    user = get_current_user(authorization)
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid document UUID format")

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT original_filename, subsidiary FROM documents WHERE id = %s;", (str(doc_uuid),))
            base = cur.fetchone()
            if not base:
                raise HTTPException(status_code=404, detail="Document not found")
            if not verify_document_access(user, base.get("subsidiary")):
                raise HTTPException(status_code=403, detail="Forbidden document scope")

            # All versions share the same filename; order by version.
            cur.execute(
                """
                SELECT id, version, status, uploaded_by, uploaded_at, supersedes_document_id,
                       left(idempotency_key, 12) AS sha_prefix
                FROM documents WHERE original_filename = %s
                ORDER BY version ASC, uploaded_at ASC;
                """,
                (base["original_filename"],)
            )
            chain = []
            for r in cur.fetchall():
                chain.append({
                    "id": str(r["id"]),
                    "version": r["version"],
                    "status": r["status"],
                    "uploaded_by": r.get("uploaded_by"),
                    "uploaded_at": r["uploaded_at"].isoformat() if r.get("uploaded_at") else None,
                    "supersedes_document_id": str(r["supersedes_document_id"]) if r.get("supersedes_document_id") else None,
                    "sha256_prefix": r.get("sha_prefix"),
                    "is_current": str(r["id"]) == document_id,
                })
            return {"filename": base["original_filename"], "versions": len(chain), "lineage": chain}
    finally:
        conn.close()


@app.get("/reports/{document_id}")
def get_report(
    document_id: str,
    authorization: Optional[str] = Header(None)
):
    user = get_current_user(authorization)
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid document UUID format")

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT subsidiary FROM documents WHERE id = %s;", (str(doc_uuid),))
            doc = cur.fetchone()
            if not doc:
                raise HTTPException(status_code=404, detail="Document not found")

            if not verify_document_access(user, doc.get("subsidiary")):
                log_audit_event(conn, user["username"], user["role"], "UNAUTHORIZED_ACCESS_ATTEMPT", "ingestion-service", "DENIED", document_id=document_id)
                raise HTTPException(status_code=403, detail="Forbidden document scope")

            cur.execute("SELECT id, document_id, report_text, sources, generated_at FROM reports WHERE document_id = %s ORDER BY generated_at DESC LIMIT 1;", (str(doc_uuid),))
            rep = cur.fetchone()
            if not rep:
                raise HTTPException(status_code=404, detail="Report not generated yet")

            rep["id"] = str(rep["id"])
            rep["document_id"] = str(rep["document_id"])
            if rep.get("generated_at"):
                rep["generated_at"] = rep["generated_at"].isoformat()
            return rep
    finally:
        conn.close()


@app.get("/reports/{document_id}/export")
def export_report(
    document_id: str,
    format: str = "pdf",
    authorization: Optional[str] = Header(None)
):
    """Download the generated report as a PDF or DOCX file (RBAC-scoped)."""
    from fastapi.responses import Response
    import report_export

    fmt = (format or "pdf").lower()
    if fmt not in ("pdf", "docx"):
        raise HTTPException(status_code=400, detail="format must be 'pdf' or 'docx'")

    user = get_current_user(authorization)
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid document UUID format")

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, original_filename, subsidiary, doc_type, topic_area FROM documents WHERE id = %s;",
                (str(doc_uuid),)
            )
            document = cur.fetchone()
            if not document:
                raise HTTPException(status_code=404, detail="Document not found")

            if not verify_document_access(user, document.get("subsidiary")):
                log_audit_event(conn, user["username"], user["role"], "UNAUTHORIZED_ACCESS_ATTEMPT", "ingestion-service", "DENIED", document_id=document_id)
                raise HTTPException(status_code=403, detail="Forbidden document scope")

            cur.execute(
                "SELECT report_text, sources FROM reports WHERE document_id = %s ORDER BY generated_at DESC LIMIT 1;",
                (str(doc_uuid),)
            )
            report = cur.fetchone()
            if not report:
                raise HTTPException(status_code=404, detail="Report not generated yet")

        base = (document.get("original_filename") or "report").rsplit(".", 1)[0]
        safe = re.sub(r'[^A-Za-z0-9_.-]+', "_", base)[:80] or "report"

        if fmt == "docx":
            data = report_export.render_docx(report, document)
            media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            data = report_export.render_pdf(report, document)
            media = "application/pdf"

        log_audit_event(conn, user["username"], user["role"], "REPORT_EXPORTED", "ingestion-service", "SUCCESS", document_id=document_id, metadata={"format": fmt})
        return Response(
            content=data,
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="MineIQ_{safe}.{fmt}"'}
        )
    finally:
        conn.close()


@app.get("/subsidiary-configs")
def get_subsidiary_configs():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT subsidiary_name, ingestion_method, connection_status, last_sync FROM subsidiary_source_config ORDER BY subsidiary_name ASC;")
            rows = cur.fetchall()
            for r in rows:
                if r.get("last_sync"):
                    r["last_sync"] = r["last_sync"].isoformat()
            return rows
    finally:
        conn.close()


@app.post("/documents/{document_id}/approve")
def approve_document(
    document_id: str,
    authorization: Optional[str] = Header(None)
):
    user = get_current_user(authorization)
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid document UUID format")

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE documents SET status = 'classified'::document_status_enum, updated_at = CURRENT_TIMESTAMP WHERE id = %s RETURNING id, status;", (str(doc_uuid),))
            updated = cur.fetchone()
            if not updated:
                raise HTTPException(status_code=404, detail="Document not found")
            conn.commit()

            log_audit_event(conn, user["username"], user["role"], "PARLIAMENTARY_FAST_TRACK_APPROVED", "ingestion-service", "APPROVED", document_id=document_id)
            return {"status": "approved", "document_id": document_id}
    finally:
        conn.close()



@app.post("/process/{document_id}")
async def process_document_pipeline(
    document_id: str,
    authorization: Optional[str] = Header(None)
):
    user = get_current_user(authorization)
    start_total = time.time()
    t_ocr = t_val = t_class = t_vec = 0

    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid document UUID format")

    conn = get_db_connection()
    doc = None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, s3_key, source_type, status, subsidiary FROM documents WHERE id = %s;", (str(doc_uuid),))
            doc = cur.fetchone()
        
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        s3_key = doc["s3_key"]
        source_type = doc["source_type"]

        with conn.cursor() as cur:
            cur.execute("UPDATE documents SET status = 'ocr_pending'::document_status_enum, updated_at = CURRENT_TIMESTAMP WHERE id = %s;", (str(doc_uuid),))
            conn.commit()

        # Step 1: OCR & Structured Extraction Service
        t0 = time.time()
        extracted_text = ""
        structured_data = {}
        structured_records = []
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                ocr_resp = await client.post(
                    f"{OCR_SERVICE_URL}/extract",
                    json={"document_id": document_id, "s3_key": s3_key, "source_type": source_type}
                )
                if ocr_resp.status_code == 200:
                    ocr_data = ocr_resp.json()
                    if ocr_data.get("error"):
                        raise ValueError(f"OCR service error: {ocr_data.get('error')}")
                    extracted_text = ocr_data.get("extracted_text", "")
                    structured_data = ocr_data.get("structured_data", {})
                    structured_records = ocr_data.get("structured_records") or []
                else:
                    raise ValueError(f"OCR returned status HTTP {ocr_resp.status_code}")
        except Exception as ocr_err:
            logger.error(f"OCR step failed for doc {document_id}: {str(ocr_err)}")
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE documents SET status = 'failed'::document_status_enum, failure_reason = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
                    (f"OCR failed: {str(ocr_err)}", str(doc_uuid))
                )
                conn.commit()
            return get_document(document_id, authorization)
        t_ocr = int((time.time() - t0) * 1000)

        # Persist extracted structured data into PostgreSQL. Tabular documents
        # yield one record per data row (e.g. one row per mine); narrative
        # documents yield a single record. Reprocessing is idempotent: clear
        # any prior rows for this document before re-inserting.
        records_to_store = structured_records or ([structured_data] if structured_data else [])
        records_to_store = [r for r in records_to_store if r and any(
            r.get(k) is not None for k in (
                "mine_name", "production_target_mt", "actual_production_mt",
                "dispatch_mt", "overburden_mcum",
            )
        )]
        if records_to_store:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM structured_data WHERE document_id = %s;", (str(doc_uuid),))
                for rec in records_to_store:
                    cur.execute(
                        """
                        INSERT INTO structured_data (document_id, mine_name, subsidiary, report_year, production_target_mt, actual_production_mt, dispatch_mt, overburden_mcum, raw_json)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
                        """,
                        (
                            str(doc_uuid), rec.get("mine_name"), rec.get("subsidiary"),
                            rec.get("report_year"), rec.get("production_target_mt"),
                            rec.get("actual_production_mt"), rec.get("dispatch_mt"),
                            rec.get("overburden_mcum"), json.dumps(rec)
                        )
                    )
                conn.commit()

        # Step 2: Validation Service
        t0 = time.time()
        val_status = "validated"
        is_duplicate = False
        flag_reason = None
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                val_resp = await client.post(
                    f"{VALIDATION_SERVICE_URL}/validate",
                    json={"document_id": document_id, "extracted_text": extracted_text}
                )
                if val_resp.status_code == 200:
                    val_data = val_resp.json()
                    val_status = val_data.get("status", "validated")
                    is_duplicate = val_data.get("is_duplicate", False)
                    flag_reason = val_data.get("flag_reason")
                else:
                    raise ValueError(f"Validation returned status HTTP {val_resp.status_code}")
        except Exception as val_err:
            logger.error(f"Validation step failed for doc {document_id}: {str(val_err)}")
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE documents SET status = 'failed'::document_status_enum, failure_reason = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
                    (f"Validation failed: {str(val_err)}", str(doc_uuid))
                )
                conn.commit()
            return get_document(document_id, authorization)
        t_val = int((time.time() - t0) * 1000)

        if val_status == "flagged" or is_duplicate:
            logger.info(f"Document {document_id} flagged: {flag_reason}. Stopping pipeline.")
            log_audit_event(conn, user["username"], user["role"], "DOCUMENT_PROCESSED", "ingestion-service", "FLAGGED", document_id=document_id, metadata={"reason": flag_reason})
            return get_document(document_id, authorization)

        # Step 3: Classification Service
        t0 = time.time()
        class_data = {}
        try:
            # Must exceed the classification service's own 60s Ollama budget,
            # otherwise LLM cold-start/inference overruns cause ingestion to
            # time out and mark the document failed while classification is
            # still (successfully) running downstream.
            async with httpx.AsyncClient(timeout=90.0) as client:
                class_resp = await client.post(
                    f"{CLASSIFICATION_SERVICE_URL}/classify",
                    json={"document_id": document_id, "extracted_text": extracted_text}
                )
                if class_resp.status_code == 200:
                    class_data = class_resp.json()
                else:
                    raise ValueError(f"Classification returned status HTTP {class_resp.status_code}")
        except Exception as class_err:
            logger.error(f"Classification step failed for doc {document_id}: {str(class_err)}")
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE documents SET status = 'failed'::document_status_enum, failure_reason = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
                    (f"Classification failed: {str(class_err)}", str(doc_uuid))
                )
                conn.commit()
            return get_document(document_id, authorization)
        t_class = int((time.time() - t0) * 1000)

        # Step 4: Vector RAG Indexing
        t0 = time.time()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                await client.post(
                    f"{RAG_SERVICE_URL}/index",
                    json={
                        "document_id": document_id,
                        "extracted_text": extracted_text,
                        "subsidiary": class_data.get("subsidiary", "CMPDI"),
                        "doc_type": class_data.get("doc_type", "general"),
                        "topic": class_data.get("topic_area", "general")
                    }
                )
        except Exception as rag_err:
            logger.warning(f"Vector indexing notice: {str(rag_err)}")
        t_vec = int((time.time() - t0) * 1000)

        # Step 5: RabbitMQ Publishing
        rabbitmq_payload = {
            "document_id": document_id,
            "doc_type": class_data.get("doc_type", "unclassified"),
            "subsidiary": class_data.get("subsidiary", "unknown"),
            "urgency": class_data.get("urgency", "medium"),
            "s3_key": s3_key
        }
        try:
            publish_to_rabbitmq("document.classified", rabbitmq_payload)
        except Exception as mq_err:
            logger.error(f"RabbitMQ publishing error: {str(mq_err)}")

        total_time = int((time.time() - start_total) * 1000)

        # Record System Metrics & Audit Trail
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO system_metrics (document_id, ocr_time_ms, validation_time_ms, classification_time_ms, vector_embed_time_ms, total_time_ms)
                VALUES (%s, %s, %s, %s, %s, %s);
                """,
                (str(doc_uuid), t_ocr, t_val, t_class, t_vec, total_time)
            )
            conn.commit()

        log_audit_event(conn, user["username"], user["role"], "DOCUMENT_PROCESSED", "ingestion-service", "SUCCESS", document_id=document_id, metadata={"total_time_ms": total_time})

        return get_document(document_id, authorization)
    finally:
        conn.close()


@app.get("/audit-logs")
def get_audit_logs(
    authorization: Optional[str] = Header(None)
):
    user = get_current_user(authorization)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, timestamp, user_id, user_role, action, document_id, service, result, metadata, ip_address FROM audit_logs ORDER BY timestamp DESC LIMIT 100;")
            logs = cur.fetchall()
            for l in logs:
                l["id"] = str(l["id"])
                if l.get("document_id"):
                    l["document_id"] = str(l["document_id"])
                if l.get("timestamp"):
                    l["timestamp"] = l["timestamp"].isoformat()
            return logs
    finally:
        conn.close()


@app.get("/prometheus")
def prometheus_metrics():
    """Prometheus exposition of current platform gauges (scraped by Prometheus)."""
    from fastapi.responses import Response
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            def one(sql, params=()):
                cur.execute(sql, params)
                return cur.fetchone()["v"]
            g = {
                "mineiq_documents_total": one("SELECT COUNT(*)::int v FROM documents;"),
                "mineiq_documents_processed_total": one("SELECT COUNT(*)::int v FROM documents WHERE status='classified';"),
                "mineiq_documents_failed_total": one("SELECT COUNT(*)::int v FROM documents WHERE status='failed';"),
                "mineiq_documents_flagged_total": one("SELECT COUNT(*)::int v FROM documents WHERE status='flagged';"),
                "mineiq_reports_total": one("SELECT COUNT(*)::int v FROM reports;"),
                "mineiq_structured_records_total": one("SELECT COUNT(*)::int v FROM structured_data;"),
                "mineiq_discrepancies_total": one("SELECT COUNT(*)::int v FROM domain_validations WHERE check_type='inconsistency';"),
                "mineiq_audit_events_total": one("SELECT COUNT(*)::int v FROM audit_logs;"),
                "mineiq_users_total": one("SELECT COUNT(*)::int v FROM users;"),
            }
            try:
                g["mineiq_parliamentary_questions_total"] = one("SELECT COUNT(*)::int v FROM parliamentary_questions;")
            except Exception:
                conn.rollback()
        lines = []
        for name, val in g.items():
            lines.append(f"# HELP {name} MineIQ gauge")
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {val}")
        return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
    finally:
        conn.close()


@app.get("/metrics")
def get_metrics():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*)::int as total FROM documents;")
            total_docs = cur.fetchone()["total"]

            cur.execute("SELECT COUNT(*)::int as processed FROM documents WHERE status = 'classified';")
            processed_docs = cur.fetchone()["processed"]

            cur.execute("SELECT COUNT(*)::int as flagged FROM documents WHERE status = 'flagged';")
            flagged_docs = cur.fetchone()["flagged"]

            cur.execute("SELECT COUNT(*)::int as reports FROM reports;")
            reports_cnt = cur.fetchone()["reports"]

            cur.execute("SELECT AVG(total_time_ms)::float as avg_ms FROM system_metrics;")
            avg_ms_row = cur.fetchone()
            avg_ms = avg_ms_row["avg_ms"] or 4500.0

            # Calculate ROI & Automation metrics
            automation_pct = ((processed_docs) / (total_docs + 1e-5)) * 100.0
            manual_baseline_mins = 180.0
            ai_processing_mins = avg_ms / 60000.0
            time_reduction_pct = ((manual_baseline_mins - ai_processing_mins) / manual_baseline_mins) * 100.0

            # Extraction accuracy is MEASURED, not hardcoded: run the real
            # extractor against the labeled benchmark via ocr-service. If the
            # evaluation is unavailable we report it as not evaluated rather
            # than inventing a number.
            extraction_accuracy = None
            extraction_evaluated = False
            extraction_eval = None
            try:
                with httpx.Client(timeout=10.0) as client:
                    ev = client.get(f"{OCR_SERVICE_URL}/evaluate/extraction")
                    if ev.status_code == 200:
                        ev_data = ev.json()
                        extraction_evaluated = bool(ev_data.get("evaluated"))
                        extraction_accuracy = ev_data.get("extraction_accuracy_percentage")
                        extraction_eval = {
                            "fields_correct": ev_data.get("fields_correct"),
                            "fields_total": ev_data.get("fields_total"),
                            "record_recall_pct": ev_data.get("record_recall_pct"),
                            "spurious_records": ev_data.get("spurious_records"),
                            "dataset": ev_data.get("dataset"),
                        }
            except Exception as eval_err:
                logger.warning(f"Extraction accuracy evaluation unavailable: {str(eval_err)}")

            return {
                "total_documents": total_docs,
                "processed_documents": processed_docs,
                "flagged_documents": flagged_docs,
                "reports_generated": reports_cnt,
                "automation_percentage": round(automation_pct, 1),
                "extraction_accuracy_percentage": extraction_accuracy,
                "extraction_accuracy_evaluated": extraction_evaluated,
                "extraction_accuracy_detail": extraction_eval,
                "average_processing_time_sec": round(avg_ms / 1000.0, 2),
                "time_reduction_percentage": round(time_reduction_pct, 1),
                "time_reduction_baseline_assumed": True,
                "manual_baseline_minutes": manual_baseline_mins,
                "ai_avg_minutes": round(ai_processing_mins, 2)
            }
    finally:
        conn.close()
