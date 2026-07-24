"""Launch the demo Flask app with OTel instrumentation."""
import os
import subprocess
import sys

os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4317"
os.environ["OTEL_SERVICE_NAME"] = "demo-api"
os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
os.environ["OTEL_METRICS_EXPORTER"] = "otlp"
os.environ["OTEL_LOGS_EXPORTER"] = "otlp"
os.environ["OTEL_RESOURCE_ATTRIBUTES"] = "service.name=demo-api,deployment.environment=development"

# Find opentelemetry-instrument
otel_bin = None
for p in [
    r"C:\Users\DELL\AppData\Roaming\Python\Python314\Scripts\opentelemetry-instrument.exe",
    "opentelemetry-instrument",
]:
    if os.path.exists(p):
        otel_bin = p
        break

if not otel_bin:
    print("ERROR: opentelemetry-instrument not found")
    sys.exit(1)

print(f"Using: {otel_bin}")
print(f"OTEL_EXPORTER_OTLP_ENDPOINT: {os.environ['OTEL_EXPORTER_OTLP_ENDPOINT']}")
print(f"OTEL_SERVICE_NAME: {os.environ['OTEL_SERVICE_NAME']}")
print(f"Starting demo app with OTel instrumentation...")

proc = subprocess.Popen(
    [otel_bin, sys.executable, "app.py"],
    cwd=os.path.dirname(os.path.abspath(__file__)),
    env=os.environ,
)
proc.wait()
