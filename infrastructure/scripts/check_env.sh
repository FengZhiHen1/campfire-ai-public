#!/usr/bin/env bash
# ============================================================
# check_env.sh — pre-flight check script for Docker Compose
#
# Verifies that the required .env file exists before starting
# containers. Docker Compose prints only a warning when env_file
# is missing; this script enforces it as a hard failure.
#
# Usage: bash infrastructure/scripts/check_env.sh
# ============================================================
set -euo pipefail

ENV_FILE="${1:-.env}"

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: Environment file '$ENV_FILE' not found." >&2
    echo "" >&2
    echo "The .env file is required for container environment variable injection." >&2
    echo "Copy .env.example to .env and fill in the required values:" >&2
    echo "  cp .env.example .env" >&2
    exit 1
fi

echo "OK: Environment file '$ENV_FILE' exists."
exit 0
