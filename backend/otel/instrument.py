"""OpenTelemetry auto-instrumentation wrapper for Siggy."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

from cli.config import SiggyConfig


def build_instrumented_env(
    config: SiggyConfig,
    service_name: str,
    session_id: str,
    extra_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build a child process environment with OTel instrumentation enabled."""
    env = os.environ.copy()

    env["OTEL_EXPORTER_OTLP_ENDPOINT"] = config.signoz.otlp_endpoint
    env["OTEL_SERVICE_NAME"] = service_name
    env["OTEL_TRACES_EXPORTER"] = "otlp"
    env["OTEL_METRICS_EXPORTER"] = "otlp"
    env["OTEL_LOGS_EXPORTER"] = "otlp"
    env["OTEL_RESOURCE_ATTRIBUTES"] = (
        f"service.name={service_name},"
        "deployment.environment=development,"
        f"siggy.session_id={session_id}"
    )
    env["OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED"] = "true"

    backend_dir = str(Path(__file__).resolve().parent.parent)
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{backend_dir}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else backend_dir

    if extra_env:
        env.update(extra_env)

    return env


def launch_process(command: list[str], env: dict[str, str]) -> subprocess.Popen:
    """Launch the instrumented process using opentelemetry-instrument."""
    full_command = ["opentelemetry-instrument"] + command

    if sys.platform == "win32":
        return subprocess.Popen(
            full_command,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            universal_newlines=True,
        )

    return subprocess.Popen(
        full_command,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        universal_newlines=True,
    )


def detect_framework(command: list[str]) -> str:
    """Detect the framework from the command arguments."""
    cmd_str = " ".join(command).lower()
    if "uvicorn" in cmd_str or "fastapi" in cmd_str:
        return "FastAPI"
    if "flask" in cmd_str or "gunicorn" in cmd_str:
        return "Flask"
    if "django" in cmd_str:
        return "Django"
    return "Python"


from pathlib import Path
