"""Siggy CLI — the main entry point for all siggy commands."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import click

from cli.config import SiggyConfig


@click.group()
@click.version_option(version="0.3.0", prog_name="siggy")
def cli():
    """Siggy — AI-powered observability with memory."""
    pass


@cli.command()
@click.option("--url", default="http://localhost:8080", help="SigNoz URL")
@click.option("--mcp-url", default="http://localhost:8000/mcp", help="SigNoz MCP URL")
@click.option("--otlp", default="http://localhost:4317", help="OTLP collector endpoint")
@click.option("--api-key", default="", help="SigNoz API key (or set SIGNOZ_API_KEY)")
@click.option("--backend-url", default="http://localhost:8010", help="Siggy backend URL")
def init(url: str, mcp_url: str, otlp: str, api_key: str, backend_url: str):
    """Initialize Siggy — connect to SigNoz and set up memory stores."""
    config = SiggyConfig()
    config.signoz.url = url
    config.signoz.mcp_url = mcp_url
    config.signoz.otlp_endpoint = otlp
    config.signoz.api_key = api_key or os.getenv("SIGNOZ_API_KEY", "")
    config.memory.backend_url = backend_url

    click.echo("Siggy Init")
    click.echo("=" * 40)

    path = config.save()
    click.echo(f"Config saved: {path}")

    click.echo("\nChecking connections...")

    signoz_ok = _check_signoz(config)
    _check_mcp(config)
    _check_backend(config)

    if signoz_ok and not config.signoz.api_key:
        config.signoz.api_key = _prompt_api_key(config.signoz.url)

    if config.signoz.api_key:
        from signoz.dashboards import validate_api_key
        valid, msg = validate_api_key(config.signoz.api_key, config.signoz.url)
        if valid:
            click.echo(f"  \u2713 {msg} — dashboard integration enabled")
        else:
            click.echo(f"  \u2717 {msg}")
            click.echo("    Other features (CLI, OTel write-back) still work fine.")
        path = config.save()
        click.echo(f"  Config updated: {path}")

    click.echo("\nSeeding baseline services...")
    _seed_baseline_services(config)

    click.echo("\n" + "=" * 40)
    click.echo("Siggy is ready. Next steps:")
    click.echo()
    click.echo("  1. Start the server:       siggy serve")
    click.echo("  2. Instrument your app:    siggy instrument python app.py")
    click.echo("  3. Watch alerts:           siggy watch")
    click.echo("  4. Investigate manually:   siggy investigate 'Redis timeout'")
    click.echo()
    click.echo("  Run 'siggy status' to check all connections.")


def _check_signoz(config: SiggyConfig) -> bool:
    import httpx

    try:
        r = httpx.get(
            f"{config.signoz.url}/api/v2/rules",
            headers={"SIGNOZ-API-KEY": config.signoz.api_key},
            timeout=5,
        )
        if r.status_code < 400:
            click.echo(f"  \u2713 SigNoz reachable ({config.signoz.url})")
            return True
        else:
            click.echo(f"  \u2717 SigNoz responded with {r.status_code}")
    except Exception as e:
        click.echo(f"  \u2717 SigNoz unreachable: {e}")
    return False


def _prompt_api_key(signoz_url: str) -> str:
    """Prompt user for a SigNoz API key with clear instructions."""
    click.echo()
    click.echo("  Dashboard integration (auto-creates panels + saved views in SigNoz)")
    click.echo()
    click.echo("  To enable:")
    click.echo(f"    1. Open {signoz_url}/settings/service-accounts")
    click.echo("    2. Create a service account (\"Admin\" role)")
    click.echo("    3. Generate an API key")
    click.echo()
    key = click.prompt("  API key (or press Enter to skip)", default="", show_default=False)
    return key.strip()


def _check_mcp(config: SiggyConfig):
    import httpx

    try:
        r = httpx.get(config.signoz.mcp_url.replace("/mcp", ""), timeout=5)
        click.echo(f"  \u2713 MCP server reachable ({config.signoz.mcp_url})")
    except Exception:
        click.echo(f"  \u2139  MCP server not reachable (will retry on use)")


def _check_backend(config: SiggyConfig):
    import httpx

    try:
        r = httpx.get(f"{config.memory.backend_url}/api/v1/health", timeout=5)
        if r.status_code == 200:
            data = r.json()
            click.echo(f"  \u2713 Siggy backend ({data.get('incident_count', 0)} knowledge objects)")
        else:
            click.echo(f"  \u2717 Backend responded with {r.status_code}")
    except Exception:
        click.echo(f"  \u2139  Backend not running (start with 'siggy serve')")


def _seed_baseline_services(config: SiggyConfig):
    import httpx

    baseline_services = [
        "api-gateway",
        "cart-service",
        "payment-service",
        "auth-service",
        "notification-service",
    ]
    try:
        for svc in baseline_services:
            httpx.post(
                f"{config.memory.backend_url}/api/v1/knowledge/store",
                json={
                    "title": f"Baseline service: {svc}",
                    "summary": f"Baseline operational knowledge for {svc}. "
                    "This service is part of the core platform stack.",
                },
                timeout=5,
            )
        click.echo(f"  [OK] Seeded {len(baseline_services)} baseline services")
    except Exception:
        click.echo("  [..] Backend not running - skipping seed (will run on first server start)")


@cli.command()
@click.option("--force", is_flag=True, help="Overwrite existing .siggy.yaml")
def quickstart(force: bool):
    """One-command setup — get Siggy running with SigNoz in under 2 minutes.

    Checks Docker, Qdrant, SigNoz, and GROQ API key. Auto-configures everything.
    """
    import httpx

    click.echo("Siggy Quickstart")
    click.echo("=" * 50)
    click.echo()

    # ── Step 1: Check Docker ──
    click.echo("Checking Docker...")
    docker_ok = _quickstart_check_docker()
    click.echo()

    # ── Step 2: Check / start Qdrant ──
    click.echo("Checking Qdrant (vector database)...")
    qdrant_ok, qdrant_mode = _quickstart_check_qdrant(docker_ok)
    click.echo()

    # ── Step 3: Check SigNoz ──
    click.echo("Checking SigNoz...")
    signoz_url, mcp_url, otlp_endpoint, api_key = _quickstart_check_signoz()
    click.echo()

    # ── Step 4: Check GROQ API key ──
    click.echo("Checking GROQ API key...")
    groq_key = _quickstart_check_groq()
    click.echo()

    # ── Step 5: Write config ──
    config_exists = (Path.cwd() / ".siggy.yaml").exists()
    if config_exists and not force:
        click.echo("  [..] .siggy.yaml already exists (use --force to overwrite)")
    else:
        config = SiggyConfig()
        config.signoz.url = signoz_url
        config.signoz.mcp_url = mcp_url
        config.signoz.otlp_endpoint = otlp_endpoint
        config.signoz.api_key = api_key
        path = config.save()
        click.echo(f"  [OK] Config saved: {path}")

    # ── Step 6: Write .env if missing ──
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        env_lines = [
            f"GROQ_API_KEY={groq_key}",
            f"QDRANT_HOST=localhost",
            f"QDRANT_PORT=6333",
        ]
        if qdrant_mode == "embedded":
            env_lines.append(f"QDRANT_PATH={os.path.join(str(Path.home()), '.siggy', 'qdrant')}")
        env_lines.extend([
            f"SIGNOZ_URL={signoz_url}",
            f"SIGNOZ_MCP_URL={mcp_url}",
            f"SIGNOZ_API_KEY={api_key}",
        ])
        env_path.write_text("\n".join(env_lines) + "\n")
        click.echo(f"  [OK] .env created")
    else:
        click.echo("  [..] .env already exists")

    # ── Summary ──
    click.echo()
    click.echo("=" * 50)

    all_ok = qdrant_ok and signoz_url != "http://localhost:8080" or True
    if all_ok:
        click.echo("Quickstart complete!")
    else:
        click.echo("Quickstart complete (some checks need attention)")

    click.echo()
    click.echo("Next steps:")
    click.echo()
    click.echo("  1. Start Siggy:          siggy serve")
    click.echo("  2. Instrument your app:  siggy instrument python app.py")
    click.echo("  3. Watch recommendations appear in SigNoz Traces Explorer")
    click.echo()
    click.echo("  Filter in SigNoz: siggy.recommendation EXISTS")
    click.echo()

    if not qdrant_ok:
        click.echo("  [!!] Qdrant not detected — vector memory will use local fallback")
    if not groq_key or groq_key == "your-groq-api-key-here":
        click.echo("  [!!] GROQ_API_KEY not set — LLM recommendations will use rule-based fallback")
    click.echo()


def _quickstart_check_docker() -> bool:
    """Check if Docker is available."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            click.echo("  [OK] Docker available")
            return True
        else:
            click.echo("  [!!] Docker not running — will check for existing Qdrant")
            return False
    except FileNotFoundError:
        click.echo("  [!!] Docker not installed — Qdrant must be started manually")
        return False
    except Exception as e:
        click.echo(f"  [!!] Docker check failed: {e}")
        return False


def _quickstart_check_qdrant(docker_available: bool) -> tuple[bool, str]:
    """Check if Qdrant is running. Start via Docker or offer embedded mode.
    Returns (ok, mode) where mode is 'remote', 'embedded', or 'unavailable'."""
    import httpx

    try:
        r = httpx.get("http://localhost:6333/healthz", timeout=3)
        if r.status_code == 200:
            click.echo("  [OK] Qdrant running on localhost:6333")
            return True, "remote"
    except Exception:
        pass

    if not docker_available:
        # Offer embedded mode as fallback
        embedded_path = os.path.join(str(Path.home()), ".siggy", "qdrant")
        click.echo("  [..] Qdrant not running, Docker unavailable")
        click.echo(f"  [OK] Using embedded mode at {embedded_path}")
        click.echo("       (no Docker required, data stored locally)")
        return True, "embedded"

    # Try to start Qdrant via Docker
    click.echo("  Starting Qdrant via Docker...")
    try:
        result = subprocess.run(
            ["docker", "run", "-d", "--name", "siggy-qdrant", "-p", "6333:6333", "qdrant/qdrant"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            # Wait for it to be ready
            for _ in range(15):
                time.sleep(1)
                try:
                    r = httpx.get("http://localhost:6333/healthz", timeout=2)
                    if r.status_code == 200:
                        click.echo("  [OK] Qdrant started via Docker")
                        return True, "remote"
                except Exception:
                    pass
            click.echo("  [!!] Qdrant started but not yet healthy — may need a moment")
            return False, "unavailable"
        elif "already in use" in result.stderr or "already exists" in result.stderr:
            subprocess.run(["docker", "start", "siggy-qdrant"], capture_output=True, timeout=10)
            for _ in range(10):
                time.sleep(1)
                try:
                    r = httpx.get("http://localhost:6333/healthz", timeout=2)
                    if r.status_code == 200:
                        click.echo("  [OK] Qdrant restarted via Docker")
                        return True, "remote"
                except Exception:
                    pass
            click.echo("  [!!] Qdrant container exists but unhealthy")
            return False, "unavailable"
        else:
            # Docker failed, fall back to embedded
            embedded_path = os.path.join(str(Path.home()), ".siggy", "qdrant")
            click.echo(f"  [!!] Docker run failed, using embedded mode")
            click.echo(f"  [OK] Embedded Qdrant at {embedded_path}")
            return True, "embedded"
    except Exception as e:
        embedded_path = os.path.join(str(Path.home()), ".siggy", "qdrant")
        click.echo(f"  [!!] Could not start Docker: {e}")
        click.echo(f"  [OK] Using embedded mode at {embedded_path}")
        return True, "embedded"


def _quickstart_check_signoz() -> tuple[str, str, str, str]:
    """Auto-detect SigNoz configuration. Returns (url, mcp_url, otlp, api_key)."""
    import httpx

    signoz_url = "http://localhost:8080"
    mcp_url = "http://localhost:8000/mcp"
    otlp_endpoint = "http://localhost:4317"
    api_key = os.getenv("SIGNOZ_API_KEY", "")

    signoz_ok = False

    # Check if SigNoz is running
    try:
        r = httpx.get(f"{signoz_url}/api/v2/rules", timeout=5)
        if r.status_code < 400:
            click.echo(f"  [OK] SigNoz UI at {signoz_url}")
            signoz_ok = True
        else:
            click.echo(f"  [!!] SigNoz responded with {r.status_code}")
    except Exception:
        click.echo(f"  [!!] SigNoz not reachable at {signoz_url}")
        click.echo("       Make sure SigNoz is running (Docker Compose or Foundry)")

    # Check MCP
    try:
        r = httpx.get(mcp_url.replace("/mcp", ""), timeout=5)
        click.echo(f"  [OK] MCP server at {mcp_url}")
    except Exception:
        click.echo(f"  [!!] MCP not reachable at {mcp_url}")

    # Check OTLP collector
    try:
        import socket
        host, port = otlp_endpoint.replace("http://", "").split(":")
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((host, int(port)))
        s.close()
        click.echo(f"  [OK] OTLP collector at {otlp_endpoint}")
    except Exception:
        click.echo(f"  [!!] OTLP collector not reachable at {otlp_endpoint}")
        click.echo("       Traces won't be collected until the collector is running")

    # API key
    if api_key:
        click.echo(f"  [OK] SIGNOZ_API_KEY set")
    elif signoz_ok:
        api_key = _prompt_api_key(signoz_url)
        if api_key:
            from signoz.dashboards import validate_api_key
            valid, msg = validate_api_key(api_key, signoz_url)
            if valid:
                click.echo(f"  [OK] {msg} — dashboard integration enabled")
            else:
                click.echo(f"  [!!] {msg}")
                click.echo("       Other features still work fine.")
    else:
        click.echo("  [..] SIGNOZ_API_KEY not set (optional — needed for dashboard integration)")

    return signoz_url, mcp_url, otlp_endpoint, api_key


def _quickstart_check_groq() -> str:
    """Check GROQ_API_KEY. Returns the key or placeholder."""
    key = os.getenv("GROQ_API_KEY", "")
    if key:
        click.echo(f"  [OK] GROQ_API_KEY set ({key[:8]}...)")
        return key

    # Check .env file
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("GROQ_API_KEY=") and not line.endswith("your-groq-api-key-here"):
                key = line.split("=", 1)[1]
                click.echo(f"  [OK] GROQ_API_KEY found in .env ({key[:8]}...)")
                return key

    click.echo("  [..] GROQ_API_KEY not found")
    click.echo("       Get a free key at https://console.groq.com")
    click.echo("       Then set it: export GROQ_API_KEY=gsk_...")
    return ""


def _detect_framework(command: tuple) -> str | None:
    """Auto-detect framework from the command."""
    cmd_list = [c.lower() for c in command]
    if "uvicorn" in cmd_list:
        return "fastapi"
    if "gunicorn" in cmd_list:
        return "wsgi"
    if any("flask" in c for c in cmd_list):
        return "flask"
    if any("django" in c for c in cmd_list):
        return "django"
    return None


def _detect_service_name(command: tuple) -> str | None:
    """Try to infer a service name from the command (e.g. app.py → app)."""
    for part in command:
        if part.endswith(".py"):
            return Path(part).stem
    return None


@cli.command()
@click.argument("command", nargs=-1, required=True)
@click.option("--service", "-s", default=None, help="Service name for OTel resource")
@click.option("--env", "-e", multiple=True, help="Extra env vars (KEY=VALUE)")
@click.option("--no-wait", is_flag=True, help="Don't wait for app to start (just launch)")
def instrument(command: tuple, service: str | None, env: tuple, no_wait: bool):
    """Wrap any Python app with OpenTelemetry and run it.

    Examples:
        siggy instrument python app.py
        siggy instrument --service checkout-api python app.py
        siggy instrument uvicorn app:app --reload
    """
    config = SiggyConfig.load()

    if not command:
        click.echo("Error: No command provided. Usage: siggy instrument python app.py")
        sys.exit(1)

    framework = _detect_framework(command)
    inferred_name = _detect_service_name(command)
    service_name = service or inferred_name or config.service.default_name
    session_id = f"sess_{uuid.uuid4().hex[:8]}"

    from otel.instrument import build_instrumented_env, launch_process

    child_env = build_instrumented_env(
        config=config,
        service_name=service_name,
        session_id=session_id,
        extra_env=dict(e.split("=", 1) for e in env if "=" in e),
    )

    cmd_str = " ".join(command)
    click.echo()
    click.echo(f"Siggy Instrument")
    click.echo("=" * 40)
    click.echo(f"  Service     {service_name}")
    if framework:
        click.echo(f"  Framework   {framework}")
    click.echo(f"  Session     {session_id}")
    click.echo(f"  Collector   {config.signoz.otlp_endpoint}")
    click.echo(f"  SigNoz      {config.signoz.url}")
    click.echo(f"  Command     {cmd_str}")
    click.echo()
    click.echo(f"  Auto-instrumentation enabled")
    click.echo(f"  Traces  yes    Metrics  yes    Logs  yes")
    click.echo()
    click.echo("Application Output")
    click.echo("-" * 40)

    proc = launch_process(list(command), child_env)

    def _shutdown(sig, frame):
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    sys.exit(proc.wait())


@cli.command()
@click.option("--interval", default=30, help="Poll interval in seconds")
@click.option("--webhook-port", default=None, type=int, help="Port for webhook callbacks (optional)")
def watch(interval: int, webhook_port: int | None):
    """Watch SigNoz alerts and enrich with memory layer.

    The sidecar polls SigNoz for alerts every INTERVAL seconds, enriches each
    with memory (vector search + experience ranking + knowledge graph), and
    writes recommendations back to SigNoz via OTel span attributes.
    """
    config = SiggyConfig.load()
    click.echo("Siggy Sidecar")
    click.echo("=" * 40)
    click.echo(f"  SigNoz     {config.signoz.url}")
    click.echo(f"  MCP        {config.signoz.mcp_url}")
    click.echo(f"  Polling    every {interval}s")
    if webhook_port:
        click.echo(f"  Webhook    port {webhook_port}")
    click.echo("  Press Ctrl+C to stop\n")

    from incident.processor import SiggySidecar

    sidecar = SiggySidecar(config)

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(sidecar.start_polling(interval=interval))
    except KeyboardInterrupt:
        click.echo("\nStopping sidecar...")
    finally:
        loop.close()


@cli.command()
def status():
    """Show Siggy system status."""
    import httpx

    config = SiggyConfig.load()

    click.echo("Siggy Status")
    click.echo("=" * 40)

    _status_check("Collector", f"http://{config.signoz.otlp_endpoint.replace('http://', '')}", "tcp")
    _status_check("SigNoz", config.signoz.url, "http")
    _status_check("MCP Server", config.signoz.mcp_url, "http")
    _status_check("Qdrant", config.memory.qdrant_url, "http")
    _status_check("Siggy Backend", config.memory.backend_url, "http")

    # Show incident count if backend is up
    try:
        r = httpx.get(f"{config.memory.backend_url}/api/v1/dashboard/summary", timeout=5)
        if r.status_code == 200:
            stats = r.json()
            click.echo()
            click.echo(f"  Knowledge objects:    {stats.get('knowledge_objects', 0)}")
            click.echo(f"  Experience records:   {stats.get('experience_records', 0)}")
            click.echo(f"  Operational patterns: {stats.get('operational_patterns', 0)}")
            click.echo(f"  Graph nodes:          {stats.get('graph_nodes', 0)}")
            click.echo(f"  Recommendation acc:   {stats.get('recommendation_accuracy', 0)}%")
    except Exception:
        pass

    click.echo("=" * 40)


def _status_check(name: str, url: str, check_type: str = "http"):
    if check_type == "tcp":
        host, port = url.replace("http://", "").split(":")
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect((host, int(port)))
            s.close()
            click.echo(f"  [OK] {name:16} {url}")
        except Exception:
            click.echo(f"  [!!] {name:16} unreachable")
    else:
        try:
            import httpx
            r = httpx.get(url, timeout=3)
            click.echo(f"  [OK] {name:16} {url}")
        except Exception:
            click.echo(f"  [!!] {name:16} unreachable")


@cli.command()
@click.argument("query")
def investigate(query: str):
    """Investigate an issue via the memory layer.

    Example: siggy investigate "Redis connection pool exhausted in cart-service"
    """
    import httpx

    config = SiggyConfig.load()
    click.echo(f"Investigating: {query}")
    click.echo("-" * 40)

    try:
        r = httpx.post(
            f"{config.memory.backend_url}/api/v1/telemetry/full-analysis",
            json={"query": query},
            timeout=30,
        )
        if r.status_code == 200:
            data = r.json()
            _print_investigation_result(data)
        else:
            click.echo(f"Error: Backend returned {r.status_code}")
            click.echo(r.text)
    except Exception as e:
        click.echo(f"Error: {e}")


def _print_investigation_result(data: dict):
    source = data.get("source", "unknown")
    click.echo(f"Source: {source}")

    if "recommendation" in data:
        click.echo(f"\nRecommendation: {data['recommendation']}")
        click.echo(f"Confidence: {data.get('confidence', 0):.0%}")
        if data.get("evidence"):
            click.echo("Evidence:")
            for item in data["evidence"][:3]:
                click.echo(f"  - {item}")

    if "similar_incidents" in data and data["similar_incidents"]:
        click.echo(f"\nSimilar incidents found: {len(data['similar_incidents'])}")
        for inc in data["similar_incidents"][:3]:
            click.echo(f"  - {inc.get('title', 'unknown')} (score: {inc.get('score', 0):.2f})")


@cli.command()
@click.option("--host", default="127.0.0.1", help="Host to bind")
@click.option("--port", default=8010, type=int, help="Port to bind")
def serve(host: str, port: int):
    """Start the Siggy API server + sidecar.

    Runs the FastAPI backend with the knowledge pipeline, experience engine,
    graph context, and the alert-watching sidecar.
    """
    config = SiggyConfig.load()

    os.environ["SIGNOZ_MCP_URL"] = config.signoz.mcp_url
    os.environ["SIGNOZ_API_KEY"] = config.signoz.api_key
    os.environ["SIGNOZ_URL"] = config.signoz.url
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = config.signoz.otlp_endpoint

    sys.path.insert(0, str(Path(__file__).parent.parent))

    click.echo("Starting Siggy server...")
    click.echo(f"  API        http://{host}:{port}/api/v1/health")
    click.echo(f"  SigNoz     {config.signoz.url}")
    click.echo(f"  MCP        {config.signoz.mcp_url}")
    click.echo(f"  Sidecar    polling every 30s (OTel write-back enabled)")
    click.echo()
    click.echo("  Press Ctrl+C to stop.")

    import uvicorn

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


@cli.command()
@click.argument("app_command", required=False)
@click.option("--service", "-s", default=None, help="Service name for OTel resource")
@click.option("--host", default="127.0.0.1", help="Backend host")
@click.option("--port", default=8010, type=int, help="Backend port")
def up(app_command: str | None, service: str | None, host: str, port: int):
    """Start Siggy sidecar + API server, optionally instrumenting your app.

    Examples:
        siggy up                              Start backend + sidecar only
        siggy up python app.py               Start backend + instrument your Flask app
        siggy up --service my-api python app.py
        siggy up uvicorn app:app --reload    Works with any Python framework

    What this does:
        1. Checks Qdrant, SigNoz, MCP connections
        2. Starts the Siggy backend (API + incident sidecar)
        3. If app_command is given, starts your app with OpenTelemetry
    """
    import httpx
    import threading

    config = SiggyConfig.load()
    os.environ["SIGNOZ_MCP_URL"] = config.signoz.mcp_url
    os.environ["SIGNOZ_API_KEY"] = config.signoz.api_key
    os.environ["SIGNOZ_URL"] = config.signoz.url
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = config.signoz.otlp_endpoint

    sys.path.insert(0, str(Path(__file__).parent.parent))

    click.echo()
    click.echo("Siggy Up")
    click.echo("=" * 50)
    click.echo()

    # ── Step 1: Check infrastructure ──
    click.echo("Checking infrastructure...")

    qdrant_ok = _up_check_qdrant(config)
    signoz_ok = _up_check_signoz(config)
    mcp_ok = _up_check_mcp(config)

    click.echo()

    # ── Step 2: Start the backend server ──
    click.echo("Starting Siggy backend...")

    import uvicorn

    def _run_server():
        uvicorn.run(
            "main:app",
            host=host,
            port=port,
            reload=False,
            log_level="warning",
        )

    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()

    backend_url = f"http://{host}:{port}"
    for _ in range(30):
        try:
            r = httpx.get(f"{backend_url}/api/v1/health", timeout=2)
            if r.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        click.echo("  Backend failed to start within 15s")
        return

    click.echo(f"  Backend ready at {backend_url}")
    click.echo(f"  API         {backend_url}/api/v1/health")
    click.echo(f"  Sidecar     polling every 30s (OTel write-back enabled)")

    # ── Step 3: Start the user's app with OTel (optional) ──
    user_proc = None
    if app_command:
        click.echo()
        click.echo("Starting instrumented application...")

        cmd_parts = _parse_app_command(app_command)
        framework = _detect_framework(tuple(cmd_parts))
        inferred_name = _detect_service_name(tuple(cmd_parts))
        service_name = service or inferred_name or config.service.default_name
        session_id = f"sess_{uuid.uuid4().hex[:8]}"

        click.echo(f"  Service   {service_name}")
        if framework:
            click.echo(f"  Framework {framework}")
        click.echo(f"  Session   {session_id}")
        click.echo(f"  Command   {app_command}")

        from otel.instrument import build_instrumented_env, launch_process

        child_env = build_instrumented_env(
            config=config,
            service_name=service_name,
            session_id=session_id,
        )

        user_proc = launch_process(cmd_parts, child_env)

        def _shutdown_user(sig, frame):
            if user_proc and user_proc.poll() is None:
                user_proc.terminate()
            sys.exit(0)

        signal.signal(signal.SIGINT, _shutdown_user)

        click.echo(f"  Application started (OTel -> {config.signoz.otlp_endpoint})")
    else:
        click.echo()
        click.echo("  No app specified. To instrument your app:")
        click.echo(f"    siggy up python app.py")
        click.echo()

    # ── Step 4: Print status ──
    click.echo()
    click.echo("=" * 50)
    click.echo("Siggy is running!")
    click.echo()
    click.echo("  API:       " + backend_url + "/api/v1/health")
    click.echo("  SigNoz:    " + config.signoz.url)
    if not qdrant_ok:
        click.echo("  [!!] Qdrant not detected - vector memory degraded")
    if not signoz_ok:
        click.echo("  [!!] SigNoz not detected - telemetry endpoints unavailable")
    if not mcp_ok:
        click.echo("  [!!] MCP not detected - live incident detection disabled")
    click.echo()
    click.echo("  How it works:")
    click.echo("    1. Your app sends traces to SigNoz via OTel")
    click.echo("    2. SigNoz detects errors in traces")
    click.echo("    3. Siggy sidecar enriches errors with memory (similar past incidents)")
    click.echo("    4. Recommendations appear in SigNoz as OTel span attributes")
    click.echo("    5. Recommendations also appear in SigNoz dashboards/logs")
    click.echo()
    click.echo("  Press Ctrl+C to stop.")
    click.echo()

    # ── Keep running ──
    try:
        while True:
            if user_proc and user_proc.poll() is not None:
                click.echo("\n  Application exited. Stopping Siggy...")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        if user_proc and user_proc.poll() is None:
            user_proc.terminate()
            try:
                user_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                user_proc.kill()
        click.echo("Siggy stopped.")


def _parse_app_command(app_command: str) -> list[str]:
    """Parse an app command string into a list of arguments.

    Handles both "python app.py" and "uvicorn app:app --reload".
    """
    import shlex
    try:
        return shlex.split(app_command)
    except ValueError:
        return app_command.split()


def _up_check_qdrant(config: SiggyConfig) -> bool:
    """Check if Qdrant is reachable. Try to start via Docker if not."""
    import httpx

    try:
        r = httpx.get(f"{config.memory.qdrant_url}/healthz", timeout=3)
        if r.status_code == 200:
            click.echo(f"  [OK] Qdrant ready ({config.memory.qdrant_url})")
            return True
    except Exception:
        pass

    # Try to start via Docker
    click.echo("  Qdrant not running, attempting Docker start...")
    try:
        result = subprocess.run(
            ["docker", "run", "-d", "--name", "siggy-qdrant", "-p", "6333:6333", "qdrant/qdrant"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            # Wait for Qdrant to be ready
            for _ in range(10):
                time.sleep(1)
                try:
                    r = httpx.get(f"{config.memory.qdrant_url}/healthz", timeout=2)
                    if r.status_code == 200:
                        click.echo(f"  [OK] Qdrant started via Docker")
                        return True
                except Exception:
                    pass
        elif "already in use" in result.stderr or "already exists" in result.stderr:
            # Container exists but might be stopped
            subprocess.run(["docker", "start", "siggy-qdrant"], capture_output=True, timeout=10)
            for _ in range(5):
                time.sleep(1)
                try:
                    r = httpx.get(f"{config.memory.qdrant_url}/healthz", timeout=2)
                    if r.status_code == 200:
                        click.echo(f"  [OK] Qdrant restarted via Docker")
                        return True
                except Exception:
                    pass
    except FileNotFoundError:
        click.echo("  [!!] Docker not found -- install Qdrant manually")
    except Exception as e:
        click.echo(f"  [!!] Could not start Qdrant: {e}")

    click.echo(f"  [!!] Qdrant unreachable at {config.memory.qdrant_url}")
    click.echo(f"       Vector memory will use local fallback mode")
    return False


def _up_check_signoz(config: SiggyConfig) -> bool:
    """Check if SigNoz is reachable."""
    import httpx

    try:
        r = httpx.get(
            f"{config.signoz.url}/api/v2/rules",
            headers={"SIGNOZ-API-KEY": config.signoz.api_key},
            timeout=5,
        )
        if r.status_code < 400:
            click.echo(f"  [OK] SigNoz ready ({config.signoz.url})")
            return True
        else:
            click.echo(f"  [!!] SigNoz responded with {r.status_code}")
    except Exception:
        click.echo(f"  [!!] SigNoz unreachable at {config.signoz.url}")
        click.echo(f"       Live telemetry endpoints will be unavailable")
    return False


def _up_check_mcp(config: SiggyConfig) -> bool:
    """Check if MCP server is reachable."""
    import httpx

    try:
        r = httpx.get(config.signoz.mcp_url.replace("/mcp", ""), timeout=5)
        click.echo(f"  [OK] MCP server ready ({config.signoz.mcp_url})")
        return True
    except Exception:
        click.echo(f"  [!!] MCP unreachable at {config.signoz.mcp_url}")
        click.echo(f"       Live incident detection will use local fallback")
    return False


@cli.command()
@click.option("--host", default="127.0.0.1", help="Host to bind")
@click.option("--port", default=8010, type=int, help="Port to bind")
def demo(host: str, port: int):
    """Start a ready-to-go demo with seeded incidents and experience data.

    One command to see Siggy in action — no SigNoz or OTel setup needed.
    Seeds realistic incidents, experience records, and starts the API server.
    """
    import json as _json
    import hashlib
    import httpx

    sys.path.insert(0, str(Path(__file__).parent.parent))

    config = SiggyConfig.load()
    os.environ["SIGNOZ_MCP_URL"] = config.signoz.mcp_url
    os.environ["SIGNOZ_API_KEY"] = config.signoz.api_key
    os.environ["SIGNOZ_URL"] = config.signoz.url

    click.echo("Siggy Demo")
    click.echo("=" * 50)
    click.echo()

    # Step 1: Start the backend server in background
    click.echo("Starting backend server...")
    import uvicorn
    import threading

    def _run_server():
        uvicorn.run(
            "main:app",
            host=host,
            port=port,
            reload=False,
            log_level="warning",
        )

    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()

    # Wait for server to be ready
    backend_url = f"http://{host}:{port}"
    for _ in range(30):
        try:
            r = httpx.get(f"{backend_url}/api/v1/health", timeout=2)
            if r.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        click.echo("  Server failed to start within 15s")
        return

    click.echo("  Backend ready")

    # Step 2: Seed demo incidents
    click.echo("Seeding demo incidents...")
    _seed_demo_incidents(backend_url)

    # Step 3: Seed experience records so memory has data
    click.echo("Seeding experience records...")
    _seed_demo_experience(backend_url)

    # Step 4: Sync graph
    click.echo("Building knowledge graph...")
    try:
        httpx.post(f"{backend_url}/api/v1/graph/sync", timeout=15)
        click.echo("  Graph synced")
    except Exception:
        pass

    click.echo()
    click.echo("=" * 50)
    click.echo("Demo is running!")
    click.echo()
    click.echo(f"  API Health:  {backend_url}/api/v1/health")
    click.echo(f"  Recommend:   POST {backend_url}/api/v1/incidents/recommend")
    click.echo()
    click.echo("What to try:")
    click.echo("  1. curl the recommend endpoint with a Redis timeout incident")
    click.echo("  2. Check /api/v1/experience/patterns for operational patterns")
    click.echo("  3. Run 'siggy investigate \"Redis connection pool exhausted\"'")
    click.echo("  4. Record experience: POST /api/v1/experience/record")
    click.echo("  5. Run the benchmark: GET /api/v1/benchmark/scorecard")
    click.echo()
    click.echo("Press Ctrl+C to stop.")
    click.echo()

    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        click.echo("\nStopping demo...")


def _seed_demo_incidents(backend_url: str):
    """Seed pre-enriched incidents directly into the incident store."""
    import json as _json
    import httpx

    demo_incidents = [
        {
            "incident_id": "demo-redis-001",
            "alert_fingerprint": "demo_redis_pool",
            "service": "checkout",
            "severity": "critical",
            "status": "active",
            "alert_summary": "Redis connection pool exhausted — checkout API latency spiked to 12s during peak traffic",
            "root_cause": "Redis connection pool maxed out at 64 concurrent connections. Peak traffic hit 200+ concurrent requests. All new requests queued waiting for connections.",
            "recommendation": "Increase Redis connection pool size from 64 to 128. Set idle connection timeout to 30 seconds.",
            "recommendation_id": "INCREASE_REDIS_CONNECTION_POOL_SIZE_FROM_64_TO_128_SET_IDLE_CONNECTION_TIMEOUT_TO_30_SECONDS",
            "confidence": 0.87,
            "evidence": _json.dumps([
                "Similarity 0.85 across 1 retrieved incident",
                "Same service: checkout",
                "Same component: redis",
                "1 historical occurrence — fix succeeded 100% of the time",
                "Average resolution time: 9 minutes",
            ]),
            "similar_incidents": _json.dumps([
                {"title": "Checkout API latency spike", "similarity": 0.85, "root_cause": "Redis connection pool exhausted"},
                {"title": "Redis timeout in session service", "similarity": 0.80, "root_cause": "Redis cluster node failure"},
            ]),
            "graph_context": _json.dumps({
                "service": "checkout",
                "component": "redis",
                "failure": "connection_pool_exhaustion",
                "related_services": ["session", "cache", "notification-service"],
            }),
            "detected_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "resolved_at": None,
            "source": "demo_seed",
            "web_url": "",
        },
        {
            "incident_id": "demo-db-002",
            "alert_fingerprint": "demo_db_timeout",
            "service": "payment",
            "severity": "high",
            "status": "active",
            "alert_summary": "PostgreSQL connection timeout — payment API returning 504 errors, error rate 25%",
            "root_cause": "Database connection pool maxed out at 100 connections. Long-running analytical queries holding connections for minutes. Payment service can't get a connection.",
            "recommendation": "Move analytical queries to read replicas. Increase connection pool to 200. Add query timeout of 30 seconds.",
            "recommendation_id": "MOVE_ANALYTICAL_QUERIES_TO_READ_REPLICAS_INCREASE_CONNECTION_POOL_TO_200_ADD_QUERY_TIMEOUT_OF_30_SECONDS",
            "confidence": 0.72,
            "evidence": _json.dumps([
                "Similarity 0.72 across 1 retrieved incident",
                "Same component: postgresql",
                "Historical pattern: analytical queries blocking connection pool",
            ]),
            "similar_incidents": _json.dumps([
                {"title": "Database connection timeout", "similarity": 0.72, "root_cause": "Connection pool exhaustion from analytical queries"},
            ]),
            "graph_context": _json.dumps({
                "service": "payment",
                "component": "postgresql",
                "failure": "connection_timeout",
                "related_services": ["order-service", "user-service"],
            }),
            "detected_at": time.strftime(
                "%Y-%m-%dT%H:%M:%S",
                time.localtime(time.time() - 180),
            ),
            "resolved_at": None,
            "source": "demo_seed",
            "web_url": "",
        },
        {
            "incident_id": "demo-mem-003",
            "alert_fingerprint": "demo_oom",
            "service": "notification-service",
            "severity": "critical",
            "status": "active",
            "alert_summary": "OOM Kill — notification-service terminated, unable to allocate memory during batch send",
            "root_cause": "Memory leak in batch notification processor. Unbounded queue growth during traffic spike. Container hit 512Mi limit.",
            "recommendation": "Fix memory leak in batch processor — add backpressure and bounded queue size. Increase container memory limit to 1Gi. Add memory usage alerts at 80% threshold.",
            "recommendation_id": "FIX_MEMORY_LEAK_IN_BATCH_PROCESSOR_ADD_BACKPRESSURE_AND_BOUNDED_QUEUE_SIZE_INCREASE_CONTAINER_MEMORY_LIMIT_TO_1GI_ADD_MEMORY_USAGE_ALERTS_AT_80_THRESHOLD",
            "confidence": 0.65,
            "evidence": _json.dumps([
                "Similarity 0.65 across 1 retrieved incident",
                "Pattern: unbounded queue + memory leak = OOM",
                "Historical fix: add backpressure + increase limits",
            ]),
            "similar_incidents": _json.dumps([
                {"title": "Memory leak in payment worker", "similarity": 0.65, "root_cause": "Memory leak in worker process"},
            ]),
            "graph_context": _json.dumps({
                "service": "notification-service",
                "component": "memory",
                "failure": "oom_kill",
                "related_services": ["email-worker", "sms-worker"],
            }),
            "detected_at": time.strftime(
                "%Y-%m-%dT%H:%M:%S",
                time.localtime(time.time() - 420),
            ),
            "resolved_at": None,
            "source": "demo_seed",
            "web_url": "",
        },
        {
            "incident_id": "demo-kafka-004",
            "alert_fingerprint": "demo_kafka_disk",
            "service": "event-processor",
            "severity": "high",
            "status": "active",
            "alert_summary": "Kafka disk pressure — broker at 92% disk usage, consumer lag growing",
            "root_cause": "Kafka topic retention set to 7 days but partition count increased 3x last week. Disk usage growing faster than expected. Consumer group 'analytics' lag at 2M messages.",
            "recommendation": "Reduce retention to 24h for non-critical topics. Add disk auto-scaling. Scale consumer group instances from 3 to 6.",
            "recommendation_ID": "REDUCE_RETENTION_TO_24H_FOR_NON_CRITICAL_TOPICS_ADD_DISK_AUTO_SCALING_SCALE_CONSUMER_GROUP_INSTANCES_FROM_3_TO_6",
            "confidence": 0.58,
            "evidence": _json.dumps([
                "Similarity 0.58 across 1 retrieved incident",
                "Pattern: partition expansion + fixed retention = disk pressure",
            ]),
            "similar_incidents": _json.dumps([
                {"title": "Kafka disk pressure", "similarity": 0.58, "root_cause": "Partition count growth exceeding disk capacity"},
            ]),
            "graph_context": _json.dumps({
                "service": "event-processor",
                "component": "kafka",
                "failure": "disk_pressure",
                "related_services": ["analytics", "event-store"],
            }),
            "detected_at": time.strftime(
                "%Y-%m-%dT%H:%M:%S",
                time.localtime(time.time() - 900),
            ),
            "resolved_at": None,
            "source": "demo_seed",
            "web_url": "",
        },
    ]

    for inc in demo_incidents:
        try:
            httpx.post(
                f"{backend_url}/api/v1/incidents/store",
                json={
                    "id": inc["incident_id"],
                    "title": inc["alert_summary"],
                    "summary": inc["alert_summary"],
                    "root_cause": inc["root_cause"],
                    "fix": inc["recommendation"],
                    "severity": inc["severity"],
                    "affected_services": [inc["service"]],
                },
                timeout=10,
            )
        except Exception:
            pass

    click.echo(f"  Seeded {len(demo_incidents)} demo incidents")


def _seed_demo_experience(backend_url: str):
    """Seed experience records so recommendations have historical data."""
    import httpx

    experiences = [
        {
            "recommendation_id": "INCREASE_REDIS_CONNECTION_POOL_SIZE_FROM_64_TO_128_SET_IDLE_CONNECTION_TIMEOUT_TO_30_SECONDS",
            "recommendation": "Increase Redis connection pool size from 64 to 128. Set idle connection timeout to 30 seconds.",
            "accepted": True,
            "worked": True,
            "confidence": 0.93,
            "resolution_time_seconds": 540,
            "incident_id": "exp-redis-001",
            "engineer_feedback": "Fixed the checkout latency issue. Pool size increase resolved it immediately.",
            "service": "checkout",
            "component": "redis",
            "failure_type": "connection_pool_exhaustion",
            "symptoms": ["high_latency", "request_timeout"],
        },
        {
            "recommendation_id": "INCREASE_REDIS_CONNECTION_POOL_SIZE_FROM_64_TO_128_SET_IDLE_CONNECTION_TIMEOUT_TO_30_SECONDS",
            "recommendation": "Increase Redis connection pool size from 64 to 128. Set idle connection timeout to 30 seconds.",
            "accepted": True,
            "worked": True,
            "confidence": 0.89,
            "resolution_time_seconds": 620,
            "incident_id": "exp-redis-002",
            "engineer_feedback": "Same issue, same fix. Worked again.",
            "service": "payment",
            "component": "redis",
            "failure_type": "connection_pool_exhaustion",
            "symptoms": ["request_timeout"],
        },
        {
            "recommendation_id": "MOVE_ANALYTICAL_QUERIES_TO_READ_REPLICAS_INCREASE_CONNECTION_POOL_TO_200_ADD_QUERY_TIMEOUT_OF_30_SECONDS",
            "recommendation": "Move analytical queries to read replicas. Increase connection pool to 200. Add query timeout of 30 seconds.",
            "accepted": True,
            "worked": True,
            "confidence": 0.85,
            "resolution_time_seconds": 1200,
            "incident_id": "exp-db-001",
            "engineer_feedback": "Moved analytics to replica, pool increase helped. Query timeout caught a runaway query.",
            "service": "payment",
            "component": "postgresql",
            "failure_type": "connection_timeout",
            "symptoms": ["high_latency", "connection_refused"],
        },
    ]

    for exp in experiences:
        try:
            httpx.post(
                f"{backend_url}/api/v1/experience/record",
                json=exp,
                timeout=10,
            )
        except Exception:
            pass

    click.echo(f"  Seeded {len(experiences)} experience records")


def main():
    cli()


if __name__ == "__main__":
    main()
