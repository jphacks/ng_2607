#!/usr/bin/env python3
"""Check the AI settings in .env: the API key, the models it can use, and one test reply.

    .venv/bin/python scripts/check_ai.py
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402  (loads .env)


def main():
    print(f"AI: {server.AI_PROVIDER} ({server.AI_BASE_URL})")
    print(f"モデル: {server.AI_MODEL or '(未設定)'} / 好感度の判定: {server.RELATIONSHIP_MODEL or '(未設定)'}")
    if server.AI_PROVIDER == "openai":
        key = server.OPENAI_API_KEY
        if not key:
            sys.exit("OPENAI_API_KEY がありません。.env に書いてください")
        print(f"API キー: {key[:7]}…{key[-4:]}")
        req = urllib.request.Request(server.AI_BASE_URL + "/models", headers={"Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(req, timeout=30, context=server.tls_context()) as response:
                models = sorted(item["id"] for item in json.load(response)["data"])
        except urllib.error.HTTPError as exc:
            detail = exc.read(1000).decode("utf-8", "replace").lower()
            sys.exit(server.ai_error(exc.code, detail, server.AI_MODEL))
        except urllib.error.URLError as exc:
            sys.exit(f"OpenAI に接続できません: {exc.reason}")
        chat = [name for name in models if name.startswith(("gpt-", "o", "chatgpt-"))
                and not any(word in name for word in ("audio", "realtime", "transcribe", "tts", "image", "search", "embedding"))]
        print(f"\nこのキーで使えるチャット向けモデル ({len(chat)}件):")
        for name in chat:
            print(f"  {name}{'  ← AI_MODEL' if name == server.AI_MODEL else ''}")
        if not server.AI_MODEL:
            sys.exit("\n上の一覧から1つ選んで、.env の AI_MODEL= に書いてください")
        if server.AI_MODEL not in models:
            sys.exit(f"\nAI_MODEL={server.AI_MODEL} はこのキーでは使えません。上の一覧から選んでください")
    try:
        answer = server.call_ai([{"role": "system", "content": '日本語で、JSON のみで {"reply": "あいさつ"} を返す。'},
                                 {"role": "user", "content": "こんにちは"}], True, 0.2)
    except RuntimeError as exc:
        sys.exit(f"\nテストの返答に失敗しました: {exc}")
    print(f"\nテストの返答: {answer.strip()[:200]}")
    print("設定は正常です。サーバーを再起動すると反映されます。")


if __name__ == "__main__":
    main()
