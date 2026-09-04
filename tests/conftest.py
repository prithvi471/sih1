"""
Shared helpers + fixtures for the MineIQ test suite.

These are integration tests that run against a LIVE stack (docker compose up).
They use only the standard library (urllib) so the only dependency is pytest.
Override base URLs with env vars (e.g. ING_URL) when running inside the
compose network instead of against host-exposed ports.
"""
import os
import json
import urllib.request
import urllib.error
import pytest

ING = os.getenv("ING_URL", "http://localhost:8000")
OCR = os.getenv("OCR_URL", "http://localhost:8002")
RAG = os.getenv("RAG_URL", "http://localhost:8005")
ANALYTICS = os.getenv("ANALYTICS_URL", "http://localhost:8006")
PQ = os.getenv("PQ_URL", "http://localhost:8007")

CREDS = {
    "admin": "admin123",
    "ministry_officer": "ministry123",
    "cmpdi_officer": "cmpdi123",
    "mcl_officer": "mcl123",
    "ecl_officer": "ecl123",
    "auditor_user": "audit123",
}


def _req(method, url, token=None, body=None, timeout=120):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw}


def get(url, token=None, **kw):
    return _req("GET", url, token, **kw)


def post(url, token=None, body=None, **kw):
    return _req("POST", url, token, body, **kw)


def login(username):
    st, d = post(f"{ING}/auth/login", body={"username": username, "password": CREDS[username]})
    assert st == 200, f"login {username} failed: {st} {d}"
    return d["access_token"]


@pytest.fixture(scope="session")
def admin():
    return login("admin")


@pytest.fixture(scope="session")
def ecl():
    return login("ecl_officer")


@pytest.fixture(scope="session")
def mcl():
    return login("mcl_officer")


@pytest.fixture(scope="session")
def ministry():
    return login("ministry_officer")
