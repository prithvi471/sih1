"""End-to-end: upload -> OCR/extract -> validate -> classify -> report -> RAG."""
import io
import json
import time
import uuid
import urllib.request
from conftest import ING, get, post


def _upload_csv(token, filename, content):
    boundary = "----mineiqtest" + uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: text/csv\r\n\r\n{content}\r\n--{boundary}--\r\n"
    ).encode()
    req = urllib.request.Request(f"{ING}/upload", data=body, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def test_full_pipeline(admin):
    # Fully randomised rows so the document is neither an exact nor a near
    # duplicate of anything already ingested (duplicate detection is a feature
    # and would otherwise halt the pipeline for a repeated file).
    import random
    rows = ["Mine,Subsidiary,Report Year,Production Target MT,Actual Production MT,Dispatch MT,Overburden MCuM"]
    n = 5
    for _ in range(n):
        name = uuid.uuid4().hex[:10]
        t = round(random.uniform(10, 60), 1)
        a = round(t - random.uniform(0.5, 4), 1)
        d = round(a - random.uniform(0.2, 2), 1)
        ob = round(random.uniform(3, 20), 1)
        rows.append(f"{name},WCL,2022,{t},{a},{d},{ob}")
    content = "\n".join(rows) + "\n"
    up = _upload_csv(admin, f"e2e_{uuid.uuid4().hex[:8]}.csv", content)
    doc_id = up["id"]

    st, proc = post(f"{ING}/process/{doc_id}", token=admin)
    assert st == 200
    assert proc["status"] == "classified", proc.get("failure_reason") or proc.get("flag_reason")

    # Structured extraction produced one row per mine.
    st, doc = get(f"{ING}/documents/{doc_id}", token=admin)
    assert st == 200
    recs = doc.get("structured_records", [])
    assert len(recs) == n
    assert {r["subsidiary"] for r in recs} == {"WCL"}

    # Report is generated asynchronously via the fanout worker — poll briefly.
    report_ok = False
    for _ in range(20):
        st, _ = get(f"{ING}/reports/{doc_id}", token=admin)
        if st == 200:
            report_ok = True
            break
        time.sleep(3)
    assert report_ok, "report was not generated within timeout"
