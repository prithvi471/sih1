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


# ---------------------------------------------------------------------------
# Neo4j knowledge graph: Subsidiary–operates–Mine, Document–about–Mine, etc.
# ---------------------------------------------------------------------------
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "mineiq_graph_pass")
_neo_driver = None


def get_graph():
    global _neo_driver
    if _neo_driver is not None:
        return _neo_driver
    try:
        from neo4j import GraphDatabase
        drv = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        drv.verify_connectivity()
        _neo_driver = drv
        logger.info("Neo4j knowledge graph connected.")
    except Exception as e:
        logger.warning(f"Neo4j unavailable: {e}")
        _neo_driver = None
    return _neo_driver


# --- Entity extraction + normalization (Phase 3) ---
_SUB_FULL = [("south eastern coalfields", "SECL"), ("eastern coalfields", "ECL"),
             ("western coalfields", "WCL"), ("central coalfields", "CCL"),
             ("northern coalfields", "NCL"), ("mahanadi coalfields", "MCL"),
             ("bharat coking coal", "BCCL"), ("central mine planning", "CMPDI")]
_SUB_CODE_RE = re.compile(r'\b(ECL|BCCL|CCL|WCL|SECL|MCL|NCL|CMPDI)\b')
_SUB_ALIASES = {
    "MCL": ["MCL", "Mahanadi Coalfields Limited", "Mahanadi Coalfields Ltd."],
    "ECL": ["ECL", "Eastern Coalfields Limited"], "NCL": ["NCL", "Northern Coalfields Limited"],
    "SECL": ["SECL", "South Eastern Coalfields Limited"], "WCL": ["WCL", "Western Coalfields Limited"],
    "CCL": ["CCL", "Central Coalfields Limited"], "BCCL": ["BCCL", "Bharat Coking Coal Limited"],
    "CMPDI": ["CMPDI", "Central Mine Planning and Design Institute"],
}


def canon_subsidiary(raw):
    """Resolve 'Mahanadi Coalfields Limited', 'MCL', 'ECL (Eastern...)' -> canonical code."""
    if not raw:
        return None
    low = raw.lower()
    for phrase, code in _SUB_FULL:
        if phrase in low:
            return code
    m = _SUB_CODE_RE.search(raw.upper())
    return m.group(1) if m else raw.strip().upper()


def extract_entities(text):
    """Domain-aware generic entity extraction -> list of (type, canonical, mention)."""
    if not text:
        return []
    ents, low = [], text.lower()
    for phrase, code in _SUB_FULL:
        if phrase in low:
            ents.append(("Subsidiary", code, phrase))
    for m in _SUB_CODE_RE.finditer(text.upper()):
        ents.append(("Subsidiary", m.group(1), m.group(1)))
    for m in re.finditer(r'([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\s+Coalfield', text):
        ents.append(("Coalfield", m.group(1) + " Coalfield", m.group(0)))
    for c in ["lignite", "coking coal", "non-coking coal", "coal"]:
        if c in low:
            ents.append(("Commodity", c.title(), c))
    for m in re.finditer(r'\bG-?(\d{1,2})\b', text):
        ents.append(("CoalGrade", "G-" + m.group(1), m.group(0)))
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*(Million\s+Tonnes|MT|MCuM|meters|metres)\b', text, re.IGNORECASE):
        ents.append(("Quantity", m.group(0).strip(), m.group(0).strip()))
    for m in re.finditer(r'\b(20[12]\d)\b', text):
        ents.append(("Year", m.group(1), m.group(1)))
    for metric in ["production", "dispatch", "offtake", "overburden", "reserve", "exploration", "borehole", "seam"]:
        if metric in low:
            ents.append(("Concept", metric.title(), metric))
    seen, out = set(), []
    for t, c, mention in ents:
        if (t, c) not in seen:
            seen.add((t, c))
            out.append((t, c, mention))
    return out


def graph_sync():
    """(Re)build the knowledge graph from PostgreSQL. Idempotent via MERGE."""
    drv = get_graph()
    if not drv:
        return {"error": "neo4j_unavailable"}
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, original_filename, subsidiary, doc_type, topic_area, extracted_text FROM documents WHERE status != 'failed';")
            docs = cur.fetchall()
            cur.execute("SELECT DISTINCT mine_name, subsidiary FROM structured_data WHERE mine_name IS NOT NULL AND subsidiary IS NOT NULL;")
            mines = cur.fetchall()
            cur.execute("SELECT document_id, mine_name, subsidiary FROM structured_data WHERE mine_name IS NOT NULL;")
            doc_mine = cur.fetchall()
            try:
                cur.execute("SELECT id, pq_number, subsidiaries, topics FROM parliamentary_questions;")
                pqs = cur.fetchall()
            except Exception:
                pqs = []
            # Canonical entity store in PostgreSQL (spec 11).
            cur.execute("""CREATE TABLE IF NOT EXISTS entities (
                id SERIAL PRIMARY KEY, canonical_name VARCHAR(200) NOT NULL, entity_type VARCHAR(50) NOT NULL,
                aliases TEXT[] DEFAULT '{}', UNIQUE(canonical_name, entity_type));""")
            cur.execute("""CREATE TABLE IF NOT EXISTS document_entities (
                document_id UUID, entity_id INT REFERENCES entities(id) ON DELETE CASCADE,
                mention TEXT, UNIQUE(document_id, entity_id));""")
            conn.commit()

        counts = {"subsidiaries": 0, "mines": 0, "documents": 0, "pqs": 0, "entities": 0, "mentions": 0}
        with drv.session() as s:
            # Full rebuild so canonicalization removes stale/duplicate nodes
            # (e.g. an old "WESTERN COALFIELDS LIMITED (WCL)" collapses to "WCL").
            s.run("MATCH (n) DETACH DELETE n")
            for m in mines:
                sub = canon_subsidiary(m["subsidiary"])
                s.run("MERGE (sub:Subsidiary {name:$sub}) MERGE (mine:Mine {name:$mine, subsidiary:$sub}) "
                      "MERGE (sub)-[:OPERATES]->(mine)", sub=sub, mine=m["mine_name"])
                counts["mines"] += 1
            counts["subsidiaries"] = len({canon_subsidiary(m["subsidiary"]) for m in mines} |
                                         {canon_subsidiary(d["subsidiary"]) for d in docs if d.get("subsidiary")})
            entity_ids = {}
            for d in docs:
                did = str(d["id"])
                sub = canon_subsidiary(d.get("subsidiary"))
                s.run("MERGE (doc:Document {id:$id}) SET doc.filename=$fn, doc.doc_type=$dt", id=did, fn=d["original_filename"], dt=d.get("doc_type"))
                if sub and sub not in ("UNKNOWN", "UNCLASSIFIED"):
                    s.run("MERGE (sub:Subsidiary {name:$sub}) WITH sub MATCH (doc:Document {id:$id}) MERGE (doc)-[:BELONGS_TO]->(sub)", sub=sub, id=did)
                if d.get("topic_area"):
                    s.run("MERGE (t:Topic {name:$t}) WITH t MATCH (doc:Document {id:$id}) MERGE (doc)-[:HAS_TOPIC]->(t)", t=d["topic_area"], id=did)
                counts["documents"] += 1

                # Generic entity extraction -> Neo4j Entity + MENTIONS, and Postgres.
                for etype, canonical, mention in extract_entities(d.get("extracted_text") or ""):
                    aliases = _SUB_ALIASES.get(canonical, []) if etype == "Subsidiary" else []
                    s.run("MERGE (e:Entity {name:$n, type:$t}) SET e.aliases=$a "
                          "WITH e MATCH (doc:Document {id:$id}) MERGE (doc)-[:MENTIONS]->(e)",
                          n=canonical, t=etype, a=aliases, id=did)
                    key = (canonical, etype)
                    if key not in entity_ids:
                        with conn.cursor() as c2:
                            c2.execute("INSERT INTO entities (canonical_name, entity_type, aliases) VALUES (%s,%s,%s) "
                                       "ON CONFLICT (canonical_name, entity_type) DO UPDATE SET aliases=EXCLUDED.aliases RETURNING id;",
                                       (canonical, etype, aliases))
                            entity_ids[key] = c2.fetchone()["id"]
                        counts["entities"] += 1
                    with conn.cursor() as c2:
                        c2.execute("INSERT INTO document_entities (document_id, entity_id, mention) VALUES (%s,%s,%s) "
                                   "ON CONFLICT DO NOTHING;", (did, entity_ids[key], mention))
                    counts["mentions"] += 1
                conn.commit()

            for dm in doc_mine:
                s.run("MATCH (doc:Document {id:$id}) MATCH (mine:Mine {name:$mine, subsidiary:$sub}) MERGE (doc)-[:ABOUT]->(mine)",
                      id=str(dm["document_id"]), mine=dm["mine_name"], sub=canon_subsidiary(dm["subsidiary"]))
            for q in pqs:
                s.run("MERGE (pq:PQ {id:$id}) SET pq.number=$num", id=str(q["id"]), num=q.get("pq_number"))
                for sub in (q.get("subsidiaries") or []):
                    s.run("MERGE (sub:Subsidiary {name:$sub}) WITH sub MATCH (pq:PQ {id:$id}) MERGE (pq)-[:CONCERNS]->(sub)", sub=canon_subsidiary(sub), id=str(q["id"]))
                for t in (q.get("topics") or []):
                    s.run("MERGE (t:Topic {name:$t}) WITH t MATCH (pq:PQ {id:$id}) MERGE (pq)-[:RELATED_TO]->(t)", t=t, id=str(q["id"]))
                counts["pqs"] += 1
        return counts
    finally:
        conn.close()


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


@app.get("/analytics/topics/semantic")
def semantic_topics(k: Optional[int] = None, authorization: Optional[str] = Header(None)):
    """
    Semantic topic modeling by clustering the document embeddings we already
    store (SentenceTransformer vectors in vector_chunks), with representative
    terms per cluster via TF-IDF. A lighter, stable alternative to BERTopic
    that is appropriate for this corpus size. RBAC-filtered.
    """
    user = get_current_user(authorization)
    try:
        import numpy as np
        from sklearn.cluster import KMeans
        from sklearn.feature_extraction.text import TfidfVectorizer
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"topic-modeling libraries unavailable: {e}")

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT v.document_id, v.embedding, d.original_filename, d.subsidiary,
                       d.extracted_text
                FROM vector_chunks v JOIN documents d ON v.document_id = d.id
                WHERE v.embedding IS NOT NULL AND d.status != 'failed';
            """)
            rows = cur.fetchall()
        # One mean embedding + concatenated text per authorized document.
        docs = {}
        for r in rows:
            if not verify_document_access(user, r.get("subsidiary")):
                continue
            did = str(r["document_id"])
            e = docs.setdefault(did, {"vecs": [], "text": "", "filename": r["original_filename"],
                                      "subsidiary": r.get("subsidiary")})
            if r["embedding"]:
                e["vecs"].append(r["embedding"])
            e["text"] += " " + (r.get("extracted_text") or "")[:2000]
        docs = {d: v for d, v in docs.items() if v["vecs"]}
        n = len(docs)
        if n < 3:
            return {"insufficient_data": True, "documents": n, "topics": []}

        ids = list(docs.keys())
        X = np.array([np.mean(docs[d]["vecs"], axis=0) for d in ids])
        n_topics = k or max(2, min(6, n // 3))
        labels = KMeans(n_clusters=n_topics, random_state=42, n_init=10).fit_predict(X)

        # Representative terms per cluster via TF-IDF over that cluster's text.
        texts = [docs[d]["text"] for d in ids]
        tfidf = TfidfVectorizer(max_features=400, stop_words="english",
                                token_pattern=r"[A-Za-z][A-Za-z]{2,}")
        tf = tfidf.fit_transform(texts)
        vocab = tfidf.get_feature_names_out()

        # Years per document from structured_data.
        with conn.cursor() as cur:
            cur.execute("SELECT document_id, array_agg(DISTINCT report_year) yrs FROM structured_data WHERE report_year IS NOT NULL GROUP BY document_id;")
            years = {str(r["document_id"]): [y for y in r["yrs"] if y] for r in cur.fetchall()}

        topics = []
        for c in range(n_topics):
            members = [i for i, lab in enumerate(labels) if lab == c]
            if not members:
                continue
            cluster_tf = np.asarray(tf[members].mean(axis=0)).ravel()
            top_idx = cluster_tf.argsort()[::-1][:8]
            terms = [vocab[i] for i in top_idx if cluster_tf[i] > 0]
            subs = sorted({docs[ids[i]]["subsidiary"] for i in members if docs[ids[i]]["subsidiary"]})
            yrs = sorted({y for i in members for y in years.get(ids[i], [])})
            topics.append({
                "topic_id": c,
                "topic_name": ", ".join(terms[:3]).title() if terms else f"Topic {c}",
                "representative_terms": terms,
                "document_count": len(members),
                "subsidiaries": subs,
                "years": yrs,
                "documents": [docs[ids[i]]["filename"] for i in members][:8],
            })
        topics.sort(key=lambda t: t["document_count"], reverse=True)
        return {"method": "embedding-clustering (KMeans + TF-IDF)", "documents": n,
                "topic_count": len(topics), "topics": topics}
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


# ---------------------------------------------------------------------------
# Knowledge graph API
# ---------------------------------------------------------------------------
_GRAPH_ADMIN = ("ADMIN", "MINISTRY_OFFICER", "CMPDI_OFFICER")


@app.post("/graph/sync")
def graph_sync_endpoint(authorization: Optional[str] = Header(None)):
    user = get_current_user(authorization)
    if user.get("role") not in _GRAPH_ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized to rebuild the knowledge graph")
    logger.info(f"Graph sync requested by '{user['username']}'")
    result = graph_sync()
    if "error" in result:
        raise HTTPException(status_code=503, detail="Neo4j knowledge graph is unavailable")
    return {"status": "synced", **result}


@app.get("/graph/overview")
def graph_overview(authorization: Optional[str] = Header(None)):
    """Subsidiary -> mines / document counts, RBAC-filtered to the caller's scope."""
    user = get_current_user(authorization)
    drv = get_graph()
    if not drv:
        raise HTTPException(status_code=503, detail="Neo4j knowledge graph is unavailable")
    with drv.session() as s:
        totals = s.run("MATCH (n) RETURN count(n) AS nodes").single()["nodes"]
        rels = s.run("MATCH ()-[r]->() RETURN count(r) AS rels").single()["rels"]
        rows = s.run(
            """
            MATCH (sub:Subsidiary)
            OPTIONAL MATCH (sub)-[:OPERATES]->(m:Mine)
            OPTIONAL MATCH (d:Document)-[:BELONGS_TO]->(sub)
            RETURN sub.name AS subsidiary, count(DISTINCT m) AS mines, count(DISTINCT d) AS documents
            ORDER BY subsidiary
            """
        ).data()
    subs = [r for r in rows if verify_document_access(user, r["subsidiary"])]
    return {"nodes": totals, "relationships": rels, "subsidiaries": subs,
            "authorized_scope": user.get("assigned_subsidiary") or "ALL"}


@app.get("/graph/related")
def graph_related(subs: str = "", authorization: Optional[str] = Header(None)):
    """Documents/mines/entities the graph connects to the given subsidiaries.
    Used by rag-service to fuse graph evidence into RAG (comma-separated codes)."""
    get_current_user(authorization)
    codes = [c.strip().upper() for c in subs.split(",") if c.strip()]
    drv = get_graph()
    if not drv or not codes:
        return {"document_ids": [], "relationships": [], "entities": codes}
    doc_ids, rels = [], []
    try:
        with drv.session() as s:
            for sub in codes:
                for r in s.run("MATCH (d:Document)-[:BELONGS_TO]->(x:Subsidiary {name:$s}) RETURN d.id AS id, d.filename AS fn LIMIT 30", s=sub):
                    if r["id"]:
                        doc_ids.append(str(r["id"]))
                        rels.append({"from": sub, "rel": "BELONGS_TO", "to": r["fn"]})
                for r in s.run("MATCH (x:Subsidiary {name:$s})-[:OPERATES]->(m:Mine) RETURN m.name AS name LIMIT 30", s=sub):
                    rels.append({"from": sub, "rel": "OPERATES", "to": r["name"]})
    except Exception as e:
        logger.warning(f"graph_related failed: {e}")
    return {"document_ids": list(dict.fromkeys(doc_ids)), "relationships": rels[:20], "entities": codes}


@app.get("/graph/entities")
def graph_entities(authorization: Optional[str] = Header(None)):
    """Entities extracted from the corpus (canonical name, type, aliases, mention count)."""
    get_current_user(authorization)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT e.canonical_name, e.entity_type, e.aliases,
                       COUNT(de.document_id)::int AS mentions
                FROM entities e LEFT JOIN document_entities de ON e.id = de.entity_id
                GROUP BY e.id, e.canonical_name, e.entity_type, e.aliases
                ORDER BY mentions DESC, e.entity_type;
            """)
            rows = cur.fetchall()
            by_type = {}
            for r in rows:
                by_type[r["entity_type"]] = by_type.get(r["entity_type"], 0) + 1
            return {"total": len(rows), "by_type": by_type,
                    "entities": [{"name": r["canonical_name"], "type": r["entity_type"],
                                  "aliases": r["aliases"], "mentions": r["mentions"]} for r in rows[:60]]}
    finally:
        conn.close()


@app.get("/graph/subsidiary/{name}")
def graph_subsidiary(name: str, authorization: Optional[str] = Header(None)):
    user = get_current_user(authorization)
    if not verify_document_access(user, name.upper()):
        raise HTTPException(status_code=403, detail=f"Not authorized for subsidiary '{name}'")
    drv = get_graph()
    if not drv:
        raise HTTPException(status_code=503, detail="Neo4j knowledge graph is unavailable")
    with drv.session() as s:
        mines = s.run("MATCH (sub:Subsidiary {name:$n})-[:OPERATES]->(m:Mine) RETURN m.name AS name ORDER BY name",
                      n=name.upper()).value()
        docs = s.run("MATCH (d:Document)-[:BELONGS_TO]->(sub:Subsidiary {name:$n}) RETURN d.filename AS filename, d.doc_type AS doc_type ORDER BY filename",
                     n=name.upper()).data()
        topics = s.run("MATCH (d:Document)-[:BELONGS_TO]->(sub:Subsidiary {name:$n}) MATCH (d)-[:HAS_TOPIC]->(t:Topic) RETURN DISTINCT t.name AS topic",
                       n=name.upper()).value()
    return {"subsidiary": name.upper(), "mines": mines, "documents": docs, "topics": topics}
