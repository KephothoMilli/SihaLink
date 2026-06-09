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

Required API token scopes (create at Settings → Access tokens):
  - openTelemetryTrace.ingest   (classic OTLP traces)
  - openTelemetryMetric.ingest  (classic OTLP metrics)
  - openTelemetryLog.ingest     (classic OTLP logs)
  - openpipeline:traces:ingest  (required on newer SaaS tenants)
  - openpipeline:logs:ingest    (required on newer SaaS tenants)

Reference: https://docs.dynatrace.com/docs/ingest-from/opentelemetry/monitor
"""

import logging
import os

logger = logging.getLogger("SihaLink-Telemetry")


class _SuppressOTLPExportErrors(logging.Filter):
    """
    Filter that lets the FIRST OTel exporter 4xx error through as a WARNING,
    then silently drops all subsequent repeats so the terminal isn't spammed.

    Attach this to every logger that the OTel SDK uses internally.
    """
    _warned: bool = False

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        is_export_error = (
            "Failed to export" in msg
            or "Export" in msg
            or "403" in msg
            or "401" in msg
            or "429" in msg
            or "missing required scope" in msg
            or "Access token" in msg
        )
        if not is_export_error:
            return True  # not an export error — pass through unchanged

        if not _SuppressOTLPExportErrors._warned:
            _SuppressOTLPExportErrors._warned = True
            # Rewrite as a single clear WARNING with a fix hint
            record.levelno   = logging.WARNING
            record.levelname = "WARNING"
            record.msg = (
                "[Telemetry] Dynatrace OTel export failed (will suppress repeats). "
                "Fix: add 'openpipeline:traces:ingest' + 'openTelemetryTrace.ingest' "
                "scopes to the token at "
                "https://xjn51780.live.dynatrace.com/ui/settings/access-tokens — "
                "original error: %s"
            )
            record.args = (msg,)
            return True

        # All subsequent export errors → drop completely (DEBUG is too noisy too)
        return False


# Attach the filter to ALL loggers the OTel SDK uses for export errors
_suppress_filter = _SuppressOTLPExportErrors()
for _log_name in (
    "opentelemetry.exporter.otlp.proto.http",
    "opentelemetry.exporter.otlp.proto.http.trace_exporter",
    "opentelemetry.exporter.otlp.proto.http.metric_exporter",
    "opentelemetry.sdk.trace.export",
    "opentelemetry.sdk.metrics.export",
    "opentelemetry.sdk.logs.export",
    # The SDK sometimes logs via the root BatchSpanProcessor logger
    "opentelemetry.sdk.trace",
):
    _otel_logger = logging.getLogger(_log_name)
    _otel_logger.addFilter(_suppress_filter)
    # Ensure the logger itself doesn't block propagation
    _otel_logger.propagate = True


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


# Holds references to OTel providers so graceful_shutdown() can flush them
_telemetry_state: dict = {}


def graceful_shutdown() -> None:
    """
    Flush and shut down OTel providers cleanly on process exit.
    Call this from the FastAPI lifespan shutdown hook to prevent
    'Task was destroyed but it is pending!' warnings from aiohttp/genai.
    """
    tracer_provider = _telemetry_state.get("tracer_provider")
    meter_provider  = _telemetry_state.get("meter_provider")

    if tracer_provider:
        try:
            tracer_provider.shutdown()
            logger.debug("[Telemetry] TracerProvider shut down cleanly")
        except Exception as exc:
            logger.debug("[Telemetry] TracerProvider shutdown error: %s", exc)

    if meter_provider:
        try:
            meter_provider.shutdown()
            logger.debug("[Telemetry] MeterProvider shut down cleanly")
        except Exception as exc:
            logger.debug("[Telemetry] MeterProvider shutdown error: %s", exc)


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
        tracer_provider.add_span_processor(
            BatchSpanProcessor(
                trace_exporter,
                # Longer schedule reduces export frequency → fewer 403 log lines
                # even before the filter kicks in
                schedule_delay_millis=60_000,   # flush every 60 s (default: 5 s)
                max_export_batch_size=128,
                export_timeout_millis=10_000,
            )
        )
        trace.set_tracer_provider(tracer_provider)
        # Store reference so graceful_shutdown() can flush + close cleanly
        _telemetry_state["tracer_provider"] = tracer_provider
        logger.info(
            "[Telemetry] Traces → %s  "
            "(if 403: add 'openpipeline:traces:ingest' and "
            "'openTelemetryTrace.ingest' to the Dynatrace token)",
            _build_otlp_endpoint("/v1/traces"),
        )

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
        _telemetry_state["meter_provider"] = meter_provider

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
