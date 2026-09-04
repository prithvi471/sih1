"""Repository hygiene: no real secrets or .env committed (spec 62)."""
import os
import re
import subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _tracked_files():
    try:
        out = subprocess.check_output(["git", "ls-files"], cwd=ROOT).decode()
        return [f for f in out.splitlines() if f.strip()]
    except Exception:
        return []


def test_env_not_committed():
    files = _tracked_files()
    assert files, "git ls-files returned nothing"
    assert ".env" not in files
    assert not any(f.endswith("/.env") for f in files)


def test_no_obvious_secrets_in_source():
    # Patterns for genuine secrets. The demo defaults (admin123, minioadmin,
    # mineiq_pass) are intentional fixtures and are NOT matched here.
    patterns = [
        re.compile(r"AKIA[0-9A-Z]{16}"),                 # AWS access key id
        re.compile(r"-----BEGIN (RSA |EC )?PRIVATE KEY----"),
        re.compile(r"sk-[A-Za-z0-9]{32,}"),              # OpenAI-style key
        re.compile(r"ghp_[A-Za-z0-9]{36}"),              # GitHub PAT
    ]
    offenders = []
    for f in _tracked_files():
        if f.endswith((".png", ".jpg", ".pdf", ".xlsx", ".ico")):
            continue
        path = os.path.join(ROOT, f)
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except Exception:
            continue
        for p in patterns:
            if p.search(text):
                offenders.append(f)
                break
    assert not offenders, f"possible secrets committed in: {offenders}"
