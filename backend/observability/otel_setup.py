"""OpenTelemetry -> Langfuse wiring.

Langfuse accepts raw OTLP/HTTP, so no vendor SDK is needed: one exporter with a
basic-auth header sends every span this codebase creates. When Langfuse keys are
absent, ``span()`` degrades to a no-op context manager and nothing else changes.
"""

from __future__ import annotations

import base64
import logging
from contextlib import contextmanager
from typing import Any, Iterator

from config import settings

logger = logging.getLogger("aries.otel")

_initialised = False
_tracer: Any = None


def setup_tracing(service_name: str = "aries-voice") -> None:
    """Install a global tracer provider. Safe to call more than once."""

    global _initialised, _tracer
    if _initialised:
        return
    _initialised = True

    if not settings.tracing_enabled:
        logger.info("Langfuse keys absent; tracing disabled")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        auth = base64.b64encode(
            f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}".encode()
        ).decode()

        provider = TracerProvider(
            resource=Resource.create({"service.name": service_name})
        )
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(
                    endpoint=f"{settings.langfuse_host.rstrip('/')}/api/public/otel/v1/traces",
                    headers={"Authorization": f"Basic {auth}"},
                )
            )
        )
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(service_name)
        logger.info("tracing enabled -> %s", settings.langfuse_host)
    except Exception as exc:  # noqa: BLE001 - tracing must never break the app
        logger.warning("tracing setup failed, continuing untraced: %s", exc)
        _tracer = None


@contextmanager
def span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    """Create a span if tracing is on, otherwise do nothing measurable."""

    if _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(name) as current:
        for key, value in (attributes or {}).items():
            try:
                current.set_attribute(key, value)
            except Exception:  # noqa: BLE001
                pass
        yield current


def shutdown_tracing() -> None:
    """Flush pending spans. Call on graceful shutdown."""

    if _tracer is None:
        return
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        if hasattr(provider, "shutdown"):
            provider.shutdown()
    except Exception:  # noqa: BLE001
        pass
