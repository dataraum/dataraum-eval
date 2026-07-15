"""Bring up Postgres + DuckLake catalog + SeaweedFS + Temporal for calibration.

The engine is a Temporal activity worker now (DAT-344/DAT-370), so a run is
driven by triggering ``addSourceWorkflow`` against a worker that polls the
``dataraum-pipeline`` task queue. We bring up three long-running pieces from the
vendor's compose stack — ``postgres`` (engine metadata + DuckLake catalog +
Temporal's own persistence), ``seaweedfs`` (S3-backed DuckLake data store,
DAT-389), and the ``temporal`` server — plus two one-shots (Temporal namespace +
S3 bucket creation), and run the **engine worker on the host**
(see :mod:`calibration.worker`) so it executes the live working-tree code. The
worker reads the host ``data/`` dir and writes DuckLake data to S3
(``s3://dataraum-lake/lake`` on the host-published SeaweedFS gateway).

The compose stack persists across test runs. ``make clean`` wipes the
local workspace directory; ``docker compose ... down -v`` wipes the Postgres +
SeaweedFS volumes.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
from pathlib import Path

EVAL_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = EVAL_ROOT / "vendor" / "dataraum-context"
COMPOSE_FILE = VENDOR_DIR / "packages" / "infra" / "docker-compose.yml"
# Layered over the vendor compose to remap host ports, and run under EVAL_PROJECT so the
# calibration stack is a fully ISOLATED docker project — own containers, network, and
# `postgres_data` volume — coexisting with the shared cockpit `infra` stack instead of
# tearing it down. `clean-pg`/`down -v` then only ever touch the eval project (DAT-445).
OVERRIDE_FILE = EVAL_ROOT / "calibration" / "compose.eval-ports.yml"
EVAL_PROJECT = "dataraum-eval"
ENV_FILE = EVAL_ROOT / ".docker.env"

# Local host workspace dir (DATARAUM_HOME). Gitignored. DuckLake *data* no
# longer lives on the host — it's S3-backed via SeaweedFS (see below).
WORKSPACE_DIR = EVAL_ROOT / "workspace"

POSTGRES_USER = "dataraum"
POSTGRES_PASSWORD = "dataraum"  # noqa: S105 — local dev default, matches vendor .env.example
POSTGRES_DB = "dataraum"
POSTGRES_LAKE_CATALOG_DB = "dataraum_lake_catalog"
POSTGRES_COCKPIT_DB = "cockpit_db"  # unused here, but postgres-init requires it set
POSTGRES_HOST = "127.0.0.1"
# Isolated host ports (remapped in compose.eval-ports.yml) so the eval stack coexists
# with the shared cockpit stack (5432 / 7233 / 8333) — the container ports are unchanged.
POSTGRES_PORT = 5433

# Active workspace_id (DAT-339 schema-per-workspace). The engine resolves the
# Postgres schema name as ws_<id-with-dashes-as-underscores>; the worker and the
# eval client must agree on it (the worker refuses cross-workspace payloads).
DATARAUM_WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"

# Temporal (DAT-344). The vendor compose runs the server against the same
# Postgres instance; the worker + eval client reach it at the published port.
TEMPORAL_PORT = 7234  # isolated host port (→ container 7233)
TEMPORAL_HOST = f"{POSTGRES_HOST}:{TEMPORAL_PORT}"
TEMPORAL_NAMESPACE = "default"
# One queue per workspace — ``engine-<workspace_id>`` (DAT-505). The engine's
# bootstrap asserts TEMPORAL_TASK_QUEUE matches its workspace, so the worker
# registration + the eval client triggers must derive the name the same way the
# engine does (``task_queue_for``).
TEMPORAL_TASK_QUEUE = f"engine-{DATARAUM_WORKSPACE_ID}"

# Pinned image versions, mirrored from vendor packages/infra/.env.example.
TEMPORAL_VERSION = "1.31.0"
TEMPORAL_ADMINTOOLS_VERSION = "1.31.0"
TEMPORAL_UI_VERSION = "2.49.1"

# SeaweedFS S3-backed DuckLake store (DAT-389). The compose `seaweedfs` service
# advertises `seaweedfs:8333` *inside* the compose network; the host worker
# reaches the same gateway at the published port. Values mirror vendor
# packages/infra/.env.example. Creds are nominal — this dev SeaweedFS runs
# without an S3 auth config — but DuckDB still wants them non-empty.
S3_PORT = 8334  # isolated host port (→ container 8333)
S3_ENDPOINT = f"{POSTGRES_HOST}:{S3_PORT}"  # host:port, no scheme (DuckDB ENDPOINT form)
S3_BUCKET = "dataraum-lake"
S3_REGION = "us-east-1"
S3_ACCESS_KEY_ID = "dataraum"
S3_SECRET_ACCESS_KEY = "dataraum-s3-secret"  # noqa: S105 — local dev default
# DuckLake data path: a bucket-relative S3 URI, NOT a host path (DAT-389).
DUCKLAKE_DATA_PATH = f"s3://{S3_BUCKET}/lake"

# Long-running, healthchecked services calibration needs: Postgres, SeaweedFS
# (S3 store), and the Temporal server. `up --wait` on these returns 0 once all
# are healthy. The cockpit + engine-worker containers are deliberately NOT
# started — the worker runs on the host.
_HEALTHCHECK_SERVICES = ["postgres", "seaweedfs", "temporal"]

# One-shots that set up state then EXIT: register the Temporal `default`
# namespace, and create the SeaweedFS lake bucket (SeaweedFS doesn't reliably
# auto-create buckets). They can't ride the `--wait` set — `up --wait` reports a
# non-zero rc when a tracked service exits — so each is started separately and
# blocked on via `docker compose wait` for its exit code.
_NAMESPACE_SERVICE = "temporal-create-namespace"
_BUCKET_SERVICE = "seaweedfs-init"

DATABASE_URL = (
    f"postgresql+psycopg://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)
DUCKLAKE_CATALOG_URL = (
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_LAKE_CATALOG_DB}"
)


def lake_catalog_db_for(strategy: str) -> str:
    """The per-strategy DuckLake catalog database name (DAT-767).

    One workspace per DuckLake is the engine's intended shape — its lake catalog
    holds GLOBAL ``raw``/``typed``/``quarantine`` schemas with bare table names,
    so two workspaces sharing one catalog silently ``CREATE OR REPLACE`` each
    other's physical tables (the last importer owns the shape; the other
    workspace's re-run then types against a foreign body — the DAT-767 binder
    error). Postgres identifier limit is 63 bytes; strategy slugs are truncated
    defensively (uniqueness holds for every current strategy name).
    """
    slug = "".join(ch if ch.isalnum() else "_" for ch in strategy.lower())
    return f"{POSTGRES_LAKE_CATALOG_DB}_{slug}"[:63]


def lake_env_for(strategy: str) -> dict[str, str]:
    """Per-strategy DuckLake env (catalog URL + data path), see :func:`lake_catalog_db_for`."""
    db = lake_catalog_db_for(strategy)
    slug = db.removeprefix(f"{POSTGRES_LAKE_CATALOG_DB}_")
    return {
        "DUCKLAKE_CATALOG_URL": (
            f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
            f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{db}"
        ),
        "DUCKLAKE_DATA_PATH": f"s3://{S3_BUCKET}/lake/{slug}",
    }


def ensure_lake_catalog_db(db_name: str) -> None:
    """Create the per-strategy lake catalog database if absent (idempotent).

    ``CREATE DATABASE`` cannot run inside a transaction — psycopg autocommit
    against the base metadata DB. The eval project's ``--reset`` (``down -v``)
    drops the whole Postgres volume, taking every per-strategy catalog with it,
    so no separate cleanup path is needed.
    """
    import psycopg

    with psycopg.connect(
        f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
        f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}",
        autocommit=True,
    ) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (db_name,)
        ).fetchone()
        if not exists:
            # Identifier is derived (sanitized slug), not user input.
            conn.execute(f'CREATE DATABASE "{db_name}"')


def _ensure_env_file() -> None:
    """Write the .env that vendor's compose file consumes via --env-file."""
    lines = [
        "# Generated by calibration/stack.py — safe to delete; will be regenerated.",
        f"POSTGRES_USER={POSTGRES_USER}",
        f"POSTGRES_PASSWORD={POSTGRES_PASSWORD}",
        f"POSTGRES_DB={POSTGRES_DB}",
        f"DUCKLAKE_CATALOG_DB={POSTGRES_LAKE_CATALOG_DB}",
        # postgres-init creates COCKPIT_DB at first boot and fails loud if unset,
        # even though calibration never starts the cockpit.
        f"COCKPIT_DB={POSTGRES_COCKPIT_DB}",
        # Temporal server image pins consumed by the `temporal` +
        # `temporal-admin-tools` services.
        f"TEMPORAL_VERSION={TEMPORAL_VERSION}",
        f"TEMPORAL_ADMINTOOLS_VERSION={TEMPORAL_ADMINTOOLS_VERSION}",
        f"TEMPORAL_UI_VERSION={TEMPORAL_UI_VERSION}",
        # HOST_SOURCES_DIR is referenced by the (unused) control-plane
        # service; setting it avoids a compose-file warning.
        f"HOST_SOURCES_DIR={EVAL_ROOT / 'data'}",
        # seaweedfs-init reads S3_BUCKET to create the lake bucket; must match
        # the bucket the engine writes to (DUCKLAKE_DATA_PATH=s3://<bucket>/lake).
        f"S3_BUCKET={S3_BUCKET}",
        "",
    ]
    ENV_FILE.write_text("\n".join(lines))


def _pg_ready() -> bool:
    """Probe Postgres via ``pg_isready`` inside the eval project's postgres container."""
    result = _compose(
        "exec", "-T", "postgres", "pg_isready", "-U", POSTGRES_USER, "-d", POSTGRES_DB
    )
    return result.returncode == 0


def _export_env() -> None:
    """Set the env vars the engine reads at runtime (eval client + host worker).

    Both the eval process (Temporal client + PG reader) and the engine worker
    subprocess inherit these. ``get_settings()`` validates the full set at
    boot, so every required field (substrate + Temporal + workspace) is set
    here even when the eval client itself doesn't read it.
    """
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["DATABASE_URL"] = DATABASE_URL
    os.environ["DUCKLAKE_CATALOG_URL"] = DUCKLAKE_CATALOG_URL
    os.environ["DUCKLAKE_DATA_PATH"] = DUCKLAKE_DATA_PATH
    os.environ["DATARAUM_HOME"] = str(WORKSPACE_DIR)
    os.environ["DATARAUM_WORKSPACE_ID"] = DATARAUM_WORKSPACE_ID
    os.environ["TEMPORAL_HOST"] = TEMPORAL_HOST
    os.environ["TEMPORAL_NAMESPACE"] = TEMPORAL_NAMESPACE
    os.environ["TEMPORAL_TASK_QUEUE"] = TEMPORAL_TASK_QUEUE
    # S3-backed DuckLake (DAT-389). The host worker reaches SeaweedFS at the
    # published gateway port; SSL off for local dev.
    os.environ["S3_ENDPOINT"] = S3_ENDPOINT
    os.environ["S3_BUCKET"] = S3_BUCKET
    os.environ["S3_REGION"] = S3_REGION
    os.environ["S3_USE_SSL"] = "false"
    os.environ["S3_ACCESS_KEY_ID"] = S3_ACCESS_KEY_ID
    os.environ["S3_SECRET_ACCESS_KEY"] = S3_SECRET_ACCESS_KEY


def _temporal_ready() -> bool:
    """Probe the Temporal frontend by TCP-connecting to its published port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex((POSTGRES_HOST, TEMPORAL_PORT)) == 0


def _seaweedfs_ready() -> bool:
    """Probe the SeaweedFS S3 gateway by TCP-connecting to its published port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex((POSTGRES_HOST, S3_PORT)) == 0


def _compose(*args: str) -> subprocess.CompletedProcess[str]:
    """Run a docker compose subcommand for the ISOLATED eval project.

    Always carries ``-p dataraum-eval`` + the port-override file, so every operation —
    up, exec, wait, down — targets the eval project, never the shared cockpit ``infra``.
    """
    return subprocess.run(
        [
            "docker", "compose", "-p", EVAL_PROJECT,
            "-f", str(COMPOSE_FILE), "-f", str(OVERRIDE_FILE),
            "--env-file", str(ENV_FILE), *args,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _check(result: subprocess.CompletedProcess[str], what: str) -> None:
    if result.returncode != 0:
        raise RuntimeError(
            f"{what} failed (rc={result.returncode}):\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def _oneshot_exit_code(wait: subprocess.CompletedProcess[str]) -> str:
    """Extract a one-shot's exit code from ``docker compose wait`` output.

    The output format varies by compose version: newer prints
    ``container "<id>" exited with status code N`` (the id contains digits, so a
    naive last-integer parse is unsafe); older prints a bare ``N``. Match the
    explicit ``status code N`` first, then fall back to a bare integer.
    """
    match = re.search(r"status code (\d+)", wait.stdout)
    if match:
        return match.group(1)
    return wait.stdout.strip()


def _run_oneshot(service: str, what: str) -> None:
    """Start a one-shot service, block on it, and assert it exited 0."""
    print(f"[stack] {what} ({service})...")
    _check(_compose("up", service, "-d"), f"docker compose up {service}")
    wait = _compose("wait", service)
    _check(wait, f"docker compose wait {service}")
    code = _oneshot_exit_code(wait)
    if code not in ("", "0"):
        raise RuntimeError(f"{service} exited non-zero: {code!r}\nstdout:\n{wait.stdout}")


def up() -> None:
    """Ensure Postgres + SeaweedFS + Temporal are up, with namespace + bucket created."""
    _ensure_env_file()
    _export_env()

    if _pg_ready() and _temporal_ready() and _seaweedfs_ready():
        return

    print(f"[stack] Starting {', '.join(_HEALTHCHECK_SERVICES)} (docker compose up -d --wait)...")
    _check(
        _compose("up", *_HEALTHCHECK_SERVICES, "-d", "--wait"),
        "docker compose up postgres+seaweedfs+temporal",
    )

    # One-shots (idempotent): register the Temporal namespace and create the S3
    # lake bucket. Each exits after running, so neither can ride the `--wait`.
    _run_oneshot(_NAMESPACE_SERVICE, "Registering Temporal namespace")
    _run_oneshot(_BUCKET_SERVICE, "Creating SeaweedFS lake bucket")


def down(volumes: bool = False) -> None:
    """Tear down the ISOLATED eval stack — never the shared cockpit project.

    ``volumes=True`` drops the eval project's ``postgres_data`` volume (a clean baseline)
    without touching cockpit's postgres or any cockpit container.
    """
    _compose("down", "-v") if volumes else _compose("down")
