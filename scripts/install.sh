#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_not_running_as_root
ensure_runtime_files

if ask_yes_no "Install/update apt packages needed for Python, Pillow, and Git?" "y"; then
  run_privileged apt-get update
  run_privileged apt-get install -y python3 python3-venv python3-pip git rsync fonts-dejavu-core
fi

ensure_venv

telegram_token="$(get_or_prompt_value "Telegram bot token" "$(get_env_value TELEGRAM_BOT_TOKEN)" "" 0)"
admin_ids="$(get_or_prompt_value "Initial admin Telegram user IDs (comma-separated)" "$(get_yaml_value security.admin_user_ids list-int)" "" 0)"
admin_ids="$(normalize_id_list "${admin_ids}")"
whitelist_ids="$(get_yaml_value security.whitelisted_user_ids list-int)"
if [[ -z "${whitelist_ids}" ]]; then
  whitelist_ids="${admin_ids}"
fi
whitelist_ids="$(normalize_id_list "${whitelist_ids}")"

inkypi_repo="$(get_yaml_value inkypi.repo_path string)"
inkypi_install_path="$(get_yaml_value inkypi.install_path string)"
inkypi_layout=()
while IFS= read -r line; do
  inkypi_layout+=("${line}")
done < <(resolve_inkypi_layout_values "${inkypi_repo}" "${inkypi_install_path}")
inkypi_repo="${inkypi_layout[0]}"
inkypi_install_path="${inkypi_layout[1]}"
inkypi_commit="$(get_yaml_value inkypi.validated_commit string)"
inkypi_commit="${inkypi_commit:-main}"
waveshare_model="$(get_yaml_value inkypi.waveshare_model string)"
waveshare_model="${waveshare_model:-epd7in3e}"
refresh_command="$(get_yaml_value inkypi.refresh_command string)"
refresh_command="${refresh_command:-sudo systemctl restart inkypi.service}"

dropbox_enabled_current="$(get_yaml_value dropbox.enabled bool)"
if [[ "${dropbox_enabled_current}" == "true" ]]; then
  dropbox_default="y"
else
  dropbox_default="n"
fi
if ask_yes_no "Enable Dropbox uploads for this frame?" "${dropbox_default}"; then
  dropbox_enabled="true"
  dropbox_token="$(get_or_prompt_value "Dropbox access token" "$(get_env_value DROPBOX_ACCESS_TOKEN)" "" 0)"
else
  dropbox_enabled="false"
  dropbox_token="$(get_env_value DROPBOX_ACCESS_TOKEN)"
fi

service_user="${SUDO_USER:-$(id -un)}"
service_workdir="${PROJECT_ROOT}"

set_env_value TELEGRAM_BOT_TOKEN "${telegram_token}"
if [[ -n "${dropbox_token}" ]]; then
  set_env_value DROPBOX_ACCESS_TOKEN "${dropbox_token}"
fi
set_yaml_value security.admin_user_ids list-int "${admin_ids}"
set_yaml_value security.whitelisted_user_ids list-int "${whitelist_ids}"
set_yaml_value inkypi.repo_path string "${inkypi_repo}"
set_yaml_value inkypi.install_path string "${inkypi_install_path}"
set_yaml_value inkypi.validated_commit string "${inkypi_commit}"
set_yaml_value inkypi.waveshare_model string "${waveshare_model}"
set_yaml_value inkypi.refresh_command string "${refresh_command}"
set_yaml_value dropbox.enabled bool "${dropbox_enabled}"

initialize_database
bash "${PROJECT_ROOT}/scripts/setup_dropbox.sh"
bash "${PROJECT_ROOT}/scripts/setup_inkypi.sh"

echo "Installing/updating photo-frame systemd service for user ${service_user}."
ensure_service_unit "${service_user}" "${service_workdir}"
run_privileged systemctl restart photo-frame.service
ensure_systemd_service_active photo-frame.service

echo "Install flow completed."
