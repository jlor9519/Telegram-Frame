#!/usr/bin/env bash
# update_display.sh — Updates the Display Pi (InkyPi + telegram_frame plugin + optional sync).
# Run this on the Pi that is physically connected to the e-ink display.
# For the server Pi, use update_server.sh instead.
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_not_running_as_root
ensure_runtime_files
ensure_venv

old_head=""
if git -C "${PROJECT_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  old_head="$(git -C "${PROJECT_ROOT}" rev-parse HEAD 2>/dev/null || echo "")"
  run_cmd git -C "${PROJECT_ROOT}" pull --ff-only || true
  new_head="$(git -C "${PROJECT_ROOT}" rev-parse HEAD 2>/dev/null || echo "")"
  if [[ -n "${old_head}" && "${old_head}" != "${new_head}" ]]; then
    echo "Updated from ${old_head:0:7} to ${new_head:0:7}:"
    git -C "${PROJECT_ROOT}" log --oneline "${old_head}..${new_head}"
  else
    echo "Already up to date ($(git -C "${PROJECT_ROOT}" rev-parse --short HEAD 2>/dev/null || echo 'unknown'))."
  fi
fi

PROMPT_MODE=missing-only bash "${PROJECT_ROOT}/scripts/setup_inkypi.sh"

if systemd_unit_exists 'display-sync.service'; then
  echo "Restarting display-sync.service."
  run_privileged systemctl restart display-sync.service
  ensure_systemd_service_active display-sync.service
fi

echo "Display update completed."
