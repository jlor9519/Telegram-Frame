#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_not_running_as_root
ensure_runtime_files
ensure_venv

if [[ -z "$(get_env_value TELEGRAM_BOT_TOKEN)" ]]; then
  telegram_token="$(prompt_value "Telegram bot token" "" "" 1)"
  set_env_value TELEGRAM_BOT_TOKEN "${telegram_token}"
fi

if [[ -z "$(get_yaml_value security.admin_user_ids list-int)" ]]; then
  admin_ids="$(prompt_value "Initial admin Telegram user IDs (comma-separated)" "" "" 0)"
  admin_ids="$(normalize_id_list "${admin_ids}")"
  set_yaml_value security.admin_user_ids list-int "${admin_ids}"
fi

if git -C "${PROJECT_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  run_cmd git -C "${PROJECT_ROOT}" pull --ff-only || true
fi

"${RUN_PYTHON}" -m pip install -r "${PROJECT_ROOT}/requirements.txt"

inkypi_update_method="$(get_yaml_value inkypi.update_method string)"
inkypi_update_now_url="$(get_yaml_value inkypi.update_now_url string)"
refresh_command="$(get_yaml_value inkypi.refresh_command string)"
inkypi_update_values=()
while IFS= read -r line; do
  inkypi_update_values+=("${line}")
done < <(resolve_inkypi_update_values "${inkypi_update_method}" "${inkypi_update_now_url}" "${refresh_command}")
set_yaml_value inkypi.update_method string "${inkypi_update_values[0]}"
set_yaml_value inkypi.update_now_url string "${inkypi_update_values[1]}"
set_yaml_value inkypi.refresh_command string "${inkypi_update_values[2]}"

PROMPT_MODE=missing-only bash "${PROJECT_ROOT}/scripts/setup_dropbox.sh"
PROMPT_MODE=missing-only bash "${PROJECT_ROOT}/scripts/setup_inkypi.sh"
initialize_database

if systemctl list-unit-files | grep -q '^photo-frame\.service'; then
  run_privileged systemctl restart photo-frame.service
fi

echo "Update flow completed."
