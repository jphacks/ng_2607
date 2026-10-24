import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import relationship as rel
import server
from test_automation import ALL_FREE, CHAR_DID, STRANGER_DID, FakeBluesky, schedule_reply
from test_server import invoke

VISITOR = "c" * 64  # Owns the character and plays as STRANGER_DID.


def dm_ai(evaluations=(), reply="うれしいな", replies=None):
    """AI stand-in for the DM flow: schedule, relationship evaluation and the reply."""
    def ai(messages, json_mode=False, temperature=0.75, model=None, timeout=120):
        system = messages[0]["content"]
        if "評価係" in system:
            return json.dumps({"evaluations": list(evaluations), "reason": "テスト", "memories": []}, ensure_ascii=False)
        if json_mode:
            return schedule_reply()
        if replies is not None:
            replies.append(system)
        return reply
    return ai


class UnlockTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.patches = [patch.object(server, "DATA", Path(self.folder.name)),
                        patch.object(server, "DB_PATH", Path(self.folder.name) / "game.sqlite3"),
                        patch.object(server, "character_posts", return_value=[])]
        for item in self.patches:
            item.start()
        server.init_db()
        server.RUNNER.state.clear()
        server.RUNNER.status.clear()
        with server.database() as db:
            db.execute("UPDATE characters SET handle='char.test',at_did=?,oauth_did=?,oauth_owner=? WHERE id=1",
                       (CHAR_DID, CHAR_DID, VISITOR))
            db.execute("INSERT INTO player_auth(visitor,did,updated_at) VALUES(?,?,1)", (VISITOR, STRANGER_DID))
        self.bsky = FakeBluesky()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.folder.cleanup()

    def save(self, **overrides):
        body = {"auto_reply": True, "auto_post": False, "post_prompt": "", "extra_persona": "",
                "schedule_base": json.dumps(ALL_FREE, ensure_ascii=False), "require_unlock": True, "unlock_score": 22, **overrides}
        return invoke("do_POST", "/api/characters/1/automation", body, visitor=VISITOR)

    def dm(self, *texts):
        self.bsky.convos.clear()
        self.bsky.add_convo("stranger", STRANGER_DID, "stranger.test", [(STRANGER_DID, text) for text in texts])

    def unlock(self):
        _, data = invoke("do_GET", "/api/characters", visitor=VISITOR)
        return data["characters"][0]["unlock"]

    def test_locked_character_is_listed_with_progress_and_refused_by_the_game(self):
        self.save()
        self.assertEqual(self.unlock(), {"required": True, "unlocked": False, "score": 18, "threshold": 22})
        for method, path, body in (("do_GET", "/api/game?characterId=1", None),
                                   ("do_GET", "/api/game/dm?characterId=1", None),
                                   ("do_POST", "/api/game/start", {"characterId": 1, "handle": "s.test", "profileContext": "情報"})):
            status, data = invoke(method, path, body, visitor=VISITOR)
            self.assertEqual(status, 403, path)
            self.assertIn("まだ解放されていません", data["error"])
        # Turning the requirement off opens it for everyone.
        self.save(require_unlock=False)
        self.assertTrue(self.unlock()["unlocked"])

    def test_dm_replies_update_the_relationship_and_open_real(self):
        self.save()
        self.dm("新作プリンの投稿見たよ！", "残念だったね")
        replies = []
        ai = dm_ai([{"condition": "sns_reference", "score": 1.0, "evidence": "プリンの投稿"},
                    {"condition": "comfort_worry", "score": 1.0, "evidence": "残念だったね"}], replies=replies)
        with patch.object(server, "oauth_call", side_effect=self.bsky), patch.object(server, "call_ai", side_effect=ai):
            server.RUNNER.tick()
        self.assertEqual([item["convoId"] for item in self.bsky.sent], ["stranger"])
        # A: 30+3, T: 20+4 -> overall 0.4*33 + 0.3*24 = 20.4 -> 20, still below 22.
        self.assertEqual(self.unlock(), {"required": True, "unlocked": False, "score": 20, "threshold": 22})
        self.assertNotIn("ReAl", replies[-1])

        _, panel = invoke("do_GET", "/api/characters/1/automation", visitor=VISITOR)
        relation = panel["relationships"][0]
        self.assertEqual((relation["handle"], relation["axes"]), ("stranger.test", {"affection": 33.0, "trust": 24.0, "romance": 0.0}))
        self.assertEqual(relation["lastDelta"], {"affection": 3.0, "trust": 4.0, "romance": 0.0})

        # The next turn crosses the threshold: the reply invites them and the game opens.
        self.dm("新作プリンの投稿見たよ！", "残念だったね", "今日もお疲れさま。無理しないでね")
        self.bsky.convos[0]["lastMessage"]["sender"]["did"] = STRANGER_DID
        self.bsky.history["stranger"].insert(2, {"id": "mine", "sender": {"did": CHAR_DID}, "text": "ありがとう"})
        ai = dm_ai([{"condition": "care_condition", "score": 1.0, "evidence": "無理しないでね"},
                    {"condition": "praise_effort", "score": 1.0, "evidence": "お疲れさま"}], replies=replies)
        server.RUNNER.state[1]["last_full"] = 0
        with patch.object(server, "oauth_call", side_effect=self.bsky), patch.object(server, "call_ai", side_effect=ai):
            server.RUNNER.tick()
        self.assertIn("ReAl", replies[-1])
        status = self.unlock()
        self.assertTrue(status["unlocked"])
        log = server.RUNNER.load_day(1, __import__("datetime").date.today())["dm_log"]
        self.assertTrue(log[-1]["unlocked"])
        self.assertNotIn("text", log[-1])

        # The game starts from the relationship built through DMs.
        status, started = invoke("do_POST", "/api/game/start", {"characterId": 1, "handle": "s.test", "profileContext": "情報"},
                                 visitor=VISITOR)
        self.assertEqual(status, 200)
        self.assertEqual(started["game"]["axes"], {"affection": 36.0, "trust": 27.0, "romance": 0.0})

    def test_only_the_partners_new_messages_are_evaluated(self):
        self.save()
        self.bsky.add_convo("stranger", STRANGER_DID, "stranger.test",
                            [(STRANGER_DID, "古い発言"), (CHAR_DID, "返事"), (STRANGER_DID, "新しい1"), (STRANGER_DID, "新しい2")])
        prompts = []

        def ai(messages, json_mode=False, temperature=0.75, model=None, timeout=120):
            prompts.append(messages)
            return dm_ai()(messages, json_mode, temperature, model, timeout)
        with patch.object(server, "oauth_call", side_effect=self.bsky), patch.object(server, "call_ai", side_effect=ai):
            server.RUNNER.tick()
        evaluation = next(item for item in prompts if "評価係" in item[0]["content"])[1]["content"]
        self.assertIn("評価するプレイヤーの最新の発言:\n新しい1\n新しい2", evaluation)
        self.assertIn("プレイヤー: 古い発言", evaluation)

    def test_unlock_settings_are_validated_and_returned(self):
        status, data = self.save(unlock_score=0)
        self.assertEqual(status, 400)
        status, data = self.save(unlock_score=55, require_unlock=False)
        self.assertEqual(status, 200)
        _, panel = invoke("do_GET", "/api/characters/1/automation", visitor=VISITOR)
        self.assertEqual((panel["settings"]["unlock_score"], panel["settings"]["require_unlock"]), (55, False))

    def test_unlock_stays_open_after_the_relationship_drops(self):
        self.save()
        with server.database() as db:
            db.execute("INSERT INTO dm_relationships(character_id,partner_did,affection,trust,romance,unlocked_at,updated_at) VALUES(1,?,0,0,0,1,1)",
                       (STRANGER_DID,))
        self.assertTrue(self.unlock()["unlocked"])


class OpenAITest(unittest.TestCase):
    def request(self, responses, **config):
        """Run call_ai against canned HTTP responses; returns the result and the captured requests."""
        sent = []

        def urlopen(req, timeout, context=None):
            sent.append(json.loads(req.data))
            sent[-1]["_auth"] = req.get_header("Authorization")
            sent[-1]["_url"] = req.full_url
            status, payload = responses.pop(0)
            if status != 200:
                raise server.urllib.error.HTTPError(req.full_url, status, "error", {}, __import__("io").BytesIO(json.dumps(payload).encode()))
            return __import__("io").BytesIO(json.dumps(payload).encode())
        settings = {"AI_PROVIDER": "openai", "OPENAI_API_KEY": "sk-test", "AI_MODEL": "gpt-test",
                    "AI_BASE_URL": "https://api.openai.com/v1", **config}
        with patch.multiple(server, **settings), patch.object(server, "NO_TEMPERATURE", set()), \
             patch.object(server.urllib.request, "urlopen", side_effect=urlopen):
            try:
                return server.call_ai([{"role": "user", "content": "JSONで"}], True, 0.2), sent
            except RuntimeError as exc:
                return exc, sent

    def test_sends_key_model_and_json_mode(self):
        result, sent = self.request([(200, {"choices": [{"message": {"content": '{"ok": true}'}}]})])
        self.assertEqual(result, '{"ok": true}')
        self.assertEqual(sent[0]["_auth"], "Bearer sk-test")
        self.assertEqual(sent[0]["_url"], "https://api.openai.com/v1/chat/completions")
        self.assertEqual((sent[0]["model"], sent[0]["temperature"], sent[0]["response_format"]), ("gpt-test", 0.2, {"type": "json_object"}))
        self.assertNotIn("reasoning_effort", sent[0])

    def test_retries_without_temperature_when_the_model_rejects_it(self):
        error = {"error": {"message": "Unsupported value: 'temperature' does not support 0.2 with this model."}}
        result, sent = self.request([(400, error), (200, {"choices": [{"message": {"content": "ok"}}]})])
        self.assertEqual(result, "ok")
        self.assertNotIn("temperature", sent[1])

    def test_explains_common_errors(self):
        result, _ = self.request([(401, {"error": {"message": "Incorrect API key provided"}})])
        self.assertIn("API キーが正しくありません", str(result))
        result, _ = self.request([(429, {"error": {"code": "insufficient_quota"}})])
        self.assertIn("利用残高", str(result))
        result, sent = self.request([], AI_MODEL="")
        self.assertIn("AI_MODEL が設定されていません", str(result))
        self.assertEqual(sent, [])
        result, sent = self.request([], OPENAI_API_KEY="")
        self.assertIn("OPENAI_API_KEY", str(result))

    def test_env_file_is_read_without_overriding_the_shell(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".env"
            path.write_text('# comment\nexport REAL_TEST_A="quoted value"\nREAL_TEST_B=from-file\n', encoding="utf-8")
            with patch.dict(server.os.environ, {"REAL_TEST_B": "from-shell"}):
                server.load_env_file(path)
                self.assertEqual(server.os.environ["REAL_TEST_A"], "quoted value")
                self.assertEqual(server.os.environ["REAL_TEST_B"], "from-shell")
                server.os.environ.pop("REAL_TEST_A")


if __name__ == "__main__":
    unittest.main()
