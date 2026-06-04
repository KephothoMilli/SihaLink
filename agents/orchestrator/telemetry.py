"""
SihaLink — Dynatrace Observability Bootstrap
=============================================
Initialises OpenTelemetry traces, metrics, and logs pointing at the
Dynatrace OTLP ingest endpoint.

Endpoint pattern (per Dynatrace docs):
  https://{ENV_ID}.live.dynatrace.com/api/v2/otlp/v1/traces
  https://{ENV_ID}.live.dynatrace.com/api/v2/otlp/v1/metrics
  https://{ENV_ID}.live.dynatrace.com/api/v2/otlp/v1/logs

Auth header:
  Authorization: Api-Token {DYNATRACE_API_TOKEN}

Required API token scopes:
  - openTelemetryTrace.ingest
  - openTelemetryMetric.ingest
  - openTelemetryLog.ingest

Reference: https://docs.dynatrace.com/docs/ingest-from/opentelemetry/monitor
"""

import logging
import os

logger = logging.getLogger("SihaLink-Telemetry")


def _build_otlp_endpoint(path: str) -> str:
    """Construct full Dynatrace OTLP endpoint URL for a given signal path."""
    env_id = os.getenv("DYNATRACE_ENV_ID", "")
    if not env_id:
        return ""
    return f"https://{env_id}.live.dynatrace.com/api/v2/otlp{path}"


def _build_headers() -> dict:
    """Build the Authorization header required by Dynatrace OTLP API."""
    token = os.getenv("DYNATRACE_API_TOKEN", "")
    if not token:
        return {}
    return {"Authorization": f"Api-Token {token}"}


def init_telemetry() -> bool:
    """
    Initialise OpenTelemetry TracerProvider, MeterProvider, and LoggerProvider
    configured to export to Dynatrace via OTLP/HTTP.

    Returns True if telemetry was initialised, False if env vars are missing
    (in which case the app continues without telemetry — no crash).
    """
    env_id = os.getenv("DYNATRACE_ENV_ID")
    token = os.getenv("DYNATRACE_API_TOKEN")

    if not env_id or not token:
        logger.info(
            "[Telemetry] DYNATRACE_ENV_ID or DYNATRACE_API_TOKEN not set — "
            "Dynatrace telemetry disabled. App continues normally."
        )
        return False

    try:
        from opentelemetry import trace, metrics
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter,
        )

        # ── Shared resource attributes ────────────────────────────────────
        resource = Resource.create(
            {
                "service.name": "sihalink-orchestrator",
                "service.version": os.getenv("SERVICE_VERSION", "1.0.0"),
                "deployment.environment": os.getenv("ENVIRONMENT", "production"),
                "service.namespace": "sihalink",
                "cloud.provider": "gcp",
                "cloud.region": os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
            }
        )

        headers = _build_headers()

        # ── Traces ────────────────────────────────────────────────────────
        trace_exporter = OTLPSpanExporter(
            endpoint=_build_otlp_endpoint("/v1/traces"),
            headers=headers,
        )
        tracer_provider = TracerProvider(resource=resource)
        tracer_provider.add_span_processor(BatchSpanProcessor(trace_exporter))
        trace.set_tracer_provider(tracer_provider)

        # ── Metrics ───────────────────────────────────────────────────────
        metric_exporter = OTLPMetricExporter(
            endpoint=_build_otlp_endpoint("/v1/metrics"),
            headers=headers,
        )
        metric_reader = PeriodicExportingMetricReader(
            metric_exporter,
            export_interval_millis=30_000,  # export every 30 s
        )
        meter_provider = MeterProvider(
            resource=resource, metric_readers=[metric_reader]
        )
        metrics.set_meter_provider(meter_provider)

        # ── Logs (OTel log bridge) ─────────────────────────────────────────
        _init_log_bridge(resource, headers)

        logger.info(
            "[Telemetry] ✅ Dynatrace OTel initialised → "
            "https://%s.live.dynatrace.com",
            env_id,
        )
        return True

    except ImportError as exc:
        logger.warning(
            "[Telemetry] OpenTelemetry package missing (%s). "
            "Run: pip install -r requirements.txt",
            exc,
        )
        return False
    except Exception as exc:
        logger.error("[Telemetry] Init failed (non-fatal): %s", exc)
        return False


def _init_log_bridge(resource, headers: dict) -> None:
    """
    Bridge Python stdlib logging → OTel log records → Dynatrace.
    Only available in opentelemetry-sdk >= 1.20.
    """
    try:
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.sdk._logs import LoggerProvider
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.exporter.otlp.proto.http._log_exporter import (
            OTLPLogExporter,
        )
        from opentelemetry.instrumentation.logging import LoggingInstrumentor

        log_exporter = OTLPLogExporter(
            endpoint=_build_otlp_endpoint("/v1/logs"),
            headers=headers,
        )
        log_provider = LoggerProvider(resource=resource)
        log_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
        set_logger_provider(log_provider)

        # Attach OTel trace/span IDs to every Python log record
        LoggingInstrumentor().instrument(set_logging_format=True)

        logger.info("[Telemetry] Log bridge initialised → Dynatrace")
    except Exception as exc:
        logger.debug("[Telemetry] Log bridge skipped: %s", exc)


def get_tracer(name: str = "sihalink"):
    """Return a named OTel tracer for custom span creation."""
    from opentelemetry import trace  # type: ignore

    return trace.get_tracer(name)


def get_meter(name: str = "sihalink"):
    """Return a named OTel meter for custom metrics."""
    from opentelemetry import metrics  # type: ignore

    return metrics.get_meter(name)
