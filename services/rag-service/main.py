import os
import json
import logging
import math
import httpx
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Header, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import numpy as np
import sys

# Try importing sentence_transformers for dense embeddings
try:
    from sentence_transformers import SentenceTransformer
    embedder = SentenceTransformer('all-MiniLM-L6-v2')
    logger_msg = "SentenceTransformer ('all-MiniLM-L6-v2') initialized successfully."
except Exception as e:
    embedder = None
    logger_msg = f"SentenceTransformer not available ({str(e)}). Falling back to TF-IDF vector similarity."

# Add parent directory for shared auth module
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from auth import get_current_user, verify_document_access, log_audit_event

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rag-service")
logger.info(logger_msg)

app = FastAPI(
    title="MineIQ Secure RAG & Vector Retrieval Service",
    description="Dense vector indexing and access-controlled grounded RAG query engine for CMPDI/CIL."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "mineiq_docs")
DB_USER = os.getenv("DB_USER", "mineiq")
DB_PASSWORD = os.getenv("DB_PASSWORD", "mineiq_pass")

OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")


def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        cursor_factory=RealDictCursor
    )


# ---------------------------------------------------------------------------
# Qdrant: the persistent vector store (primary). Postgres vector_chunks is kept
# as a dual-write fallback so retrieval still works if Qdrant is unavailable.
# ---------------------------------------------------------------------------
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = "mineiq_documents"
EMBED_DIM = 384

_qclient = None
_qdrant_ready = False


def get_qdrant():
    global _qclient, _qdrant_ready
    if _qclient is not None:
        return _qclient
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.http import models as qm
        client = QdrantClient(url=QDRANT_URL, timeout=10.0)
        existing = [c.name for c in client.get_collections().collections]
        if QDRANT_COLLECTION not in existing:
            client.create_collection(
                collection_name=QDRANT_COLLECTION,
                vectors_config=qm.VectorParams(size=EMBED_DIM, distance=qm.Distance.COSINE),
            )
            logger.info(f"Created Qdrant collection '{QDRANT_COLLECTION}'.")
        _qclient = client
        _qdrant_ready = True
        logger.info("Qdrant vector store connected.")
    except Exception as e:
        _qdrant_ready = False
        logger.warning(f"Qdrant unavailable, falling back to Postgres vectors: {e}")
    return _qclient


def qdrant_index(document_id, doc_type, chunks_with_vecs, subsidiary, topic):
    """Replace this document's points (for the given doc_type) then upsert fresh ones."""
    import uuid as _uuid
    client = get_qdrant()
    if not client:
        return 0
    from qdrant_client.http import models as qm
    flt = qm.Filter(must=[
        qm.FieldCondition(key="document_id", match=qm.MatchValue(value=str(document_id))),
        qm.FieldCondition(key="doc_type", match=qm.MatchValue(value=doc_type)),
    ])
    try:
        client.delete(collection_name=QDRANT_COLLECTION, points_selector=qm.FilterSelector(filter=flt))
        points = []
        for idx, chunk, vec in chunks_with_vecs:
            if not vec:
                continue
            points.append(qm.PointStruct(
                id=str(_uuid.uuid4()), vector=vec,
                payload={"document_id": str(document_id), "chunk_index": idx, "chunk_text": chunk,
                         "subsidiary": subsidiary, "doc_type": doc_type, "topic": topic},
            ))
        if points:
            client.upsert(collection_name=QDRANT_COLLECTION, points=points)
        return len(points)
    except Exception as e:
        logger.warning(f"Qdrant index failed: {e}")
        return 0


def qdrant_search(query_vec, document_id, limit):
    """Return candidate chunks from Qdrant (payload + score); [] if unavailable."""
    client = get_qdrant()
    if not client or not query_vec:
        return None
    from qdrant_client.http import models as qm
    qfilter = None
    if document_id:
        qfilter = qm.Filter(must=[qm.FieldCondition(key="document_id", match=qm.MatchValue(value=str(document_id)))])
    try:
        hits = client.search(collection_name=QDRANT_COLLECTION, query_vector=query_vec,
                             limit=limit, query_filter=qfilter, with_payload=True)
        out = []
        for h in hits:
            p = h.payload or {}
            out.append({"document_id": p.get("document_id"), "chunk_index": p.get("chunk_index", 0),
                        "chunk_text": p.get("chunk_text", ""), "subsidiary": p.get("subsidiary"),
                        "doc_type": p.get("doc_type"), "score": float(h.score)})
        return out
    except Exception as e:
        logger.warning(f"Qdrant search failed: {e}")
        return None


class IndexRequest(BaseModel):
    document_id: str
    extracted_text: str
    subsidiary: Optional[str] = "CMPDI"
    doc_type: Optional[str] = "general"
    topic: Optional[str] = "general"
    source_kind: Optional[str] = "document" # 'document' or 'report'


class QueryRequest(BaseModel):
    query: str
    top_k: Optional[int] = 5
    document_id: Optional[str] = None
    mode: Optional[str] = "SELECTED"


@app.get("/health")
def health():
    get_qdrant()
    return {"status": "ok", "embedder_active": embedder is not None,
            "vector_store": "qdrant" if _qdrant_ready else "postgres"}


def chunk_text(text: str, chunk_size: int = 400, overlap: int = 50) -> List[str]:
    """Splits text into overlapping paragraph chunks."""
    words = text.split()
    if not words:
        return []
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i:i + chunk_size])
        chunks.append(chunk)
        i += (chunk_size - overlap)
    return chunks


def compute_dense_embedding(text: str) -> Optional[List[float]]:
    """Generates 384-dim dense vector embedding using SentenceTransformer."""
    if embedder:
        try:
            vec = embedder.encode(text)
            return vec.tolist()
        except Exception as e:
            logger.warning(f"Dense embedding failed: {str(e)}")
    return None


def compute_cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """Calculates cosine similarity between two vector lists."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    a = np.array(vec_a)
    b = np.array(vec_b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def compute_tf_similarity(query: str, text: str) -> float:
    """Lightweight term-frequency similarity matching for vector fallback."""
    q_words = set(query.lower().split())
    t_words = text.lower().split()
    if not q_words or not t_words:
        return 0.0
    matches = sum(1 for w in t_words if w in q_words)
    return matches / (math.sqrt(len(q_words)) * math.sqrt(len(set(t_words))) + 1e-5)


import re

SUBSIDIARY_RE = re.compile(r'\b(ECL|BCCL|CCL|WCL|SECL|MCL|NCL|CMPDI)\b', re.IGNORECASE)

# Query keyword -> structured_data column. "production" alone implies both
# target and actual so the user sees the comparison.
_METRIC_KEYWORDS = {
    "production_target_mt": ("target", "planned", "budget"),
    "actual_production_mt": ("actual", "achieved", "output", "produced"),
    "dispatch_mt": ("dispatch", "despatch", "offtake"),
    "overburden_mcum": ("overburden", "over burden"),
}
_METRIC_LABELS = {
    "production_target_mt": "production target (MT)",
    "actual_production_mt": "actual production (MT)",
    "dispatch_mt": "dispatch (MT)",
    "overburden_mcum": "overburden (MCuM)",
}
_AGG_WORDS = ("total", "sum", "combined", "overall", "aggregate", "how much", "how many")
_TREND_WORDS = ("trend", "over the", "year on year", "year-on-year", "year wise", "year-wise", "each year", "annual")
_COMPARE_WORDS = ("compare", "comparison", "versus", " vs ", " vs.", "between", "against")


def _round(v: Optional[float]) -> Optional[float]:
    return round(float(v), 2) if v is not None else None


def detect_numeric_intent(query: str) -> Optional[Dict[str, Any]]:
    """
    Decide whether a query should be answered from the structured_data table
    rather than vector retrieval. Returns an intent dict, or None to defer to
    the vector RAG path.
    """
    q = query.lower()

    metrics = [col for col, kws in _METRIC_KEYWORDS.items() if any(k in q for k in kws)]
    mentions_production = "production" in q or "produce" in q
    # Bare "production" (no target/actual qualifier) -> show target AND actual.
    if mentions_production and "production_target_mt" not in metrics and "actual_production_mt" not in metrics:
        metrics = ["production_target_mt", "actual_production_mt"] + metrics

    if not metrics:
        return None  # No numeric metric requested -> let vector RAG handle it.

    subsidiaries = sorted({m.group(1).upper() for m in SUBSIDIARY_RE.finditer(query)})

    years: List[int] = []
    range_match = re.search(r'\b(20[12]\d)\s*(?:-|to|through|and|–|—)\s*(20[12]\d)\b', q)
    if range_match:
        y0, y1 = int(range_match.group(1)), int(range_match.group(2))
        years = list(range(min(y0, y1), max(y0, y1) + 1))
    else:
        years = sorted({int(y) for y in re.findall(r'\b(20[12]\d)\b', q)})

    # An aggregation/comparison/trend word, or a subsidiary, or a year, is
    # enough to treat this as a structured numeric question.
    has_signal = (
        bool(subsidiaries) or bool(years)
        or any(w in q for w in _AGG_WORDS + _TREND_WORDS + _COMPARE_WORDS)
    )
    if not has_signal:
        return None

    if any(w in q for w in _COMPARE_WORDS) or len(subsidiaries) > 1:
        agg = "COMPARISON"
    elif any(w in q for w in _TREND_WORDS) or len(years) > 1:
        agg = "TREND"
    elif "average" in q or "avg" in q or "mean" in q:
        agg = "AVERAGE"
    elif any(w in q for w in _AGG_WORDS):
        agg = "AGGREGATION"
    else:
        agg = "FACT_LOOKUP"

    return {"metrics": metrics, "subsidiaries": subsidiaries, "years": years, "agg": agg}


def run_numeric_query(user: dict, intent: Dict[str, Any], document_id: Optional[str], conn) -> Optional[Dict[str, Any]]:
    """
    Answer a numeric question from structured_data with server-side RBAC.
    Returns a grounded response dict, or None if there are no authorized rows
    (caller then falls back to vector retrieval).
    """
    where = []
    params: List[Any] = []
    if document_id:
        where.append("s.document_id = %s")
        params.append(document_id)
    if intent["subsidiaries"]:
        where.append("UPPER(s.subsidiary) = ANY(%s)")
        params.append(intent["subsidiaries"])
    if intent["years"]:
        where.append("s.report_year = ANY(%s)")
        params.append(intent["years"])
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    sql = f"""
        SELECT s.mine_name, s.subsidiary, s.report_year,
               s.production_target_mt, s.actual_production_mt,
               s.dispatch_mt, s.overburden_mcum,
               s.document_id, d.original_filename
        FROM structured_data s
        JOIN documents d ON s.document_id = d.id
        {where_sql};
    """
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()

    # Enforce RBAC per row (defense in depth, identical to vector path).
    rows = [r for r in rows if verify_document_access(user, r.get("subsidiary"))]
    if not rows:
        return None

    metrics = intent["metrics"]

    # Aggregate by (subsidiary, year), summing each metric across mines.
    groups: Dict[tuple, Dict[str, Any]] = {}
    contributing = {}
    for r in rows:
        key = (r["subsidiary"], r["report_year"])
        g = groups.setdefault(key, {"subsidiary": r["subsidiary"], "report_year": r["report_year"], "mines": 0})
        g["mines"] += 1
        for col in metrics:
            val = r.get(col)
            if val is not None:
                g[col] = round(g.get(col, 0.0) + float(val), 2)
        contributing[(str(r["document_id"]), r["original_filename"])] = True

    table = sorted(
        groups.values(),
        key=lambda x: (str(x["subsidiary"]), x["report_year"] or 0)
    )

    # Build a deterministic, fully-grounded answer sentence from the SQL result.
    def fmt_group(g) -> str:
        parts = []
        for col in metrics:
            if g.get(col) is not None:
                parts.append(f"{_METRIC_LABELS[col]} {g[col]}")
        span = ", ".join(parts) if parts else "no recorded figures"
        detail = f"{g['subsidiary']} {g['report_year']}: {span} (across {g['mines']} mine{'s' if g['mines'] != 1 else ''})"
        if g.get("production_target_mt") is not None and g.get("actual_production_mt") is not None:
            diff = round(g["production_target_mt"] - g["actual_production_mt"], 2)
            detail += f"; shortfall {diff} MT" if diff >= 0 else f"; surplus {abs(diff)} MT"
        return detail

    lines = [fmt_group(g) for g in table]
    if intent["agg"] == "AVERAGE" and "actual_production_mt" in metrics:
        vals = [g["actual_production_mt"] for g in table if g.get("actual_production_mt") is not None]
        if vals:
            lines.append(f"Average actual production across {len(vals)} group(s): {round(sum(vals)/len(vals), 2)} MT")
    answer = "Computed from structured records:\n- " + "\n- ".join(lines)

    sources = [
        {"filename": fname, "document_id": did, "relevance_snippet": "structured production/dispatch record"}
        for (did, fname) in contributing
    ]

    return {
        "answer": answer,
        "sources": sources,
        "grounded": True,
        "mode": "SQL_NUMERIC",
        "intent": intent["agg"],
        "table": table,
        "user_role": user["role"],
        "authorized_scope": user.get("assigned_subsidiary") or "ALL",
    }


@app.post("/index")
def index_document(payload: IndexRequest):
    logger.info(f"Indexing document_id={payload.document_id} (kind={payload.source_kind}) for RAG")
    chunks = chunk_text(payload.extracted_text)
    if not chunks:
        return {"status": "skipped", "chunks_indexed": 0}

    conn = get_db_connection()
    try:
        chunks_with_vecs = []
        with conn.cursor() as cur:
            # Clear previous chunks for this document/report kind
            cur.execute("DELETE FROM vector_chunks WHERE document_id = %s AND doc_type = %s;", (payload.document_id, payload.doc_type))

            for idx, chunk in enumerate(chunks):
                vec = compute_dense_embedding(chunk)
                chunks_with_vecs.append((idx, chunk, vec))
                cur.execute(
                    """
                    INSERT INTO vector_chunks (document_id, chunk_index, chunk_text, embedding, subsidiary, doc_type, topic)
                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                    """,
                    (payload.document_id, idx, chunk, vec, payload.subsidiary, payload.doc_type, payload.topic)
                )
            conn.commit()

        # Primary vector store: Qdrant (Postgres above is the fallback copy).
        q_indexed = qdrant_index(payload.document_id, payload.doc_type, chunks_with_vecs,
                                 payload.subsidiary, payload.topic)
        return {"status": "indexed", "chunks_indexed": len(chunks),
                "embeddings_generated": embedder is not None,
                "qdrant_points": q_indexed, "vector_store": "qdrant" if _qdrant_ready else "postgres"}
    finally:
        conn.close()


@app.post("/query")
async def query_rag(payload: QueryRequest, authorization: Optional[str] = Header(None)):
    user = get_current_user(authorization)
    logger.info(f"RAG query requested by user '{user['username']}' (role={user['role']}, sub={user['assigned_subsidiary']}, doc_id={payload.document_id}, mode={payload.mode}): '{payload.query}'")

    conn = get_db_connection()
    try:
        # Structured numeric path: route aggregation/fact-lookup questions to
        # the structured_data table so figures come from real records (SQL),
        # never from LLM text generation. Falls through to vector RAG when the
        # question is not numeric or no authorized rows exist.
        intent = detect_numeric_intent(payload.query)
        if intent:
            numeric = run_numeric_query(user, intent, payload.document_id, conn)
            if numeric:
                log_audit_event(
                    conn, user["username"], user["role"], "RAG_QUERY", "rag-service", "SUCCESS",
                    metadata={"query": payload.query, "mode": "SQL_NUMERIC", "intent": intent["agg"],
                              "rows": len(numeric["table"]), "document_id": payload.document_id}
                )
                logger.info(f"Answered via SQL_NUMERIC path (intent={intent['agg']}, groups={len(numeric['table'])})")
                return numeric

        query_vec = compute_dense_embedding(payload.query)

        # --- Candidate retrieval: Qdrant (primary), Postgres (fallback) ---
        limit = max(payload.top_k * 5, 25)
        candidates = qdrant_search(query_vec, payload.document_id, limit)
        vector_backend = "qdrant"
        if candidates is None:
            vector_backend = "postgres"
            with conn.cursor() as cur:
                sql = "SELECT document_id, chunk_index, chunk_text, embedding, subsidiary, doc_type FROM vector_chunks"
                params = []
                if payload.document_id:
                    sql += " WHERE document_id = %s"
                    params.append(payload.document_id)
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
            candidates = []
            for r in rows:
                if query_vec and r.get("embedding"):
                    sc = compute_cosine_similarity(query_vec, r["embedding"])
                else:
                    sc = compute_tf_similarity(payload.query, r["chunk_text"])
                candidates.append({"document_id": str(r["document_id"]), "chunk_index": r.get("chunk_index", 0),
                                   "chunk_text": r["chunk_text"], "subsidiary": r.get("subsidiary"),
                                   "doc_type": r.get("doc_type"), "score": sc})

        # Resolve filenames for candidate documents in one query.
        fnmap = {}
        docids = list({c["document_id"] for c in candidates if c.get("document_id")})
        if docids:
            with conn.cursor() as cur:
                cur.execute("SELECT id, original_filename FROM documents WHERE id = ANY(%s::uuid[]);", (docids,))
                fnmap = {str(r["id"]): r["original_filename"] for r in cur.fetchall()}

        # Enforce RBAC & strict document isolation on retrieved candidates
        # (defense in depth — applied in Python regardless of vector backend).
        authorized_chunks = []
        for c in candidates:
            if not verify_document_access(user, c.get("subsidiary")):
                continue
            if payload.document_id and str(c["document_id"]) != str(payload.document_id):
                logger.error(f"SECURITY ISOLATION VIOLATION: chunk doc '{c['document_id']}' leaked for requested doc '{payload.document_id}'. Purging.")
                log_audit_event(conn, user["username"], user["role"], "ISOLATION_VIOLATION_BLOCKED", "rag-service", "PURGED", document_id=payload.document_id)
                continue
            if c["score"] > 0.001:
                authorized_chunks.append({
                    "doc_id": str(c["document_id"]),
                    "filename": fnmap.get(str(c["document_id"]), "document"),
                    "chunk_index": c.get("chunk_index", 0),
                    "subsidiary": c.get("subsidiary"),
                    "doc_type": c.get("doc_type"),
                    "text": c["chunk_text"],
                    "score": c["score"],
                })

        authorized_chunks.sort(key=lambda x: x["score"], reverse=True)
        top_chunks = authorized_chunks[:payload.top_k]
        logger.info(f"Vector retrieval via {vector_backend}: {len(candidates)} candidates -> {len(top_chunks)} authorized")

        if not top_chunks:
            log_audit_event(
                conn, user["username"], user["role"], "RAG_QUERY", "rag-service", "NO_RELEVANT_CONTEXT",
                metadata={"query": payload.query, "document_id": payload.document_id, "user_assigned": user.get("assigned_subsidiary")}
            )
            msg = "The requested information is not available in the selected document." if payload.document_id else "I could not find sufficient evidence in the authorized documents to answer this question."
            return {
                "answer": msg,
                "sources": [],
                "grounded": False,
                "user_role": user["role"],
                "authorized_scope": user.get("assigned_subsidiary") or "ALL"
            }

        # Build Grounded LLM Prompt with Strict Isolation Instructions
        context_str = "\n\n".join([
            f"[Source: {c['filename']} | Chunk: #{c['chunk_index']} | ID: {c['doc_id']}]\n{c['text']}"
            for c in top_chunks
        ])

        if payload.document_id:
            target_doc_name = top_chunks[0]['filename']
            system_prompt = (
                "You are MineIQ AI, an enterprise intelligence system for Coal India Limited (CIL) and CMPDI.\n"
                f"The user is asking a question about the SPECIFIC SELECTED DOCUMENT: '{target_doc_name}' (ID: {payload.document_id}).\n\n"
                "STRICT GROUNDING RULES:\n"
                "1. Answer ONLY using the provided context below, which is restricted to the selected document.\n"
                "2. Do NOT use facts, figures, memory, or knowledge from other documents or general training data.\n"
                "3. If the answer is not explicitly stated in the context for this document, respond EXACTLY:\n"
                "'The requested information is not available in the selected document.'\n"
                "4. Do NOT hallucinate production targets or figures if they are not in the selected document.\n\n"
                f"--- CONTEXT FOR {target_doc_name} ---\n{context_str}\n\n"
                f"--- USER QUESTION ---\n{payload.query}"
            )
        else:
            system_prompt = (
                "You are MineIQ AI, an enterprise intelligence system for Coal India Limited (CIL) and CMPDI.\n"
                "Answer the user's question using ONLY the authorized cross-document context below.\n\n"
                "STRICT GROUNDING RULES:\n"
                "1. Base your answer EXCLUSIVELY on facts explicitly stated in the context.\n"
                "2. Clearly identify which specific document supplied each fact.\n"
                "3. If the context does not contain enough information, respond exactly: "
                "'I could not find sufficient evidence in the authorized documents to answer this question.'\n"
                "4. Do NOT invent numbers, figures, or dates.\n\n"
                f"--- CONTEXT ---\n{context_str}\n\n"
                f"--- USER QUESTION ---\n{payload.query}"
            )

        answer = ""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{OLLAMA_ENDPOINT}/api/generate",
                    json={
                        "model": OLLAMA_MODEL,
                        "prompt": system_prompt,
                        "stream": False,
                        "options": {"temperature": 0.0}
                    }
                )
                if resp.status_code == 200:
                    answer = resp.json().get("response", "").strip()
                else:
                    logger.warning(f"Ollama returned HTTP {resp.status_code}, generating grounded summary fallback")
                    answer = f"Based on {top_chunks[0]['filename']}: " + top_chunks[0]['text'][:300] + "..."
        except Exception as llm_err:
            logger.error(f"Ollama call failed: {str(llm_err)}")
            answer = f"Based on {top_chunks[0]['filename']}: " + top_chunks[0]['text'][:300] + "..."

        sources = []
        seen = set()
        for c in top_chunks:
            key = (c["doc_id"], c["filename"], c["chunk_index"])
            if key not in seen:
                seen.add(key)
                snippet = c["text"][:180] + "..." if len(c["text"]) > 180 else c["text"]
                sources.append({
                    "filename": c["filename"],
                    "document_id": c["doc_id"],
                    "chunk_index": c["chunk_index"],
                    "subsidiary": c["subsidiary"],
                    "relevance_snippet": snippet
                })

        log_audit_event(
            conn, user["username"], user["role"], "RAG_QUERY", "rag-service", "SUCCESS",
            metadata={"query": payload.query, "document_id": payload.document_id, "sources_count": len(sources)}
        )

        return {
            "answer": answer,
            "sources": sources,
            "grounded": True,
            "user_role": user["role"],
            "authorized_scope": user.get("assigned_subsidiary") or "ALL"
        }
    finally:
        conn.close()
