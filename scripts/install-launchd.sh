#!/bin/bash
# Install LaunchAgents for guardian (proactive) + slack bot (interactive) at login.
# Requires SLACK_* env vars in your shell profile — LaunchAgents inherit a minimal env.
# Add exports to ~/.zshrc or use launchctl setenv (see docs/SLACK.md).

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${REPO}/.venv/bin/python"

install_plist() {
  local name="$1"
  local src="${REPO}/scripts/com.focusguardian.${name}.plist.template"
  local dst="${HOME}/Library/LaunchAgents/com.focusguardian.${name}.plist"
  sed -e "s|@PYTHON@|${PYTHON}|g" \
      -e "s|@REPO@|${REPO}|g" \
      -e "s|USER_PLACEHOLDER|${USER}|g" \
    "${src}" > "${dst}"
  launchctl unload "${dst}" 2>/dev/null || true
  launchctl load "${dst}"
  echo "Loaded com.focusguardian.${name}"
}

if [[ ! -x "${PYTHON}" ]]; then
  echo "Create venv first:"
  echo "  cd ${REPO} && /opt/homebrew/bin/python3.12 -m venv .venv && source .venv/bin/activate && pip install -e ."
  exit 1
fi

mkdir -p "${HOME}/Library/LaunchAgents"
install_plist "guardian"
install_plist "slack"

echo ""
echo "Installed guardian + slack LaunchAgents."
echo "Logs: ~/.focus-guardian/state/launchd.log and slack-launchd.log"
echo "Ensure SLACK_BOT_TOKEN, SLACK_APP_TOKEN, SLACK_USER_ID are available at login (see docs/SLACK.md)."
