"""Demo Flask app for Siggy — generates telemetry to test the full pipeline.

Run with:
  siggy instrument python app.py          (recommended — auto-instrumented)
  python app.py                           (needs opentelemetry-instrument wrapper)
  python app.py --no-otel                 (no tracing, just the Flask routes)

When run under `siggy instrument`, OTel is configured via environment variables
set by the CLI wrapper. Programmatic setup is only used as a fallback when
neither the CLI wrapper nor the opentelemetry-instrument CLI is available.
"""

import os
import random
import time
from flask import Flask, jsonify

app = Flask(__name__)

# Only set up OTel if not already configured by the instrumentor
_otel_enabled = os.getenv("OTEL_SERVICE_NAME") or os.getenv("OTEL_TRACES_EXPORTER")

if not _otel_enabled and "--no-otel" not in os.sys.argv:
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.flask import FlaskInstrumentor

        resource = Resource.create({
            SERVICE_NAME: os.getenv("OTEL_SERVICE_NAME", "demo-api"),
            "deployment.environment": "development",
        })
        provider = TracerProvider(resource=resource)
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        FlaskInstrumentor().instrument_app(app)
    except ImportError:
        pass  # OTel packages not installed, run without tracing

REQUEST_COUNT = 0


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "demo-api"})


@app.route("/fast")
def fast():
    time.sleep(random.uniform(0.01, 0.05))
    return jsonify({"status": "ok", "latency_ms": random.randint(10, 50)})


@app.route("/slow")
def slow():
    delay = random.uniform(2.0, 5.0)
    time.sleep(delay)
    return jsonify({"status": "ok", "latency_ms": int(delay * 1000)})


@app.route("/error")
def error():
    error_type = random.choice([
        "ConnectionRefusedError: Redis connection refused",
        "TimeoutError: Request timeout after 30s",
        "MemoryError: Unable to allocate 2GB",
        "ValueError: Invalid JSON payload",
    ])
    raise Exception(error_type)


@app.route("/flaky")
def flaky():
    if random.random() < 0.3:
        raise Exception("Intermittent database connection timeout")
    time.sleep(random.uniform(0.1, 0.3))
    return jsonify({"status": "ok"})


@app.route("/load")
def load():
    total = 0
    for _ in range(100000):
        total += random.randint(1, 100)
    return jsonify({"status": "ok", "computed": total})


@app.route("/")
def index():
    return jsonify({
        "service": "demo-api",
        "endpoints": ["/health", "/fast", "/slow", "/error", "/flaky", "/load"],
    })


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
