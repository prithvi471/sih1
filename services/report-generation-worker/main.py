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


def _num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _fmt(v):
    return "—" if v is None else (f"{v:.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v))


def _build_tables(rows):
    """Build Annexure-style production & off-take tables from structured rows.
    Numbers come straight from the extracted data (no LLM), so figures are exact."""
    prod_lines = ["| Area / Unit | Target (MT) | Actual (MT) | Achievement % | Variance (MT) |",
                  "| --- | --- | --- | --- | --- |"]
    disp_lines = ["| Area / Unit | Dispatch (MT) | Overburden (MCuM) |",
                  "| --- | --- | --- |"]
    tt = ta = td = 0.0
    have_t = have_a = have_d = False
    for r in rows:
        name = r.get("mine_name") or "—"
        t, a = _num(r.get("production_target_mt")), _num(r.get("actual_production_mt"))
        d, ob = _num(r.get("dispatch_mt")), _num(r.get("overburden_mcum"))
        ach = f"{(a / t * 100):.1f}%" if (t and a is not None and t != 0) else "—"
        var = _fmt(round(a - t, 2)) if (t is not None and a is not None) else "—"
        prod_lines.append(f"| {name} | {_fmt(t)} | {_fmt(a)} | {ach} | {var} |")
        disp_lines.append(f"| {name} | {_fmt(d)} | {_fmt(ob)} |")
        if t is not None: tt += t; have_t = True
        if a is not None: ta += a; have_a = True
        if d is not None: td += d; have_d = True
    tot_ach = f"{(ta / tt * 100):.1f}%" if (have_t and tt != 0) else "—"
    tot_var = _fmt(round(ta - tt, 2)) if (have_t and have_a) else "—"
    prod_lines.append(f"| **Total** | **{_fmt(round(tt,2)) if have_t else '—'}** | **{_fmt(round(ta,2)) if have_a else '—'}** | **{tot_ach}** | **{tot_var}** |")
    disp_lines.append(f"| **Total** | **{_fmt(round(td,2)) if have_d else '—'}** | | ")
    totals = {"target": round(tt, 2) if have_t else None, "actual": round(ta, 2) if have_a else None,
              "dispatch": round(td, 2) if have_d else None, "achievement": tot_ach}
    return "\n".join(prod_lines), "\n".join(disp_lines), totals


def _summary_via_ollama(period, rows, totals, extracted_text):
    """LLM writes ONLY the narrative summary + observations from the given figures."""
    facts = "; ".join(
        f"{(r.get('mine_name') or '—')}: target={r.get('production_target_mt')}, "
        f"actual={r.get('actual_production_mt')}, dispatch={r.get('dispatch_mt')}"
        for r in rows
    ) or extracted_text[:1500]
    prompt = f"""You are drafting the narrative for a coal production & off-take performance report.
Period: {period}. Overall target: {totals.get('target')} MT, actual: {totals.get('actual')} MT, achievement: {totals.get('achievement')}, total dispatch: {totals.get('dispatch')} MT.
Per-unit figures: {facts}

Write:
SUMMARY: 3-4 sentences on production vs target, overall achievement, notable shortfalls/surpluses, and dispatch.
OBSERVATIONS: 3-5 short bullet points on the key variances.

STRICT RULES:
- Use ONLY the figures given above. Do NOT invent numbers.
- Do NOT include any company letterhead, official names, signatories, addresses, stock-exchange references, or registration numbers.
- Refer to the reporting area only as "—".
- Output plain text with a 'SUMMARY:' line then an 'OBSERVATIONS:' section with '- ' bullets. No preamble."""
    try:
        with httpx.Client(timeout=90.0) as client:
            resp = client.post(f"{OLLAMA_ENDPOINT}/api/generate",
                               json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
                                     "options": {"temperature": 0.1}})
            if resp.status_code == 200:
                txt = resp.json().get("response", "").strip()
                if txt:
                    return txt
    except Exception as e:
        logger.warning(f"Ollama summary call failed: {str(e)}")
    # Deterministic fallback (no LLM): summary straight from the numbers.
    ta, tt = totals.get("actual"), totals.get("target")
    gap = (round(tt - ta, 2) if (ta is not None and tt is not None) else None)
    return (
        f"SUMMARY: For the period {period}, actual production was {ta} MT against a target of {tt} MT "
        f"(achievement {totals.get('achievement')}). Total dispatch was {totals.get('dispatch')} MT.\n"
        "OBSERVATIONS:\n"
        + (f"- Production {'shortfall' if (gap or 0) > 0 else 'surplus'} of {abs(gap)} MT vs target.\n" if gap is not None else "")
        + "- Review unit-level variances against operational plans."
    )


def draft_production_report(document_id, subsidiary, rows, extracted_text) -> str:
    """Assemble an Annexure-style Production & Off-take Performance report.
    No official CIL letterhead / names / signatories; area shown as '—'."""
    period = "—"
    years = [r.get("report_year") for r in rows if r.get("report_year")]
    if years:
        period = str(max(years))

    if rows:
        prod_tbl, disp_tbl, totals = _build_tables(rows)
        narrative = _summary_via_ollama(period, rows, totals, extracted_text)
    else:
        prod_tbl = disp_tbl = "_No structured production figures were extracted from this document._"
        totals = {}
        narrative = _summary_via_ollama(period, [], totals, extracted_text)

    # Split narrative into summary + observations.
    summary, observations = narrative, ""
    up = narrative.upper()
    if "OBSERVATIONS" in up:
        idx = up.index("OBSERVATIONS")
        summary = narrative[:idx].replace("SUMMARY:", "").replace("Summary:", "").strip()
        observations = narrative[idx:].split(":", 1)[-1].strip()
    else:
        summary = narrative.replace("SUMMARY:", "").strip()

    obs_block = observations if observations else "- See tables above for unit-level figures."

    return f"""# Provisional Production & Off-take Performance Report

**Period:** {period}   |   **Area / Office:** —   |   **Status:** PROVISIONAL (AI-generated draft)

## Summary
{summary}

## 1. Coal Production (Figures in MT)
{prod_tbl}

## 2. Off-take / Dispatch (Figures in MT)
{disp_tbl}

## 3. Key Observations
{obs_block}

**Note:** Provisional figures compiled by the MineIQ pipeline for internal review. This is an AI-generated draft, NOT an official Coal India Limited communication, and must be validated and approved before any use."""


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
            structured_rows = []
            with conn.cursor() as cur:
                cur.execute("SELECT original_filename, extracted_text FROM documents WHERE id = %s;", (doc_id,))
                row = cur.fetchone()
                if row:
                    filename = row.get("original_filename") or filename
                    if row.get("extracted_text"):
                        extracted_text = row["extracted_text"]
                cur.execute(
                    """
                    SELECT mine_name, report_year, production_target_mt, actual_production_mt,
                           dispatch_mt, overburden_mcum
                    FROM structured_data WHERE document_id = %s
                    ORDER BY actual_production_mt DESC NULLS LAST;
                    """,
                    (doc_id,)
                )
                structured_rows = [dict(r) for r in cur.fetchall()]

            # Draft the Annexure-style production & off-take report
            report_text = draft_production_report(doc_id, subsidiary, structured_rows, extracted_text)

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
