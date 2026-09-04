import os
import time
import jwt
import json
import hmac
import logging
from typing import Optional, Dict, Any, List
from fastapi import HTTPException, Header, Depends, status

try:
    import bcrypt
except ImportError:  # pragma: no cover - bcrypt is a declared dependency
    bcrypt = None

logger = logging.getLogger("mineiq-auth")

JWT_SECRET = os.getenv("JWT_SECRET", "mineiq-secure-secret-key-2026-cmpdi-cil-platform")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_SECONDS = 86400  # 24 hours

# ---------------------------------------------------------------------------
# Optional Keycloak / OIDC integration (OFF by default).
# When KEYCLOAK_ENABLED=true, RS256 tokens are validated against the realm's
# JWKS and Keycloak realm-roles are mapped onto MineIQ roles. The existing
# HS256 demo tokens keep working, so nothing changes unless this is enabled.
# ---------------------------------------------------------------------------
KEYCLOAK_ENABLED = os.getenv("KEYCLOAK_ENABLED", "false").lower() == "true"
KEYCLOAK_JWKS_URL = os.getenv("KEYCLOAK_JWKS_URL", "")
_jwks_client = None


def _keycloak_decode(token: str) -> Dict[str, Any]:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(KEYCLOAK_JWKS_URL)
    signing_key = _jwks_client.get_signing_key_from_jwt(token).key
    payload = jwt.decode(token, signing_key, algorithms=["RS256"], options={"verify_aud": False})
    realm_roles = payload.get("realm_access", {}).get("roles", [])
    role = next((r for r in realm_roles if r in ROLES), "VIEWER")
    return {
        "sub": payload.get("preferred_username") or payload.get("sub"),
        "role": role,
        "full_name": payload.get("name") or payload.get("preferred_username"),
        "assigned_subsidiary": payload.get("assigned_subsidiary"),
    }

ROLES = [
    "ADMIN",
    "MINISTRY_OFFICER",
    "CMPDI_OFFICER",
    "SUBSIDIARY_OFFICER",
    "ANALYST",
    "AUDITOR",
    "VIEWER"
]

# Role -> granted permissions. "*" means every permission (super-user).
ROLE_PERMISSIONS: Dict[str, set] = {
    "ADMIN": {"*"},
    "MINISTRY_OFFICER": {
        "documents.read", "reports.read", "reports.export",
        "analytics.read", "rag.query", "audit.read", "users.read",
    },
    "CMPDI_OFFICER": {
        "documents.read", "documents.upload", "reports.read",
        "reports.export", "analytics.read", "rag.query",
    },
    "SUBSIDIARY_OFFICER": {
        "documents.read", "documents.upload", "reports.read",
        "reports.export", "analytics.read", "rag.query",
    },
    "ANALYST": {"documents.read", "reports.read", "analytics.read", "rag.query"},
    "AUDITOR": {"audit.read", "documents.read", "reports.read", "users.read"},
    "VIEWER": {"documents.read", "reports.read"},
}

ALL_PERMISSIONS = sorted({p for perms in ROLE_PERMISSIONS.values() for p in perms if p != "*"} | {"users.write"})


def has_permission(user: Dict[str, Any], permission: str) -> bool:
    perms = ROLE_PERMISSIONS.get(user.get("role", "VIEWER"), set())
    return "*" in perms or permission in perms


def require_permission(permission: str):
    """FastAPI dependency factory enforcing a permission on the caller's role."""
    def _dep(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        if not has_permission(user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.get('role')}' lacks required permission '{permission}'",
            )
        return user
    return _dep


# ---------------------------------------------------------------------------
# Password hashing (bcrypt) with transparent upgrade from legacy plaintext.
# ---------------------------------------------------------------------------
def hash_password(plain: str) -> str:
    if bcrypt is None:
        raise RuntimeError("bcrypt is not installed")
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def is_hashed(stored: Optional[str]) -> bool:
    return bool(stored) and stored.startswith("$2")


def verify_password(plain: str, stored: Optional[str]) -> bool:
    """Verify a password against a bcrypt hash, or a legacy plaintext value."""
    if not stored:
        return False
    if is_hashed(stored):
        if bcrypt is None:
            return False
        try:
            return bcrypt.checkpw(plain.encode("utf-8"), stored.encode("utf-8"))
        except Exception:
            return False
    # Legacy plaintext password (pre-hashing). Constant-time compare.
    return hmac.compare_digest(plain, stored)

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
        # Keycloak path only when explicitly enabled AND the token is RS256.
        if KEYCLOAK_ENABLED and KEYCLOAK_JWKS_URL:
            try:
                if jwt.get_unverified_header(token).get("alg") == "RS256":
                    return _keycloak_decode(token)
            except HTTPException:
                raise
            except Exception as ke:
                logger.warning(f"Keycloak token validation failed, falling back to HS256: {ke}")
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token")

def get_current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    if not authorization:
        return {
            "username": "anonymous",
            "role": "ADMIN",
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
    role = user.get("role", "VIEWER")
    assigned = user.get("assigned_subsidiary")

    if role in ["ADMIN", "MINISTRY_OFFICER", "CMPDI_OFFICER", "AUDITOR", "ANALYST"]:
        return True

    if role == "SUBSIDIARY_OFFICER":
        if not doc_subsidiary or not assigned:
            return True
        return doc_subsidiary.upper() == assigned.upper()

    return True

def log_audit_event(conn, user_id: str, user_role: str, action: str, service: str, result: str, document_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None, ip_address: Optional[str] = None):
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
