#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

if [[ ! -x .venv/bin/python ]]; then
  printf 'Python 仮想環境がありません。先に ./scripts/setup.sh を実行してください。\n' >&2
  exit 1
fi

if ! command -v node >/dev/null 2>&1 || ! node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit(major > 22 || (major === 22 && minor >= 19) ? 0 : 1)' >/dev/null 2>&1; then
  printf 'OAuth には Node.js 22.19 以上が必要です。現在の Node.js を node -v で確認してください。\n' >&2
  exit 1
fi

if [[ ! -d node_modules/@atproto/oauth-client-node || ! -d node_modules/@atproto/api ]]; then
  printf 'OAuth 用の Node.js パッケージがありません。先に npm install を実行してください。\n' >&2
  exit 1
fi

exec "$project_dir/.venv/bin/python" "$project_dir/server.py"
