#!/usr/bin/env python3
"""Write the shareable character settings to shared/characters.sql for committing to Git.

    .venv/bin/python scripts/export_shared.py [--out shared/characters.sql]
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
import shared_settings  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="キャラ設定を共有用の SQL に書き出す")
    parser.add_argument("--out", type=Path, default=ROOT / "shared" / "characters.sql")
    args = parser.parse_args()
    server.init_db()
    with server.database() as db:
        sql = shared_settings.export_sql(db)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(sql, encoding="utf-8")
    handles = shared_settings.shared_handles(sql)
    print(f"{len(handles)} 人のキャラ設定を {args.out} に書き出しました: {', '.join('@' + h for h in handles) or 'なし'}")
    print("git diff で内容を確認してからコミットしてください。")


if __name__ == "__main__":
    main()
