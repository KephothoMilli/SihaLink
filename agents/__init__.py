"""
SihaLink Agent Swarm — Google ADK
Multi-agent disease surveillance system for Kenya.

Architecture:
  orchestrator  — root entry point, state machine, human-in-the-loop
  intake        — Gemini Live API, multilingual clinical extraction, TTS
  geo           — Google Maps, admin hierarchy, facility ETAs
  data          — MongoDB Atlas, vector embeddings, 7 collections
  surveillance  — outbreak detection, silent pandemic, protocol formulation
  notify        — Telegram grammY bot (Node.js, see agents/notify/bot.ts)

Run any agent with the ADK CLI:
  adk run agents/orchestrator      # primary entry point
  adk run agents/intake
  adk run agents/surveillance
  adk web agents/orchestrator      # browser UI

Deploy to Google Agent Runtime:
  adk deploy agent-runtime agents/orchestrator

Collections managed by the Data Agent:
  encounters  — clinical cases + Voyage AI / Google vector embeddings
  alerts      — outbreak signals (spike, silent pandemic, cross-county)
  referrals   — patient referral records
  follow_ups  — CHW follow-up task schedule (RED→4 visits, YELLOW→3, GREEN→1)
  chws        — Community Health Worker registry
  protocols   — WHO/MoH response protocols with Atlas Search
  baselines   — 4-week rolling syndrome baselines
"""

# Lazy imports — agents are only loaded when explicitly imported.
# This prevents MONGODB_ATLAS_URI / GEMINI_API_KEY errors at import time
# when only a subset of agents is needed.

__version__ = "2.0.0"
__all__ = [
    "orchestrator",
    "intake",
    "geo",
    "data",
    "surveillance",
    "notify",
]
