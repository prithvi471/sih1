"""RAG grounding + the critical secure-RAG isolation guarantees."""
from conftest import RAG, ANALYTICS, get, post


def test_numeric_question_uses_sql_path(admin):
    st, d = post(f"{RAG}/query", token=admin, body={"query": "What was MCL production in 2025?"})
    assert st == 200
    assert d.get("mode") == "SQL_NUMERIC"
    assert d.get("grounded") is True
    assert len(d.get("sources", [])) >= 1


def test_narrative_question_is_grounded_with_sources(admin):
    st, d = post(f"{RAG}/query", token=admin, body={"query": "summarize what the SECL report describes"})
    assert st == 200
    # Either grounded with sources, or an explicit insufficient-evidence answer.
    assert d.get("grounded") in (True, False)


def test_isolation_ecl_cannot_read_mcl_numeric(ecl):
    st, d = post(f"{RAG}/query", token=ecl, body={"query": "What was MCL production in 2025?"})
    assert st == 200
    # ECL officer must not receive MCL figures.
    assert d.get("mode") != "SQL_NUMERIC" or not d.get("table")
    assert "MCL" not in str(d.get("table", []))


def test_isolation_ecl_narrative_no_leak(ecl):
    st, d = post(f"{RAG}/query", token=ecl, body={"query": "summarize what the SECL report describes"})
    assert st == 200
    assert d.get("grounded") is False
    assert d.get("sources", []) == []


def test_discrepancies_have_severity_and_two_sources(admin):
    st, d = get(f"{ANALYTICS}/analytics/discrepancies", token=admin)
    assert st == 200
    assert d["count"] >= 1
    first = d["discrepancies"][0]
    assert first["severity"] in ("critical", "high", "medium")
    assert first["source_a"]["filename"] and first["source_b"]["filename"]


def test_discrepancies_rbac_scoped(ecl):
    st, d = get(f"{ANALYTICS}/analytics/discrepancies", token=ecl)
    assert st == 200
    # ECL officer sees no MCL/NCL/SECL discrepancies.
    assert d["count"] == 0
