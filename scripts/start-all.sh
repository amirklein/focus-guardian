#!/bin/bash
# Start both Focus Guardian daemons (run after: source .venv/bin/activate && source ~/.zshrc)

set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
FGR="${REPO}/.venv/bin/fgr"

if [[ ! -x "${FGR}" ]]; then
  echo "Missing venv. Run: cd ${REPO} && python3.12 -m venv .venv && source .venv/bin/activate && pip install -e ."
  exit 1
fi

"${FGR}" slack check || exit 1
"${FGR}" init
"${FGR}" slack start
"${FGR}" guardian start
"${FGR}" status
