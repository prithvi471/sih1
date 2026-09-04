"""Every service is up and the vector store is the persistent one (Qdrant)."""
import pytest
from conftest import ING, OCR, RAG, ANALYTICS, PQ, get


@pytest.mark.parametrize("url", [ING, OCR, RAG, ANALYTICS, PQ])
def test_service_health(url):
    st, d = get(f"{url}/health")
    assert st == 200
    assert d.get("status") == "ok"


def test_rag_uses_qdrant():
    st, d = get(f"{RAG}/health")
    assert st == 200
    assert d.get("vector_store") == "qdrant"
    assert d.get("embedder_active") is True
