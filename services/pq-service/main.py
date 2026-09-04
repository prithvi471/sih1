import os
import re
import json
import logging
from datetime import date, datetime, timedelta
from typing import Optional, List, Dict, Any

import httpx
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from auth import (get_current_user, verify_document_access, log_audit_event,
                  require_permission, has_permission)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pq-service")

app = FastAPI(title="MineIQ Parliamentary Question Copilot",
              description="Registers PQs, gathers grounded evidence (SQL + RAG), drafts cited responses, human approval.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "mineiq_docs")
DB_USER = os.getenv("DB_USER", "mineiq")
DB_PASSWORD = os.getenv("DB_PASSWORD", "mineiq_pass")
RAG_SERVICE_URL = os.getenv("RAG_SERVICE_URL", "http://rag-service:8000")
ANALYTICS_SERVICE_URL = os.getenv("ANALYTICS_SERVICE_URL", "http://analytics-service:8000")

SUBSIDIARY_RE = re.compile(r'\b(ECL|BCCL|CCL|WCL|SECL|MCL|NCL|CMPDI)\b', re.IGNORECASE)
_SUB_FULLNAMES = [
    ("south eastern coalfields", "SECL"), ("eastern coalfields", "ECL"),
    ("western coalfields", "WCL"), ("central coalfields", "CCL"),
    ("northern coalfields", "NCL"), ("mahanadi coalfields", "MCL"),
    ("bharat coking coal", "BCCL"), ("central mine planning", "CMPDI"),
]
_METRIC_KEYWORDS = {
    "production": ("production", "produce", "output", "raised"),
    "dispatch": ("dispatch", "despatch", "offtake", "off-take"),
    "target": ("target", "planned"),
    "overburden": ("overburden", "ob "),
}
_TOPIC_KEYWORDS = {
    "Production": ("production", "dispatch", "offtake", "output"),
    "Geological": ("geolog", "borehole", "reserve", "exploration", "seam"),
    "Safety": ("safety", "accident", "fatal", "injury", "incident"),
    "Environment": ("environment", "pollution", "rehabilit", "forest", "water"),
    "Equipment": ("equipment", "machine", "hemm", "breakdown"),
}
_TOPIC_DEPT = {"Production": "Production Dept", "Geological": "Geological Dept",
               "Safety": "Safety Dept", "Environment": "Environment Dept",
               "Equipment": "Equipment Dept"}


def get_db():
    conn = psycopg2.connect(host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                            user=DB_USER, password=DB_PASSWORD, cursor_factory=RealDictCursor)
    ensure_schema(conn)
    return conn


_PQ_SCHEMA = """
CREATE TABLE IF NOT EXISTS parliamentary_questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pq_number VARCHAR(50) UNIQUE,
    question_text TEXT NOT NULL,
    house VARCHAR(50), member_name VARCHAR(150),
    ministry VARCHAR(150) DEFAULT 'Ministry of Coal',
    received_date DATE DEFAULT CURRENT_DATE, due_date DATE,
    subsidiaries VARCHAR(50)[] DEFAULT ARRAY[]::VARCHAR(50)[],
    metrics VARCHAR(50)[] DEFAULT ARRAY[]::VARCHAR(50)[],
    topics VARCHAR(100)[] DEFAULT ARRAY[]::VARCHAR(100)[],
    period_from INT, period_to INT,
    status VARCHAR(30) NOT NULL DEFAULT 'REGISTERED',
    analysis JSONB DEFAULT '{}'::jsonb, created_by VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pq_status ON parliamentary_questions(status);
CREATE TABLE IF NOT EXISTS pq_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pq_id UUID REFERENCES parliamentary_questions(id) ON DELETE CASCADE,
    subsidiary VARCHAR(50) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'OPEN', assigned_user VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (pq_id, subsidiary)
);
CREATE TABLE IF NOT EXISTS parliamentary_responses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pq_id UUID REFERENCES parliamentary_questions(id) ON DELETE CASCADE,
    draft_text TEXT NOT NULL, sources JSONB DEFAULT '[]'::jsonb,
    data_table JSONB DEFAULT '[]'::jsonb, discrepancies JSONB DEFAULT '[]'::jsonb,
    status VARCHAR(30) NOT NULL DEFAULT 'DRAFT',
    generated_by VARCHAR(100), approved_by VARCHAR(100), approved_at TIMESTAMPTZ,
    review_note TEXT, generated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pq_responses_pq ON parliamentary_responses(pq_id);
"""


def ensure_schema(conn):
    old = conn.autocommit
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(_PQ_SCHEMA)
    except Exception as e:
        logger.debug(f"schema notice: {e}")
    finally:
        conn.autocommit = old


def detect_subsidiary(text: str):
    subs = {m.group(1).upper() for m in SUBSIDIARY_RE.finditer(text)}
    low = text.lower()
    for phrase, code in _SUB_FULLNAMES:
        if phrase in low:
            subs.add(code)
    return sorted(subs)


def analyze_question(text: str) -> Dict[str, Any]:
    low = text.lower()
    subs = detect_subsidiary(text)
    metrics = [m for m, kws in _METRIC_KEYWORDS.items() if any(k in low for k in kws)]
    topics = [t for t, kws in _TOPIC_KEYWORDS.items() if any(k in low for k in kws)]
    if not topics:
        topics = ["Production"] if metrics else ["General"]
    departments = sorted({_TOPIC_DEPT.get(t) for t in topics if t in _TOPIC_DEPT})
    years = sorted({int(y) for y in re.findall(r'\b(20[12]\d)\b', text)})
    rng = re.search(r'\b(20[12]\d)\s*(?:-|to|through|and|–)\s*(20[12]\d)\b', low)
    period_from = period_to = None
    if rng:
        period_from, period_to = sorted([int(rng.group(1)), int(rng.group(2))])
    elif years:
        period_from, period_to = min(years), max(years)
    elif re.search(r'last\s+(five|5)\s+year', low):
        period_to = date.today().year
        period_from = period_to - 4
    missing = []
    if not subs:
        missing.append("No subsidiary identified in the question")
    if not metrics:
        missing.append("No specific metric identified")
    if period_from is None:
        missing.append("No time period identified")
    return {"subsidiaries": subs, "metrics": metrics or ["production"], "topics": topics,
            "departments": departments, "period_from": period_from, "period_to": period_to,
            "missing_information": missing}


class RegisterPQ(BaseModel):
    question_text: str
    pq_number: Optional[str] = None
    house: Optional[str] = "Lok Sabha"
    member_name: Optional[str] = None
    due_date: Optional[str] = None


class ReviewBody(BaseModel):
    decision: str  # APPROVED / REJECTED
    note: Optional[str] = None


@app.get("/health")
def health():
    return {"status": "ok"}


def _serialize_pq(p: dict) -> dict:
    for k in ("received_date", "due_date"):
        if p.get(k):
            p[k] = p[k].isoformat()
    for k in ("created_at", "updated_at"):
        if p.get(k):
            p[k] = p[k].isoformat()
    p["id"] = str(p["id"])
    return p


@app.post("/api/parliament/questions", status_code=201)
def register_pq(body: RegisterPQ, user: dict = Depends(require_permission("pq.write"))):
    a = analyze_question(body.question_text)
    due = body.due_date
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO parliamentary_questions
                    (pq_number, question_text, house, member_name, due_date, subsidiaries,
                     metrics, topics, period_from, period_to, status, analysis, created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ANALYZED',%s,%s)
                RETURNING *;
                """,
                (body.pq_number, body.question_text, body.house, body.member_name, due or None,
                 a["subsidiaries"], a["metrics"], a["topics"], a["period_from"], a["period_to"],
                 json.dumps(a), user["username"]),
            )
            pq = cur.fetchone()
            pq_id = pq["id"]
            for s in a["subsidiaries"]:
                cur.execute("INSERT INTO pq_tasks (pq_id, subsidiary) VALUES (%s,%s) ON CONFLICT DO NOTHING;",
                            (pq_id, s))
            conn.commit()
            log_audit_event(conn, user["username"], user["role"], "PQ_CREATED", "pq-service", "SUCCESS",
                            metadata={"pq_id": str(pq_id), "subsidiaries": a["subsidiaries"]})
            return _serialize_pq(pq)
    finally:
        conn.close()


@app.get("/api/parliament/questions")
def list_pq(user: dict = Depends(require_permission("pq.read"))):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM parliamentary_questions ORDER BY created_at DESC;")
            rows = cur.fetchall()
            # RBAC: a subsidiary officer only sees PQs touching their subsidiary.
            out = []
            for p in rows:
                subs = p.get("subsidiaries") or []
                if user["role"] == "SUBSIDIARY_OFFICER" and user.get("assigned_subsidiary"):
                    if user["assigned_subsidiary"].upper() not in [s.upper() for s in subs]:
                        continue
                out.append(_serialize_pq(p))
            return out
    finally:
        conn.close()


def _get_pq(cur, pq_id):
    cur.execute("SELECT * FROM parliamentary_questions WHERE id = %s;", (pq_id,))
    return cur.fetchone()


@app.get("/api/parliament/questions/{pq_id}")
def get_pq(pq_id: str, user: dict = Depends(require_permission("pq.read"))):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            pq = _get_pq(cur, pq_id)
            if not pq:
                raise HTTPException(404, "PQ not found")
            cur.execute("SELECT subsidiary, status, assigned_user FROM pq_tasks WHERE pq_id = %s ORDER BY subsidiary;", (pq_id,))
            tasks = cur.fetchall()
            cur.execute("SELECT * FROM parliamentary_responses WHERE pq_id = %s ORDER BY generated_at DESC LIMIT 1;", (pq_id,))
            resp = cur.fetchone()
            out = _serialize_pq(pq)
            out["tasks"] = tasks
            if resp:
                resp["id"] = str(resp["id"]); resp["pq_id"] = str(resp["pq_id"])
                if resp.get("generated_at"): resp["generated_at"] = resp["generated_at"].isoformat()
                if resp.get("approved_at"): resp["approved_at"] = resp["approved_at"].isoformat()
            out["response"] = resp
            return out
    finally:
        conn.close()


def _gather_year_table(cur, user, subs, pf, pt):
    """Year-wise production/dispatch totals per subsidiary from structured_data (SQL, RBAC-filtered)."""
    where = ["subsidiary = ANY(%s)"]
    params: List[Any] = [subs]
    if pf is not None and pt is not None:
        where.append("report_year BETWEEN %s AND %s")
        params += [pf, pt]
    cur.execute(
        f"""
        SELECT subsidiary, report_year,
               ROUND(SUM(actual_production_mt),2) AS actual,
               ROUND(SUM(production_target_mt),2) AS target,
               ROUND(SUM(dispatch_mt),2) AS dispatch,
               COUNT(*) AS mines
        FROM structured_data
        WHERE {' AND '.join(where)} AND subsidiary IS NOT NULL AND report_year IS NOT NULL
        GROUP BY subsidiary, report_year ORDER BY subsidiary, report_year;
        """, tuple(params))
    rows = [dict(r) for r in cur.fetchall()]
    return [r for r in rows if verify_document_access(user, r.get("subsidiary"))]


def _rag_narrative(question, authorization):
    try:
        with httpx.Client(timeout=90.0) as c:
            r = c.post(f"{RAG_SERVICE_URL}/query",
                       headers={"Authorization": authorization} if authorization else {},
                       json={"query": question, "top_k": 4, "mode": "CROSS_DOCUMENT"})
            if r.status_code == 200:
                d = r.json()
                return d.get("answer", ""), d.get("sources", [])
    except Exception as e:
        logger.warning(f"RAG narrative failed: {e}")
    return "", []


def _discrepancies(authorization):
    try:
        with httpx.Client(timeout=30.0) as c:
            r = c.get(f"{ANALYTICS_SERVICE_URL}/analytics/discrepancies",
                      headers={"Authorization": authorization} if authorization else {})
            if r.status_code == 200:
                return r.json().get("discrepancies", [])
    except Exception as e:
        logger.warning(f"Discrepancy fetch failed: {e}")
    return []


@app.post("/api/parliament/questions/{pq_id}/generate-draft")
def generate_draft(pq_id: str, authorization: Optional[str] = Header(None),
                   user: dict = Depends(require_permission("pq.write"))):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            pq = _get_pq(cur, pq_id)
            if not pq:
                raise HTTPException(404, "PQ not found")
            subs = pq.get("subsidiaries") or []
            pf, pt = pq.get("period_from"), pq.get("period_to")

            table = _gather_year_table(cur, user, subs, pf, pt) if subs else []
            narrative, rag_sources = _rag_narrative(pq["question_text"], authorization)
            all_disc = _discrepancies(authorization)
            relevant_disc = [d for d in all_disc if d.get("subsidiary") in subs] if subs else all_disc

            # ---- Assemble structured, cited draft ----
            period_str = f"{pf}–{pt}" if pf and pt else "the requested period"
            lines = ["# AI-GENERATED DRAFT — REQUIRES HUMAN APPROVAL", ""]
            lines.append(f"**Question:** {pq['question_text']}")
            lines.append("")
            lines.append("## Background")
            lines.append(f"This response covers {', '.join(subs) if subs else 'the applicable subsidiaries'} for {period_str}, "
                         f"compiled from structured production records held in the MineIQ knowledge base.")
            lines.append("")
            lines.append("## Direct Answer")
            if table:
                by_sub = {}
                for r in table:
                    by_sub.setdefault(r["subsidiary"], []).append(r)
                for s, rs in by_sub.items():
                    tot = sum(float(r["actual"]) for r in rs if r["actual"] is not None)
                    lines.append(f"- **{s}**: total actual production {round(tot,2)} MT across {period_str} "
                                 f"({len(rs)} reporting year(s)).")
            else:
                lines.append("- No structured production figures are available in authorized sources for the requested scope.")
            lines.append("")
            lines.append("## Supporting Figures (Year-wise)")
            if table:
                lines.append("| Subsidiary | Year | Target (MT) | Actual (MT) | Dispatch (MT) |")
                lines.append("| --- | --- | --- | --- | --- |")
                for r in table:
                    lines.append(f"| {r['subsidiary']} | {r['report_year']} | {r['target']} | {r['actual']} | {r['dispatch']} |")
            else:
                lines.append("_No year-wise figures available in authorized sources._")
            lines.append("")
            if narrative and "insufficient" not in narrative.lower():
                lines.append("## Explanation of Variations")
                lines.append(narrative.strip())
                lines.append("")
            if relevant_disc:
                lines.append("## ⚠ Data Consistency Notes")
                for d in relevant_disc[:5]:
                    lines.append(f"- {d.get('subsidiary')} {d.get('mine_name')} {d.get('report_year')} — "
                                 f"{d.get('metric_label')}: {d.get('value_a')} ({d['source_a']['filename']}) vs "
                                 f"{d.get('value_b')} ({d['source_b']['filename']}) — **{d.get('severity','').upper()}**, requires verification.")
                lines.append("")
            lines.append("## Source References")
            src_list = []
            seen = set()
            for r in table:
                key = r["subsidiary"]
                if key not in seen:
                    seen.add(key)
                    src_list.append({"type": "structured_record", "subsidiary": r["subsidiary"]})
            for s in rag_sources:
                src_list.append({"type": "document", "filename": s.get("filename"), "document_id": s.get("document_id")})
            if src_list:
                for i, s in enumerate(src_list, 1):
                    if s["type"] == "structured_record":
                        lines.append(f"{i}. Structured production records — {s['subsidiary']}")
                    else:
                        lines.append(f"{i}. {s.get('filename')} (doc {str(s.get('document_id'))[:8]})")
            else:
                lines.append("_No sources — insufficient evidence in authorized data._")
            lines.append("")
            lines.append("---")
            lines.append("*This is an AI-generated draft compiled by MineIQ from authorized records. "
                         "It is NOT an official response and MUST be reviewed and approved by an authorized officer before submission.*")

            draft_text = "\n".join(lines)

            cur.execute(
                """
                INSERT INTO parliamentary_responses (pq_id, draft_text, sources, data_table, discrepancies, status, generated_by)
                VALUES (%s,%s,%s,%s,%s,'PENDING_APPROVAL',%s) RETURNING id, generated_at;
                """,
                (pq_id, draft_text, json.dumps(src_list), json.dumps(table, default=str),
                 json.dumps(relevant_disc, default=str), user["username"]),
            )
            r = cur.fetchone()
            cur.execute("UPDATE parliamentary_questions SET status='PENDING_APPROVAL', updated_at=CURRENT_TIMESTAMP WHERE id=%s;", (pq_id,))
            conn.commit()
            log_audit_event(conn, user["username"], user["role"], "PQ_DRAFT_GENERATED", "pq-service", "SUCCESS",
                            metadata={"pq_id": pq_id, "rows": len(table), "discrepancies": len(relevant_disc)})
            return {"response_id": str(r["id"]), "status": "PENDING_APPROVAL",
                    "draft_text": draft_text, "data_table": table, "sources": src_list,
                    "discrepancies": relevant_disc}
    finally:
        conn.close()


@app.post("/api/parliament/questions/{pq_id}/review")
def review_pq(pq_id: str, body: ReviewBody, user: dict = Depends(require_permission("pq.approve"))):
    decision = body.decision.upper()
    if decision not in ("APPROVED", "REJECTED"):
        raise HTTPException(400, "decision must be APPROVED or REJECTED")
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM parliamentary_responses WHERE pq_id=%s ORDER BY generated_at DESC LIMIT 1;", (pq_id,))
            resp = cur.fetchone()
            if not resp:
                raise HTTPException(404, "No draft to review")
            cur.execute(
                "UPDATE parliamentary_responses SET status=%s, approved_by=%s, approved_at=CURRENT_TIMESTAMP, review_note=%s WHERE id=%s;",
                (decision, user["username"], body.note, resp["id"]))
            cur.execute("UPDATE parliamentary_questions SET status=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s;",
                        (decision, pq_id))
            conn.commit()
            log_audit_event(conn, user["username"], user["role"],
                            "PQ_APPROVED" if decision == "APPROVED" else "PQ_REJECTED",
                            "pq-service", "SUCCESS", metadata={"pq_id": pq_id})
            return {"pq_id": pq_id, "status": decision, "reviewed_by": user["username"]}
    finally:
        conn.close()


@app.get("/api/parliament/dashboard")
def dashboard(user: dict = Depends(require_permission("pq.read"))):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status, COUNT(*)::int c FROM parliamentary_questions GROUP BY status;")
            by_status = {r["status"]: r["c"] for r in cur.fetchall()}
            today = date.today()
            cur.execute("SELECT id, pq_number, question_text, subsidiaries, due_date, status FROM parliamentary_questions WHERE due_date IS NOT NULL ORDER BY due_date ASC;")
            rows = cur.fetchall()
            buckets = {"overdue": 0, "due_today": 0, "due_3_days": 0, "later": 0}
            for r in rows:
                d = r["due_date"]
                if d < today: buckets["overdue"] += 1
                elif d == today: buckets["due_today"] += 1
                elif d <= today + timedelta(days=3): buckets["due_3_days"] += 1
                else: buckets["later"] += 1
            cur.execute("SELECT COUNT(*)::int c FROM parliamentary_questions;")
            total = cur.fetchone()["c"]
            return {"total": total, "by_status": by_status, "deadlines": buckets}
    finally:
        conn.close()
