#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_not_running_as_root
ensure_runtime_files
ensure_venv

configured_repo_path="$(get_yaml_value inkypi.repo_path string)"
configured_install_path="$(get_yaml_value inkypi.install_path string)"
inkypi_layout=()
while IFS= read -r line; do
  inkypi_layout+=("${line}")
done < <(resolve_inkypi_layout_values "${configured_repo_path}" "${configured_install_path}")
repo_path="${inkypi_layout[0]}"
install_path="${inkypi_layout[1]}"
source_root="${inkypi_layout[2]}"
device_config_path="${inkypi_layout[3]}"
git_sync_path="${inkypi_layout[4]}"
source_origin="${inkypi_layout[5]}"
replaced_stale_repo_path="${inkypi_layout[6]}"
install_src_exists="${inkypi_layout[7]}"

validated_commit="$(get_yaml_value inkypi.validated_commit string)"
validated_commit="${validated_commit:-main}"
waveshare_model="$(get_yaml_value inkypi.waveshare_model string)"
waveshare_model="${waveshare_model:-epd7in3e}"
plugin_id="$(get_yaml_value inkypi.plugin_id string)"
plugin_id="${plugin_id:-telegram_frame}"
payload_dir="$(get_yaml_value inkypi.payload_dir string)"
payload_dir="${payload_dir:-${PROJECT_ROOT}/data/inkypi}"
payload_dir="$(expand_path "${payload_dir}")"
refresh_command="$(get_yaml_value inkypi.refresh_command string)"
refresh_command="${refresh_command:-sudo systemctl restart inkypi.service}"

set_yaml_value inkypi.repo_path string "${repo_path}"
set_yaml_value inkypi.install_path string "${install_path}"
set_yaml_value inkypi.validated_commit string "${validated_commit}"
set_yaml_value inkypi.waveshare_model string "${waveshare_model}"
set_yaml_value inkypi.plugin_id string "${plugin_id}"
set_yaml_value inkypi.payload_dir string "${payload_dir}"
set_yaml_value inkypi.refresh_command string "${refresh_command}"

fresh_clone=0
if [[ "${replaced_stale_repo_path}" == "1" ]]; then
  echo "Replaced stale InkyPi repo_path with ${repo_path}."
fi

echo "Resolved InkyPi checkout path: ${repo_path}"
echo "Resolved InkyPi runtime install path: ${install_path}"
echo "Resolved InkyPi source tree: ${source_root}"
echo "Resolved InkyPi device config path: ${device_config_path}"

if [[ "${source_origin}" == "planned_clone" ]]; then
  fresh_clone=1
  echo "Git sync source: no existing InkyPi checkout found, cloning into ${repo_path}."
  if path_parent_is_writable "${repo_path}"; then
    run_cmd git clone https://github.com/fatihak/InkyPi.git "${repo_path}"
  else
    run_privileged git clone https://github.com/fatihak/InkyPi.git "${repo_path}"
  fi
  source_root="${repo_path}/src"
  device_config_path="${source_root}/config/device.json"
  git_sync_path="${repo_path}"
elif [[ -n "${git_sync_path}" && -d "${git_sync_path}/.git" ]]; then
  echo "Git sync source: ${git_sync_path}"
  if path_is_writable_or_creatable "${git_sync_path}/.git"; then
    run_cmd git -C "${git_sync_path}" fetch --all --tags
  else
    run_privileged git -C "${git_sync_path}" fetch --all --tags
  fi
else
  echo "Git sync source: skipped because the resolved source tree does not have a writable git checkout."
fi

if [[ -n "${git_sync_path}" && -d "${git_sync_path}/.git" ]]; then
  if path_is_writable_or_creatable "${git_sync_path}/.git"; then
    run_cmd git -C "${git_sync_path}" checkout "${validated_commit}"
  else
    run_privileged git -C "${git_sync_path}" checkout "${validated_commit}"
  fi
fi

source_plugin_dir="${PROJECT_ROOT}/integrations/inkypi_plugin/telegram_frame"
target_plugin_dir="${source_root}/plugins/${plugin_id}"
echo "Final plugin target path: ${target_plugin_dir}"

if path_is_writable_or_creatable "${source_root}"; then
  mkdir -p "${source_root}/plugins" "${source_root}/config"
  rsync -a --delete "${source_plugin_dir}/" "${target_plugin_dir}/"
else
  run_privileged mkdir -p "${source_root}/plugins" "${source_root}/config"
  run_privileged rsync -a --delete "${source_plugin_dir}/" "${target_plugin_dir}/"
fi

payload_json_path="${payload_dir%/}/current.json"

if path_is_writable_or_creatable "${device_config_path}"; then
  python3 - "${device_config_path}" "${plugin_id}" "${payload_json_path}" <<'PY'
import json
import sys
from pathlib import Path

device_path = Path(sys.argv[1])
plugin_id = sys.argv[2]
payload_path = sys.argv[3]
device_path.parent.mkdir(parents=True, exist_ok=True)
data = {}
if device_path.exists():
    data = json.loads(device_path.read_text(encoding="utf-8"))

playlists = data.setdefault("playlists", {})
if playlists.get("Default"):
    playlists["Telegram Frame"] = [plugin_id]
    print("Preserved existing Default playlist and wrote/updated a dedicated 'Telegram Frame' playlist.")
else:
    playlists["Default"] = [plugin_id]
    print("Created Default playlist for the Telegram Frame plugin.")
plugin_settings = data.setdefault(plugin_id, {})
plugin_settings["payload_path"] = payload_path

device_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
else
  run_privileged python3 - "${device_config_path}" "${plugin_id}" "${payload_json_path}" <<'PY'
import json
import sys
from pathlib import Path

device_path = Path(sys.argv[1])
plugin_id = sys.argv[2]
payload_path = sys.argv[3]
device_path.parent.mkdir(parents=True, exist_ok=True)
data = {}
if device_path.exists():
    data = json.loads(device_path.read_text(encoding="utf-8"))

playlists = data.setdefault("playlists", {})
if playlists.get("Default"):
    playlists["Telegram Frame"] = [plugin_id]
    print("Preserved existing Default playlist and wrote/updated a dedicated 'Telegram Frame' playlist.")
else:
    playlists["Default"] = [plugin_id]
    print("Created Default playlist for the Telegram Frame plugin.")
plugin_settings = data.setdefault(plugin_id, {})
plugin_settings["payload_path"] = payload_path

device_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
fi

if [[ -x "${repo_path}/install/install.sh" ]]; then
  should_run_inkypi_install=0
  if [[ "${fresh_clone}" == "1" ]]; then
    should_run_inkypi_install=1
  elif [[ "${install_src_exists}" != "1" ]]; then
    should_run_inkypi_install=1
  elif [[ "${INKYPI_FORCE_INSTALL:-0}" == "1" ]]; then
    should_run_inkypi_install=1
  fi

  if [[ "${should_run_inkypi_install}" == "1" ]]; then
    echo "Running InkyPi installer for Waveshare model ${waveshare_model}."
    if [[ "${MOCK_INSTALL}" == "1" ]]; then
      echo "[mock sudo] bash ${repo_path}/install/install.sh -W ${waveshare_model}"
    else
      run_privileged bash "${repo_path}/install/install.sh" -W "${waveshare_model}"
    fi
  else
    echo "Skipping InkyPi installer rerun because an existing installation was detected."
    echo "Set INKYPI_FORCE_INSTALL=1 when running setup_inkypi.sh if you need to rerun it."
  fi
fi

if [[ ! -f "${target_plugin_dir}/telegram_frame.py" ]]; then
  echo >&2 "Plugin verification failed: ${target_plugin_dir}/telegram_frame.py was not created."
  exit 1
fi
if [[ ! -f "${target_plugin_dir}/plugin-info.json" ]]; then
  echo >&2 "Plugin verification failed: ${target_plugin_dir}/plugin-info.json was not created."
  exit 1
fi

python3 - "${device_config_path}" "${plugin_id}" "${payload_json_path}" <<'PY'
import json
import sys
from pathlib import Path

device_path = Path(sys.argv[1])
plugin_id = sys.argv[2]
payload_path = sys.argv[3]

if not device_path.exists():
    raise SystemExit(f"Device config verification failed: {device_path} does not exist.")

data = json.loads(device_path.read_text(encoding="utf-8"))
plugin_settings = data.get(plugin_id)
if not isinstance(plugin_settings, dict):
    raise SystemExit(f"Device config verification failed: plugin entry {plugin_id!r} is missing.")
if plugin_settings.get("payload_path") != payload_path:
    raise SystemExit(
        f"Device config verification failed: payload_path is {plugin_settings.get('payload_path')!r}, expected {payload_path!r}."
    )

playlists = data.get("playlists", {})
if not any(
    isinstance(items, list) and plugin_id in items
    for items in playlists.values()
):
    raise SystemExit(f"Device config verification failed: no playlist includes plugin {plugin_id!r}.")
PY

if [[ "${MOCK_INSTALL}" == "1" ]]; then
  echo "[mock] Skipping inkypi.service restart and active verification."
elif systemd_unit_exists 'inkypi.service'; then
  echo "Restarting inkypi.service so the plugin is loaded."
  run_privileged systemctl restart inkypi.service
  ensure_systemd_service_active inkypi.service
else
  echo >&2 "inkypi.service was not found after setup."
  exit 1
fi

echo "InkyPi setup completed. Plugin copied to ${target_plugin_dir}."
