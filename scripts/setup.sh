#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10 以上が必要です")
PY

python3 -m venv .venv
"$project_dir/.venv/bin/python" -m pip --version >/dev/null
printf 'Python 仮想環境を作成しました: %s/.venv\n' "$project_dir"
if ! command -v node >/dev/null 2>&1 || ! node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit(major > 22 || (major === 22 && minor >= 19) ? 0 : 1)' >/dev/null 2>&1; then
  printf 'OAuth には Node.js 22.19 以上が必要です。Node.js を更新してから npm install を実行してください。\n' >&2
  exit 1
fi
printf '次に npm install を実行し、.env に OpenAI の API キーとモデルを書いてください (cp .env.example .env)。\n'
