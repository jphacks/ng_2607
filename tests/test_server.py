import io
import json
import datetime
import hashlib
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import server


DID = "did:plc:abcde2345"
CHAR_DID = "did:plc:character2345"
VISITOR = "a" * 64


class FakeDm:
    def __init__(self, messages=None):
        self.messages = list(messages or [])
        self.sent = []

    def __call__(self, command):
        op = command["op"]
        if op == "convoWithMember":
            return {"convo": {"id": "convo-1", "members": [{"did": DID}, {"did": CHAR_DID}]}}
        if op == "convoForPlayer":
            return {"convo": {"id": "convo-1"}}
        if op == "messages":
            return {"messages": list(reversed(self.messages)), "cursor": None}
        if op == "sendMessage":
            self.sent.append(command)
            item = {"id": f"dm-{len(self.messages) + 1}", "text": command["text"],
                    "sender": {"did": command["did"]},
                    "sentAt": datetime.datetime.now(datetime.timezone.utc).isoformat()}
            self.messages.append(item)
            return {"message": item}
        raise AssertionError(op)


def fake_ai(reply="うん", evaluations=(), memories=()):
    """Local AI stand-in: answers the relationship evaluation and the reply prompts separately."""
    def ai(messages, json_mode=False, temperature=0.75, model=None, timeout=120):
        if "評価係" in messages[0]["content"]:
            return json.dumps({"evaluations": list(evaluations), "reason": "テスト", "memories": list(memories)}, ensure_ascii=False)
        return json.dumps({"reply": reply}, ensure_ascii=False)
    return ai


def invoke(method, path, body=None, visitor=VISITOR):
    handler = server.Handler.__new__(server.Handler)
    handler.path = path
    handler.headers = {"Cookie": f"visitor={visitor}", "Origin": f"http://127.0.0.1:{server.PORT}"}
    if body is not None:
        raw = json.dumps(body).encode()
        handler.headers["Content-Length"] = str(len(raw))
        handler.rfile = io.BytesIO(raw)
    handler.wfile = io.BytesIO()
    result = {}
    handler.send_response = lambda status: result.update(status=status)
    handler.send_header = lambda key, value: result.update({key.lower(): value})
    handler.end_headers = lambda: None
    getattr(handler, method)()
    if result["status"] == 303:
        return result["status"], {"location": result["location"]}
    return result["status"], json.loads(handler.wfile.getvalue())


class ServerFixture(unittest.TestCase):
    """Temporary database with an authenticated player; shared by other test modules."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.data = patch.object(server, "DATA", Path(self.folder.name))
        self.db = patch.object(server, "DB_PATH", Path(self.folder.name) / "game.sqlite3")
        self.data.start()
        self.db.start()
        server.init_db()
        with server.database() as db:
            db.execute("INSERT INTO player_auth(visitor,did,updated_at) VALUES(?,?,?)", (VISITOR, DID, 1))
        # Never reach the public AppView from tests; game tests start with the ReAl lock off.
        self.posts = patch.object(server, "character_posts", return_value=[])
        self.posts.start()
        self.unlock = patch.object(server, "UNLOCK_REQUIRED_BY_DEFAULT", False)
        self.unlock.start()

    def tearDown(self):
        self.unlock.stop()
        self.posts.stop()
        self.db.stop()
        self.data.stop()
        self.folder.cleanup()

    def connect_character(self, selected=1):
        with server.database() as db:
            db.execute("UPDATE characters SET at_did=?,oauth_did=?,oauth_owner=? WHERE id=?",
                       (CHAR_DID, CHAR_DID, VISITOR, selected))

    def chat(self, message, selected=1, client_id=None):
        return invoke("do_POST", "/api/game/chat", {"characterId": selected, "message": message,
                                                    "clientMessageId": client_id or hashlib.sha256(message.encode()).hexdigest()[:16]})


class ServerTest(ServerFixture):

    def test_game_sends_both_sides_as_dm_without_local_chat_rows(self):
        self.connect_character()
        dm = FakeDm()
        status, body = invoke("do_POST", "/api/game/start", {
            "did": DID, "handle": "example.bsky.social", "profileContext": "公開投稿では映画が好き"
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["game"]["affinity"], 18)
        self.assertEqual(body["game"]["axes"], {"affection": 30.0, "trust": 20.0, "romance": 0.0})

        ai = fake_ai("映画の話を聞かせて", [{"condition": "interest_in_hobby", "score": 1.0, "evidence": "映画"}])
        with patch.object(server, "oauth_call", side_effect=dm), patch.object(server, "call_ai", side_effect=ai):
            for turn in range(10):
                status, body = self.chat(f"こんにちは {turn}")
                self.assertEqual(status, 200)

        status, loaded = invoke("do_GET", f"/api/game?did={DID}")
        self.assertEqual(status, 200)
        self.assertEqual(loaded["game"]["turns"], 10)
        axes = loaded["game"]["axes"]
        self.assertGreater(axes["affection"], 30)
        self.assertEqual(axes["trust"], 20.0)
        self.assertEqual(loaded["game"]["affinity"], server.relationship.overall(axes))
        self.assertEqual(loaded["game"]["messages"], [])
        self.assertEqual(len(dm.messages), 20)
        with server.database() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM character_messages").fetchone()[0], 0)
        self.assertTrue(loaded["game"]["ending"])
        with patch.object(server, "oauth_call", side_effect=dm):
            status, _ = self.chat("もう一度")
        self.assertEqual(status, 400)

    def test_ai_failure_does_not_store_message(self):
        self.connect_character()
        dm = FakeDm()
        invoke("do_POST", "/api/game/start", {"did": DID, "handle": "example.bsky.social", "profileContext": "公開データ"})
        with patch.object(server, "oauth_call", side_effect=dm), \
             patch.object(server, "call_ai", side_effect=RuntimeError("AI unavailable")):
            status, _ = self.chat("こんにちは")
        self.assertEqual(status, 503)
        self.assertEqual(len(dm.messages), 1)
        with patch.object(server, "oauth_call", side_effect=dm), \
             patch.object(server, "call_ai", return_value='{"reply":"うん","affinity_delta":1}'):
            status, _ = self.chat("こんにちは")
        self.assertEqual(status, 200)
        self.assertEqual(len(dm.messages), 2)
        _, loaded = invoke("do_GET", f"/api/game?did={DID}")
        self.assertEqual(loaded["game"]["turns"], 1)
        self.assertEqual(loaded["game"]["messages"], [])

    def test_rejected_character_dm_can_retry_without_resending_player_dm(self):
        self.connect_character()
        dm = FakeDm()
        invoke("do_POST", "/api/game/start", {"handle": "example.bsky.social", "profileContext": "公開データ"})

        def reject_once(command):
            if command["op"] == "sendMessage" and command["did"] == CHAR_DID:
                return {"rejected": "InsufficientScope"}
            return dm(command)

        with patch.object(server, "oauth_call", side_effect=reject_once), \
             patch.object(server, "call_ai", return_value='{"reply":"うん","affinity_delta":1}'):
            status, error = self.chat("こんにちは")
        self.assertEqual(status, 503)
        self.assertIn("再認証", error["error"])
        self.assertEqual(len(dm.messages), 1)
        with patch.object(server, "oauth_call", side_effect=dm), \
             patch.object(server, "call_ai", return_value='{"reply":"うん","affinity_delta":1}'):
            status, result = self.chat("こんにちは")
        self.assertEqual(status, 200)
        self.assertEqual(result["game"]["turns"], 1)
        self.assertEqual([item["sender"]["did"] for item in dm.messages], [DID, CHAR_DID])

    def test_disconnected_character_never_falls_back_to_local_chat(self):
        invoke("do_POST", "/api/game/start", {"handle": "example.bsky.social", "profileContext": "公開データ"})
        with patch.object(server, "oauth_call") as oauth:
            status, result = self.chat("こんにちは")
        self.assertEqual(status, 401)
        self.assertIn("OAuth", result["error"])
        oauth.assert_not_called()
        with server.database() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM character_messages").fetchone()[0], 0)

    def test_public_appview_uses_node_when_python_cannot_connect(self):
        profile = {"did": DID, "handle": "example.bsky.social"}
        with patch.object(server.urllib.request, "build_opener") as opener, \
             patch.object(server, "oauth_call", return_value={"data": profile}) as oauth:
            opener.return_value.open.side_effect = urllib.error.URLError("TLS failure")
            self.assertEqual(server.xrpc(server.APPVIEW, "app.bsky.actor.getProfile", actor="example.bsky.social"), profile)
        self.assertEqual(oauth.call_args.args[0]["op"], "publicGet")

    def test_character_management_and_separate_game_history(self):
        avatar = "https://cdn.bsky.app/img/avatar/example"
        with patch.object(server, "xrpc", return_value={"did": CHAR_DID, "handle": "hoshino.bsky.social", "displayName": "星野 灯", "avatar": avatar}):
            status, data = invoke("do_POST", "/api/characters/save", {
                "name": "手入力の名前は使わない", "profile": "成人。星を見るのが好き。", "handle": "hoshino.bsky.social",
            })
        self.assertEqual(status, 200)
        character = data["character"]
        self.assertEqual(character["name"], "星野 灯")
        self.assertEqual(character["atDid"], CHAR_DID)
        self.assertEqual(character["iconUrl"], avatar)
        second_id = character["id"]
        status, listed = invoke("do_GET", "/api/characters")
        self.assertEqual(status, 200)
        self.assertEqual(len(listed["characters"]), 2)
        with patch.object(server, "xrpc", return_value={"did": CHAR_DID, "handle": "hoshino.bsky.social", "displayName": "星野 灯・新", "avatar": "https://cdn.bsky.app/img/avatar/new"}):
            status, refreshed = invoke("do_GET", f"/api/characters/{second_id}/profile")
        self.assertEqual(status, 200)
        self.assertEqual(refreshed["character"]["name"], "星野 灯・新")
        self.assertEqual(refreshed["character"]["iconUrl"], "https://cdn.bsky.app/img/avatar/new")

        for selected in (1, second_id):
            status, _ = invoke("do_POST", "/api/game/start", {
                "did": DID, "characterId": selected, "handle": "example.bsky.social", "profileContext": "映画が好き",
            })
            self.assertEqual(status, 200)
        self.connect_character(second_id)
        dm = FakeDm()
        with patch.object(server, "oauth_call", side_effect=dm), \
             patch.object(server, "call_ai", return_value='{"reply":"星を見よう","affinity_delta":2}') as ai:
            status, _ = self.chat("こんばんは", second_id)
            self.assertEqual(status, 200)
            self.assertIn("星野 灯", ai.call_args.args[0][0]["content"])
        _, first = invoke("do_GET", f"/api/game?did={DID}&characterId=1")
        _, second = invoke("do_GET", f"/api/game?did={DID}&characterId={second_id}")
        self.assertEqual(first["game"]["turns"], 0)
        self.assertEqual(second["game"]["turns"], 1)

        status, _ = invoke("do_POST", "/api/characters/delete", {"id": second_id})
        self.assertEqual(status, 200)
        _, deleted_game = invoke("do_GET", f"/api/game?did={DID}&characterId={second_id}")
        self.assertIsNone(deleted_game["game"])

    def test_legacy_conversation_is_migrated_once(self):
        with server.database() as db:
            db.execute("INSERT INTO games(visitor,did,handle,profile_context,updated_at) VALUES(?,?,?,?,?)",
                       (VISITOR, DID, "example.bsky.social", "映画", 1))
            db.execute("INSERT INTO messages(visitor,did,role,content,created_at) VALUES(?,?,?,?,?)",
                       (VISITOR, DID, "user", "こんにちは", 1))
            db.execute("DELETE FROM meta WHERE key='legacy_games_migrated'")
        server.init_db()
        server.init_db()
        _, data = invoke("do_GET", f"/api/game?did={DID}&characterId=1")
        self.assertEqual(data["game"]["messages"], [])
        with server.database() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM character_messages").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 1)

    def test_chat_retry_with_same_client_id_does_not_duplicate_or_regenerate(self):
        self.connect_character()
        dm = FakeDm()
        invoke("do_POST", "/api/game/start", {"characterId": 1, "handle": "example.bsky.social",
                                                "profileContext": "認証済みユーザー"})
        payload = {"characterId": 1, "message": "こんにちは", "clientMessageId": "client-123"}
        with patch.object(server, "oauth_call", side_effect=dm), \
             patch.object(server, "call_ai", side_effect=fake_ai("こんにちは")) as ai:
            status, first = invoke("do_POST", "/api/game/chat", payload)
            self.assertEqual(status, 200)
            status, second = invoke("do_POST", "/api/game/chat", payload)
            self.assertEqual(status, 200)
            self.assertEqual(ai.call_count, 2)  # One evaluation and one reply, not regenerated on retry.
        self.assertEqual(second["game"]["turns"], 1)
        self.assertEqual(len(dm.messages), 2)
        self.assertEqual(len(second["dmMessages"]), 2)
        self.assertEqual(second["game"]["messages"], first["game"]["messages"])
        status, _ = invoke("do_POST", "/api/game/chat", {**payload, "message": "別の文"})
        self.assertEqual(status, 400)

    def test_player_identity_is_required_and_cannot_be_spoofed(self):
        other = "did:plc:other2345"
        status, _ = invoke("do_POST", "/api/game/start", {
            "did": other, "handle": "other.bsky.social", "profileContext": "情報"})
        self.assertEqual(status, 401)
        with server.database() as db:
            db.execute("DELETE FROM player_auth WHERE visitor=?", (VISITOR,))
        status, _ = invoke("do_POST", "/api/game/start", {
            "did": DID, "handle": "example.bsky.social", "profileContext": "情報"})
        self.assertEqual(status, 401)

    def test_character_oauth_binds_matching_did_and_exposes_dm_pages(self):
        char_did = "did:plc:character2345"
        with patch.object(server, "xrpc", return_value={"did": char_did, "handle": "character.bsky.social"}):
            status, saved = invoke("do_POST", "/api/characters/save", {
                "name": "灯", "profile": "成人", "handle": "character.bsky.social"})
        self.assertEqual(status, 200)
        selected = saved["character"]["id"]
        with patch.object(server, "oauth_call", return_value={"url": "https://example.com/authorize"}):
            status, started = invoke("do_POST", "/api/oauth/start", {"role": "character", "characterId": selected})
        self.assertEqual(status, 200)
        self.assertEqual(started["url"], "https://example.com/authorize")
        with server.database() as db:
            state = db.execute("SELECT state FROM oauth_flows").fetchone()["state"]
        sdk_state = "sdkGeneratedState"
        with patch.object(server, "oauth_call", return_value={"did": char_did, "state": state}) as oauth:
            status, callback = invoke("do_POST", "/api/oauth/finish", {"query": f"state={sdk_state}&code=abc"})
        self.assertEqual(oauth.call_args.args[0]["query"], f"state={sdk_state}&code=abc")
        self.assertEqual(status, 200)
        self.assertIn("/characters", callback["location"])
        with patch.object(server, "oauth_call", return_value={"convos": [{"id": "convo-1", "members": []}], "cursor": "next"}):
            status, page = invoke("do_GET", f"/api/characters/{selected}/convos")
        self.assertEqual(status, 200)
        self.assertEqual(page["cursor"], "next")
        status, _ = invoke("do_GET", f"/api/characters/{selected}/convos", visitor="b" * 64)
        self.assertEqual(status, 401)
        with patch.object(server, "oauth_call", side_effect=lambda command: (
            {"convo": {"id": "convo-1"}} if command["op"] == "convoForPlayer" else
            {"messages": [{"id": "dm-1", "text": "原文", "sender": {"did": DID}}], "cursor": None}
        )):
            status, page = invoke("do_GET", f"/api/game/dm?characterId={selected}")
        self.assertEqual(status, 200)
        self.assertEqual(page["messages"][0]["text"], "原文")
        with patch.object(server, "oauth_call", return_value={"convo": {"id": "convo-1"}}):
            status, _ = invoke("do_GET", f"/api/game/dm?characterId={selected}&convoId=someone-elses-convo")
        self.assertEqual(status, 401)

    def test_oauth_callback_does_not_bind_another_browser_session(self):
        app_state = "app-state"
        sdk_state = "sdk-state"
        authenticated_did = "did:plc:character2345"
        with server.database() as db:
            db.execute("INSERT INTO oauth_flows(state,visitor,role,character_id,expected_did,created_at) VALUES(?,?,?,?,?,?)",
                       (app_state, VISITOR, "character", 1, authenticated_did, int(server.time.time())))
        with patch.object(server, "oauth_call", return_value={"did": authenticated_did, "state": app_state}), \
             patch.object(server, "forget_if_unused") as forget:
            status, response = invoke("do_POST", "/api/oauth/finish", {"query": f"state={sdk_state}&code=abc"}, visitor="b" * 64)
        self.assertEqual(status, 400)
        self.assertIn("ブラウザのセッション", response["error"])
        forget.assert_called_once_with(authenticated_did)

    def test_player_oauth_callback_uses_application_state(self):
        with patch.object(server, "oauth_call", return_value={"url": "https://example.com/authorize"}):
            status, _ = invoke("do_POST", "/api/oauth/start", {"role": "player", "handle": "example.bsky.social"})
        self.assertEqual(status, 200)
        with server.database() as db:
            app_state = db.execute("SELECT state FROM oauth_flows").fetchone()["state"]
        with patch.object(server, "oauth_call", return_value={"did": DID, "state": app_state}):
            status, callback = invoke("do_POST", "/api/oauth/finish", {"query": "state=sdkGeneratedState&code=abc"})
        self.assertEqual(status, 200)
        self.assertEqual(callback["location"], "/?oauth=connected")

    def test_oauth_callback_serves_same_origin_completion_page(self):
        handler = server.Handler.__new__(server.Handler)
        handler.path = "/oauth/callback?state=sdkGeneratedState&code=abc"
        handler.headers = {}
        handler.wfile = io.BytesIO()
        result = {}
        handler.send_response = lambda status: result.update(status=status)
        handler.send_header = lambda key, value: result.update({key.lower(): value})
        handler.end_headers = lambda: None
        handler.do_GET()
        self.assertEqual(result["status"], 200)
        self.assertIn(b"oauth_callback.js", handler.wfile.getvalue())
        self.assertEqual(result["referrer-policy"], "no-referrer")

    def test_hiyori_pages_and_images_are_served(self):
        for route, content_type, marker in (
            ("/", "text/html", b"hiyori-app.js"),
            ("/login", "text/html", b"hiyori-login.js"),
            ("/avatar-placeholder.svg", "image/svg+xml", b"<svg"),
            ("/assets-karesi.png", "image/png", b"\x89PNG"),
            ("/real-logo.png", "image/png", b"\x89PNG"),
        ):
            handler = server.Handler.__new__(server.Handler)
            handler.path = route
            handler.headers = {}
            handler.wfile = io.BytesIO()
            result = {}
            handler.send_response = lambda status: result.update(status=status)
            handler.send_header = lambda key, value: result.update({key.lower(): value})
            handler.end_headers = lambda: None
            handler.do_GET()
            self.assertEqual(result["status"], 200, route)
            self.assertIn(content_type, result["content-type"])
            self.assertIn(marker, handler.wfile.getvalue())

    def test_recent_character_dm_is_context_but_not_local_chat_history(self):
        self.connect_character()
        status, _ = invoke("do_POST", "/api/game/start", {
            "characterId": 1, "handle": "example.bsky.social", "profileContext": "映画が好き"})
        self.assertEqual(status, 200)
        dm = FakeDm([{"id": "prior", "text": "週末は映画を見たい", "sender": {"did": DID},
                      "sentAt": "2026-10-20T00:00:00Z"}])
        with patch.object(server, "oauth_call", side_effect=dm), \
             patch.object(server, "call_ai", return_value='{"reply":"映画の話をしよう","affinity_delta":1}') as ai:
            status, result = self.chat("こんにちは")
        self.assertEqual(status, 200)
        self.assertIn("週末は映画を見たい", ai.call_args.args[0][0]["content"])
        self.assertEqual(result["game"]["messages"], [])
        self.assertEqual(len(dm.messages), 3)

    def save_secrets(self, secrets):
        with patch.object(server, "xrpc", return_value={"did": "did:plc:character2345", "handle": "character.bsky.social"}):
            status, saved = invoke("do_POST", "/api/characters/save", {
                "id": 1, "profile": "成人", "handle": "character.bsky.social", "secrets": secrets})
        self.assertEqual(status, 200)

    def test_secrets_unlock_at_affinity_levels_and_hide_locked_content(self):
        self.save_secrets([
            {"level": 25, "title": "", "content": "朝が苦手"},
            {"level": 50, "title": "好きな場所", "content": "海が見えるカフェ"},
            {"level": 75, "title": "大切なこと", "content": "静かな時間"},
            {"level": 100, "title": "いつか", "content": "一緒に旅へ"},
        ])
        status, edited = invoke("do_GET", "/api/characters/1/secrets")
        self.assertEqual(status, 200)
        self.assertEqual([item["level"] for item in edited["secrets"]], [25, 50, 75, 100])
        self.assertEqual(edited["secrets"][2]["content"], "静かな時間")

        _, started = invoke("do_POST", "/api/game/start", {"characterId": 1, "handle": "example.bsky.social", "profileContext": "情報"})
        secrets = {item["level"]: item for item in started["game"]["secrets"]}
        self.assertEqual(secrets[25]["title"], "好感度25のヒミツ")
        self.assertFalse(secrets[25]["unlocked"], "a new story starts at overall 18")
        self.assertIsNone(secrets[75]["content"])
        self.assertEqual(secrets[75]["title"], "大切なこと")
        status, _ = invoke("do_POST", "/api/game/secret/read", {"characterId": 1, "level": 50})
        self.assertEqual(status, 400)

        # Overall 74 -> 75 unlocks 25, 50 and 75 at once; a later drop keeps them unlocked.
        with server.database() as db:
            db.execute("""INSERT INTO dm_relationships(character_id,partner_did,affection,trust,romance,updated_at)
                          VALUES(1,?,74,74,74,1)""", (DID,))
        self.connect_character()
        dm = FakeDm()
        praise = fake_ai("うれしい", [{"condition": "praise_effort", "score": 1.0, "evidence": "頑張ってるね"}])
        insult = fake_ai("そっか", [{"condition": "insult", "score": 1.0, "evidence": "ひどい言葉"}])
        with patch.object(server, "oauth_call", side_effect=dm), patch.object(server, "call_ai", side_effect=praise):
            status, chat = self.chat("頑張ってるね")
        self.assertEqual(status, 200)
        self.assertEqual(chat["game"]["affinity"], 75)
        status, _ = invoke("do_POST", "/api/game/secret/read", {"characterId": 1, "level": 50})
        self.assertEqual(status, 200)
        with patch.object(server, "oauth_call", side_effect=dm), patch.object(server, "call_ai", side_effect=insult):
            status, chat = self.chat("ひどい言葉")
        self.assertEqual(status, 200)
        self.assertEqual(chat["relationshipUpdate"]["delta"]["affection"], -7.0)
        self.assertLess(chat["game"]["affinity"], 75)
        secrets = {item["level"]: item for item in chat["game"]["secrets"]}
        self.assertTrue(secrets[75]["unlocked"], "unlocked secrets stay unlocked after affinity drops")
        self.assertEqual(secrets[75]["content"], "静かな時間")
        self.assertTrue(secrets[50]["read"])
        self.assertFalse(secrets[75]["read"])
        self.assertFalse(secrets[100]["unlocked"])

        self.save_secrets([{"level": 25, "title": "", "content": ""}])
        _, loaded = invoke("do_GET", "/api/game?characterId=1")
        self.assertEqual([item["level"] for item in loaded["game"]["secrets"]], [50, 75, 100])
        status, _ = invoke("do_POST", "/api/characters/save", {"id": 1, "profile": "成人", "handle": "character.bsky.social",
                                                                "secrets": [{"level": 30, "content": "不正"}]})
        self.assertEqual(status, 400)

    def test_chat_does_not_hold_db_lock_while_waiting_for_ai(self):
        self.connect_character()
        dm = FakeDm()
        invoke("do_POST", "/api/game/start", {"characterId": 1, "handle": "example.bsky.social", "profileContext": "情報"})
        acquired = []

        def ai(*args):
            thread = threading.Thread(target=lambda: acquired.append(server.DB_LOCK.acquire(timeout=1) and server.DB_LOCK.release() is None))
            thread.start()
            thread.join()
            return '{"reply":"うん","affinity_delta":1}'
        with patch.object(server, "oauth_call", side_effect=dm), patch.object(server, "call_ai", side_effect=ai):
            status, _ = self.chat("こんにちは")
        self.assertEqual(status, 200)
        self.assertTrue(acquired and all(acquired))

    def test_chat_is_not_saved_when_game_restarts_during_generation(self):
        self.connect_character()
        dm = FakeDm()
        invoke("do_POST", "/api/game/start", {"characterId": 1, "handle": "example.bsky.social", "profileContext": "情報"})

        def ai(*args):
            invoke("do_POST", "/api/game/start", {"characterId": 1, "handle": "example.bsky.social", "profileContext": "情報"})
            return '{"reply":"うん","affinity_delta":1}'
        with patch.object(server, "oauth_call", side_effect=dm), patch.object(server, "call_ai", side_effect=ai):
            status, _ = self.chat("こんにちは")
        self.assertEqual(status, 409)
        self.assertEqual(len(dm.sent), 1)
        _, loaded = invoke("do_GET", "/api/game?characterId=1")
        self.assertEqual(loaded["game"]["messages"], [])


if __name__ == "__main__":
    unittest.main()
