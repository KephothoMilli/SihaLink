"""Contact Tracing Agent — SihaLink package."""
import sys
import os

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from .agent import root_agent, ContactTracingAgent  # noqa: E402

__all__ = ["root_agent", "ContactTracingAgent"]
