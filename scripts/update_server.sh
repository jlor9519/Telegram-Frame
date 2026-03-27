#!/usr/bin/env bash
# update_server.sh — Updates the Server Pi (Telegram bot + database + Dropbox).
# Run this on the Pi that runs the Telegram bot.
# For the display Pi, use update_display.sh instead.
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

PROMPT_MODE=missing-only bash "${PROJECT_ROOT}/scripts/setup_dropbox.sh"

initialize_database

if systemd_unit_exists 'photo-frame.service'; then
  echo "Restarting photo-frame.service."
  run_privileged systemctl restart photo-frame.service
  ensure_systemd_service_active photo-frame.service
fi

echo "Server update completed."
