#!/usr/bin/env python3
"""
SihaLink — deployment validation script.
Checks Dockerfile, supervisord.conf, .dockerignore, and deploy/service.yaml
for common Cloud Run deployment issues.
"""
import configparser
import pathlib
import re
import sys
import yaml

ROOT = pathlib.Path(__file__).parent.parent
ERRORS   = []
WARNINGS = []

def ok(msg):    print(f"  \033[32m✓\033[0m {msg}")
def warn(msg):  WARNINGS.append(msg); print(f"  \033[33m⚠\033[0m {msg}")
def error(msg): ERRORS.append(msg);   print(f"  \033[31m✗\033[0m {msg}")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Dockerfile
# ─────────────────────────────────────────────────────────────────────────────
print("\n── Dockerfile ─────────────────────────────────────────────────────")
dockerfile = ROOT / "Dockerfile"
if not dockerfile.exists():
    error("Dockerfile not found")
else:
    content = dockerfile.read_text()
    lines   = content.splitlines()

    stages       = []
    has_cmd      = False
    has_expose   = False
    has_workdir  = False
    has_nonroot  = False

    for i, line in enumerate(lines, 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue

        if re.match(r"FROM\s+", s, re.I):
            m = re.search(r"\bAS\s+(\w[\w-]*)", s, re.I)
            stages.append(m.group(1) if m else f"anonymous_{len(stages)}")

        if re.match(r"COPY\s+--from=", s, re.I):
            m = re.search(r"--from=([^\s]+)", s, re.I)
            if m:
                ref = m.group(1)
                if ref not in stages[:-1]:
                    error(f"Line {i}: COPY --from={ref} references unknown stage "
                          f"(known: {stages[:-1]})")

        if re.match(r"CMD\s+", s, re.I):    has_cmd     = True
        if re.match(r"EXPOSE\s+", s, re.I): has_expose  = True
        if re.match(r"WORKDIR\s+", s, re.I):has_workdir = True
        if "useradd" in s or "adduser" in s: has_nonroot = True

    ok(f"Stages: {stages}")
    ok(f"CMD present: {has_cmd}")           if has_cmd     else error("No CMD in final stage")
    ok(f"EXPOSE 8080 present")              if has_expose  else warn("No EXPOSE instruction")
    ok("WORKDIR set")                       if has_workdir else warn("No WORKDIR instruction")
    ok("Non-root user created")             if has_nonroot else warn("No non-root user (security best practice)")

    # Cloud Run specific
    if "PORT" not in content:
        warn("PORT env var not referenced — Cloud Run injects it at runtime")
    else:
        ok("PORT env var referenced")

    if ":8080" in content or "8080" in content:
        ok("Port 8080 referenced (Cloud Run default)")
    else:
        error("Port 8080 not found — Cloud Run requires this port")

    # .env must NOT be in image
    if re.search(r"^COPY\s+\.env\s", content, re.M):
        error("Dockerfile COPYs .env — secrets must NOT be baked into the image")
    else:
        ok(".env not copied into image")


# ─────────────────────────────────────────────────────────────────────────────
# 2. supervisord.conf
# ─────────────────────────────────────────────────────────────────────────────
print("\n── supervisord.conf ───────────────────────────────────────────────")
conf_path = ROOT / "deploy" / "supervisord.conf"
if not conf_path.exists():
    error("deploy/supervisord.conf not found")
else:
    conf = configparser.RawConfigParser()
    conf.read(str(conf_path))
    sections = conf.sections()

    required_sections = [
        "supervisord", "program:orchestrator", "program:notify-agent",
        "unix_http_server", "supervisorctl", "rpcinterface:supervisor",
    ]
    for s in required_sections:
        if s in sections:
            ok(f"Section [{s}] present")
        else:
            error(f"Missing required section [{s}]")

    if "program:orchestrator" in sections:
        cmd = conf.get("program:orchestrator", "command", fallback="")
        if "8080" in cmd:
            ok(f"Orchestrator binds :8080")
        else:
            error(f"Orchestrator command does not bind port 8080: {cmd!r}")

        if "nodaemon" in conf.get("supervisord", "nodaemon", fallback=""):
            ok("nodaemon=true (required — supervisord must stay in foreground)")
        elif conf.get("supervisord", "nodaemon", fallback="false") != "true":
            error("supervisord nodaemon must be true for Docker")

    if "program:notify-agent" in sections:
        cmd2 = conf.get("program:notify-agent", "command", fallback="")
        if "bot.js" in cmd2 or "bot.ts" in cmd2:
            ok(f"Notify Agent command: {cmd2}")
        else:
            warn(f"Notify Agent command looks unexpected: {cmd2!r}")


# ─────────────────────────────────────────────────────────────────────────────
# 3. .dockerignore
# ─────────────────────────────────────────────────────────────────────────────
print("\n── .dockerignore ──────────────────────────────────────────────────")
di = ROOT / ".dockerignore"
if not di.exists():
    error(".dockerignore not found — build context will be huge")
else:
    content_di = di.read_text()
    for must_ignore in [".env", "SihaLinkEnv", "node_modules", ".git"]:
        if must_ignore in content_di:
            ok(f"{must_ignore!r} excluded")
        else:
            warn(f"{must_ignore!r} not in .dockerignore")


# ─────────────────────────────────────────────────────────────────────────────
# 4. service.yaml (YAML validity only — no kubectl required)
# ─────────────────────────────────────────────────────────────────────────────
print("\n── deploy/service.yaml ────────────────────────────────────────────")
sy = ROOT / "deploy" / "service.yaml"
if not sy.exists():
    warn("deploy/service.yaml not found (optional for gcloud CLI deploy)")
else:
    try:
        doc = yaml.safe_load(sy.read_text())
        ok("YAML parses without errors")

        # Basic structural checks
        kind = doc.get("kind", "")
        if kind == "Service":
            ok(f"kind: {kind}")
        else:
            error(f"Expected kind: Service, got: {kind!r}")

        container = (doc.get("spec", {})
                        .get("template", {})
                        .get("spec", {})
                        .get("containers", [{}])[0])
        port = container.get("ports", [{}])[0].get("containerPort", 0)
        if port == 8080:
            ok("containerPort: 8080")
        else:
            error(f"containerPort should be 8080, got {port}")

        timeout = (doc.get("spec", {})
                      .get("template", {})
                      .get("spec", {})
                      .get("timeoutSeconds", 0))
        if timeout >= 3600:
            ok(f"timeoutSeconds: {timeout} (SSE streams need ≥3600)")
        else:
            warn(f"timeoutSeconds: {timeout} — SSE /swarm/stream needs ≥3600")

    except Exception as exc:
        error(f"service.yaml parse error: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# 5. requirements.txt — check for known Cloud Run issues
# ─────────────────────────────────────────────────────────────────────────────
print("\n── requirements.txt ───────────────────────────────────────────────")
req = ROOT / "requirements.txt"
if req.exists():
    req_text = req.read_text()
    if "uvicorn" in req_text:
        ok("uvicorn present")
    else:
        error("uvicorn not in requirements.txt")
    if "fastapi" in req_text:
        ok("fastapi present")
    else:
        error("fastapi not in requirements.txt")
    if "bson" in req_text and "pymongo" in req_text:
        # Only flag if bson appears as an actual package line (not a comment)
        bson_as_pkg = any(
            line.strip().lower().startswith("bson")
            for line in req_text.splitlines()
            if not line.strip().startswith("#")
        )
        if bson_as_pkg:
            warn("standalone 'bson' + 'pymongo' conflict — pymongo bundles bson")
        else:
            ok("No bson conflict (comment-only reference)")
    else:
        ok("No bson conflict")


# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "═" * 60)
if ERRORS:
    print(f"\033[31m✗ {len(ERRORS)} error(s) found — fix before deploying:\033[0m")
    for e in ERRORS:
        print(f"  • {e}")
    sys.exit(1)
elif WARNINGS:
    print(f"\033[33m⚠ {len(WARNINGS)} warning(s) — review before deploying:\033[0m")
    for w in WARNINGS:
        print(f"  • {w}")
    print("\033[32m✓ No blocking errors — ready to deploy\033[0m")
else:
    print("\033[32m✓ All checks passed — ready to deploy\033[0m")
