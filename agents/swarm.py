"""
SihaLink Agent Swarm Controller
================================
Coordinates all agents as a single autonomous Kenya National Disease
Surveillance System. Agents self-organise around events and scheduled
cycles. Humans are involved at defined gates — not in every step.

Architecture
------------
  SwarmController          — singleton that owns all agent instances + scheduler
  SwarmEventBus            — async pub/sub so agents communicate without tight coupling
  SwarmScheduler           — cron-style background tasks (surveillance cycles, etc.)
  HumanGatePolicy          — defines when/how humans are consulted

Autonomous cycles (no human required)
--------------------------------------
  Every  6 hours  — Outbreak detection for all active counties
  Every 24 hours  — Silent pandemic scan + baseline update
  Every  1 hour   — Pending follow-up reminder dispatch
  Every 30 minutes — Offline queue sync attempt
  On every new encounter — geo-enrich, store, triage, follow-up schedule

Human involvement (clearly defined gates)
------------------------------------------
  YELLOW/RED encounter → CHV gets 60s to confirm referral via Telegram/web
    RED timeout   → auto-escalate (system acts without human)
    YELLOW timeout → queue for later, notify district officer
  CRITICAL alert  → district officer Telegram notification + web dashboard ping
  Silent pandemic → district officer notified; protocol auto-formulated
  Cross-county spread ≥3 counties → national escalation notification sent
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger("SihaLink-Swarm")

# ── Active Kenya counties tracked by default ─────────────────────────────────
# Coordinates are approximate county centroids
KENYA_ACTIVE_COUNTIES: Dict[str, Dict[str, float]] = {
    "Homa Bay":   {"lat": -0.5273,  "lng": 34.4571},
    "Kisumu":     {"lat": -0.0917,  "lng": 34.7679},
    "Siaya":      {"lat": 0.0612,   "lng": 34.2873},
    "Migori":     {"lat": -1.0634,  "lng": 34.4731},
    "Kisii":      {"lat": -0.6817,  "lng": 34.7667},
    "Garissa":    {"lat": -0.4532,  "lng": 39.6461},
    "Wajir":      {"lat": 1.7471,   "lng": 40.0573},
    "Mandera":    {"lat": 3.9366,   "lng": 41.8670},
    "Turkana":    {"lat": 3.1166,   "lng": 35.5966},
    "Nairobi":    {"lat": -1.2921,  "lng": 36.8219},
    "Mombasa":    {"lat": -4.0435,  "lng": 39.6682},
    "Nakuru":     {"lat": -0.3031,  "lng": 36.0800},
    "Kilifi":     {"lat": -3.5107,  "lng": 39.9093},
    "Kwale":      {"lat": -4.1817,  "lng": 39.4523},
    "Bungoma":    {"lat": 0.5635,   "lng": 34.5606},
    "Kakamega":   {"lat": 0.2827,   "lng": 34.7519},
    "Marsabit":   {"lat": 2.3284,   "lng": 37.9899},
    "Isiolo":     {"lat": 0.3544,   "lng": 38.0054},
    "Tana River": {"lat": -1.3003,  "lng": 40.0276},
    "Lamu":       {"lat": -2.2686,  "lng": 40.9020},
}


# =============================================================================
# Event Bus — async pub/sub for inter-agent communication
# =============================================================================

class SwarmEvent:
    """A single event on the swarm bus."""
    __slots__ = ("topic", "payload", "source", "ts")

    def __init__(self, topic: str, payload: Any, source: str = "system"):
        self.topic   = topic
        self.payload = payload
        self.source  = source
        self.ts      = datetime.utcnow().isoformat()

    def __repr__(self) -> str:
        return f"<SwarmEvent topic={self.topic} source={self.source} ts={self.ts}>"


class SwarmEventBus:
    """
    Lightweight async pub/sub bus.
    Agents subscribe to topics; the bus delivers events asynchronously.
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Callable]] = {}
        self._history:     List[SwarmEvent]          = []
        self._max_history = 500

    def subscribe(self, topic: str, handler: Callable) -> None:
        self._subscribers.setdefault(topic, []).append(handler)
        logger.debug("[EventBus] %s subscribed to '%s'", handler.__qualname__, topic)

    async def publish(self, event: SwarmEvent) -> None:
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        handlers = self._subscribers.get(event.topic, []) + \
                   self._subscribers.get("*", [])

        if handlers:
            logger.info("[EventBus] 📣 %s → %d handler(s)", event, len(handlers))
        else:
            logger.debug("[EventBus] 📣 %s (no subscribers)", event)

        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as exc:
                logger.error("[EventBus] Handler %s failed: %s", handler.__qualname__, exc)

    def recent(self, topic: Optional[str] = None, limit: int = 20) -> List[Dict]:
        events = self._history if not topic else [e for e in self._history if e.topic == topic]
        return [
            {"topic": e.topic, "source": e.source, "ts": e.ts, "payload": e.payload}
            for e in events[-limit:]
        ]


# =============================================================================
# Scheduler — cron-style background tasks
# =============================================================================

class ScheduledTask:
    __slots__ = ("name", "interval_seconds", "handler", "last_run", "enabled")

    def __init__(self, name: str, interval_seconds: int, handler: Callable):
        self.name             = name
        self.interval_seconds = interval_seconds
        self.handler          = handler
        self.last_run: Optional[datetime] = None
        self.enabled          = True

    def is_due(self) -> bool:
        if not self.last_run:
            return True
        return (datetime.utcnow() - self.last_run).total_seconds() >= self.interval_seconds


class SwarmScheduler:
    """
    Runs background tasks on configurable intervals.
    Each task is a coroutine that the swarm calls autonomously.
    """

    def __init__(self, bus: SwarmEventBus) -> None:
        self._tasks:   List[ScheduledTask] = []
        self._bus      = bus
        self._running  = False

    def register(self, name: str, interval_seconds: int, handler: Callable) -> None:
        self._tasks.append(ScheduledTask(name, interval_seconds, handler))
        logger.info("[Scheduler] Registered '%s' every %ds", name, interval_seconds)

    async def run(self) -> None:
        self._running = True
        logger.info("[Scheduler] ▶ Swarm scheduler started (%d tasks)", len(self._tasks))
        while self._running:
            for task in self._tasks:
                if not task.enabled:
                    continue
                if task.is_due():
                    task.last_run = datetime.utcnow()
                    logger.info("[Scheduler] 🕐 Running task: %s", task.name)
                    try:
                        if asyncio.iscoroutinefunction(task.handler):
                            await task.handler()
                        else:
                            task.handler()
                        await self._bus.publish(SwarmEvent(
                            f"task.{task.name}.complete",
                            {"task": task.name, "ts": task.last_run.isoformat()},
                            source="scheduler",
                        ))
                    except Exception as exc:
                        logger.error("[Scheduler] Task '%s' failed: %s", task.name, exc)
                        await self._bus.publish(SwarmEvent(
                            f"task.{task.name}.error",
                            {"task": task.name, "error": str(exc)},
                            source="scheduler",
                        ))
            await asyncio.sleep(10)  # check every 10s

    def stop(self) -> None:
        self._running = False
        logger.info("[Scheduler] ⏹ Scheduler stopped")


# =============================================================================
# Human Gate Policy
# =============================================================================

class HumanGatePolicy:
    """
    Defines when and how humans are involved.
    All other decisions are autonomous.
    """

    # Seconds to wait for human response before auto-acting
    TIMEOUT_RED    = 60    # RED: auto-escalate after 60s
    TIMEOUT_YELLOW = 120   # YELLOW: auto-queue after 2 min
    TIMEOUT_ALERT  = 300   # CRITICAL alerts: notify then auto-act after 5 min

    @staticmethod
    def requires_gate(triage_color: str) -> bool:
        """Only RED and YELLOW encounters go to the human gate."""
        return triage_color in ("RED", "YELLOW")

    @staticmethod
    def auto_action_on_timeout(triage_color: str) -> str:
        """What the system does automatically if the human doesn't respond."""
        if triage_color == "RED":
            return "escalate"   # send referral regardless
        return "queue"          # defer to next CHV check-in

    @staticmethod
    def national_escalation_threshold() -> int:
        """Number of counties with same syndrome before national escalation."""
        return 3


# =============================================================================
# SwarmController — the brain
# =============================================================================

class SwarmController:
    """
    Singleton that owns all agent instances, the event bus, and the scheduler.
    Coordinates the full swarm lifecycle autonomously.

    Usage:
        swarm = SwarmController()
        await swarm.start()          # starts scheduler + background loops
        await swarm.stop()
    """

    _instance: Optional["SwarmController"] = None

    def __init__(self) -> None:
        self.bus       = SwarmEventBus()
        self.scheduler = SwarmScheduler(self.bus)
        self.policy    = HumanGatePolicy()
        self.started   = False
        self._task:    Optional[asyncio.Task] = None

        # Agent instances (set by initialise())
        self.intake     = None
        self.geo        = None
        self.data       = None
        self.notify     = None
        self.surveillance = None
        self.orchestrator = None

        # Runtime state
        self.active_counties: Dict[str, Dict] = dict(KENYA_ACTIVE_COUNTIES)
        self.swarm_stats: Dict[str, Any] = {
            "encounters_today": 0,
            "alerts_dispatched": 0,
            "protocols_formulated": 0,
            "counties_monitored": len(KENYA_ACTIVE_COUNTIES),
            "last_surveillance_run": None,
            "last_baseline_update": None,
            "swarm_started_at": None,
        }

    @classmethod
    def get(cls) -> "SwarmController":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def initialise(self, intake, geo, data, notify, surveillance, orchestrator) -> None:
        """Wire in all agent instances."""
        self.intake       = intake
        self.geo          = geo
        self.data         = data
        self.notify       = notify
        self.surveillance = surveillance
        self.orchestrator = orchestrator
        logger.info("[Swarm] 🐝 All agents wired into swarm controller")

    async def start(self) -> None:
        """Start the autonomous swarm — register all scheduled tasks and event handlers."""
        if self.started:
            logger.warning("[Swarm] Already started")
            return

        self._register_event_handlers()
        self._register_scheduled_tasks()
        self.swarm_stats["swarm_started_at"] = datetime.utcnow().isoformat()
        self.started = True

        # Run the scheduler in a background task
        self._task = asyncio.create_task(self.scheduler.run(), name="swarm-scheduler")
        logger.info("[Swarm] ✅ SihaLink Agent Swarm is LIVE — monitoring %d counties",
                    len(self.active_counties))
        await self.bus.publish(SwarmEvent("swarm.started", self.swarm_stats, "swarm"))

    async def stop(self) -> None:
        self.scheduler.stop()
        if self._task:
            self._task.cancel()
        self.started = False
        logger.info("[Swarm] ⏹ Swarm stopped")

    # ─────────────────────────────────────────────────────────────────
    # Event handlers — agents react to each other's outputs
    # ─────────────────────────────────────────────────────────────────

    def _register_event_handlers(self) -> None:
        """Wire agents to respond to each other's events."""

        # When a new encounter is stored → run immediate surveillance check
        self.bus.subscribe("encounter.stored", self._on_encounter_stored)

        # When an alert is detected → formulate protocol + notify
        self.bus.subscribe("alert.detected", self._on_alert_detected)

        # When a silent pandemic signal fires → escalate
        self.bus.subscribe("alert.silent_pandemic", self._on_silent_pandemic)

        # When cross-county spread is detected → national escalation
        self.bus.subscribe("alert.cross_county_spread", self._on_cross_county_spread)

        # When CHW outreach gap detected → supervisor notification
        self.bus.subscribe("gap.chw_outreach", self._on_chw_gap)

        # When a follow-up is overdue → send reminder
        self.bus.subscribe("followup.overdue", self._on_followup_overdue)

        # Log everything to the swarm audit trail
        self.bus.subscribe("*", self._audit_log)

        logger.info("[Swarm] 🔗 Event handlers registered")

    def _register_scheduled_tasks(self) -> None:
        """Register all autonomous background cycles."""

        self.scheduler.register(
            "outbreak_detection",
            interval_seconds=6 * 3600,      # every 6 hours
            handler=self._run_outbreak_cycle,
        )
        self.scheduler.register(
            "silent_pandemic_scan",
            interval_seconds=24 * 3600,     # every 24 hours
            handler=self._run_silent_pandemic_cycle,
        )
        self.scheduler.register(
            "baseline_update",
            interval_seconds=24 * 3600,     # every 24 hours
            handler=self._run_baseline_update,
        )
        self.scheduler.register(
            "followup_reminders",
            interval_seconds=3600,          # every hour
            handler=self._run_followup_reminders,
        )
        self.scheduler.register(
            "offline_queue_sync",
            interval_seconds=1800,          # every 30 minutes
            handler=self._run_offline_sync,
        )
        self.scheduler.register(
            "chw_outreach_gaps",
            interval_seconds=24 * 3600,     # daily
            handler=self._run_chw_gap_check,
        )
        logger.info("[Swarm] ⏰ %d scheduled tasks registered", 6)

    # ─────────────────────────────────────────────────────────────────
    # Scheduled task implementations
    # ─────────────────────────────────────────────────────────────────

    async def _run_outbreak_cycle(self) -> None:
        """Autonomous outbreak detection across all monitored counties."""
        logger.info("[Swarm] 🔍 Starting outbreak detection cycle (%d counties)",
                    len(self.active_counties))
        total_alerts = 0
        for county, coords in self.active_counties.items():
            try:
                from agents.surveillance.agent import run_outbreak_detection
                result = run_outbreak_detection(
                    county, coords["lat"], coords["lng"], hours=6
                )
                n = result.get("alerts_detected", 0)
                total_alerts += n
                if n > 0:
                    logger.info("[Swarm] ⚠️  %s: %d alert(s) detected", county, n)
                    for alert in result.get("alerts", []):
                        await self.bus.publish(SwarmEvent(
                            "alert.detected", alert, source="surveillance_agent"
                        ))
            except Exception as exc:
                logger.error("[Swarm] Outbreak detection failed for %s: %s", county, exc)

        self.swarm_stats["last_surveillance_run"] = datetime.utcnow().isoformat()
        logger.info("[Swarm] ✅ Outbreak cycle complete — %d total alerts", total_alerts)

    async def _run_silent_pandemic_cycle(self) -> None:
        """Autonomous silent pandemic scan — weekly trends."""
        logger.info("[Swarm] 🔬 Starting silent pandemic scan")
        from agents.surveillance.agent import detect_silent_pandemic, detect_cross_county_spread
        all_syndromes: Set[str] = set()

        for county in self.active_counties:
            try:
                result = detect_silent_pandemic(county, weeks=4)
                for signal in result.get("silent_signals", []):
                    all_syndromes.add(signal["syndrome"])
                    await self.bus.publish(SwarmEvent(
                        "alert.silent_pandemic", {**signal, "county": county},
                        source="surveillance_agent"
                    ))
            except Exception as exc:
                logger.error("[Swarm] Silent pandemic scan failed for %s: %s", county, exc)

        # Cross-county spread check for any flagged syndromes
        for syndrome in all_syndromes:
            try:
                spread = detect_cross_county_spread(syndrome, hours=48)
                if spread.get("spread_detected"):
                    await self.bus.publish(SwarmEvent(
                        "alert.cross_county_spread", spread,
                        source="surveillance_agent"
                    ))
            except Exception as exc:
                logger.error("[Swarm] Cross-county check failed for %s: %s", syndrome, exc)

        logger.info("[Swarm] ✅ Silent pandemic scan complete")

    async def _run_baseline_update(self) -> None:
        """Recalculate 4-week rolling baselines for all counties."""
        logger.info("[Swarm] 📊 Updating baselines for all counties")
        from agents.surveillance.agent import update_baselines
        try:
            result = update_baselines(county=None)  # all counties
            self.swarm_stats["last_baseline_update"] = datetime.utcnow().isoformat()
            logger.info("[Swarm] ✅ Baselines updated: %d records",
                        result.get("baselines_updated", 0))
        except Exception as exc:
            logger.error("[Swarm] Baseline update failed: %s", exc)

    async def _run_followup_reminders(self) -> None:
        """Check for overdue follow-ups and dispatch reminders to CHWs."""
        if not self.data or not self.data.connected:
            return
        logger.info("[Swarm] 📅 Checking overdue follow-ups")
        try:
            overdue = self.data.db.follow_ups.find({
                "status": "pending",
                "due_date": {"$lte": datetime.utcnow()},
            }).limit(50)
            count = 0
            for fu in overdue:
                await self.bus.publish(SwarmEvent(
                    "followup.overdue", fu, source="data_agent"
                ))
                count += 1
            if count:
                logger.info("[Swarm] 📬 %d overdue follow-up(s) dispatched", count)
        except Exception as exc:
            logger.error("[Swarm] Follow-up reminder check failed: %s", exc)

    async def _run_offline_sync(self) -> None:
        """Attempt to sync offline-queued encounters."""
        if self.orchestrator and self.orchestrator.offline_queue:
            queue_size = len(self.orchestrator.offline_queue)
            logger.info("[Swarm] 🔄 Syncing offline queue (%d encounters)", queue_size)
            try:
                result = await self.orchestrator.process_offline_queue()
                logger.info("[Swarm] ✅ Offline sync: %d processed, %d errors",
                            result["processed"], result["errors"])
            except Exception as exc:
                logger.error("[Swarm] Offline sync failed: %s", exc)

    async def _run_chw_gap_check(self) -> None:
        """Detect wards with no CHW activity in the past 7 days."""
        logger.info("[Swarm] 👥 Checking CHW outreach gaps")
        from agents.surveillance.agent import detect_chw_outreach_gaps
        for county in self.active_counties:
            try:
                result = detect_chw_outreach_gaps(county, days=7)
                if result.get("total_gap_wards", 0) > 0:
                    await self.bus.publish(SwarmEvent(
                        "gap.chw_outreach", result, source="surveillance_agent"
                    ))
            except Exception as exc:
                logger.error("[Swarm] CHW gap check failed for %s: %s", county, exc)

    # ─────────────────────────────────────────────────────────────────
    # Event handler implementations
    # ─────────────────────────────────────────────────────────────────

    async def _on_encounter_stored(self, event: SwarmEvent) -> None:
        """When an encounter is stored, immediately check for local outbreak signal."""
        encounter = event.payload
        county = encounter.get("admin_hierarchy", {}).get("county")
        coords = self.active_counties.get(county, {"lat": 0.0, "lng": 0.0})
        if county and self.data and self.data.connected:
            try:
                from agents.surveillance.agent import run_outbreak_detection
                result = run_outbreak_detection(county, coords["lat"], coords["lng"], hours=1)
                for alert in result.get("alerts", []):
                    await self.bus.publish(SwarmEvent(
                        "alert.detected", alert, source="surveillance_agent"
                    ))
                self.swarm_stats["encounters_today"] += 1
            except Exception as exc:
                logger.error("[Swarm] Post-encounter surveillance failed: %s", exc)

    async def _on_alert_detected(self, event: SwarmEvent) -> None:
        """Auto-formulate protocol and notify district officer."""
        alert = event.payload
        syndrome = alert.get("syndrome", "unknown")
        county   = alert.get("location", {}).get("county", "unknown")
        logger.warning("[Swarm] 🚨 ALERT: %s in %s", syndrome.upper(), county)

        # 1. Auto-formulate response protocol
        try:
            from agents.surveillance.agent import formulate_response_protocol
            protocol = formulate_response_protocol(
                syndrome, county, alert.get("alert_type", "YELLOW").upper()
            )
            self.swarm_stats["protocols_formulated"] += 1
            logger.info("[Swarm] 📋 Protocol formulated for %s/%s", syndrome, county)
        except Exception as exc:
            logger.error("[Swarm] Protocol formulation failed: %s", exc)

        # 2. Notify district officer via Telegram
        if self.notify:
            try:
                await self.notify.dispatch_outbreak_alert(alert)
                self.swarm_stats["alerts_dispatched"] += 1
                logger.info("[Swarm] 📱 Alert dispatched to Telegram")
            except Exception as exc:
                logger.warning("[Swarm] Telegram dispatch failed: %s", exc)

    async def _on_silent_pandemic(self, event: SwarmEvent) -> None:
        """Silent pandemic signal — formulate protocol, escalate to district."""
        signal = event.payload
        logger.warning("[Swarm] 🌊 SILENT PANDEMIC: %s in %s (risk: %s)",
                       signal.get("syndrome"), signal.get("county"),
                       signal.get("risk_level"))
        # Reuse alert handler — same notify path
        await self._on_alert_detected(SwarmEvent(
            "alert.detected",
            {
                "syndrome": signal["syndrome"],
                "alert_type": "silent_pandemic",
                "location": {"county": signal["county"], "ward": "Multiple"},
                "risk_level": signal.get("risk_level"),
                "trend_delta": signal.get("trend_delta"),
                "alert_id": f"silent-{signal['syndrome']}-{signal['county']}",
                "percent_above_baseline": 0,
                "count": signal.get("total_cases", 0),
                "detected_at": datetime.utcnow().isoformat(),
                "status": "active",
            },
            source="swarm",
        ))

    async def _on_cross_county_spread(self, event: SwarmEvent) -> None:
        """Cross-county spread — escalate nationally if ≥3 counties."""
        spread = event.payload
        n_counties = spread.get("counties_count", 0)
        syndrome   = spread.get("syndrome")
        level      = spread.get("escalation_level", "REGIONAL")
        logger.critical(
            "[Swarm] 🔴 CROSS-COUNTY SPREAD: %s across %d counties — %s escalation",
            syndrome, n_counties, level
        )
        if self.notify and n_counties >= self.policy.national_escalation_threshold():
            try:
                await self.notify.dispatch_outbreak_alert({
                    "alert_id": f"spread-{syndrome}",
                    "syndrome": syndrome,
                    "location": {"county": "NATIONAL", "ward": "Multiple Counties"},
                    "count": sum(c.get("count", 0) for c in spread.get("counties_affected", [])),
                    "percent_above_baseline": 0,
                    "detected_at": datetime.utcnow().isoformat(),
                    "status": "active",
                    "escalation_level": level,
                    "counties_affected": spread.get("counties_affected", []),
                })
            except Exception as exc:
                logger.error("[Swarm] National escalation notify failed: %s", exc)

    async def _on_chw_gap(self, event: SwarmEvent) -> None:
        """CHW outreach gap — notify supervisor."""
        result = event.payload
        county = result.get("county")
        n_gaps = result.get("total_gap_wards", 0)
        logger.warning("[Swarm] 👥 CHW OUTREACH GAP: %d wards in %s", n_gaps, county)
        # Notify the district officer for the affected county
        if self.notify:
            try:
                await self.notify.dispatch_outbreak_alert({
                    "alert_id": f"gap-{county}-{datetime.utcnow().strftime('%Y%m%d')}",
                    "syndrome": "chw_outreach_gap",
                    "location": {"county": county, "ward": "Multiple"},
                    "count": n_gaps,
                    "percent_above_baseline": 0,
                    "detected_at": datetime.utcnow().isoformat(),
                    "status": "active",
                    "gap_wards": result.get("gap_wards", []),
                    "recommended_actions": result.get("recommended_actions", []),
                })
            except Exception as exc:
                logger.warning("[Swarm] CHW gap notify failed: %s", exc)

    async def _on_followup_overdue(self, event: SwarmEvent) -> None:
        """Dispatch Telegram reminder for overdue follow-up."""
        fu = event.payload
        chw_id = fu.get("chw_id")
        if not chw_id or not self.notify:
            return
        try:
            await self.notify.dispatch_outbreak_alert({
                "alert_id": f"overdue-fu-{fu.get('_id', 'unknown')}",
                "syndrome": "follow_up_overdue",
                "location": {"county": fu.get("county", ""), "ward": fu.get("ward", "")},
                "count": 1,
                "percent_above_baseline": 0,
                "detected_at": datetime.utcnow().isoformat(),
                "status": "active",
                "follow_up": fu,
            })
        except Exception as exc:
            logger.warning("[Swarm] Follow-up reminder notify failed: %s", exc)

    async def _audit_log(self, event: SwarmEvent) -> None:
        """Log every swarm event for the audit trail."""
        if not event.topic.startswith("task."):  # skip noisy scheduler ticks
            logger.info("[Audit] %s | source=%s | ts=%s",
                        event.topic, event.source, event.ts)

    # ─────────────────────────────────────────────────────────────────
    # Public API — called by HTTP routes and Telegram bot
    # ─────────────────────────────────────────────────────────────────

    async def process_encounter(
        self,
        session_id: str,
        audio_b64: str = "",
        coords: Optional[Dict] = None,
        form_data: Optional[Dict] = None,
        telegram_payload: Optional[Dict] = None,
        agent_payload: Optional[Dict] = None,
        source: str = "audio",
    ) -> Dict[str, Any]:
        """
        Unified encounter entry point for all sources.
        Runs the full lifecycle and returns the final session state.
        """
        if not coords:
            coords = {"lat": 0.0, "lng": 0.0}

        logger.info("[Swarm] 🏥 New encounter: %s (source=%s)", session_id, source)
        await self.bus.publish(SwarmEvent(
            "encounter.started", {"session_id": session_id, "source": source},
            source="swarm"
        ))

        if self.orchestrator:
            await self.orchestrator.run_lifecycle(session_id, audio_b64, coords)
            state = self.orchestrator.sessions.get(session_id, {})
            # Fire encounter.stored event if we have an encounter_id
            if "encounter_id" in state:
                await self.bus.publish(SwarmEvent(
                    "encounter.stored",
                    {**state, "session_id": session_id},
                    source="orchestrator"
                ))
            return state
        return {"error": "orchestrator not initialised"}

    def get_swarm_status(self) -> Dict[str, Any]:
        """Return current swarm health for the dashboard."""
        return {
            "status": "running" if self.started else "stopped",
            "stats": self.swarm_stats,
            "counties_monitored": len(self.active_counties),
            "active_counties": list(self.active_counties.keys()),
            "scheduler_tasks": [
                {
                    "name": t.name,
                    "interval_seconds": t.interval_seconds,
                    "last_run": t.last_run.isoformat() if t.last_run else None,
                    "enabled": t.enabled,
                }
                for t in self.scheduler._tasks
            ],
            "recent_events": self.bus.recent(limit=10),
        }

    def add_county(self, county: str, lat: float, lng: float) -> None:
        """Dynamically add a county to the surveillance scope."""
        self.active_counties[county] = {"lat": lat, "lng": lng}
        self.swarm_stats["counties_monitored"] = len(self.active_counties)
        logger.info("[Swarm] ➕ Added county: %s", county)

    def remove_county(self, county: str) -> None:
        """Remove a county from active surveillance."""
        self.active_counties.pop(county, None)
        self.swarm_stats["counties_monitored"] = len(self.active_counties)
        logger.info("[Swarm] ➖ Removed county: %s", county)
