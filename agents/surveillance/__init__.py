"""SihaLink Surveillance Agent — ADK package entry point."""
from .agent import (
    root_agent,
    SurveillanceAgent,
    # Outbreak detection
    run_outbreak_detection,
    # Silent pandemic
    detect_silent_pandemic,
    detect_cross_county_spread,
    # Protocol formulation
    formulate_response_protocol,
    get_protocol,
    # Vector search
    run_vector_similarity_search,
    # Baselines
    update_baselines,
    # Stats
    get_county_stats,
    # CHW outreach
    detect_chw_outreach_gaps,
    get_chw_performance,
)

__all__ = [
    "root_agent",
    "SurveillanceAgent",
    "run_outbreak_detection",
    "detect_silent_pandemic",
    "detect_cross_county_spread",
    "formulate_response_protocol",
    "get_protocol",
    "run_vector_similarity_search",
    "update_baselines",
    "get_county_stats",
    "detect_chw_outreach_gaps",
    "get_chw_performance",
]
