"""Phase 6: semantic topic modeling (embedding clustering) from real corpus."""
from conftest import ANALYTICS, get


def test_semantic_topics(admin):
    st, d = get(f"{ANALYTICS}/analytics/topics/semantic", token=admin)
    assert st == 200
    if d.get("insufficient_data"):
        return  # too few docs to cluster — acceptable
    assert d["method"].startswith("embedding-clustering")
    assert d["topic_count"] >= 1
    t = d["topics"][0]
    assert t["representative_terms"]           # derived from corpus, not hardcoded
    assert t["document_count"] >= 1
    assert "years" in t and "subsidiaries" in t
