import sys
import uuid
sys.path.insert(0, 'services/report-generation-worker')

import main as worker_main

print("=== 1. Testing Report Generation Worker Draft Logic ===")
doc_id = str(uuid.uuid4())
report = worker_main.draft_report_with_ollama(
    document_id=doc_id,
    doc_type="production_report",
    subsidiary="ECL",
    urgency="medium",
    extracted_text="=== Sheet: Production Summary ===\nMine Site | Target (MT) | Actual (MT) | Status\nRajmahal OCP | 15.5 | 14.8 | Operational"
)

print("Generated Report Output:")
print(report[:350])
print("...\nReport Generation Test Passed!")
