from psycopg2.extras import RealDictCursor
import os
import re
import json
import logging
from typing import Optional
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
try:
    # pyrefly: ignore [missing-import]
    from rapidfuzz import fuzz
except ImportError:
    from difflib import SequenceMatcher

    class FuzzFallback:
        @staticmethod
        def token_sort_ratio(s1: str, s2: str) -> float:
            s1_sorted = " ".join(sorted((s1 or "").split()))
            s2_sorted = " ".join(sorted((s2 or "").split()))
            return SequenceMatcher(None, s1_sorted, s2_sorted).ratio() * 100.0

    fuzz = FuzzFallback()

logger = logging.getLogger("validation-service")

app = FastAPI(
    title="MineIQ Data Validation & Consistency Engine",
    description="Cross-checks extracted document text against historical records, flags anomalies and near-duplicates."
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
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "85.0"))


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
        logger.error(f"Database connection failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database connection error: {str(e)}"
        )



class ValidateRequest(BaseModel):
    document_id: str
    extracted_text: str


class ValidateResponse(BaseModel):
    document_id: str
    status: str
    flag_reason: Optional[str] = None
    is_duplicate: bool


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/validate", response_model=ValidateResponse)
def validate_document(payload: ValidateRequest):
    logger.info(f"Validating document_id={payload.document_id}, text_len={len(payload.extracted_text)}")
    
    extracted_text = payload.extracted_text or ""
    text_stripped = extracted_text.strip()
    flag_reasons = []
    is_duplicate = False

    # 1. Anomaly Check: Empty or near-empty text
    if len(text_stripped) < 10:
        flag_reasons.append("Empty or near-empty extracted text")

    # 2. Anomaly Check: Garbled text / Low alphabetic character ratio
    non_space_chars = [c for c in text_stripped if not c.isspace()]
    if len(non_space_chars) >= 20:
        alpha_chars = [c for c in non_space_chars if c.isalnum()]
        alpha_ratio = len(alpha_chars) / len(non_space_chars)
        if alpha_ratio < 0.40:
            flag_reasons.append(f"Low alphanumeric character ratio ({alpha_ratio:.2f}) — possible garbled OCR")

    # 3. Near-Duplicate Check against historical records in Postgres
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, extracted_text 
                FROM documents 
                WHERE extracted_text IS NOT NULL AND id != %s 
                ORDER BY updated_at DESC 
                LIMIT 50;
                """,
                (payload.document_id,)
            )
            recent_docs = cur.fetchall()

            for doc in recent_docs:
                past_text = doc.get("extracted_text") or ""
                if not past_text.strip():
                    continue
                
                similarity = fuzz.token_sort_ratio(extracted_text, past_text)
                if similarity >= SIMILARITY_THRESHOLD:
                    is_duplicate = True
                    match_id = str(doc["id"])
                    flag_reasons.append(f"Near duplicate detected ({similarity:.1f}% similarity with document {match_id})")
                    break

            # 3b. Cross-Document Numerical Consistency Check.
            # Aligns the current document's structured rows to other documents'
            # rows by the SAME fact key (subsidiary, mine, year, metric) — so a
            # conflict means two documents genuinely disagree on the same figure,
            # not just that two different mines have different production.
            try:
                _METRICS = {
                    "production_target_mt": "production target (MT)",
                    "actual_production_mt": "actual production (MT)",
                    "dispatch_mt": "dispatch (MT)",
                    "overburden_mcum": "overburden (MCuM)",
                }

                def _norm_mine(name):
                    return re.sub(r'\s+', ' ', name.strip().lower()) if name else None

                # Current document's structured rows (inserted upstream before validation).
                cur.execute(
                    """
                    SELECT mine_name, subsidiary, report_year,
                           production_target_mt, actual_production_mt, dispatch_mt, overburden_mcum
                    FROM structured_data WHERE document_id = %s;
                    """,
                    (payload.document_id,)
                )
                current_rows = cur.fetchall()

                for cr in current_rows:
                    mine = cr.get("mine_name")
                    year = cr.get("report_year")
                    sub = cr.get("subsidiary")
                    if not mine or not year:
                        continue

                    cur.execute(
                        """
                        SELECT d.id, d.original_filename, s.mine_name,
                               s.production_target_mt, s.actual_production_mt,
                               s.dispatch_mt, s.overburden_mcum
                        FROM structured_data s
                        JOIN documents d ON s.document_id = d.id
                        WHERE s.document_id != %s AND s.report_year = %s
                          AND (s.subsidiary = %s OR (%s IS NULL AND s.subsidiary IS NULL));
                        """,
                        (payload.document_id, year, sub, sub)
                    )
                    for comp in cur.fetchall():
                        if _norm_mine(comp.get("mine_name")) != _norm_mine(mine):
                            continue
                        for col, label in _METRICS.items():
                            cur_val = cr.get(col)
                            comp_val = comp.get(col)
                            if cur_val is None or comp_val is None:
                                continue
                            diff = abs(float(cur_val) - float(comp_val))
                            denom = max(abs(float(cur_val)), abs(float(comp_val))) or 1.0
                            pct = diff / denom * 100.0
                            if diff < 0.5 or pct < 1.0:
                                continue
                            severity = "critical" if pct >= 10.0 else ("warning" if pct >= 3.0 else "info")
                            msg = (
                                f"{label} for {mine} ({sub} {year}): this document reports "
                                f"{cur_val} vs {comp_val} in {comp['original_filename']} "
                                f"(diff {round(diff, 2)}, {round(pct, 1)}%)"
                            )
                            flag_reasons.append(msg)
                            cur.execute(
                                """
                                INSERT INTO domain_validations (document_id, check_type, severity, message, competing_doc_id, details)
                                VALUES (%s, 'inconsistency', %s, %s, %s, %s);
                                """,
                                (
                                    payload.document_id, severity, msg, str(comp["id"]),
                                    json.dumps({
                                        "metric": col, "mine_name": mine, "report_year": year,
                                        "subsidiary": sub, "current_val": float(cur_val),
                                        "comp_val": float(comp_val), "difference": round(diff, 2),
                                        "pct_difference": round(pct, 2),
                                    })
                                )
                            )
            except Exception as cd_err:
                logger.warning(f"Cross-document consistency check notice: {str(cd_err)}")

            # Status determination: 'flagged' if any flag exists, else 'validated'
            final_status = "flagged" if (flag_reasons or is_duplicate) else "validated"
            combined_flag_reason = " | ".join(flag_reasons) if flag_reasons else None

            # 4. Update the documents row in PostgreSQL
            cur.execute(
                """
                UPDATE documents 
                SET extracted_text = %s,
                    status = %s::document_status_enum,
                    flag_reason = %s,
                    is_duplicate = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
                """,
                (
                    extracted_text,
                    final_status,
                    combined_flag_reason,
                    is_duplicate,
                    payload.document_id
                )
            )
            conn.commit()

            return ValidateResponse(
                document_id=payload.document_id,
                status=final_status,
                flag_reason=combined_flag_reason,
                is_duplicate=is_duplicate
            )
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Validation failed for document_id={payload.document_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Validation processing failed: {str(e)}"
        )
    finally:
        conn.close()
