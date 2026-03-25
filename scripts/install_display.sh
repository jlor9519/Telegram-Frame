#!/usr/bin/env bash
# install_display.sh — Sets up the Display Pi (InkyPi + telegram_frame plugin only).
# Run this on the Pi that is physically connected to the e-ink display.
# The Telegram bot runs on a separate server Pi (see install_server.sh).
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_not_running_as_root
ensure_runtime_files

echo "=== Display Pi installer ==="
echo "This installs InkyPi and the telegram_frame plugin."
echo "No Telegram bot, no database, and no Dropbox are installed here."
echo

if ask_yes_no "Install/update apt packages needed for Python, Git, and Pillow?" "y"; then
  run_privileged apt-get update
  run_privileged apt-get install -y python3 python3-venv python3-pip git rsync fonts-dejavu-core
fi

ensure_venv

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
inkypi_update_method="$(get_yaml_value inkypi.update_method string)"
inkypi_update_now_url="$(get_yaml_value inkypi.update_now_url string)"
refresh_command="$(get_yaml_value inkypi.refresh_command string)"
inkypi_update_values=()
while IFS= read -r line; do
  inkypi_update_values+=("${line}")
done < <(resolve_inkypi_update_values "${inkypi_update_method}" "${inkypi_update_now_url}" "${refresh_command}")
inkypi_update_method="${inkypi_update_values[0]}"
inkypi_update_now_url="${inkypi_update_values[1]}"
refresh_command="${inkypi_update_values[2]}"

set_yaml_value inkypi.repo_path string "${inkypi_repo}"
set_yaml_value inkypi.install_path string "${inkypi_install_path}"
set_yaml_value inkypi.validated_commit string "${inkypi_commit}"
set_yaml_value inkypi.waveshare_model string "${waveshare_model}"
set_yaml_value inkypi.update_method string "${inkypi_update_method}"
set_yaml_value inkypi.update_now_url string "${inkypi_update_now_url}"
set_yaml_value inkypi.refresh_command string "${refresh_command}"

bash "${PROJECT_ROOT}/scripts/setup_inkypi.sh"

# Show the display Pi's IP so the user can configure the server Pi
echo
echo "=== Display Pi setup complete ==="
echo "InkyPi is running and ready to receive display commands."
echo
echo "Note the IP address of this Pi — you will need it when running install_server.sh:"
hostname -I 2>/dev/null | tr ' ' '\n' | grep -v '^$' | head -5 || true
echo
echo "On the server Pi, set the display URL to: http://<this-ip>/update_now"
