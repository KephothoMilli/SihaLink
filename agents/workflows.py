"""
SihaLink Agentic Workflow Engine
==================================
Implements IBM agentic workflow patterns for the SihaLink swarm:

  1. ReAct Loop         — Reason → Act → Observe → Reflect per tool call
  2. Reflection         — Post-pipeline self-evaluation + correction
  3. Agent Registry     — Named agent lookup for direct delegation
  4. Workflow State     — MongoDB-persistent workflow state (survives restarts)
  5. Tool Retry         — Automatic retry with backoff on transient failures
  6. Memory Store       — Per-session cross-turn context window

Reference: https://www.ibm.com/think/topics/agentic-workflows
           Components: AI Agents + LLMs, Tools, HITL Feedback,
                       Prompt Engineering, Multi-Agent Collaboration, Integrations
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger("SihaLink-Workflows")


# =============================================================================
# 1. Agent Registry — multi-agent delegation by name
# =============================================================================

class AgentRegistry:
    """
    Named registry of all SihaLink agents.
    Any agent can look up and delegate to another by name without importing it
    directly — decoupling agents from each other's implementation.

    IBM principle: Multi-agent collaboration where each agent has a domain
    of expertise and shares learned information with the rest of the system.
    """

    _agents: Dict[str, Any] = {}

    @classmethod
    def register(cls, name: str, agent: Any) -> None:
        cls._agents[name] = agent
        logger.info("[AgentRegistry] Registered: %s", name)

    @classmethod
    def get(cls, name: str) -> Optional[Any]:
        agent = cls._agents.get(name)
        if not agent:
            logger.warning("[AgentRegistry] Agent '%s' not found", name)
        return agent

    @classmethod
    def list_agents(cls) -> List[str]:
        return list(cls._agents.keys())

    @classmethod
    def delegate(cls, from_agent: str, to_agent: str, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Direct agent-to-agent delegation with structured task handoff.
        The receiving agent's name, task payload, and delegating agent are logged.
        """
        agent = cls.get(to_agent)
        if not agent:
            return {"error": f"Agent '{to_agent}' not registered", "delegated": False}

        logger.info(
            "[AgentRegistry] 📨 %s → %s: %s",
            from_agent, to_agent, list(task.keys()),
        )
        return {"agent": to_agent, "task": task, "delegated": True}


# =============================================================================
# 2. Workflow State — MongoDB-persistent, survives restarts
# =============================================================================

class WorkflowState:
    """
    Persistent workflow state stored in MongoDB `workflow_states` collection.

    IBM principle: Integrations — workflow state is integrated with existing
    MongoDB infrastructure so in-flight encounters survive server restarts,
    network interruptions, and scaling events.

    State machine:
      PENDING → INTAKE → GEO → STORING → CONTACT_TRACING →
      DECISION_GATE → NOTIFYING → COMPLETE | FAILED | OFFLINE_QUEUED
    """

    COLLECTION = "workflow_states"

    VALID_STATES = {
        "PENDING", "INTAKE", "GEO", "STORING",
        "CONTACT_TRACING", "DECISION_GATE", "NOTIFYING",
        "COMPLETE", "FAILED", "OFFLINE_QUEUED",
    }

    def __init__(self, db=None):
        self._db = db

    def _col(self):
        if not self._db:
            return None
        return self._db[self.COLLECTION]

    def create(
        self,
        session_id: str,
        source: str = "telegram",
        chw_id: str = "unknown",
        county: str = "Unknown",
    ) -> Dict[str, Any]:
        """Create a new workflow state document."""
        doc = {
            "workflow_id":  session_id,
            "session_id":   session_id,
            "state":        "PENDING",
            "source":       source,
            "chw_id":       chw_id,
            "county":       county,
            "created_at":   datetime.utcnow().isoformat(),
            "updated_at":   datetime.utcnow().isoformat(),
            "history": [
                {
                    "state":     "PENDING",
                    "timestamp": datetime.utcnow().isoformat(),
                    "note":      "Workflow created",
                }
            ],
            "data":     {},   # accumulated pipeline data
            "errors":   [],   # non-fatal errors encountered
            "retries":  {},   # per-step retry counts
        }
        col = self._col()
        if col is not None:
            try:
                col.update_one(
                    {"workflow_id": session_id},
                    {"$setOnInsert": doc},
                    upsert=True,
                )
            except Exception as exc:
                logger.warning("[WorkflowState] Create failed (non-fatal): %s", exc)
        return doc

    def transition(
        self,
        session_id: str,
        new_state: str,
        data: Optional[Dict] = None,
        note: str = "",
        error: Optional[str] = None,
    ) -> bool:
        """
        Transition workflow to a new state, persisting to MongoDB.
        Returns True on success, False if DB unavailable (graceful degradation).
        """
        if new_state not in self.VALID_STATES:
            logger.warning("[WorkflowState] Invalid state: %s", new_state)
            return False

        col = self._col()
        if col is None:
            return False

        now = datetime.utcnow().isoformat()
        update: Dict[str, Any] = {
            "$set": {
                "state":      new_state,
                "updated_at": now,
            },
            "$push": {
                "history": {
                    "state":     new_state,
                    "timestamp": now,
                    "note":      note,
                }
            },
        }
        if data:
            for k, v in data.items():
                update["$set"][f"data.{k}"] = v
        if error:
            update["$push"]["errors"] = {"error": error, "state": new_state, "ts": now}

        try:
            result = col.update_one({"workflow_id": session_id}, update)
            return result.matched_count > 0
        except Exception as exc:
            logger.warning("[WorkflowState] Transition failed (non-fatal): %s", exc)
            return False

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve workflow state. Returns None if not found or DB unavailable."""
        col = self._col()
        if col is None:
            return None
        try:
            return col.find_one({"workflow_id": session_id}, {"_id": 0})
        except Exception:
            return None

    def increment_retry(self, session_id: str, step: str) -> int:
        """Increment retry counter for a specific step. Returns new count."""
        col = self._col()
        if col is None:
            return 0
        try:
            result = col.find_one_and_update(
                {"workflow_id": session_id},
                {"$inc": {f"retries.{step}": 1}},
                return_document=True,
            )
            return (result or {}).get("retries", {}).get(step, 1)
        except Exception:
            return 1

    def list_incomplete(self, older_than_minutes: int = 30) -> List[Dict]:
        """Find workflows stuck in non-terminal states — for recovery."""
        col = self._col()
        if col is None:
            return []
        cutoff = (datetime.utcnow() - timedelta(minutes=older_than_minutes)).isoformat()
        try:
            return list(col.find(
                {
                    "state":      {"$nin": ["COMPLETE", "FAILED"]},
                    "updated_at": {"$lt": cutoff},
                },
                {"_id": 0, "workflow_id": 1, "state": 1, "chw_id": 1, "updated_at": 1},
            ).limit(50))
        except Exception:
            return []


# =============================================================================
# 3. Tool Retry with Exponential Backoff
# =============================================================================

async def with_retry(
    tool_fn: Callable,
    args: tuple = (),
    kwargs: dict = None,
    max_retries: int = 3,
    base_delay: float = 1.0,
    step_name: str = "tool",
) -> Any:
    """
    Execute a tool function with automatic retry + exponential backoff.

    IBM principle: Adaptive tool use — if a tool fails the agent should
    dynamically try alternatives or retry rather than immediately failing.

    Args:
        tool_fn:     The function to call (sync or async).
        args:        Positional arguments.
        kwargs:      Keyword arguments.
        max_retries: Maximum attempts before raising.
        base_delay:  Base delay in seconds (doubles each retry).
        step_name:   Name for logging.

    Returns:
        Tool result on success.
    Raises:
        The last exception if all retries exhausted.
    """
    kwargs = kwargs or {}
    last_exc: Exception = RuntimeError("No attempts made")

    for attempt in range(1, max_retries + 1):
        try:
            if asyncio.iscoroutinefunction(tool_fn):
                result = await tool_fn(*args, **kwargs)
            else:
                result = tool_fn(*args, **kwargs)

            # Check for error keys in dict result
            if isinstance(result, dict) and result.get("error"):
                raise RuntimeError(f"Tool returned error: {result['error']}")

            logger.debug("[Retry] ✅ %s succeeded (attempt %d)", step_name, attempt)
            return result

        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "[Retry] ⚠️  %s failed (attempt %d/%d): %s — retrying in %.1fs",
                    step_name, attempt, max_retries, exc, delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "[Retry] ❌ %s failed after %d attempts: %s",
                    step_name, max_retries, exc,
                )

    raise last_exc


# =============================================================================
# 4. ReAct Step — structured Reason + Act + Observe + Reflect
# =============================================================================

class ReActStep:
    """
    Represents one step in a ReAct (Reason→Act→Observe→Reflect) loop.

    IBM principle: AI agents break down complex tasks into multistep,
    iterative processes — reasoning about what to do, executing, observing
    results, and refining their approach.

    Usage:
        step = ReActStep("intake", session_id)
        with step.executing("Extracting clinical data from audio"):
            result = await tool_fn(...)
            step.observe(result)
        reflection = step.reflect(success_condition=lambda r: "syndrome" in r)
    """

    def __init__(self, name: str, session_id: str):
        self.name       = name
        self.session_id = session_id
        self.start_ts   = datetime.utcnow()
        self.result     = None
        self.success    = False
        self.reason     = ""
        self.observation = ""
        self.reflection  = ""

    def reason_why(self, reason: str) -> "ReActStep":
        self.reason = reason
        logger.info("[ReAct] 🤔 REASON [%s/%s]: %s", self.session_id[:8], self.name, reason)
        return self

    def observe(self, result: Any) -> "ReActStep":
        self.result = result
        self.observation = str(result)[:200]
        logger.info("[ReAct] 👁️  OBSERVE [%s/%s]: %s", self.session_id[:8], self.name, self.observation)
        return self

    def reflect(self, success_condition: Optional[Callable] = None) -> bool:
        """
        Evaluate the observation. Returns True if the step succeeded.
        The success_condition is a callable that takes the result and returns bool.
        """
        if success_condition:
            self.success = success_condition(self.result)
        else:
            self.success = self.result is not None and not (
                isinstance(self.result, dict) and self.result.get("error")
            )

        elapsed = (datetime.utcnow() - self.start_ts).total_seconds()
        self.reflection = "PASS" if self.success else "FAIL"
        logger.info(
            "[ReAct] 💭 REFLECT [%s/%s]: %s (%.2fs)",
            self.session_id[:8], self.name, self.reflection, elapsed,
        )
        return self.success

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step":        self.name,
            "reason":      self.reason,
            "observation": self.observation,
            "reflection":  self.reflection,
            "success":     self.success,
            "elapsed_ms":  int((datetime.utcnow() - self.start_ts).total_seconds() * 1000),
        }


# =============================================================================
# 5. Pipeline Reflection — post-pipeline self-evaluation
# =============================================================================

class PipelineReflection:
    """
    Evaluates the complete output of a multi-step pipeline and identifies
    anomalies, data quality issues, and improvement suggestions.

    IBM principle: Feedback mechanisms — agents refine their actions over
    time by reflecting on completed workflows, logging for future training.
    """

    @staticmethod
    def evaluate_encounter(pipeline_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate a completed encounter pipeline.
        Returns a structured reflection with quality score and issues found.
        """
        issues   : List[str] = []
        warnings : List[str] = []
        score = 100  # start at 100, deduct for issues

        extracted = pipeline_result.get("extracted", {})
        enriched  = pipeline_result.get("enriched_encounter", {})
        stored    = pipeline_result.get("stored", {})

        # Check 1: Clinical extraction quality
        syndrome = extracted.get("syndrome", "unknown")
        if syndrome == "unknown":
            issues.append("Syndrome not identified — consider clarification request")
            score -= 20
        confidence = extracted.get("confidence", 1.0)
        if confidence < 0.7:
            warnings.append(f"Low extraction confidence: {confidence:.0%}")
            score -= 10
        if not extracted.get("triage_color"):
            issues.append("Triage color missing — defaulted to YELLOW")
            score -= 15

        # Check 2: Geo enrichment quality
        county = (enriched.get("admin_hierarchy") or {}).get("county", "")
        if not county or county == "Unknown":
            issues.append("County not resolved — GPS coordinates may be missing")
            score -= 10
        facilities = enriched.get("nearest_facilities", [])
        if not facilities:
            warnings.append("No nearby facilities found — referral path unavailable")
            score -= 5

        # Check 3: Storage confirmation
        if not stored.get("inserted_id"):
            issues.append("Encounter storage failed — data loss risk")
            score -= 30

        # Check 4: Triage-syndrome consistency
        triage = extracted.get("triage_color", "GREEN")
        if syndrome in ("ebola", "viral_hemorrhagic_fever") and triage != "RED":
            issues.append(f"Triage mismatch: {syndrome} should be RED, got {triage}")
            score -= 15

        quality = "EXCELLENT" if score >= 90 else "GOOD" if score >= 70 else "FAIR" if score >= 50 else "POOR"

        logger.info(
            "[Reflection] Pipeline quality: %s (%d/100) — %d issues, %d warnings",
            quality, score, len(issues), len(warnings),
        )

        return {
            "quality_score":  score,
            "quality_label":  quality,
            "issues":         issues,
            "warnings":       warnings,
            "syndrome":       syndrome,
            "triage":         triage,
            "county":         county,
            "has_facilities": len(facilities) > 0,
            "data_complete":  len(issues) == 0,
            "timestamp":      datetime.utcnow().isoformat(),
        }

    @staticmethod
    def evaluate_surveillance_cycle(results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Reflect on a completed surveillance cycle across multiple counties.
        Identifies patterns the agent should act on in the next cycle.
        """
        total_alerts     = sum(r.get("alerts_detected", 0) for r in results)
        failed_counties  = [r.get("county", "?") for r in results if r.get("error")]
        red_syndromes    = set()
        cross_county     : Dict[str, int] = {}

        for result in results:
            for alert in result.get("alerts", []):
                syndrome = alert.get("syndrome", "")
                if alert.get("alert_level") == "RED" or alert.get("risk_level") == "HIGH":
                    red_syndromes.add(syndrome)
                cross_county[syndrome] = cross_county.get(syndrome, 0) + 1

        multi_county_syndromes = {s: c for s, c in cross_county.items() if c >= 2}

        logger.info(
            "[Reflection] Surveillance cycle: %d alerts, %d RED syndromes, "
            "%d cross-county, %d failed counties",
            total_alerts, len(red_syndromes), len(multi_county_syndromes), len(failed_counties),
        )

        return {
            "total_alerts":            total_alerts,
            "red_syndromes":           list(red_syndromes),
            "cross_county_syndromes":  multi_county_syndromes,
            "failed_counties":         failed_counties,
            "next_cycle_priorities":   list(red_syndromes) + list(multi_county_syndromes.keys()),
            "escalation_needed":       any(c >= 3 for c in multi_county_syndromes.values()),
            "timestamp":               datetime.utcnow().isoformat(),
        }


# =============================================================================
# 6. Memory Store — cross-turn context for agentic conversations
# =============================================================================

class AgentMemory:
    """
    Per-session key-value memory store that persists context across conversation turns.
    Stored in MongoDB `agent_memory` collection.

    IBM principle: LLM parameters and feedback mechanisms — maintaining context
    about the CHV, their registered county, recent encounters, and conversation
    state so each message doesn't start from scratch.
    """

    COLLECTION = "agent_memory"
    TTL_HOURS  = 72  # memories expire after 72 hours of inactivity

    def __init__(self, db=None):
        self._db = db

    def _col(self):
        return self._db[self.COLLECTION] if self._db else None

    def remember(self, session_id: str, key: str, value: Any) -> None:
        """Store a memory entry for a session."""
        col = self._col()
        if col is None:
            return
        try:
            col.update_one(
                {"session_id": session_id},
                {
                    "$set": {
                        f"memory.{key}": value,
                        "updated_at": datetime.utcnow().isoformat(),
                    },
                    "$setOnInsert": {
                        "session_id": session_id,
                        "created_at": datetime.utcnow().isoformat(),
                    },
                },
                upsert=True,
            )
        except Exception as exc:
            logger.debug("[Memory] Remember failed (non-fatal): %s", exc)

    def recall(self, session_id: str, key: str, default: Any = None) -> Any:
        """Retrieve a memory entry."""
        col = self._col()
        if col is None:
            return default
        try:
            doc = col.find_one({"session_id": session_id}, {f"memory.{key}": 1, "_id": 0})
            return (doc or {}).get("memory", {}).get(key, default)
        except Exception:
            return default

    def recall_all(self, session_id: str) -> Dict[str, Any]:
        """Retrieve all memory for a session."""
        col = self._col()
        if col is None:
            return {}
        try:
            doc = col.find_one({"session_id": session_id}, {"memory": 1, "_id": 0})
            return (doc or {}).get("memory", {})
        except Exception:
            return {}

    def forget(self, session_id: str, key: Optional[str] = None) -> None:
        """Clear one key or the entire session memory."""
        col = self._col()
        if col is None:
            return
        try:
            if key:
                col.update_one({"session_id": session_id}, {"$unset": {f"memory.{key}": ""}})
            else:
                col.delete_one({"session_id": session_id})
        except Exception:
            pass


# =============================================================================
# Module-level singletons (populated by orchestrator on startup)
# =============================================================================

agent_registry  = AgentRegistry()
pipeline_reflect = PipelineReflection()


def get_workflow_state(db=None) -> WorkflowState:
    """Return a WorkflowState bound to the given MongoDB database."""
    return WorkflowState(db)


def get_agent_memory(db=None) -> AgentMemory:
    """Return an AgentMemory bound to the given MongoDB database."""
    return AgentMemory(db)
