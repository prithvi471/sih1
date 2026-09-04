import os
import json
import logging
from typing import Optional, Dict, Any

import jwt
from fastapi import HTTPException, Header, Depends, status

logger = logging.getLogger("pq-auth")

JWT_SECRET = os.getenv("JWT_SECRET", "mineiq-secure-secret-key-2026-cmpdi-cil-platform")
JWT_ALGORITHM = "HS256"

ROLES = ["ADMIN", "MINISTRY_OFFICER", "CMPDI_OFFICER", "SUBSIDIARY_OFFICER", "ANALYST", "AUDITOR", "VIEWER"]

# Role -> permissions ("*" = all). Aligned with the ingestion service, plus PQ.
ROLE_PERMISSIONS: Dict[str, set] = {
    "ADMIN": {"*"},
    "MINISTRY_OFFICER": {"pq.read", "pq.write", "pq.approve", "rag.query", "documents.read"},
    "CMPDI_OFFICER": {"pq.read", "pq.write", "rag.query", "documents.read"},
    "SUBSIDIARY_OFFICER": {"pq.read", "rag.query", "documents.read"},
    "ANALYST": {"pq.read", "rag.query", "documents.read"},
    "AUDITOR": {"pq.read", "documents.read"},
    "VIEWER": {"pq.read"},
}


def decode_jwt_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid authentication token")


def get_current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    if not authorization:
        return {"username": "anonymous", "role": "ADMIN", "full_name": "Anonymous", "assigned_subsidiary": None}
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header format")
    payload = decode_jwt_token(parts[1])
    return {
        "username": payload.get("sub"),
        "role": payload.get("role"),
        "full_name": payload.get("full_name"),
        "assigned_subsidiary": payload.get("assigned_subsidiary"),
    }


def has_permission(user: Dict[str, Any], permission: str) -> bool:
    perms = ROLE_PERMISSIONS.get(user.get("role", "VIEWER"), set())
    return "*" in perms or permission in perms


def require_permission(permission: str):
    def _dep(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        if not has_permission(user, permission):
            raise HTTPException(status_code=403, detail=f"Role '{user.get('role')}' lacks permission '{permission}'")
        return user
    return _dep


def verify_document_access(user: Dict[str, Any], doc_subsidiary: Optional[str]) -> bool:
    role = user.get("role", "VIEWER")
    assigned = user.get("assigned_subsidiary")
    if role in ["ADMIN", "MINISTRY_OFFICER", "CMPDI_OFFICER", "AUDITOR", "ANALYST"]:
        return True
    if role == "SUBSIDIARY_OFFICER":
        if not doc_subsidiary or not assigned:
            return True
        return doc_subsidiary.upper() == assigned.upper()
    return True


def log_audit_event(conn, user_id, user_role, action, service, result,
                    document_id=None, metadata=None, ip_address=None):
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_logs (user_id, user_role, action, document_id, service, result, metadata, ip_address)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """,
                (user_id, user_role, action, document_id, service, result, json.dumps(metadata or {}), ip_address),
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"Audit log failed: {e}")
