import os
import time
import json
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
import httpx
import pika
from sklearn.feature_extraction.text import TfidfVectorizer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("topic-modeling-worker")

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

CLASSIFIED_EXCHANGE = "document.classified.fanout"
MAIN_QUEUE = "document.classified.topic"   # own queue on the fanout


def ensure_schema(conn):
    old_autocommit = conn.autocommit
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS topics (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
                    topics TEXT[] DEFAULT '{}',
                    keywords TEXT[] DEFAULT '{}',
                    generated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
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


def extract_keywords_tfidf(text: str, top_n: int = 8) -> list:
    """Extracts top N keywords using TF-IDF."""
    if not text or len(text.strip()) < 20:
        return ["mining", "operational", "report"]
    try:
        vectorizer = TfidfVectorizer(stop_words='english', max_features=50)
        tfidf_matrix = vectorizer.fit_transform([text])
        feature_names = vectorizer.get_feature_names_out()
        scores = tfidf_matrix.toarray()[0]
        keyword_scores = sorted(zip(feature_names, scores), key=lambda x: x[1], reverse=True)
        return [k for k, s in keyword_scores[:top_n]]
    except Exception as e:
        logger.warning(f"TF-IDF keyword extraction error: {str(e)}")
        return ["coal", "production", "safety", "dispatch"]


def extract_topics(doc_type: str, text: str, keywords: list) -> list:
    """Categorizes document text into domain topic clusters."""
    topics = []
    text_lower = text.lower()
    
    if "production" in text_lower or "target" in text_lower or "mt" in text_lower:
        topics.append("Coal Production & Yield")
    if "overburden" in text_lower or "mcum" in text_lower or "stripping" in text_lower:
        topics.append("Overburden Removal & Excavation")
    if "safety" in text_lower or "inspection" in text_lower or "compliance" in text_lower:
        topics.append("Mine Safety & Environmental Compliance")
    if "dispatch" in text_lower or "offtake" in text_lower or "rake" in text_lower or "transport" in text_lower:
        topics.append("Coal Dispatch & Logistics")
    if "survey" in text_lower or "geological" in text_lower or "borehole" in text_lower or "seam" in text_lower:
        topics.append("Geological Survey & Reserves")

    if not topics:
        topics = ["General Operations & Administration"]

    return topics


def process_message(ch, method, properties, body):
    logger.info("Topic Modeling Worker received message on 'document.classified'")
    try:
        payload = json.loads(body.decode('utf-8'))
        doc_id = payload.get("document_id")
        doc_type = payload.get("doc_type", "unclassified")
        subsidiary = payload.get("subsidiary", "unknown")

        conn = get_db_connection()
        try:
            extracted_text = ""
            with conn.cursor() as cur:
                cur.execute("SELECT extracted_text FROM documents WHERE id = %s;", (doc_id,))
                row = cur.fetchone()
                if row and row.get("extracted_text"):
                    extracted_text = row["extracted_text"]

            keywords = extract_keywords_tfidf(extracted_text)
            topics = extract_topics(doc_type, extracted_text, keywords)

            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO topics (document_id, topics, keywords)
                    VALUES (%s, %s, %s);
                    """,
                    (doc_id, topics, keywords)
                )
                cur.execute(
                    "UPDATE documents SET topic_area = %s WHERE id = %s;",
                    (topics[0], doc_id)
                )
                conn.commit()

            logger.info(f"Saved topics={topics} and keywords={keywords} for doc_id={doc_id}")

            # Index topic modeling output into RAG vector store
            try:
                topic_summary = f"Document ID {doc_id} ({subsidiary}). Primary Topics: {', '.join(topics)}. Key Terminology: {', '.join(keywords)}."
                with httpx.Client(timeout=10.0) as client:
                    client.post(
                        f"{RAG_SERVICE_URL}/index",
                        json={
                            "document_id": doc_id,
                            "extracted_text": topic_summary,
                            "subsidiary": subsidiary,
                            "doc_type": f"topic_{doc_type}",
                            "topic": topics[0],
                            "source_kind": "topic"
                        }
                    )
            except Exception as rag_err:
                logger.warning(f"RAG indexing notice for topic modeling: {str(rag_err)}")

        finally:
            conn.close()

    except Exception as e:
        logger.error(f"Topic modeling failed: {str(e)}", exc_info=True)


def run_worker():
    logger.info("Starting Topic Modeling Worker loop...")
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

            channel.exchange_declare(exchange=CLASSIFIED_EXCHANGE, exchange_type="fanout", durable=True)
            channel.queue_declare(queue=MAIN_QUEUE, durable=True)
            channel.queue_bind(exchange=CLASSIFIED_EXCHANGE, queue=MAIN_QUEUE)
            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue=MAIN_QUEUE, on_message_callback=process_message, auto_ack=True)

            logger.info(f"Topic modeling worker listening on queue '{MAIN_QUEUE}'...")
            channel.start_consuming()
        except Exception as e:
            logger.warning(f"Topic worker connection error ({str(e)}). Reconnecting in 5s...")
            time.sleep(5)


if __name__ == "__main__":
    run_worker()
