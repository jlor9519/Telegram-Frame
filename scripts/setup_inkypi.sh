#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_not_running_as_root
ensure_runtime_files
ensure_venv

repo_path="$(get_yaml_value inkypi.repo_path string)"
repo_path="${repo_path:-/opt/InkyPi}"
validated_commit="$(get_yaml_value inkypi.validated_commit string)"
validated_commit="${validated_commit:-main}"
waveshare_model="$(get_yaml_value inkypi.waveshare_model string)"
waveshare_model="${waveshare_model:-epd7in3e}"
plugin_id="$(get_yaml_value inkypi.plugin_id string)"
plugin_id="${plugin_id:-telegram_frame}"
payload_dir="$(get_yaml_value inkypi.payload_dir string)"
payload_dir="${payload_dir:-${PROJECT_ROOT}/data/inkypi}"
refresh_command="$(get_yaml_value inkypi.refresh_command string)"
refresh_command="${refresh_command:-sudo systemctl restart inkypi.service}"

set_yaml_value inkypi.repo_path string "${repo_path}"
set_yaml_value inkypi.validated_commit string "${validated_commit}"
set_yaml_value inkypi.waveshare_model string "${waveshare_model}"
set_yaml_value inkypi.plugin_id string "${plugin_id}"
set_yaml_value inkypi.payload_dir string "${payload_dir}"
set_yaml_value inkypi.refresh_command string "${refresh_command}"

fresh_clone=0
if [[ ! -d "${repo_path}" ]]; then
  fresh_clone=1
  if path_parent_is_writable "${repo_path}"; then
    run_cmd git clone https://github.com/fatihak/InkyPi.git "${repo_path}"
  else
    run_privileged git clone https://github.com/fatihak/InkyPi.git "${repo_path}"
  fi
elif [[ ! -d "${repo_path}/.git" ]]; then
  echo "Existing InkyPi directory found at ${repo_path} without git metadata. Skipping git sync and injecting the plugin only."
else
  if path_is_writable_or_creatable "${repo_path}/.git"; then
    run_cmd git -C "${repo_path}" fetch --all --tags
  else
    run_privileged git -C "${repo_path}" fetch --all --tags
  fi
fi

if [[ -d "${repo_path}/.git" ]]; then
  if path_is_writable_or_creatable "${repo_path}/.git"; then
    run_cmd git -C "${repo_path}" checkout "${validated_commit}"
  else
    run_privileged git -C "${repo_path}" checkout "${validated_commit}"
  fi
fi

source_plugin_dir="${PROJECT_ROOT}/integrations/inkypi_plugin/telegram_frame"
target_plugin_dir="${repo_path}/src/plugins/${plugin_id}"
if path_is_writable_or_creatable "${repo_path}/src"; then
  mkdir -p "${repo_path}/src/plugins" "${repo_path}/src/config"
  rsync -a --delete "${source_plugin_dir}/" "${target_plugin_dir}/"
else
  run_privileged mkdir -p "${repo_path}/src/plugins" "${repo_path}/src/config"
  run_privileged rsync -a --delete "${source_plugin_dir}/" "${target_plugin_dir}/"
fi

payload_json_path="${payload_dir%/}/current.json"

if path_is_writable_or_creatable "${repo_path}/src/config"; then
  python3 - "${repo_path}" "${plugin_id}" "${payload_json_path}" <<'PY'
import json
import sys
from pathlib import Path

repo_path = Path(sys.argv[1])
plugin_id = sys.argv[2]
payload_path = sys.argv[3]
device_path = repo_path / "src" / "config" / "device.json"
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
  run_privileged python3 - "${repo_path}" "${plugin_id}" "${payload_json_path}" <<'PY'
import json
import sys
from pathlib import Path

repo_path = Path(sys.argv[1])
plugin_id = sys.argv[2]
payload_path = sys.argv[3]
device_path = repo_path / "src" / "config" / "device.json"
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
  elif ! systemd_unit_exists 'inkypi\.service'; then
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

if systemd_unit_exists 'inkypi\.service'; then
  echo "Restarting inkypi.service so the plugin is loaded."
  run_privileged systemctl restart inkypi.service
else
  echo "inkypi.service was not found yet. If InkyPi was just installed, you can rerun scripts/setup_inkypi.sh later."
fi

echo "InkyPi setup completed. Plugin copied to ${target_plugin_dir}."
