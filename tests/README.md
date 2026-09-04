# MineIQ test suite

Integration + security + E2E tests that run against a **live stack**
(`docker compose up -d`). They use only the standard library plus `pytest`,
so no `requests`/`httpx` install is required.

## Run

```bash
# from the mineiq/ directory, with the stack running:
pip install pytest
pytest tests/ -v
```

Base URLs default to the host-exposed ports and can be overridden with env
vars (`ING_URL`, `OCR_URL`, `RAG_URL`, `ANALYTICS_URL`, `PQ_URL`) — e.g. when
running inside the compose network against service names.

## Coverage

| File | Area (spec §) |
|---|---|
| `test_health.py` | services up, Qdrant is the vector store (§50, §12) |
| `test_auth_rbac.py` | login, bcrypt, permissions, subsidiary scoping (§31–32) |
| `test_extraction.py` | measured extraction accuracy, no fabricated numbers (§64, §68) |
| `test_rag_security.py` | grounded RAG, SQL-numeric path, **secure-RAG isolation**, discrepancies (§14–16, §33, §62) |
| `test_pq_copilot.py` | PQ analyze → cited draft → approval, RBAC (§18–23) |
| `test_e2e.py` | upload → extract → validate → classify → report (§55) |
| `test_secret_scan.py` | no `.env` or real secrets committed (§62) |
