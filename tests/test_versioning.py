"""Document versioning & lineage (spec 7): same filename, new content -> new version."""
import uuid
from conftest import ING, get, upload_csv


def test_version_chain_and_lineage(admin):
    fname = f"VerTest_{uuid.uuid4().hex[:8]}.csv"
    m = uuid.uuid4().hex[:8]  # unique mine name so each run has a distinct SHA
    v1 = upload_csv(admin, fname, f"Mine,Subsidiary,Report Year,Actual Production MT\n{m},WCL,2021,10.0\n")
    assert v1["version"] == 1
    assert v1.get("supersedes_document_id") in (None, "")

    v2 = upload_csv(admin, fname, f"Mine,Subsidiary,Report Year,Actual Production MT\n{m},WCL,2021,12.5\n")
    assert v2["version"] == 2
    assert v2["supersedes_document_id"] == v1["id"]

    st, lin = get(f"{ING}/documents/{v2['id']}/lineage", token=admin)
    assert st == 200
    assert lin["versions"] == 2
    versions = {x["version"]: x for x in lin["lineage"]}
    assert versions[2]["is_current"] is True
    assert versions[1]["is_current"] is False
    # Immutable originals: the two versions have different content hashes.
    assert versions[1]["sha256_prefix"] != versions[2]["sha256_prefix"]
