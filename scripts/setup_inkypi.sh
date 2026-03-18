#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_runtime_files
ensure_venv

repo_path="$(prompt_value "InkyPi checkout path" "$(get_yaml_value inkypi.repo_path string)" "/opt/InkyPi" 0)"
validated_commit="$(prompt_value "Pinned InkyPi commit or branch" "$(get_yaml_value inkypi.validated_commit string)" "main" 0)"
waveshare_model="$(prompt_value "Waveshare model identifier for InkyPi" "$(get_yaml_value inkypi.waveshare_model string)" "epd7in3e" 0)"
plugin_id="$(get_yaml_value inkypi.plugin_id string)"
plugin_id="${plugin_id:-telegram_frame}"
payload_dir="$(prompt_value "Bridge payload directory" "$(get_yaml_value inkypi.payload_dir string)" "${PROJECT_ROOT}/data/inkypi" 0)"
refresh_command="$(prompt_value "Local InkyPi refresh command" "$(get_yaml_value inkypi.refresh_command string)" "sudo systemctl restart inkypi.service" 0)"

set_yaml_value inkypi.repo_path string "${repo_path}"
set_yaml_value inkypi.validated_commit string "${validated_commit}"
set_yaml_value inkypi.waveshare_model string "${waveshare_model}"
set_yaml_value inkypi.plugin_id string "${plugin_id}"
set_yaml_value inkypi.payload_dir string "${payload_dir}"
set_yaml_value inkypi.refresh_command string "${refresh_command}"

if [[ ! -d "${repo_path}" ]]; then
  run_cmd git clone https://github.com/fatihak/InkyPi.git "${repo_path}"
elif [[ ! -d "${repo_path}/.git" ]]; then
  echo "Existing InkyPi directory found at ${repo_path} without git metadata. Skipping git sync and injecting the plugin only."
else
  run_cmd git -C "${repo_path}" fetch --all --tags
fi

if [[ -d "${repo_path}/.git" ]]; then
  run_cmd git -C "${repo_path}" checkout "${validated_commit}"
fi

source_plugin_dir="${PROJECT_ROOT}/integrations/inkypi_plugin/telegram_frame"
target_plugin_dir="${repo_path}/src/plugins/${plugin_id}"
mkdir -p "${repo_path}/src/plugins" "${repo_path}/src/config"
rsync -a --delete "${source_plugin_dir}/" "${target_plugin_dir}/"

payload_json_path="${payload_dir%/}/current.json"

"${RUN_PYTHON}" - "${repo_path}" "${plugin_id}" "${payload_json_path}" <<'PY'
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

if [[ -x "${repo_path}/install/install.sh" ]]; then
  if ask_yes_no "Run InkyPi's installer now with -W ${waveshare_model}?" "y"; then
    if [[ "${MOCK_INSTALL}" == "1" ]]; then
      echo "[mock sudo] bash ${repo_path}/install/install.sh -W ${waveshare_model}"
    else
      run_privileged bash "${repo_path}/install/install.sh" -W "${waveshare_model}"
    fi
  fi
fi

if ask_yes_no "Restart inkypi.service now so the plugin is loaded?" "y"; then
  run_privileged systemctl restart inkypi.service
fi

echo "InkyPi setup completed. Plugin copied to ${target_plugin_dir}."
