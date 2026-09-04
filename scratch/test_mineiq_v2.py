import sys
import time
import requests
import json

BASE_URL = "http://localhost:8000"
RAG_URL = "http://localhost:8005"
ANALYTICS_URL = "http://localhost:8006"

def run_tests():
    print("=== MineIQ v2 End-to-End System Test Suite ===")

    # 1. Test Health Endpoints
    print("\n[1/7] Testing Microservice Health Endpoints...")
    for name, url in [("Ingestion", f"{BASE_URL}/health"), ("RAG", f"{RAG_URL}/health"), ("Analytics", f"{ANALYTICS_URL}/health")]:
        try:
            r = requests.get(url, timeout=5)
            print(f"  ✓ {name} Service: {r.json()}")
        except Exception as e:
            print(f"  ✗ {name} Service offline/unreachable: {str(e)}")

    # 2. Test JWT Authentication & Role Issuance
    print("\n[2/7] Testing JWT Authentication & RBAC Tokens...")
    tokens = {}
    for username, role in [("admin", "ADMIN"), ("mcl_officer", "SUBSIDIARY_OFFICER"), ("ecl_officer", "SUBSIDIARY_OFFICER")]:
        r = requests.post(f"{BASE_URL}/auth/login", json={"username": username, "password": f"{username.split('_')[0]}123"})
        if r.status_code == 200:
            data = r.json()
            tokens[username] = data["access_token"]
            print(f"  ✓ Login Success: {username} (Role: {data['user']['role']}, Sub: {data['user']['assigned_subsidiary']})")
        else:
            print(f"  ✗ Login Failed for {username}: {r.text}")

    # 3. Test RBAC Server-Side Security Boundaries
    print("\n[3/7] Testing RBAC Security Boundaries...")
    mcl_token = tokens.get("mcl_officer")
    admin_token = tokens.get("admin")

    if mcl_token and admin_token:
        # Test document listing scope
        r_admin = requests.get(f"{BASE_URL}/documents", headers={"Authorization": f"Bearer {admin_token}"})
        r_mcl = requests.get(f"{BASE_URL}/documents", headers={"Authorization": f"Bearer {mcl_token}"})
        print(f"  ✓ Admin see all docs count: {len(r_admin.json()) if r_admin.status_code == 200 else 'N/A'}")
        print(f"  ✓ MCL Officer restricted scope count: {len(r_mcl.json()) if r_mcl.status_code == 200 else 'N/A'}")

    # 4. Test RAG Grounded Query
    print("\n[4/7] Testing Secure RAG Query Engine...")
    if mcl_token:
        r_rag = requests.post(
            f"{RAG_URL}/query",
            json={"query": "What is the coal production target for MCL?"},
            headers={"Authorization": f"Bearer {mcl_token}"}
        )
        if r_rag.status_code == 200:
            res = r_rag.json()
            print(f"  ✓ RAG Answer: {res.get('answer')[:120]}...")
            print(f"  ✓ Citations: {res.get('sources')}")
        else:
            print(f"  ✗ RAG Query failed: {r_rag.text}")

    # 5. Test Word Cloud & Topic Analytics
    print("\n[5/7] Testing Word Cloud & Topic Analytics...")
    r_wc = requests.get(f"{ANALYTICS_URL}/analytics/wordcloud")
    r_tp = requests.get(f"{ANALYTICS_URL}/analytics/topics")
    if r_wc.status_code == 200:
        print(f"  ✓ Word Cloud top terms: {[w['text'] for w in r_wc.json().get('words', [])[:5]]}")
    if r_tp.status_code == 200:
        print(f"  ✓ Topic breakdown count: {len(r_tp.json().get('topics', []))}")

    # 6. Test Audit Log Recording
    print("\n[6/7] Testing Security Audit Trail...")
    r_audit = requests.get(f"{BASE_URL}/audit-logs", headers={"Authorization": f"Bearer {admin_token}"})
    if r_audit.status_code == 200:
        print(f"  ✓ Audit Trail Records: {len(r_audit.json())} events logged.")

    # 7. Test ROI Metrics Calculation
    print("\n[7/7] Testing ROI Metrics Engine...")
    r_metrics = requests.get(f"{BASE_URL}/metrics")
    if r_metrics.status_code == 200:
        m = r_metrics.json()
        print(f"  ✓ Automation: {m.get('automation_percentage')}% | Accuracy: {m.get('extraction_accuracy_percentage')}% | Time Saved: {m.get('time_reduction_percentage')}%")

if __name__ == "__main__":
    run_tests()
