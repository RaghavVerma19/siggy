#!/bin/bash
# Demo: instrument a Flask app with Siggy and run it
#
# Usage:
#   cd demo
#   pip install -r requirements.txt
#   bash run.sh
#
# Or with siggy CLI:
#   siggy instrument --service demo-api python app.py

set -e

echo "Starting demo-api with Siggy auto-instrumentation..."
echo ""

cd "$(dirname "$0")"

if command -v siggy &> /dev/null; then
    siggy instrument --service demo-api python app.py
else
    echo "siggy CLI not found. Running with manual OTel setup..."
    export OTEL_SERVICE_NAME=demo-api
    export OTEL_TRACES_EXPORTER=otlp
    export OTEL_METRICS_EXPORTER=otlp
    export OTEL_LOGS_EXPORTER=otlp
    export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
    export OTEL_RESOURCE_ATTRIBUTES="service.name=demo-api,deployment.environment=development"

    opentelemetry-instrument python app.py
fi
