import os
import socket

import phoenix as px
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from openinference.instrumentation.google_genai import GoogleGenAIInstrumentor

_initialized = False


def _is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def init_agent_observability():
    """
    Initializes Arize Phoenix tracing backend and instruments the next-generation google-genai SDK for complete telemetry.
    """
    global _initialized
    if _initialized:
        return

    # 1. Check if it is local development or Cloud Run environment
    # If in Cloud Run, we will send data to the remote Phoenix Collector; if local, directly launch the embedded dashboard
    PHOENIX_COLLECTOR_URL = os.getenv("PHOENIX_COLLECTOR_URL")

    provider = TracerProvider()

    on_cloud_run = bool(os.getenv("K_SERVICE"))

    if PHOENIX_COLLECTOR_URL:
        print(f"🌐 [Phoenix Radar] Routing telemetry to remote collector: {PHOENIX_COLLECTOR_URL}")
        exporter = OTLPSpanExporter(endpoint=f"{PHOENIX_COLLECTOR_URL}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))

    elif on_cloud_run:
        print("☁️ [Phoenix Radar] Cloud Run — skipping embedded Phoenix UI (set PHOENIX_COLLECTOR_URL for remote traces)")

    else:
        phoenix_ui_port = int(os.getenv("PHOENIX_PORT", "6006"))
        phoenix_grpc_port = int(os.getenv("PHOENIX_GRPC_PORT", "4317"))

        if _is_port_in_use(phoenix_ui_port) or _is_port_in_use(phoenix_grpc_port):
            # uvicorn --reload imports the app twice; reuse the already-running Phoenix instance
            print(
                f"🖥️ [Phoenix Radar] Phoenix already running on ports {phoenix_ui_port}/{phoenix_grpc_port}, "
                "attaching to existing instance..."
            )
        else:
            print("🖥️ [Phoenix Radar] Launching local embedded Phoenix database server...")
            px.launch_app()

        local_exporter = OTLPSpanExporter(endpoint=f"http://127.0.0.1:{phoenix_ui_port}/v1/traces")
        provider.add_span_processor(SimpleSpanProcessor(local_exporter))

    trace.set_tracer_provider(provider)

    instrumentor = GoogleGenAIInstrumentor()
    if not instrumentor.is_instrumented_by_opentelemetry:
        instrumentor.instrument(tracer_provider=provider)

    _initialized = True
    print("🟢 [Phoenix Radar] Next-Gen Google GenAI client successfully instrumented!")