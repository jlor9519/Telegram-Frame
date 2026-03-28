#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_not_running_as_root
ensure_runtime_files
ensure_venv

current_enabled="$(get_yaml_value dropbox.enabled bool)"
if [[ "${current_enabled}" != "true" ]]; then
  echo "Dropbox uploads disabled in config. Skipping Dropbox setup."
  exit 0
fi

# --- App key (stored in config.yaml) ---
current_app_key="$(get_yaml_value dropbox.app_key string)"
app_key="$(get_or_prompt_value "Dropbox App key" "${current_app_key}" "" 0)"
set_yaml_value dropbox.app_key string "${app_key}"

# --- Refresh token (stored in .env) ---
current_refresh_token="$(get_env_value DROPBOX_REFRESH_TOKEN)"
if [[ -n "${current_refresh_token}" ]]; then
  if [[ "${PROMPT_MODE}" == "missing-only" ]]; then
    echo "Dropbox refresh token already set."
  else
    if ask_yes_no "Dropbox refresh token is already set. Keep the existing value?" "y"; then
      current_refresh_token="$(get_env_value DROPBOX_REFRESH_TOKEN)"
    else
      current_refresh_token=""
    fi
  fi
fi

if [[ -z "${current_refresh_token}" ]]; then
  if ! command -v curl >/dev/null 2>&1; then
    echo >&2 "curl is required for Dropbox OAuth token exchange. Install it and rerun this script."
    exit 1
  fi

  echo
  echo "We need to authorize this app with Dropbox to get a refresh token."
  echo "You will need the App secret from your Dropbox app's Settings page."
  echo
  read -r -s -p "Dropbox App secret (hidden): " app_secret
  echo

  auth_url="https://www.dropbox.com/oauth2/authorize?client_id=${app_key}&response_type=code&token_access_type=offline"
  echo
  echo "Open this URL in a browser and authorize the app:"
  echo
  echo "  ${auth_url}"
  echo
  read -r -p "Paste the authorization code here: " auth_code

  if [[ -z "${auth_code}" ]]; then
    echo >&2 "No authorization code entered. Aborting."
    exit 1
  fi

  echo "Exchanging authorization code for refresh token..."
  token_response="$(curl -s -X POST https://api.dropboxapi.com/oauth2/token \
    -d "code=${auth_code}" \
    -d "grant_type=authorization_code" \
    -d "client_id=${app_key}" \
    -d "client_secret=${app_secret}")"

  refresh_token="$("${RUN_PYTHON}" -c "
import json, sys
data = json.loads(sys.argv[1])
if 'error' in data:
    print(data.get('error_description', data['error']), file=sys.stderr)
    sys.exit(1)
print(data['refresh_token'])
" "${token_response}")"

  set_env_value DROPBOX_REFRESH_TOKEN "${refresh_token}"
  echo "Refresh token saved."
fi

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
