#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_runtime_files

if ask_yes_no "Install/update apt packages needed for Python, Pillow, and Git?" "y"; then
  run_privileged apt-get update
  run_privileged apt-get install -y python3 python3-venv python3-pip git rsync fonts-dejavu-core
fi

ensure_venv

telegram_token="$(prompt_value "Telegram bot token" "$(get_env_value TELEGRAM_BOT_TOKEN)" "" 0)"
admin_ids="$(prompt_value "Initial admin Telegram user IDs (comma-separated)" "$(get_yaml_value security.admin_user_ids list-int)" "" 0)"
admin_ids="$(normalize_id_list "${admin_ids}")"
whitelist_ids="$(prompt_value "Additional whitelisted Telegram user IDs (comma-separated, optional)" "$(get_yaml_value security.whitelisted_user_ids list-int)" "${admin_ids}" 0)"
whitelist_ids="$(normalize_id_list "${whitelist_ids}")"

inkypi_repo="$(prompt_value "InkyPi checkout path" "$(get_yaml_value inkypi.repo_path string)" "/opt/InkyPi" 0)"
inkypi_commit="$(prompt_value "Pinned InkyPi commit or branch" "$(get_yaml_value inkypi.validated_commit string)" "main" 0)"
waveshare_model="$(prompt_value "Waveshare model identifier for InkyPi" "$(get_yaml_value inkypi.waveshare_model string)" "epd7in3e" 0)"
refresh_command="$(prompt_value "Local InkyPi refresh command" "$(get_yaml_value inkypi.refresh_command string)" "sudo systemctl restart inkypi.service" 0)"

dropbox_enabled_current="$(get_yaml_value dropbox.enabled bool)"
if [[ "${dropbox_enabled_current}" == "true" ]]; then
  dropbox_default="y"
else
  dropbox_default="n"
fi
if ask_yes_no "Enable Dropbox uploads for this frame?" "${dropbox_default}"; then
  dropbox_enabled="true"
  dropbox_token="$(prompt_value "Dropbox access token" "$(get_env_value DROPBOX_ACCESS_TOKEN)" "" 0)"
else
  dropbox_enabled="false"
  dropbox_token="$(get_env_value DROPBOX_ACCESS_TOKEN)"
fi

service_user="$(prompt_value "Systemd service user" "${SUDO_USER:-$(id -un)}" "${SUDO_USER:-$(id -un)}" 0)"
service_workdir="$(prompt_value "Systemd working directory" "${PROJECT_ROOT}" "${PROJECT_ROOT}" 0)"

set_env_value TELEGRAM_BOT_TOKEN "${telegram_token}"
if [[ -n "${dropbox_token}" ]]; then
  set_env_value DROPBOX_ACCESS_TOKEN "${dropbox_token}"
fi
set_yaml_value security.admin_user_ids list-int "${admin_ids}"
set_yaml_value security.whitelisted_user_ids list-int "${whitelist_ids}"
set_yaml_value inkypi.repo_path string "${inkypi_repo}"
set_yaml_value inkypi.validated_commit string "${inkypi_commit}"
set_yaml_value inkypi.waveshare_model string "${waveshare_model}"
set_yaml_value inkypi.refresh_command string "${refresh_command}"
set_yaml_value dropbox.enabled bool "${dropbox_enabled}"

initialize_database
bash "${PROJECT_ROOT}/scripts/setup_dropbox.sh"
bash "${PROJECT_ROOT}/scripts/setup_inkypi.sh"

if ask_yes_no "Install or update the companion app systemd service?" "y"; then
  ensure_service_unit "${service_user}" "${service_workdir}"
  if ask_yes_no "Start or restart photo-frame.service now?" "y"; then
    run_privileged systemctl restart photo-frame.service
  fi
fi

echo "Install flow completed."
