#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python_bin="$project_root/.venv/bin/python"
if [[ ! -x "$python_bin" ]]; then
  python_bin="$(command -v python3)"
fi

cd "$project_root"
exec "$python_bin" run.py "$@"
