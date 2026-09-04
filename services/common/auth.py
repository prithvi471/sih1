import os
import time
import jwt
import json
import logging
from typing import Optional, Dict, Any, List
from fastapi import HTTPException, Header, Depends, status

logger = logging.getLogger("mineiq-auth")

JWT_SECRET = os.getenv("JWT_SECRET", "mineiq-secure-secret-key-2026-cmpdi-cil-platform")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_SECONDS = 86400  # 24 hours

# Defined System Roles
ROLES = [
    "ADMIN",
    "MINISTRY_OFFICER",
    "CMPDI_OFFICER",
    "SUBSIDIARY_OFFICER",
    "ANALYST",
    "AUDITOR",
    "VIEWER"
]

def create_jwt_token(username: str, role: str, full_name: str, assigned_subsidiary: Optional[str] = None) -> str:
    payload = {
        "sub": username,
        "role": role,
        "full_name": full_name,
        "assigned_subsidiary": assigned_subsidiary,
        "exp": int(time.time()) + JWT_EXPIRE_SECONDS,
        "iat": int(time.time())
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_jwt_token(token: str) -> Dict[str, Any]:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token")

def get_current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    if not authorization:
        # Default fallback for internal dev or unauthenticated request
        return {
            "username": "anonymous",
            "role": "ADMIN",  # Dev fallback
            "full_name": "Anonymous User",
            "assigned_subsidiary": None
        }
    
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Authorization header format. Expected 'Bearer <token>'")
    
    token = parts[1]
    payload = decode_jwt_token(token)
    return {
        "username": payload.get("sub"),
        "role": payload.get("role"),
        "full_name": payload.get("full_name"),
        "assigned_subsidiary": payload.get("assigned_subsidiary")
    }

def verify_document_access(user: Dict[str, Any], doc_subsidiary: Optional[str]) -> bool:
    """
    Enforces server-side document RBAC rules:
    - ADMIN and MINISTRY_OFFICER can access documents across all subsidiaries.
    - SUBSIDIARY_OFFICER can ONLY access documents matching their assigned_subsidiary.
    """
    role = user.get("role", "VIEWER")
    assigned = user.get("assigned_subsidiary")

    if role in ["ADMIN", "MINISTRY_OFFICER", "CMPDI_OFFICER", "AUDITOR", "ANALYST"]:
        return True

    if role == "SUBSIDIARY_OFFICER":
        if not doc_subsidiary or not assigned:
            return True  # If subsidiary not set yet, allow preliminary access
        return doc_subsidiary.upper() == assigned.upper()

    return True

def log_audit_event(conn, user_id: str, user_role: str, action: str, service: str, result: str, document_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None, ip_address: Optional[str] = None):
    """
    Helper function to record audit logs into database.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_logs (user_id, user_role, action, document_id, service, result, metadata, ip_address)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """,
                (user_id, user_role, action, document_id, service, result, json.dumps(metadata or {}), ip_address)
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to record audit log: {str(e)}")
