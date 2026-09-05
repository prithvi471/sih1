"""Historical PQ pipeline (spec Phase 4). Pipeline is tested; the real corpus
is MISSING, so the feature is NOT marked PASS here — only the pipeline."""
from conftest import PQ, get, post


def test_historical_format_documented(ministry):
    st, d = get(f"{PQ}/api/parliament/historical/format", token=ministry)
    assert st == 200
    assert "question_text" in d["required"]
    assert "answer_text" in d["record_schema"]


def test_empty_ingest_is_safe(ministry):
    st, d = post(f"{PQ}/api/parliament/historical/ingest", token=ministry, body=[])
    assert st == 200
    assert d["ingested"] == 0


def test_corpus_status_reported_honestly(ministry):
    # With no real historical dataset ingested, the corpus must report MISSING
    # rather than pretending to be populated.
    st, d = get(f"{PQ}/api/parliament/historical/search", token=ministry)
    assert st == 200
    assert "corpus_status" in d
    assert d["corpus_size"] == 0
    assert "MISSING" in d["corpus_status"]
