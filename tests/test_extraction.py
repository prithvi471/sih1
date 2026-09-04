"""Structured extraction + the measured accuracy eval (no fabricated numbers)."""
from conftest import OCR, ING, get


def test_extraction_eval_is_measured():
    st, d = get(f"{OCR}/evaluate/extraction")
    assert st == 200
    assert d["evaluated"] is True
    acc = d["extraction_accuracy_percentage"]
    assert acc is not None and 0 < acc <= 100
    assert d["fields_total"] > 0


def test_negative_case_no_spurious_records():
    # The benchmark's negative case must not hallucinate structured records.
    st, d = get(f"{OCR}/evaluate/extraction")
    assert st == 200
    neg = [c for c in d["cases"] if c["id"] == "negative_no_metrics"]
    assert neg and neg[0]["spurious_records"] == 0


def test_metrics_accuracy_is_evaluated_not_hardcoded(admin):
    st, d = get(f"{ING}/metrics", token=admin)
    assert st == 200
    # The old fabricated 94.8 is gone; accuracy is flagged as measured.
    assert d.get("extraction_accuracy_evaluated") is True
    assert d.get("extraction_accuracy_percentage") != 94.8
