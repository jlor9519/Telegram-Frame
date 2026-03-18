#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_runtime_files
ensure_venv

current_enabled="$(get_yaml_value dropbox.enabled bool)"
if [[ "${current_enabled}" == "true" ]]; then
  default_enable="y"
else
  default_enable="n"
fi

if ask_yes_no "Enable Dropbox uploads?" "${default_enable}"; then
  token="$(prompt_value "Dropbox access token" "$(get_env_value DROPBOX_ACCESS_TOKEN)" "" 0)"
  set_env_value DROPBOX_ACCESS_TOKEN "${token}"
  set_yaml_value dropbox.enabled bool "true"
  if ask_yes_no "Validate the Dropbox token now?" "y"; then
    "${RUN_PYTHON}" - <<'PY'
from app.config import load_config
from app.dropbox_client import DropboxService

config = load_config()
service = DropboxService(config.dropbox)
if not service.enabled:
    raise SystemExit("Dropbox is enabled in config, but the SDK client could not be created.")
print("Dropbox client configured successfully.")
PY
  fi
else
  set_yaml_value dropbox.enabled bool "false"
  echo "Dropbox uploads disabled in config."
fi
