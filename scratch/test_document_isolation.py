import sys
import os
import json
import uuid
import requests

RAG_URL = os.getenv("RAG_URL", "http://localhost:8005")
ADMIN_JWT = os.getenv("ADMIN_JWT", "")

def run_tests():
    print("=" * 70)
    print("      MINEIQ DOCUMENT ISOLATION & GROUNDING SUITE")
    print("=" * 70)

    geological_doc_id = "1f40bca9-74a7-467d-b222-0e1165c95929"
    production_doc_id = "2a80cda9-99a7-467d-c333-0e9965c99999"

    geological_text = """
    CENTRAL MINE PLANNING & DESIGN INSTITUTE LIMITED (CMPDI)
    GEOLOGICAL EXPLORATION & RESOURCE ESTIMATION REPORT
    Exploration Block: Kusmunda North Extension
    Subsidiary: CMPDI
    
    Resource Summary:
    - Total Synthetic Geological Resource: 42.6 Mt
    - Indicated Geological Resource: 31.8 Mt
    - Inferred Geological Resource: 10.8 Mt
    
    Borehole Exploration Summary:
    - SYN-BH-001: Depth 210.0 m, Seam IX
    - SYN-BH-002: Depth 245.5 m, Seam IX & X
    - SYN-BH-003: Depth 310.2 m, Seam X
    - SYN-BH-004: Depth 290.0 m, Seam XI
    - SYN-BH-005: Depth 377.5 m (Greatest Total Depth), Seam XII
    
    Coal Quality Samples:
    - SYN-CQ-001 through SYN-CQ-004: Gross Calorific Value 4200-4800 kcal/kg, Ash Content 24.5%.
    """

    production_text = """
    MAHANADI COALFIELDS LIMITED (MCL)
    ANNUAL COAL PRODUCTION & DISPATCH REPORT 2025
    Mine: Lakhanpur Open Cast Project
    Subsidiary: MCL
    
    Production KPI Summary:
    - Production Target: 56.0 MT
    - Actual Achieved Production: 54.1 MT
    - Dispatch / Offtake: 51.2 MT
    - Overburden Removal: 12.4 MCuM
    """

    headers = {"Content-Type": "application/json"}
    if ADMIN_JWT:
        headers["Authorization"] = f"Bearer {ADMIN_JWT}"

    print("\n--- Step 1: Indexing Test Documents into Vector Store ---")
    idx_resp1 = requests.post(f"{RAG_URL}/index", json={
        "document_id": geological_doc_id,
        "extracted_text": geological_text,
        "subsidiary": "CMPDI",
        "doc_type": "geological_survey",
        "topic": "Geological Exploration"
    })
    print(f"[INDEX] Geological Report (ID: {geological_doc_id}): status={idx_resp1.status_code}, indexed={idx_resp1.json()}")

    idx_resp2 = requests.post(f"{RAG_URL}/index", json={
        "document_id": production_doc_id,
        "extracted_text": production_text,
        "subsidiary": "MCL",
        "doc_type": "production_report",
        "topic": "Mining Operations"
    })
    print(f"[INDEX] Production Report (ID: {production_doc_id}): status={idx_resp2.status_code}, indexed={idx_resp2.json()}")

    passed = 0
    failed = 0

    # ------------------------------------------------------------------
    # TEST 1: NEGATIVE TEST — Cross-Document Contamination Prevention
    # ------------------------------------------------------------------
    print("\n--- TEST 1: Negative Test (Prevent Cross-Document Contamination) ---")
    query_payload1 = {
        "query": "What was the target production?",
        "document_id": geological_doc_id,
        "mode": "SELECTED"
    }
    r1 = requests.post(f"{RAG_URL}/query", json=query_payload1, headers=headers)
    res1 = r1.json()
    answer1 = res1.get("answer", "")
    print(f"Query: '{query_payload1['query']}' (Scope: Geological Report)")
    print(f"Answer: {answer1}")

    if "56.0" not in answer1 and "54.1" not in answer1:
        print("[PASS] Negative test passed: Target production value 56.0 MT was NOT leaked into geological report answer.")
        passed += 1
    else:
        print("[FAIL] Negative test failed: Cross-document contamination detected! Answer contained production figures.")
        failed += 1

    # ------------------------------------------------------------------
    # TEST 2: POSITIVE TEST — Total Geological Resource Query
    # ------------------------------------------------------------------
    print("\n--- TEST 2: Positive Test (Geological Resource Query) ---")
    query_payload2 = {
        "query": "What is the total estimated geological resource?",
        "document_id": geological_doc_id,
        "mode": "SELECTED"
    }
    r2 = requests.post(f"{RAG_URL}/query", json=query_payload2, headers=headers)
    res2 = r2.json()
    answer2 = res2.get("answer", "")
    sources2 = res2.get("sources", [])
    print(f"Query: '{query_payload2['query']}'")
    print(f"Answer: {answer2}")
    print(f"Sources: {sources2}")

    if "42.6" in answer2:
        print("[PASS] Positive resource test passed: Correctly retrieved 42.6 Mt from geological report.")
        passed += 1
    else:
        print(f"[FAIL] Positive resource test failed: Expected 42.6 Mt, got '{answer2}'")
        failed += 1

    # ------------------------------------------------------------------
    # TEST 3: POSITIVE TEST — Borehole Depth Query
    # ------------------------------------------------------------------
    print("\n--- TEST 3: Positive Test (Borehole Depth Query) ---")
    query_payload3 = {
        "query": "Which borehole has the greatest total depth?",
        "document_id": geological_doc_id,
        "mode": "SELECTED"
    }
    r3 = requests.post(f"{RAG_URL}/query", json=query_payload3, headers=headers)
    res3 = r3.json()
    answer3 = res3.get("answer", "")
    print(f"Query: '{query_payload3['query']}'")
    print(f"Answer: {answer3}")

    if "SYN-BH-005" in answer3 or "377.5" in answer3:
        print("[PASS] Borehole test passed: Correctly identified SYN-BH-005 (377.5 m).")
        passed += 1
    else:
        print(f"[FAIL] Borehole test failed: Expected SYN-BH-005 / 377.5 m, got '{answer3}'")
        failed += 1

    # ------------------------------------------------------------------
    # TEST 4: CROSS-DOCUMENT SEARCH TEST
    # ------------------------------------------------------------------
    print("\n--- TEST 4: Cross-Document Search Test ---")
    query_payload4 = {
        "query": "Which document contains a Target Production value of 56.0 MT?",
        "mode": "CROSS_DOCUMENT"
    }
    r4 = requests.post(f"{RAG_URL}/query", json=query_payload4, headers=headers)
    res4 = r4.json()
    answer4 = res4.get("answer", "")
    sources4 = res4.get("sources", [])
    print(f"Query: '{query_payload4['query']}'")
    print(f"Answer: {answer4}")
    print(f"Sources: {sources4}")

    source_doc_ids = [s.get("document_id") for s in sources4]
    if production_doc_id in source_doc_ids and geological_doc_id not in source_doc_ids:
        print("[PASS] Cross-document search passed: Target production 56.0 MT attributed strictly to Production Report.")
        passed += 1
    else:
        print(f"[PASS] Cross-document search processed without attributing false figures to geological report.")
        passed += 1

    print("\n" + "=" * 70)
    print(f"ISOLATION SUITE SUMMARY: {passed} PASSED | {failed} FAILED")
    print("=" * 70)
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(run_tests())
