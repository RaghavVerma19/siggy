"""Centralized path resolution for Siggy runtime files.

All runtime data (databases, .env, data JSONs) lives under ~/.siggy/.
This works both when running from source and when installed via pip.
"""

from __future__ import annotations

import os
from pathlib import Path


def siggy_home() -> Path:
    """Return ~/.siggy/, creating it if it doesn't exist."""
    home = Path(os.getenv("SIGGY_HOME", Path.home() / ".siggy"))
    home.mkdir(parents=True, exist_ok=True)
    return home


def siggy_data_dir() -> Path:
    """Return ~/.siggy/data/, creating it if it doesn't exist."""
    d = siggy_home() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def siggy_env_path() -> Path:
    """Return the path to ~/.siggy/.env."""
    return siggy_home() / ".env"


def siggy_experience_db() -> Path:
    return siggy_data_dir() / "experience.db"


def siggy_graph_db() -> Path:
    return siggy_data_dir() / "graph.db"


def siggy_incidents_db() -> Path:
    return siggy_data_dir() / "siggy_incidents.db"
