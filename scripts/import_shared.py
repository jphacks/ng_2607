#!/usr/bin/env python3
"""Load shared/characters.sql (from Git) into this PC's database.

    .venv/bin/python scripts/import_shared.py [--file shared/characters.sql]

Characters are matched by handle. Local OAuth connections, relationships, game progress and the
auto-reply / auto-post switches are kept. Characters that are not in the file are left alone.
"""

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
import shared_settings  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="共有用の SQL からキャラ設定を取り込む")
    parser.add_argument("--file", type=Path, default=ROOT / "shared" / "characters.sql")
    args = parser.parse_args()
    if not args.file.is_file():
        sys.exit(f"{args.file} がありません。git pull するか、共有元で scripts/export_shared.py を実行してください")
    sql = args.file.read_text(encoding="utf-8")
    server.init_db()
    backup = server.DB_PATH.with_name("game.before-import.sqlite3")
    with server.database() as db:
        db.execute("PRAGMA wal_checkpoint(FULL)")
    shutil.copy2(server.DB_PATH, backup)
    try:
        with server.database() as db:
            added, updated = shared_settings.import_sql(db, sql)
    except ValueError as exc:
        sys.exit(str(exc))
    print(f"取り込みました。追加: {', '.join('@' + h for h in added) or 'なし'} / 更新: {', '.join('@' + h for h in updated) or 'なし'}")
    print(f"取り込み前の DB は {backup} に保存しました。")
    print("新しく追加したキャラは、/characters で「保存してOAuth認証へ」を押して接続してください。")


if __name__ == "__main__":
    main()
