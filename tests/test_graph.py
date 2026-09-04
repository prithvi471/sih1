"""Neo4j knowledge graph: sync, relationship queries, RBAC (spec 30)."""
from conftest import ANALYTICS, get, post


def test_sync_and_overview(admin):
    st, d = post(f"{ANALYTICS}/graph/sync", token=admin)
    assert st == 200
    assert d["status"] == "synced"
    assert d["mines"] >= 1 and d["subsidiaries"] >= 1

    st, o = get(f"{ANALYTICS}/graph/overview", token=admin)
    assert st == 200
    assert o["nodes"] >= 1 and o["relationships"] >= 1
    assert any(s["subsidiary"] == "MCL" for s in o["subsidiaries"])


def test_subsidiary_relationships(admin):
    st, d = get(f"{ANALYTICS}/graph/subsidiary/MCL", token=admin)
    assert st == 200
    assert len(d["mines"]) >= 1


def test_graph_rbac_isolation(ecl, mcl):
    st, _ = get(f"{ANALYTICS}/graph/subsidiary/MCL", token=ecl)
    assert st == 403
    st, _ = get(f"{ANALYTICS}/graph/subsidiary/MCL", token=mcl)
    assert st == 200


def test_only_privileged_can_sync(mcl):
    st, _ = post(f"{ANALYTICS}/graph/sync", token=mcl)
    assert st == 403
