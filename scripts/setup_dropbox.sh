#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_not_running_as_root
ensure_runtime_files
ensure_venv

current_enabled="$(get_yaml_value dropbox.enabled bool)"
if [[ "${current_enabled}" == "true" ]]; then
  token="$(get_or_prompt_value "Dropbox access token" "$(get_env_value DROPBOX_ACCESS_TOKEN)" "" 0)"
  set_env_value DROPBOX_ACCESS_TOKEN "${token}"
  set_yaml_value dropbox.enabled bool "true"
  echo "Validating Dropbox configuration."
  "${RUN_PYTHON}" - <<'PY'
from app.config import load_config
from app.dropbox_client import DropboxService

config = load_config()
service = DropboxService(config.dropbox)
if not service.enabled:
    raise SystemExit("Dropbox is enabled in config, but the SDK client could not be created.")
print("Dropbox client configured successfully.")
PY
else
  echo "Dropbox uploads disabled in config. Skipping Dropbox setup."
fi
