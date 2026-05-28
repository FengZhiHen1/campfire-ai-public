"""Infrastructure service launcher — Docker Compose (PostgreSQL, Redis, MinIO).

Starts the dev data containers defined in docker-compose.yml.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def start_infra() -> subprocess.Popen:
    """Start infrastructure containers via docker compose up -d.

    Returns:
        A completed Popen (the up -d command exits immediately after starting containers).
    """
    return subprocess.Popen(
        ["docker", "compose", "up", "-d"],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def stop_infra() -> None:
    """Stop infrastructure containers via docker compose down."""
    subprocess.run(
        ["docker", "compose", "down"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        timeout=30,
    )


def main() -> None:
    """CLI entry point for standalone use."""
    print("Starting infrastructure containers...")
    proc = start_infra()
    stdout, _ = proc.communicate(timeout=60)
    if proc.returncode == 0:
        print("Infrastructure containers started successfully.")
        if stdout:
            print(stdout)
    else:
        print(f"Failed to start infrastructure (exit code {proc.returncode})")
        if stdout:
            print(stdout)
        sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
