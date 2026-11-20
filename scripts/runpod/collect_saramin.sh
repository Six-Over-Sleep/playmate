#!/usr/bin/env bash
# Legacy Saramin entry point; current #156 workflow uses collect_itchaeyong_jobs.py locally.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
exec uv run --frozen python database/scripts/collect_saramin_jobs.py "$@"
