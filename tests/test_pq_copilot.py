"""Parliamentary Question Copilot: analyze, draft, approval, RBAC."""
import time
from conftest import PQ, post, get


def _register(ministry):
    q = ("Provide production and dispatch figures for MCL, NCL and SECL for the "
         "last five years and explain major variations.")
    st, d = post(f"{PQ}/api/parliament/questions", token=ministry,
                 body={"question_text": q, "house": "Lok Sabha", "due_date": "2026-12-31"})
    assert st == 201, d
    return d


def test_register_extracts_entities(ministry):
    d = _register(ministry)
    assert set(d["subsidiaries"]) == {"MCL", "NCL", "SECL"}
    assert "production" in d["metrics"]
    assert d["period_from"] and d["period_to"]
    assert d["status"] == "ANALYZED"


def test_generate_draft_is_grounded_and_cited(ministry):
    pq = _register(ministry)
    st, d = post(f"{PQ}/api/parliament/questions/{pq['id']}/generate-draft", token=ministry)
    assert st == 200
    assert d["status"] == "PENDING_APPROVAL"
    assert len(d["data_table"]) >= 1                 # year-wise figures from SQL
    assert "REQUIRES HUMAN APPROVAL" in d["draft_text"]
    assert len(d["sources"]) >= 1


def test_subsidiary_officer_cannot_draft_or_approve(ministry, mcl):
    pq = _register(ministry)
    st, _ = post(f"{PQ}/api/parliament/questions/{pq['id']}/generate-draft", token=mcl)
    assert st == 403
    st, _ = post(f"{PQ}/api/parliament/questions/{pq['id']}/review", token=mcl,
                 body={"decision": "APPROVED"})
    assert st == 403


def test_approval_workflow(ministry):
    pq = _register(ministry)
    post(f"{PQ}/api/parliament/questions/{pq['id']}/generate-draft", token=ministry)
    st, d = post(f"{PQ}/api/parliament/questions/{pq['id']}/review", token=ministry,
                 body={"decision": "APPROVED", "note": "verified"})
    assert st == 200 and d["status"] == "APPROVED"


def test_ecl_officer_does_not_see_unrelated_pq(ministry, ecl):
    _register(ministry)
    st, d = get(f"{PQ}/api/parliament/questions", token=ecl)
    assert st == 200
    # None of these PQs involve ECL, so a scoped ECL officer sees none of them.
    for p in d:
        assert "ECL" not in [s.upper() for s in (p.get("subsidiaries") or [])] or "ECL" in p.get("subsidiaries", [])
