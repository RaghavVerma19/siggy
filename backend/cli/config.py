"""Siggy configuration — reads and writes .siggy.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


CONFIG_FILENAME = ".siggy.yaml"


@dataclass
class SigNozConfig:
    url: str = "http://localhost:8080"
    otlp_endpoint: str = "http://localhost:4317"
    mcp_url: str = "http://localhost:8000/mcp"
    api_key: str = ""
    dashboard_url: str = ""


@dataclass
class ServiceConfig:
    default_name: str = "my-service"


@dataclass
class MemoryConfig:
    backend_url: str = "http://localhost:8010"
    qdrant_url: str = "http://localhost:6333"


@dataclass
class SiggyConfig:
    signoz: SigNozConfig = field(default_factory=SigNozConfig)
    service: ServiceConfig = field(default_factory=ServiceConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)

    @classmethod
    def load(cls, path: Path | None = None) -> "SiggyConfig":
        path = path or _find_config()
        if path is None:
            return cls()

        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        return cls(
            signoz=SigNozConfig(**raw.get("signoz", {})),
            service=ServiceConfig(**raw.get("service", {})),
            memory=MemoryConfig(**raw.get("memory", {})),
        )

    def save(self, path: Path | None = None) -> Path:
        path = path or Path.cwd() / CONFIG_FILENAME
        data = {
            "signoz": {
                "url": self.signoz.url,
                "otlp_endpoint": self.signoz.otlp_endpoint,
                "mcp_url": self.signoz.mcp_url,
                "api_key": self.signoz.api_key or os.getenv("SIGNOZ_API_KEY", ""),
                "dashboard_url": self.signoz.dashboard_url,
            },
            "service": {"default_name": self.service.default_name},
            "memory": {
                "backend_url": self.memory.backend_url,
                "qdrant_url": self.memory.qdrant_url,
            },
        }
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        return path


def _find_config() -> Path | None:
    current = Path.cwd()
    for parent in [current, *current.parents]:
        candidate = parent / CONFIG_FILENAME
        if candidate.exists():
            return candidate
    return None
