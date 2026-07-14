#!/bin/bash
# Start both Focus Guardian daemons (run after: source .venv/bin/activate && source ~/.zshrc)

set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
FG="${REPO}/.venv/bin/fg"

if [[ ! -x "${FG}" ]]; then
  echo "Missing venv. Run: cd ${REPO} && python3.12 -m venv .venv && source .venv/bin/activate && pip install -e ."
  exit 1
fi

"${FG}" slack check || exit 1
"${FG}" init
"${FG}" slack start
"${FG}" guardian start
"${FG}" status
