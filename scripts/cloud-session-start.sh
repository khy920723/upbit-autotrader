#!/usr/bin/env bash
# SessionStart hook: prepares the Python environment, in Claude cloud sessions only.
set -uo pipefail

[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
[ -f pyproject.toml ] || exit 0

uv python install 3.13 >/dev/null 2>&1
uv sync >/dev/null 2>&1 || echo "uv sync failed: run 'uv sync' to see the error" >&2
exit 0
