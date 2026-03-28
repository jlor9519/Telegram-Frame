#!/usr/bin/env bash
# install_server.sh — Sets up the Server Pi (Telegram bot + Dropbox + database only).
# Run this on the Pi that runs the Telegram bot. InkyPi must be running on a separate
# display Pi — see install_display.sh.
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_not_running_as_root
ensure_runtime_files

echo "=== Server Pi installer ==="
echo "This installs the Telegram bot, database, and Dropbox integration."
echo "InkyPi and the e-ink display must be running on a separate display Pi."
echo "If you only want Telegram + Dropbox right now, answer 'no' to the same-network question."
echo "That mode does not require a display Pi URL."
echo

if ask_yes_no "Install/update apt packages needed for Python, Git, and Dropbox setup?" "y"; then
  run_privileged apt-get update
  run_privileged apt-get install -y python3 python3-venv python3-pip git curl fonts-dejavu-core
fi

ensure_venv

# Telegram bot configuration
telegram_token="$(get_or_prompt_value "Telegram bot token" "$(get_env_value TELEGRAM_BOT_TOKEN)" "" 0)"
admin_ids="$(get_or_prompt_value "Initial admin Telegram user IDs (comma-separated)" "$(get_yaml_value security.admin_user_ids list-int)" "" 0)"
admin_ids="$(normalize_id_list "${admin_ids}")"
whitelist_ids="$(get_yaml_value security.whitelisted_user_ids list-int)"
if [[ -z "${whitelist_ids}" ]]; then
  whitelist_ids="${admin_ids}"
fi
whitelist_ids="$(normalize_id_list "${whitelist_ids}")"

# Display Pi connection
if ask_yes_no "Is the display Pi on the same local network as this server Pi?" "n"; then
  current_update_now_url="$(get_yaml_value inkypi.update_now_url string)"
  if [[ -n "${current_update_now_url}" && "${current_update_now_url}" != "http://127.0.0.1/update_now" ]]; then
    display_pi_url_default="${current_update_now_url%/update_now}"
  else
    display_pi_url_default=""
  fi
  echo
  echo "Enter the URL of the display Pi (e.g. http://inkypi.local or http://192.168.1.42)."
  echo "InkyPi must be running on that Pi (install_display.sh must have been run there)."
  display_pi_url="$(prompt_value "Display Pi URL" "${display_pi_url_default}" "http://inkypi.local" 0)"
  display_pi_url="${display_pi_url%/}"
  update_now_url="${display_pi_url}/update_now"
  update_method="http_update_now"
else
  update_now_url=""
  update_method="none"
  echo "Display updates will be delivered via Dropbox sync."
fi

# Dropbox configuration
dropbox_enabled_current="$(get_yaml_value dropbox.enabled bool)"
if [[ "${dropbox_enabled_current}" == "true" ]]; then
  dropbox_default="y"
else
  dropbox_default="n"
fi
if [[ "${update_method}" == "none" ]]; then
  dropbox_default="y"
fi
if ask_yes_no "Enable Dropbox uploads for this frame?" "${dropbox_default}"; then
  dropbox_enabled="true"
else
  dropbox_enabled="false"
fi

if [[ "${update_method}" == "none" && "${dropbox_enabled}" != "true" ]]; then
  echo >&2 "Dropbox is required when the display Pi is not on the same network."
  echo >&2 "Rerun install_server.sh and enable Dropbox for the remote two-Pi setup."
  exit 1
fi

service_user="${SUDO_USER:-$(id -un)}"
service_workdir="${PROJECT_ROOT}"

set_env_value TELEGRAM_BOT_TOKEN "${telegram_token}"
set_yaml_value security.admin_user_ids list-int "${admin_ids}"
set_yaml_value security.whitelisted_user_ids list-int "${whitelist_ids}"
set_yaml_value inkypi.update_method string "${update_method}"
if [[ -n "${update_now_url}" ]]; then
  set_yaml_value inkypi.update_now_url string "${update_now_url}"
fi
set_yaml_value dropbox.enabled bool "${dropbox_enabled}"

bash "${PROJECT_ROOT}/scripts/setup_dropbox.sh"
initialize_database

echo "Installing/updating photo-frame systemd service for user ${service_user}."
ensure_service_unit "${service_user}" "${service_workdir}"
run_privileged systemctl restart photo-frame.service
ensure_systemd_service_active photo-frame.service

echo
echo "=== Server Pi setup complete ==="
if [[ "${update_method}" == "http_update_now" ]]; then
  echo "The Telegram bot is running and will send images to ${display_pi_url}."
else
  echo "The Telegram bot is running. Images will be delivered via Dropbox sync."
  echo "Note: /settings is intentionally unavailable on the server Pi in Dropbox mode."
fi
echo
echo "Next checks:"
echo "  - systemctl status photo-frame.service"
echo "  - /myid and /status in Telegram"
echo "  - send one test photo"
echo "  - confirm Dropbox files under /photo-frame/images/originals, /photo-frame/display, and /photo-frame/backup"
