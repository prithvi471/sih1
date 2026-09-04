import os
import re
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from collections import Counter
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sys

# Add parent directory for shared auth module
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from auth import get_current_user, verify_document_access

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("analytics-service")

app = FastAPI(
    title="MineIQ Topic & Word Cloud Analytics Engine",
    description="Analyzes document text corpus to generate word clouds, topic distributions, and historical trends for CIL/CMPDI."
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

STOP_WORDS = {
    "the", "and", "to", "of", "a", "in", "is", "that", "for", "it", "as", "was", "with", "on", "at", "by",
    "an", "be", "this", "which", "or", "from", "are", "have", "has", "had", "not", "been", "were", "they",
    "their", "more", "also", "its", "into", "than", "will", "all", "can", "only", "other", "shall", "per",
    "document", "report", "page", "section", "table", "value", "status", "data", "total", "year", "target"
}


def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        cursor_factory=RealDictCursor
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/analytics/wordcloud")
def get_wordcloud(
    subsidiary: Optional[str] = None,
    doc_type: Optional[str] = None,
    authorization: Optional[str] = Header(None)
):
    user = get_current_user(authorization)
    logger.info(f"Wordcloud requested by '{user['username']}' (role={user['role']})")

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            query = "SELECT extracted_text, subsidiary FROM documents WHERE extracted_text IS NOT NULL AND status != 'failed'"
            params = []
            if subsidiary:
                query += " AND UPPER(subsidiary) = %s"
                params.append(subsidiary.upper())
            if doc_type:
                query += " AND doc_type = %s"
                params.append(doc_type)

            cur.execute(query, tuple(params))
            docs = cur.fetchall()

        words = []
        for d in docs:
            doc_sub = d.get("subsidiary")
            if verify_document_access(user, doc_sub):
                txt = d.get("extracted_text") or ""
                tokens = re.findall(r'\b[A-Za-z]{3,}\b', txt.lower())
                filtered = [w for w in tokens if w not in STOP_WORDS]
                words.extend(filtered)

        counts = Counter(words)
        top_words = [{"text": word, "value": count} for word, count in counts.most_common(60)]
        return {"words": top_words, "total_terms": len(words)}
    finally:
        conn.close()


@app.get("/analytics/topics")
def get_topic_distribution(
    subsidiary: Optional[str] = None,
    authorization: Optional[str] = Header(None)
):
    user = get_current_user(authorization)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            query = "SELECT topic_area, doc_type, extracted_text, subsidiary FROM documents WHERE status != 'failed'"
            params = []
            if subsidiary:
                query += " AND UPPER(subsidiary) = %s"
                params.append(subsidiary.upper())

            cur.execute(query, tuple(params))
            docs = cur.fetchall()

        topic_counts = Counter()
        default_topics = [
            "Coal Production", "Geological Exploration", "Mine Development",
            "Overburden Removal", "Coal Dispatch", "Safety & Compliance",
            "Equipment & Machinery", "Reserves & Quality", "Land Acquisition"
        ]

        for d in docs:
            if verify_document_access(user, d.get("subsidiary")):
                topic = d.get("topic_area")
                txt = (d.get("extracted_text") or "").lower()

                if topic and topic.strip():
                    topic_counts[topic.strip().title()] += 1
                elif "production" in txt or "target" in txt:
                    topic_counts["Coal Production"] += 1
                elif "geological" in txt or "survey" in txt or "borehole" in txt:
                    topic_counts["Geological Exploration"] += 1
                elif "overburden" in txt or "removal" in txt:
                    topic_counts["Overburden Removal"] += 1
                elif "dispatch" in txt or "offtake" in txt:
                    topic_counts["Coal Dispatch"] += 1
                elif "safety" in txt or "inspection" in txt:
                    topic_counts["Safety & Compliance"] += 1
                else:
                    topic_counts["Mine Development"] += 1

        # Seed missing topics with 0 for nice UI graphs
        for dt in default_topics:
            if dt not in topic_counts:
                topic_counts[dt] = 0

        distribution = [{"topic": k, "count": v} for k, v in topic_counts.items()]
        distribution.sort(key=lambda x: x["count"], reverse=True)

        return {"topics": distribution, "total_documents": len(docs)}
    finally:
        conn.close()


_DISCREPANCY_METRICS = {
    "production_target_mt": "production target (MT)",
    "actual_production_mt": "actual production (MT)",
    "dispatch_mt": "dispatch (MT)",
    "overburden_mcum": "overburden (MCuM)",
}


def _norm_mine(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    return re.sub(r'\s+', ' ', name.strip().lower())


def _severity(pct: float) -> str:
    if pct >= 10.0:
        return "critical"
    if pct >= 3.0:
        return "high"
    return "medium"


@app.get("/analytics/discrepancies")
def get_discrepancies(
    subsidiary: Optional[str] = None,
    authorization: Optional[str] = Header(None)
):
    """
    Cross-document discrepancy detection. Finds the same fact — a
    (subsidiary, mine, year, metric) tuple — reported with materially
    different values by two or more distinct documents. RBAC-scoped: a user
    only sees conflicts within the subsidiaries they are authorized for.
    """
    user = get_current_user(authorization)
    logger.info(f"Discrepancy scan requested by '{user['username']}' (role={user['role']})")

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            query = """
                SELECT s.document_id, s.mine_name, s.subsidiary, s.report_year,
                       s.production_target_mt, s.actual_production_mt,
                       s.dispatch_mt, s.overburden_mcum,
                       d.original_filename, d.uploaded_at
                FROM structured_data s
                JOIN documents d ON s.document_id = d.id
                WHERE d.status != 'failed'
                  AND s.mine_name IS NOT NULL AND s.report_year IS NOT NULL
            """
            params = []
            if subsidiary:
                query += " AND UPPER(s.subsidiary) = %s"
                params.append(subsidiary.upper())
            cur.execute(query, tuple(params))
            rows = cur.fetchall()

        # RBAC filter before any comparison (defense in depth).
        rows = [r for r in rows if verify_document_access(user, r.get("subsidiary"))]

        # Group by (subsidiary, normalized mine, year, metric). Within a group,
        # keep one value per document (last write wins if a doc repeats a fact).
        groups: Dict[tuple, Dict[str, Dict[str, Any]]] = {}
        for r in rows:
            mine_key = _norm_mine(r.get("mine_name"))
            if not mine_key:
                continue
            for col in _DISCREPANCY_METRICS:
                val = r.get(col)
                if val is None:
                    continue
                key = (r.get("subsidiary"), mine_key, r.get("report_year"), col)
                per_doc = groups.setdefault(key, {})
                per_doc[str(r["document_id"])] = {
                    "value": round(float(val), 2),
                    "document_id": str(r["document_id"]),
                    "filename": r.get("original_filename"),
                    "mine_name": r.get("mine_name"),
                }

        discrepancies = []
        for (sub, _mine, year, col), per_doc in groups.items():
            if len(per_doc) < 2:
                continue  # a fact reported by only one document cannot conflict
            entries = list(per_doc.values())
            lo = min(entries, key=lambda e: e["value"])
            hi = max(entries, key=lambda e: e["value"])
            diff = round(hi["value"] - lo["value"], 2)
            denom = abs(hi["value"]) or 1.0
            pct = round(diff / denom * 100.0, 2)
            # Ignore rounding-level noise: need a real absolute and relative gap.
            if diff < 0.5 or pct < 1.0:
                continue
            discrepancies.append({
                "subsidiary": sub,
                "mine_name": hi["mine_name"],
                "report_year": year,
                "metric": col,
                "metric_label": _DISCREPANCY_METRICS[col],
                "value_a": lo["value"],
                "source_a": {"filename": lo["filename"], "document_id": lo["document_id"]},
                "value_b": hi["value"],
                "source_b": {"filename": hi["filename"], "document_id": hi["document_id"]},
                "difference": diff,
                "pct_difference": pct,
                "reporting_documents": len(per_doc),
                "severity": _severity(pct),
                "status": "pending_verification",
            })

        sev_rank = {"critical": 0, "high": 1, "medium": 2}
        discrepancies.sort(key=lambda x: (sev_rank[x["severity"]], -x["pct_difference"]))

        by_severity = Counter(d["severity"] for d in discrepancies)
        return {
            "discrepancies": discrepancies,
            "count": len(discrepancies),
            "by_severity": {
                "critical": by_severity.get("critical", 0),
                "high": by_severity.get("high", 0),
                "medium": by_severity.get("medium", 0),
            },
            "scanned_records": len(rows),
            "authorized_scope": user.get("assigned_subsidiary") or "ALL",
        }
    finally:
        conn.close()


@app.get("/analytics/trends")
def get_topic_trends(
    authorization: Optional[str] = Header(None)
):
    user = get_current_user(authorization)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXTRACT(YEAR FROM uploaded_at)::int as yr, topic_area, COUNT(*)::int as cnt
                FROM documents
                WHERE status != 'failed'
                GROUP BY yr, topic_area
                ORDER BY yr ASC;
                """
            )
            rows = cur.fetchall()

        if not rows:
            return {"insufficient_data": True, "trends": []}

        trends_map = {}
        for r in rows:
            yr = r["yr"] or 2026
            topic = r["topic_area"] or "Coal Production"
            if yr not in trends_map:
                trends_map[yr] = {}
            trends_map[yr][topic] = r["cnt"]

        trend_list = []
        for yr, topics in trends_map.items():
            trend_list.append({
                "year": yr,
                "Coal Production": topics.get("Coal Production", 0),
                "Geological Exploration": topics.get("Geological Exploration", 0),
                "Overburden Removal": topics.get("Overburden Removal", 0),
                "Safety & Compliance": topics.get("Safety & Compliance", 0)
            })

        return {"insufficient_data": False, "trends": trend_list}
    finally:
        conn.close()
