"""Backward-compatibility wrapper.

When running from source, this delegates to siggy_server.main.
When installed via pip, use ``uvicorn siggy_server.main:app`` directly.
"""
from siggy_server.main import app  # noqa: F401
