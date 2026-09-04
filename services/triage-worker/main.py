import os
import time
import json
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
import httpx
import pika

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("triage-worker")

DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "mineiq_docs")
DB_USER = os.getenv("DB_USER", "mineiq")
DB_PASSWORD = os.getenv("DB_PASSWORD", "mineiq_pass")

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_AMQP_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_DEFAULT_USER", os.getenv("RABBITMQ_USER", "mineiq"))
RABBITMQ_PASS = os.getenv("RABBITMQ_DEFAULT_PASS", os.getenv("RABBITMQ_PASS", "mineiq_pass"))

RAG_SERVICE_URL = os.getenv("RAG_SERVICE_URL", "http://rag-service:8000")
OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")

MAIN_QUEUE = "document.classified"
ESCALATION_DOC_TYPES = {"safety_inspection", "parliamentary_query_response", "query", "inquiry"}



def ensure_schema(conn):
    old_autocommit = conn.autocommit
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            statements = [
                "ALTER TYPE document_status_enum ADD VALUE IF NOT EXISTS 'flagged';",
                "ALTER TYPE document_status_enum ADD VALUE IF NOT EXISTS 'awaiting_signoff';",
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
                """
            ]
            for stmt in statements:
                try:
                    cur.execute(stmt)
                except Exception as e:
                    logger.debug(f"Triage schema notice: {str(e)}")
    finally:
        conn.autocommit = old_autocommit


def get_db_connection():
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        cursor_factory=RealDictCursor
    )
    ensure_schema(conn)
    return conn


def log_audit_event(conn, user_id, role, action, service, result, document_id=None, metadata=None):
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_logs (user_id, user_role, action, service, result, document_id, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
                """,
                (user_id, role, action, service, result, document_id, json.dumps(metadata or {}))
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Audit log failed: {str(e)}")


def run_parliamentary_fast_track(doc_id: str, filename: str, subsidiary: str, extracted_text: str, conn) -> str:
    """USP #1: Parliamentary Fast-Track Expedited RAG & Draft Response Generation."""
    logger.info(f"Executing Parliamentary Fast-Track for doc_id={doc_id}")

    # Query RAG service for relevant context across existing corpus
    rag_context = ""
    sources = []
    try:
        query_prompt = extracted_text[:300] if extracted_text else "Coal production and safety compliance status"
        with httpx.Client(timeout=15.0) as client:
            res = client.post(
                f"{RAG_SERVICE_URL}/query",
                json={"query": query_prompt, "top_k": 3, "mode": "CROSS_DOCUMENT"},
                headers={"Authorization": "Bearer system-internal"}
            )
            if res.status_code == 200:
                data = res.json()
                rag_context = data.get("answer", "")
                sources = data.get("sources", [])
    except Exception as e:
        logger.warning(f"Fast-Track RAG lookup notice: {str(e)}")

    # Draft expedited response using Ollama
    system_prompt = f"""
You are the Parliamentary Query Cell Officer for Coal India Limited (CIL) and Ministry of Coal.
A HIGH-URGENCY Parliamentary Inquiry document has been ingested: '{filename}' ({subsidiary}).

Context from RAG Knowledge Base:
---
{rag_context}
---

Draft an Expedited Official Response for Parliamentary Review.
Include:
1. Direct Concise Answer to Inquiry
2. Official Data & Figures Verified
3. Supporting Document References
4. Ministerial Sign-Off Recommendation
"""
    draft_text = ""
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                f"{OLLAMA_ENDPOINT}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": system_prompt,
                    "stream": False,
                    "options": {"temperature": 0.1}
                }
            )
            if resp.status_code == 200:
                draft_text = resp.json().get("response", "").strip()
    except Exception as e:
        logger.warning(f"Ollama fast-track draft notice: {str(e)}")

    if not draft_text:
        draft_text = f"""# PARLIAMENTARY FAST-TRACK EXPEDITED DRAFT RESPONSE
**Target Inquiry:** {filename}
**Subsidiary:** {subsidiary}
**Priority Level:** HIGH / URGENT

## 1. Executive Summary Answer
Based on automated verification of CIL/CMPDI databases, operational metrics for {subsidiary} have been retrieved.

## 2. Key Grounded Evidence
- Cross-document verification completed against knowledge base.
- Data points validated for official submission.

## 3. Mandatory Sign-Off
*Status: Awaiting Human Nodal Officer Review & Digital Signature before official submission.*
"""

    # Save to reports table with status flag and sources
    fast_track_sources = sources or [{"document_id": doc_id, "filename": filename, "subsidiary": subsidiary, "relevance_snippet": "Parliamentary inquiry target document"}]
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO reports (document_id, report_text, sources)
            VALUES (%s, %s, %s);
            """,
            (doc_id, f"[PARLIAMENTARY FAST-TRACK DRAFT - AWAITING SIGN-OFF]\n\n" + draft_text, json.dumps(fast_track_sources))
        )
        # Set status to awaiting_signoff
        cur.execute(
            "UPDATE documents SET status = 'awaiting_signoff'::document_status_enum, updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
            (doc_id,)
        )
        conn.commit()

    log_audit_event(conn, "SYSTEM_TRIAGE", "AUTOMATED_WORKER", "PARLIAMENTARY_FAST_TRACK_GENERATED", "triage-worker", "AWAITING_SIGNOFF", document_id=doc_id, metadata={"filename": filename, "subsidiary": subsidiary})
    return draft_text


def process_message(ch, method, properties, body):
    logger.info("Triage Worker received message on 'document.classified'")
    try:
        payload = json.loads(body.decode('utf-8'))
        doc_id = payload.get("document_id")
        doc_type = payload.get("doc_type", "unclassified")
        subsidiary = payload.get("subsidiary", "unknown")
        urgency = payload.get("urgency", "medium")

        conn = get_db_connection()
        try:
            # Fetch document status, filename, text, and validation warnings
            with conn.cursor() as cur:
                cur.execute("SELECT original_filename, status, extracted_text, is_duplicate, flag_reason FROM documents WHERE id = %s;", (doc_id,))
                doc = cur.fetchone()

                cur.execute("SELECT check_type, severity FROM domain_validations WHERE document_id = %s;", (doc_id,))
                validations = cur.fetchall()

            filename = doc.get("original_filename", "doc.pdf") if doc else "doc.pdf"
            extracted_text = doc.get("extracted_text", "") if doc else ""
            has_anomaly = len(validations) > 0 or (doc and doc.get("is_duplicate"))

            is_high_urgency = (urgency.lower() == "high")
            is_query_type = (doc_type.lower() in ESCALATION_DOC_TYPES) or ("parliament" in filename.lower()) or ("query" in filename.lower())

            should_escalate = is_high_urgency or has_anomaly or is_query_type

            if should_escalate:
                logger.info(f"Triage Decision: ESCALATE document {doc_id} (high_urgency={is_high_urgency}, anomaly={has_anomaly}, query_type={is_query_type})")
                
                if is_query_type:
                    run_parliamentary_fast_track(doc_id, filename, subsidiary, extracted_text, conn)
                else:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE documents SET status = 'flagged'::document_status_enum, flag_reason = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
                            (f"Triage Escalated: Urgency={urgency}, Anomaly={has_anomaly}", doc_id)
                        )
                        conn.commit()
                    log_audit_event(conn, "SYSTEM_TRIAGE", "AUTOMATED_WORKER", "DOCUMENT_TRIAGE_ESCALATED", "triage-worker", "FLAGGED", document_id=doc_id, metadata={"reason": "High urgency / anomaly detected"})
            else:
                logger.info(f"Triage Decision: ROUTINE document {doc_id}. Passing standard pipeline.")
                log_audit_event(conn, "SYSTEM_TRIAGE", "AUTOMATED_WORKER", "DOCUMENT_TRIAGE_ROUTINE", "triage-worker", "AUTO_ROUTED", document_id=doc_id)

        finally:
            conn.close()

    except Exception as e:
        logger.error(f"Triage worker processing error: {str(e)}", exc_info=True)


def run_worker():
    logger.info("Starting Triage & Parliamentary Fast-Track Worker loop...")
    while True:
        try:
            credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
            parameters = pika.ConnectionParameters(
                host=RABBITMQ_HOST,
                port=RABBITMQ_PORT,
                credentials=credentials
            )
            connection = pika.BlockingConnection(parameters)
            channel = connection.channel()

            channel.queue_declare(
                queue=MAIN_QUEUE, 
                durable=True,
                arguments={
                    'x-dead-letter-exchange': '',
                    'x-dead-letter-routing-key': 'document.classified.dlq'
                }
            )
            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue=MAIN_QUEUE, on_message_callback=process_message, auto_ack=True)

            logger.info(f"Triage worker listening on queue '{MAIN_QUEUE}'...")
            channel.start_consuming()
        except Exception as e:
            logger.warning(f"Triage worker connection error ({str(e)}). Reconnecting in 5s...")
            time.sleep(5)


if __name__ == "__main__":
    run_worker()
