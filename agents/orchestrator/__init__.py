"""
SihaLink Orchestrator Agent — ADK package entry point.

Ensures the project root is on sys.path so that `from agents.X import Y`
works regardless of whether ADK loads this as:
  - `orchestrator`  (adk web agents/orchestrator — agents/ is the cwd)
  - `agents.orchestrator`  (uvicorn / direct Python import)
"""
import sys
import os

# Insert the project root (two levels up from this file: agents/orchestrator/ → /)
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from .agent import root_agent, app  # noqa: E402

__all__ = ["root_agent", "app"]
