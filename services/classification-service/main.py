import os
import re
import json
import hashlib
import logging
from typing import Optional
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
# pyrefly: ignore [missing-import]
import redis
import httpx
import pika

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("classification-service")

app = FastAPI(
    title="MineIQ Classification Agent",
    description="Tags validated documents by doc_type, subsidiary, topic_area, and urgency using Ollama (Llama 3.1) and Redis."
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

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))  # 1 hour
# RabbitMQ configuration
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_AMQP_PORT", "5672"))
RABBITMQ_USER = os.getenv(
    "RABBITMQ_DEFAULT_USER",
    os.getenv("RABBITMQ_USER", "mineiq")
)
RABBITMQ_PASS = os.getenv(
    "RABBITMQ_DEFAULT_PASS",
    os.getenv("RABBITMQ_PASS", "mineiq_pass")
)

CLASSIFIED_QUEUE = "document.classified"

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
                """
            ]
            for stmt in statements:
                try:
                    cur.execute(stmt)
                except Exception as e:
                    logger.debug(f"Schema statement notice: {str(e)}")
    finally:
        conn.autocommit = old_autocommit



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
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database connection error: {str(e)}"
        )



def get_redis_client():
    try:
        return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
    except Exception as e:
        logger.warning(f"Redis connection warning: {str(e)}")
        return None


import uuid

class ClassifyRequest(BaseModel):
    document_id: uuid.UUID
    extracted_text: str


class ClassifyResponse(BaseModel):
    document_id: uuid.UUID
    doc_type: str
    subsidiary: str
    topic_area: str
    urgency: str
    cached: bool


def clean_and_parse_json(text_content: str) -> Optional[dict]:
    """Helper to extract and parse JSON defensively from LLM text output."""
    if not text_content:
        return None
    
    # Strip markdown code blocks ```json ... ```
    cleaned = re.sub(r"^```(?:json)?\s*", "", text_content.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    
    # Try direct parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    
    # Match JSON object structure {...}
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


async def query_ollama_llm(extracted_text: str, strict_mode: bool = False) -> Optional[dict]:
    """Queries Ollama endpoint running Llama 3.1 to classify text content."""
    prompt_snippet = extracted_text[:3000]
    
    system_instruction = (
        "You are an expert AI document classifier for Coal India Limited (CIL) and CMPDI mining operations.\n"
        "Analyze the provided document text and return ONLY a valid, single JSON object with exact keys: "
        "\"doc_type\", \"subsidiary\", \"topic_area\", \"urgency\". Do NOT include markdown fences, preambles, or explanations."
    )
    if strict_mode:
        system_instruction += " CRITICAL: Output ONLY raw JSON matching schema {\"doc_type\": \"...\", \"subsidiary\": \"...\", \"topic_area\": \"...\", \"urgency\": \"...\"}."

    user_prompt = f"{system_instruction}\n\nDocument Text:\n---\n{prompt_snippet}\n---"

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{OLLAMA_ENDPOINT}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": user_prompt,
                    "stream": False,
                    "format": "json"
                }
            )
            if response.status_code == 200:
                res_data = response.json()
                raw_response = res_data.get("response", "")
                parsed = clean_and_parse_json(raw_response)
                if parsed:
                    return parsed
                logger.warning(f"Failed to parse JSON from Ollama output: {raw_response[:200]}")
    except Exception as e:
        logger.error(f"Ollama API request failed: {str(e)}")
    
    return None

def publish_classified_event(
    document_id: str,
    doc_type: str,
    subsidiary: str,
    topic_area: str,
    urgency: str
):
    """Publish a classified document event to RabbitMQ."""

    payload = {
        "document_id": document_id,
        "doc_type": doc_type,
        "subsidiary": subsidiary,
        "topic_area": topic_area,
        "urgency": urgency
    }

    credentials = pika.PlainCredentials(
        RABBITMQ_USER,
        RABBITMQ_PASS
    )

    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        credentials=credentials
    )

    connection = None

    try:
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()

        # Make sure the queue exists.
        channel.queue_declare(
            queue="document.classified.dlq",
            durable=True
        )
        channel.queue_declare(
            queue=CLASSIFIED_QUEUE,
            durable=True,
            arguments={
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": "document.classified.dlq"
            }
        )

        channel.basic_publish(
            exchange="",
            routing_key=CLASSIFIED_QUEUE,
            body=json.dumps(payload),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2
            )
        )

        logger.info(
            f"Published classified event for document_id={document_id} "
            f"to queue '{CLASSIFIED_QUEUE}'"
        )

    finally:
        if connection and connection.is_open:
            connection.close()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/classify", response_model=ClassifyResponse)
async def classify_document(payload: ClassifyRequest):
    logger.info(f"Classify request for document_id={payload.document_id}, text_len={len(payload.extracted_text)}")
    
    extracted_text = payload.extracted_text or ""
    # Compute SHA-256 cache key of first ~500 chars
    text_sample = extracted_text[:500]
    cache_hash = hashlib.sha256(text_sample.encode('utf-8')).hexdigest()
    cache_key = f"doc_class:{cache_hash}"

    r = get_redis_client()
    cached_data = None
    is_cached = False

    # 1. Check Redis Cache
    if r:
        try:
            val = r.get(cache_key)
            if val:
                cached_data = json.loads(val)
                is_cached = True
                logger.info(f"Redis cache hit for key={cache_key}")
        except Exception as re_err:
            logger.warning(f"Redis lookup error: {str(re_err)}")

    result = None
    if is_cached and cached_data:
        result = cached_data
    else:
        # 2. Query Ollama LLM
        result = await query_ollama_llm(extracted_text, strict_mode=False)
        # If first attempt failed, retry once with strict mode prompt
        if not result:
            logger.info("First Ollama attempt failed, retrying with strict prompt...")
            result = await query_ollama_llm(extracted_text, strict_mode=True)
        
        # Fallback if Ollama model fails or is offline
        if not result:
            logger.warning("Ollama LLM classification unavailable/failed, using unclassified fallback")
            result = {
                "doc_type": "unclassified",
                "subsidiary": "unknown",
                "topic_area": "general",
                "urgency": "medium"
            }
        
        # Store in Redis Cache with TTL
        if r:
            try:
                r.setex(cache_key, CACHE_TTL, json.dumps(result))
            except Exception as re_err:
                logger.warning(f"Failed to set Redis cache: {str(re_err)}")

    # Extract required fields with safe fallbacks
    doc_type = str(result.get("doc_type", "unclassified"))
    subsidiary = str(result.get("subsidiary", "unknown"))
    topic_area = str(result.get("topic_area", "general"))
    urgency = str(result.get("urgency", "medium")).lower()

    if urgency not in ["low", "medium", "high"]:
        urgency = "medium"

    # 3. Update PostgreSQL documents table
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE documents 
                SET doc_type = %s,
                    subsidiary = %s,
                    topic_area = %s,
                    urgency = %s,
                    status = 'classified'::document_status_enum,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
                """,
                (
                    doc_type,
                    subsidiary,
                    topic_area,
                    urgency,
                    str(payload.document_id)
                )
            )
            conn.commit()

            # Note: the classified event is published by the ingestion
            # orchestrator (single publisher) to the fanout exchange, so this
            # service no longer publishes — avoids duplicate events and the
            # earlier "publish failed -> 503" pipeline break.

            return ClassifyResponse(
                document_id=payload.document_id,
                doc_type=doc_type,
                subsidiary=subsidiary,
                topic_area=topic_area,
                urgency=urgency,
                cached=is_cached
            )
    except Exception as db_err:
        conn.rollback()
        logger.error(f"Postgres update failed for {payload.document_id}: {str(db_err)}")
        raise HTTPException(
            status_code=500,
            detail=f"Postgres update failed: {str(db_err)}"
        )
    finally:
        conn.close()
