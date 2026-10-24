import datetime
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import automation
import server
from test_server import invoke

CHAR_DID = "did:plc:character2345"
PLAYER_DID = "did:plc:abcde2345"
STRANGER_DID = "did:plc:stranger2345"
VISITOR = "a" * 64
OTHER_VISITOR = "b" * 64
ALL_FREE = {"week": {day: "毎日" for day in automation.WEEKDAYS}, "posts_per_day": {"毎日": 2},
            "patterns": {"毎日": [{"start": "00:00", "end": "24:00", "activity": "自由", "status": "free"}]}}


def schedule_reply(plan="のんびりする"):
    return json.dumps({"plans": {"00:00〜24:00 自由": plan}, "events": [{"slot": "00:00〜24:00 自由", "text": "猫を見かけた"}]})


class FakeBluesky:
    def __init__(self):
        self.convos = []
        self.history = {}
        self.sent = []
        self.posts = []
        self.logs = []

    def __call__(self, command):
        op = command["op"]
        if op == "chatLog":
            logs, self.logs = self.logs, []
            return {"logs": logs, "cursor": f"c{len(self.sent)}-{len(logs)}"}
        if op == "convos":
            return {"convos": self.convos, "cursor": None}
        if op == "messages":
            return {"messages": list(reversed(self.history[command["convoId"]])), "cursor": None}
        if op == "sendMessage":
            self.sent.append(command)
            return {"message": {"id": f"sent-{len(self.sent)}", "text": command["text"]}}
        if op == "updateRead":
            return {"ok": True}
        if op == "createPost":
            self.posts.append(command)
            return {"uri": f"at://{CHAR_DID}/app.bsky.feed.post/{len(self.posts)}", "cid": "cid"}
        if op == "scope":
            return {"scope": "atproto"}
        raise AssertionError(op)

    def add_convo(self, convo_id, partner_did, handle, texts):
        self.convos.append({"id": convo_id, "status": "accepted", "muted": False,
                            "members": [{"did": CHAR_DID}, {"did": partner_did, "handle": handle}],
                            "lastMessage": {"sender": {"did": texts[-1][0]}, "text": texts[-1][1]}})
        self.history[convo_id] = [{"id": f"{convo_id}-{i}", "sender": {"did": did}, "text": text} for i, (did, text) in enumerate(texts)]


class AutomationTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.patches = [patch.object(server, "DATA", Path(self.folder.name)),
                        patch.object(server, "DB_PATH", Path(self.folder.name) / "game.sqlite3")]
        self.patches.append(patch.object(server, "character_posts", return_value=[]))
        for item in self.patches:
            item.start()
        server.init_db()
        server.RUNNER.state.clear()
        server.RUNNER.status.clear()
        with server.database() as db:
            db.execute("UPDATE characters SET handle='char.test',at_did=?,oauth_did=?,oauth_owner=?,oauth_scope='atproto' WHERE id=1",
                       (CHAR_DID, CHAR_DID, VISITOR))
        self.bsky = FakeBluesky()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.folder.cleanup()

    def save(self, **overrides):
        body = {"auto_reply": True, "auto_post": False, "post_prompt": "", "extra_persona": "語尾は〜だよ",
                "schedule_base": json.dumps(ALL_FREE, ensure_ascii=False), **overrides}
        return invoke("do_POST", "/api/characters/1/automation", body)

    def test_settings_are_owner_only_and_validated(self):
        status, data = invoke("do_GET", "/api/characters/1/automation", visitor=OTHER_VISITOR)
        self.assertEqual(status, 401)
        status, data = invoke("do_POST", "/api/characters/1/automation", {"auto_reply": True}, visitor=OTHER_VISITOR)
        self.assertEqual(status, 401)

        with patch.object(server, "oauth_call", side_effect=self.bsky):
            status, data = invoke("do_GET", "/api/characters/1/automation")
        self.assertEqual(status, 200)
        self.assertFalse(data["settings"]["auto_reply"])
        self.assertIn("patterns", json.loads(data["settings"]["schedule_base"]))
        self.assertTrue(data["missingScopes"]["post"])

        broken = json.loads(json.dumps(ALL_FREE))
        broken["patterns"]["毎日"][0]["end"] = "23:00"
        status, data = self.save(schedule_base=json.dumps(broken))
        self.assertEqual(status, 400)
        self.assertIn("24:00", data["error"])

        status, data = self.save()
        self.assertEqual(status, 200)
        with patch.object(server, "oauth_call", side_effect=self.bsky):
            status, data = invoke("do_GET", "/api/characters/1/automation")
        self.assertTrue(data["settings"]["auto_reply"])
        self.assertEqual(data["settings"]["extra_persona"], "語尾は〜だよ")

    def test_scope_tokens_are_checked(self):
        granted = " ".join(automation.REQUIRED_SCOPES["reply"] + automation.REQUIRED_SCOPES["post"])
        self.assertEqual(automation.missing_scopes(granted), {"reply": [], "post": []})
        self.assertEqual(automation.missing_scopes("atproto")["post"], ["repo:app.bsky.feed.post?action=create"])

    def test_auto_reply_answers_game_players_but_leaves_real_turns_to_the_game(self):
        self.save()
        real_did = "did:plc:realturn2345"
        with server.database() as db:
            for player in (PLAYER_DID, real_did):
                db.execute("INSERT INTO character_games(visitor,did,character_id,handle,profile_context,updated_at,session) VALUES(?,?,?,?,?,?,?)",
                           (VISITOR, player, 1, "player.test", "ctx", 1, "s"))
            # ReAl is still answering this player's message.
            db.execute("""INSERT INTO dm_turns(visitor,did,character_id,game_session,client_message_id,message_hash,status,user_dm_id,created_at)
                          VALUES(?,?,1,'s','c1','h','sending_reply','real-0',1)""", (VISITOR, real_did))
        # A game player writing from the Bluesky app still gets an answer.
        self.bsky.add_convo("game", PLAYER_DID, "player.test", [(PLAYER_DID, "Blueskyアプリから")])
        self.bsky.add_convo("real", real_did, "real.test", [(real_did, "ReAlから送った")])
        self.bsky.add_convo("stranger", STRANGER_DID, "stranger.test", [(STRANGER_DID, "こんにちは"), (CHAR_DID, "やあ"), (STRANGER_DID, "元気？")])
        self.bsky.add_convo("answered", "did:plc:answered2345", "done.test", [("did:plc:answered2345", "おはよ"), (CHAR_DID, "おはよう")])
        prompts = []

        def ai(messages, json_mode=False, temperature=0.75, model=None, timeout=120):
            prompts.append(messages)
            return schedule_reply() if json_mode else "元気だよ、ありがとう"

        with patch.object(server, "oauth_call", side_effect=self.bsky), patch.object(server, "call_ai", side_effect=ai):
            server.RUNNER.tick()  # First tick reads the newest cursor and runs the initial full check.
        self.assertEqual([item["convoId"] for item in self.bsky.sent], ["game", "stranger"])
        dm_prompt = prompts[-1]
        self.assertIn("語尾は〜だよ", dm_prompt[0]["content"])
        self.assertIn("のんびりする", dm_prompt[0]["content"])  # Event times are random, so check the plan.
        self.assertEqual([item["role"] for item in dm_prompt[1:]], ["user", "assistant", "user"])
        today = server.RUNNER.load_day(1, datetime.date.today())
        self.assertEqual([item["handle"] for item in today["dm_log"]], ["player.test", "stranger.test"])
        self.assertNotIn("text", today["dm_log"][0])

    def test_messages_sent_from_real_are_recognised(self):
        with server.database() as db:
            db.execute("INSERT INTO character_games(visitor,did,character_id,handle,profile_context,updated_at,session) VALUES(?,?,1,'p','c',1,'s')",
                       (VISITOR, PLAYER_DID))
            db.execute("""INSERT INTO dm_turns(visitor,did,character_id,game_session,client_message_id,message_hash,status,user_dm_id,created_at)
                          VALUES(?,?,1,'s','c1','h','reply_sent','real-msg',1)""", (VISITOR, PLAYER_DID))
            self.assertTrue(server.real_turn_active(db, 1, PLAYER_DID, "real-msg"))
            self.assertFalse(server.real_turn_active(db, 1, PLAYER_DID, "app-msg"))

    def test_new_dm_triggers_reply_only_while_free(self):
        busy = {"week": ALL_FREE["week"], "patterns": {"毎日": [{"start": "00:00", "end": "24:00", "activity": "仕事", "status": "busy"}]}}
        self.save(schedule_base=json.dumps(busy, ensure_ascii=False))
        self.bsky.add_convo("stranger", STRANGER_DID, "stranger.test", [(STRANGER_DID, "いる？")])
        ai = lambda messages, json_mode=False, temperature=0.75, model=None, timeout=120: json.dumps(
            {"plans": {"00:00〜24:00 仕事": "資料作り"}, "events": [{"slot": "00:00〜24:00 仕事", "text": "コピー機が詰まった"}]}) if json_mode else "あとでね"
        with patch.object(server, "oauth_call", side_effect=self.bsky), patch.object(server, "call_ai", side_effect=ai):
            server.RUNNER.tick()
            self.bsky.logs = [{"$type": "chat.bsky.convo.defs#logCreateMessage", "message": {"sender": {"did": STRANGER_DID}}}]
            server.RUNNER.tick()
        self.assertEqual(self.bsky.sent, [])
        self.assertEqual(server.RUNNER.status[1]["currentStatus"], "busy")

    def test_post_due_posts_latest_and_skips_stale_times(self):
        self.save(auto_reply=False, auto_post=True)
        now = datetime.datetime.combine(datetime.date.today(), datetime.time(12, 0))
        day = {"date": now.date().isoformat(), "label": "x", "pattern": "毎日",
               "blocks": [{"start": "00:00", "end": "24:00", "activity": "自由", "status": "free", "detail": "のんびり"}],
               "events": [], "post_times": ["09:00", "11:50", "15:00"], "post_log": [], "dm_log": []}
        server.RUNNER.save_day(1, day)
        with server.database() as db:
            target = server.automation_target(db, 1, VISITOR)
        with patch.object(server, "oauth_call", side_effect=self.bsky), \
             patch.object(server, "call_ai", return_value="お昼はオムライス #ランチ"):
            server.RUNNER.post_due(target, now)
            server.RUNNER.post_due(target, now)  # Already logged: no second post.
        self.assertEqual([item["text"] for item in self.bsky.posts], ["お昼はオムライス #ランチ"])
        log = server.RUNNER.load_day(1, now.date())["post_log"]
        self.assertEqual(sorted((item["time"], item["status"]) for item in log), [("09:00", "missed"), ("11:50", "posted")])
        with server.database() as db:
            recent = json.loads(db.execute("SELECT recent_posts FROM character_automation WHERE character_id=1").fetchone()[0])
        self.assertEqual(recent, ["お昼はオムライス #ランチ"])

    def test_manual_post_endpoint(self):
        self.save(auto_reply=False)
        with patch.object(server, "oauth_call", side_effect=self.bsky), patch.object(server, "call_ai", return_value=schedule_reply()):
            status, data = invoke("do_POST", "/api/characters/1/automation/post", {"text": "テスト投稿"})
        self.assertEqual(status, 200)
        self.assertEqual(data["record"]["status"], "manual")
        self.assertEqual(self.bsky.posts[0]["did"], CHAR_DID)
        status, data = invoke("do_POST", "/api/characters/1/automation/post", {"text": "x"}, visitor=OTHER_VISITOR)
        self.assertEqual(status, 401)

    def test_schedule_generation_picks_post_times_in_free_blocks(self):
        base = automation.parse_schedule_base(json.dumps(automation.DEFAULT_SCHEDULE))
        name = base["week"]["月"]
        keys = [f"{b['start']}〜{b['end']} {b['activity']}" for b in base["patterns"][name] if b["status"] != "sleep"]
        reply = json.dumps({"plans": {key: f"10:00 予定{i}" for i, key in enumerate(keys)},
                            "events": [{"slot": keys[0], "text": "傘を忘れた"}]})
        monday = datetime.date(2026, 10, 19)
        day = automation.generate_day(lambda *args: reply, {"name": "n", "profile": "p"}, {}, base, monday, [])
        self.assertEqual(len(day["post_times"]), 3)
        free = [b for b in day["blocks"] if b["status"] == "free"]
        for t in day["post_times"]:
            self.assertTrue(any(b["start"] <= t < b["end"] for b in free))
        self.assertEqual(day["blocks"][1]["detail"], "予定0")  # Echoed times are stripped.

    def test_oauth_callback_records_granted_scope(self):
        with patch.object(server, "oauth_call", return_value={"url": "https://example.com/authorize"}):
            invoke("do_POST", "/api/oauth/start", {"role": "character", "characterId": 1})
        with server.database() as db:
            state = db.execute("SELECT state FROM oauth_flows").fetchone()["state"]
        with patch.object(server, "oauth_call", return_value={"did": CHAR_DID, "state": state, "scope": "atproto repo:app.bsky.feed.post?action=create"}):
            status, _ = invoke("do_POST", "/api/oauth/finish", {"query": f"state={state}&code=x"})
        self.assertEqual(status, 200)
        with server.database() as db:
            self.assertIn("repo:app.bsky.feed.post", db.execute("SELECT oauth_scope FROM characters WHERE id=1").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
