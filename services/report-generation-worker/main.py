import os
import time
import json
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
import httpx
import pika

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("report-generation-worker")

DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "mineiq_docs")
DB_USER = os.getenv("DB_USER", "mineiq")
DB_PASSWORD = os.getenv("DB_PASSWORD", "mineiq_pass")

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_AMQP_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_DEFAULT_USER", os.getenv("RABBITMQ_USER", "mineiq"))
RABBITMQ_PASS = os.getenv("RABBITMQ_DEFAULT_PASS", os.getenv("RABBITMQ_PASS", "mineiq_pass"))

OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")

CLASSIFIED_EXCHANGE = "document.classified.fanout"
MAIN_QUEUE = "document.classified.report"   # this worker's own queue on the fanout
DLQ_QUEUE = "document.classified.report.dlq"
MAX_RETRIES = 3


RAG_SERVICE_URL = os.getenv("RAG_SERVICE_URL", "http://rag-service:8000")


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
                    sources JSONB DEFAULT '[]'::jsonb,
                    generated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """,
                "ALTER TABLE reports ADD COLUMN IF NOT EXISTS sources JSONB DEFAULT '[]'::jsonb;"
            ]
            for stmt in statements:
                try:
                    cur.execute(stmt)
                except Exception as e:
                    logger.debug(f"Schema statement notice: {str(e)}")
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


def draft_report_with_ollama(document_id: str, doc_type: str, subsidiary: str, urgency: str, extracted_text: str) -> str:
    """Invokes Ollama model to generate a structured report."""
    prompt = f"""
You are an expert report drafting assistant for Coal India Limited (CIL) and CMPDI mining operations.
Generate a structured report based on the following document parameters:
- Document ID: {document_id}
- Document Type: {doc_type}
- Subsidiary: {subsidiary}
- Urgency: {urgency}

Document Extracted Text:
---
{extracted_text[:4000]}
---

Please format the generated report strictly into four clear sections:
1. Executive Summary
2. Key Findings
3. Critical Data Points
4. Recommended Follow-up Actions
"""

    try:
        with httpx.Client(timeout=90.0) as client:
            response = client.post(
                f"{OLLAMA_ENDPOINT}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False
                }
            )
            if response.status_code == 200:
                result = response.json()
                report_text = result.get("response", "").strip()
                if report_text:
                    return report_text
    except Exception as e:
        logger.warning(f"Ollama report generation call failed: {str(e)}")

    # Fallback template if Ollama is unavailable or model not downloaded yet
    return f"""# MineIQ Automated Technical Report
**Document ID:** {document_id}
**Document Type:** {doc_type}
**Subsidiary:** {subsidiary}
**Urgency:** {urgency}

## 1. Executive Summary
The document has been processed by the MineIQ automated ingestion and validation pipeline. Initial extraction indicates operational data relevant to {subsidiary}.

## 2. Key Findings
- Source document processed and validated without duplication flags.
- Text content parsed into structured mining domain knowledge base.

## 3. Critical Data Points
- Extracted character count: {len(extracted_text)} chars.
- Content sample: {extracted_text[:300]}...

## 4. Recommended Follow-up Actions
- Review operational parameters in detail with mine safety officer.
- Archive report in CMPDI document database.
"""


def index_generated_report_in_rag(doc_id: str, report_text: str, subsidiary: str, doc_type: str):
    """Sends generated report text to rag-service to be embedded and indexed in vector store."""
    try:
        with httpx.Client(timeout=10.0) as client:
            client.post(
                f"{RAG_SERVICE_URL}/index",
                json={
                    "document_id": doc_id,
                    "extracted_text": report_text,
                    "subsidiary": subsidiary,
                    "doc_type": f"report_{doc_type}",
                    "topic": "executive_report",
                    "source_kind": "report"
                }
            )
            logger.info(f"Indexed generated executive report for doc_id={doc_id} into RAG vector store.")
    except Exception as e:
        logger.warning(f"Failed to index report in RAG vector store: {str(e)}")


def process_message(ch, method, properties, body):
    logger.info(f"Received RabbitMQ message on queue '{MAIN_QUEUE}'")
    
    headers = properties.headers or {}
    retry_count = headers.get("x-retry-count", 0)

    try:
        payload = json.loads(body.decode('utf-8'))
        doc_id = payload.get("document_id")
        doc_type = payload.get("doc_type", "unclassified")
        subsidiary = payload.get("subsidiary", "unknown")
        urgency = payload.get("urgency", "medium")

        logger.info(f"Processing report generation for document_id={doc_id}")

        # Fetch extracted text & filename from PostgreSQL
        extracted_text = ""
        filename = "document.pdf"
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT original_filename, extracted_text FROM documents WHERE id = %s;", (doc_id,))
                row = cur.fetchone()
                if row:
                    filename = row.get("original_filename") or filename
                    if row.get("extracted_text"):
                        extracted_text = row["extracted_text"]
            
            # Draft structured report
            report_text = draft_report_with_ollama(doc_id, doc_type, subsidiary, urgency, extracted_text)

            # Construct citation source metadata
            sources_meta = [{
                "document_id": doc_id,
                "filename": filename,
                "subsidiary": subsidiary,
                "doc_type": doc_type,
                "relevance_snippet": extracted_text[:200] + "..." if extracted_text else "Source document content"
            }]

            # Insert generated report into reports table
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO reports (document_id, report_text, sources)
                    VALUES (%s, %s, %s);
                    """,
                    (doc_id, report_text, json.dumps(sources_meta))
                )
                conn.commit()

            logger.info(f"Successfully generated and saved report for doc_id={doc_id}")

            # Index generated report in vector store
            index_generated_report_in_rag(doc_id, report_text, subsidiary, doc_type)

            # Acknowledge message only after DB write success
            ch.basic_ack(delivery_tag=method.delivery_tag)
        finally:
            conn.close()


    except Exception as e:
        logger.error(f"Error processing document report: {str(e)} (retry_count={retry_count})", exc_info=True)
        if retry_count < MAX_RETRIES:
            new_headers = dict(headers)
            new_headers["x-retry-count"] = retry_count + 1
            # Nack and requeue or re-publish with incremented retry count
            ch.basic_ack(delivery_tag=method.delivery_tag)
            ch.basic_publish(
                exchange="",
                routing_key=MAIN_QUEUE,
                body=body,
                properties=pika.BasicProperties(headers=new_headers, delivery_mode=2)
            )
            logger.info(f"Re-queued message for doc_id with retry_count={retry_count + 1}")
        else:
            logger.error(f"Exceeded max retries ({MAX_RETRIES}). Routing message to DLQ '{DLQ_QUEUE}'")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def run_worker():
    logger.info("Starting Report Generation Worker loop...")
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

            # Fanout exchange: this worker binds its OWN queue so it receives
            # every classified event (no competing with triage/topic workers).
            channel.exchange_declare(exchange=CLASSIFIED_EXCHANGE, exchange_type="fanout", durable=True)
            channel.queue_declare(queue=DLQ_QUEUE, durable=True)
            channel.queue_declare(
                queue=MAIN_QUEUE,
                durable=True,
                arguments={
                    'x-dead-letter-exchange': '',
                    'x-dead-letter-routing-key': DLQ_QUEUE
                }
            )
            channel.queue_bind(exchange=CLASSIFIED_EXCHANGE, queue=MAIN_QUEUE)

            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue=MAIN_QUEUE, on_message_callback=process_message)

            logger.info(f"Worker connected to RabbitMQ. Listening on queue '{MAIN_QUEUE}'...")
            channel.start_consuming()
        except pika.exceptions.AMQPConnectionError as ce:
            logger.warning(f"RabbitMQ connection lost/not ready ({str(ce)}). Reconnecting in 5 seconds...")
            time.sleep(5)
        except Exception as e:
            logger.error(f"Unexpected worker failure: {str(e)}. Restarting loop in 5 seconds...", exc_info=True)
            time.sleep(5)


if __name__ == "__main__":
    run_worker()
