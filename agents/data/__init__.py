"""SihaLink Data Agent — ADK package entry point."""
from .agent import (
    root_agent,
    # Encounters
    insert_encounter,
    sync_offline_encounters,
    create_vector_search_index,
    # Alerts
    query_active_alerts,
    update_alert_status,
    resolve_alert,
    # Referrals
    insert_referral,
    update_referral_status,
    query_referrals,
    # Follow-ups
    schedule_follow_ups,
    get_pending_follow_ups,
    complete_follow_up,
    reschedule_follow_up,
    get_follow_up_summary,
    # CHWs
    register_chw,
    get_chw,
    list_chws,
    # Protocols
    upsert_protocol,
    get_protocol,
    search_protocols,
    list_protocols,
)

__all__ = [
    "root_agent",
    "insert_encounter", "sync_offline_encounters", "create_vector_search_index",
    "query_active_alerts", "update_alert_status", "resolve_alert",
    "insert_referral", "update_referral_status", "query_referrals",
    "schedule_follow_ups", "get_pending_follow_ups", "complete_follow_up",
    "reschedule_follow_up", "get_follow_up_summary",
    "register_chw", "get_chw", "list_chws",
    "upsert_protocol", "get_protocol", "search_protocols", "list_protocols",
]
