# -*- coding: utf-8 -*-
"""Quick health check for all SihaLink endpoints."""
import sys
import os
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


import requests

BASE = "http://localhost:8000"

endpoints = [
    "/health/intake",
    "/health/geo",
    "/health/data",
    "/health/notify",
    "/health/surveillance",
    "/swarm/status",
    "/swarm/agent_logs",
]

print("=" * 60)
print("SihaLink Swarm Health Check")
print("=" * 60)

for ep in endpoints:
    try:
        r = requests.get(f"{BASE}{ep}", timeout=15)
        body = r.json()
        status = body.get("status", body)
        # Truncate long output
        status_str = str(status)
        if len(status_str) > 120:
            status_str = status_str[:120] + "..."
        print(f"  {ep:30s} -> {r.status_code}  {status_str}")
    except Exception as exc:
        print(f"  {ep:30s} -> FAIL  {exc}")

print()

# Test intake form submission
print("Testing intake form submission...")
form_data = {
    "text": "Child has fever and diarrhea for 3 days in Kisumu",
    "source": "web_form",
    "language": "english",
    "latitude": -0.1022,
    "longitude": 34.7617,
}
try:
    r = requests.post(f"{BASE}/intake/form", json=form_data, timeout=60)
    print(f"  POST /intake/form -> {r.status_code}")
    data = r.json()
    print(f"  Session: {data.get('session_id', 'N/A')}")
    result = data.get("result", {})
    print(f"  Triage: {result.get('triage_color', 'N/A')}")
    print(f"  Syndrome: {result.get('syndrome', 'N/A')}")
    print(f"  Severity: {result.get('severity', 'N/A')}")
except Exception as exc:
    print(f"  POST /intake/form -> FAIL  {exc}")

print()

# Test agent logs
print("Checking agent logs...")
try:
    r = requests.get(f"{BASE}/swarm/agent_logs?limit=5", timeout=15)
    logs = r.json()
    if isinstance(logs, list):
        print(f"  Agent logs count: {len(logs)}")
        for log in logs[:3]:
            agent = log.get("agent_name", "?")
            step = log.get("step", "?")
            detail = str(log.get("detail", ""))[:80]
            print(f"    [{agent}] {step}: {detail}")
    else:
        print(f"  Agent logs: {logs}")
except Exception as exc:
    print(f"  Agent logs -> FAIL  {exc}")

print()
print("=" * 60)
print("Health check complete!")
print("=" * 60)
