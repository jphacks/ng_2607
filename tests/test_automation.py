import base64
import datetime
import json
import tempfile
import time
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
        self.stories = []
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
        if op == "convoWithMember":
            convo = next((c for c in self.convos if any(m["did"] == command["memberDid"] for m in c["members"])), None)
            if convo is None:
                self.add_convo(f"new-{command['memberDid']}", command["memberDid"], "new.test", [])
                convo = self.convos[-1]
            return {"convo": convo}
        if op == "createStory":
            self.stories.append(command)
            return {"uri": f"at://{CHAR_DID}/app.bsky.feed.post/s{len(self.stories)}", "cid": "cid"}
        if op == "scope":
            return {"scope": "atproto"}
        raise AssertionError(op)

    def add_convo(self, convo_id, partner_did, handle, texts):
        self.convos.append({"id": convo_id, "status": "accepted", "muted": False,
                            "members": [{"did": CHAR_DID}, {"did": partner_did, "handle": handle}],
                            "lastMessage": {"sender": {"did": texts[-1][0]}, "text": texts[-1][1]} if texts else None})
        self.history[convo_id] = [{"id": f"{convo_id}-{i}", "sender": {"did": did}, "text": text} for i, (did, text) in enumerate(texts)]


class AutomationTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.patches = [patch.object(server, "DATA", Path(self.folder.name)),
                        patch.object(server, "DB_PATH", Path(self.folder.name) / "game.sqlite3")]
        self.patches.append(patch.object(server, "character_posts", return_value=[]))
        self.patches.append(patch.object(server, "BASE_IMAGE_DIR", Path(self.folder.name) / "base_images"))
        for item in self.patches:
            item.start()
        server.init_db()
        server.RUNNER.state.clear()
        server.RUNNER.status.clear()
        server.RUNNER.story_previews.clear()
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
        self.assertEqual(automation.missing_scopes(granted), {"reply": [], "post": [], "story": ["blob:image/*"]})
        self.assertEqual(automation.missing_scopes("atproto")["post"], ["repo:app.bsky.feed.post?action=create"])

    def test_reach_out_conditions_are_saved_normalized_and_owner_only(self):
        defaults = automation.settings_from_row(None)
        self.assertEqual(defaults["reach_out_mode"], "close")
        self.assertEqual(defaults["reach_out_hashtag"], "結城めもり")
        settings = dict(auto_reach_out=True, reach_out_mode="hashtag", reach_out_hashtag=" ＃結城めもり ")
        status, _ = invoke("do_POST", "/api/characters/1/automation", settings, visitor=OTHER_VISITOR)
        self.assertEqual(status, 401)
        status, data = self.save(**settings)
        self.assertEqual(status, 200)
        self.assertEqual(data["settings"]["reach_out_mode"], "hashtag")
        self.assertEqual(data["settings"]["reach_out_hashtag"], "結城めもり")
        with patch.object(server, "oauth_call", side_effect=self.bsky):
            status, data = invoke("do_GET", "/api/characters/1/automation")
        self.assertEqual(status, 200)
        self.assertEqual(data["settings"]["reach_out_hashtag"], "結城めもり")
        target = server.RUNNER.targets()[0]
        self.assertEqual(target["reach_out_mode"], "hashtag")
        self.assertEqual(target["reach_out_hashtag"], "結城めもり")

    def test_reach_out_conditions_reject_invalid_values_without_overwriting(self):
        status, _ = self.save(auto_reach_out=True, reach_out_mode="hashtag", reach_out_hashtag="#結城めもり")
        self.assertEqual(status, 200)
        invalid = [dict(reach_out_mode="everyone", reach_out_hashtag="結城めもり")]
        invalid.extend(dict(reach_out_mode="hashtag", reach_out_hashtag=value)
                       for value in ("", "#", "two tags", "memori#extra", "a" * 65))
        for settings in invalid:
            with self.subTest(settings=settings):
                status, _ = self.save(**settings)
                self.assertEqual(status, 400)
        with server.database() as db:
            target = server.automation_target(db, 1, VISITOR)
        self.assertEqual((target["reach_out_mode"], target["reach_out_hashtag"]), ("hashtag", "結城めもり"))

    def test_close_reach_out_accepts_empty_disabled_hashtag_and_keeps_saved_tag(self):
        status, data = self.save(reach_out_mode="close", reach_out_hashtag="")
        self.assertEqual(status, 200)
        self.assertEqual(data["settings"]["reach_out_hashtag"], "結城めもり")
        status, _ = self.save(reach_out_mode="hashtag", reach_out_hashtag="#めもりとおでかけ")
        self.assertEqual(status, 200)
        status, data = self.save(reach_out_mode="close", reach_out_hashtag="")
        self.assertEqual(status, 200)
        self.assertEqual(data["settings"]["reach_out_hashtag"], "めもりとおでかけ")

    def test_reach_out_cooldown_setting_round_trips_and_old_clients_preserve_it(self):
        self.assertTrue(automation.settings_from_row(None)["reach_out_cooldown_enabled"])
        status, _ = invoke("do_POST", "/api/characters/1/automation",
                           {"reach_out_cooldown_enabled": False}, visitor=OTHER_VISITOR)
        self.assertEqual(status, 401)
        status, data = self.save(auto_reach_out=True, reach_out_cooldown_enabled=False)
        self.assertEqual(status, 200)
        self.assertIs(data["settings"]["reach_out_cooldown_enabled"], False)
        with patch.object(server, "oauth_call", side_effect=self.bsky):
            status, data = invoke("do_GET", "/api/characters/1/automation")
        self.assertEqual(status, 200)
        self.assertIs(data["settings"]["reach_out_cooldown_enabled"], False)
        self.assertIs(server.RUNNER.targets()[0]["reach_out_cooldown_enabled"], False)
        status, data = self.save(auto_reach_out=True)  # An older UI omits the new field.
        self.assertEqual(status, 200)
        self.assertIs(data["settings"]["reach_out_cooldown_enabled"], False)
        status, data = self.save(auto_reach_out=True, reach_out_cooldown_enabled=True)
        self.assertEqual(status, 200)
        self.assertIs(data["settings"]["reach_out_cooldown_enabled"], True)

    def test_reach_out_cooldown_setting_rejects_non_booleans_without_overwriting(self):
        status, _ = self.save(reach_out_cooldown_enabled=False)
        self.assertEqual(status, 200)
        for value in ("false", 0, None):
            with self.subTest(value=value):
                status, _ = self.save(reach_out_cooldown_enabled=value)
                self.assertEqual(status, 400)
                with server.database() as db:
                    target = server.automation_target(db, 1, VISITOR)
                self.assertIs(target["reach_out_cooldown_enabled"], False)

    def test_reach_out_reply_wait_setting_round_trips_preserves_and_validates(self):
        self.assertTrue(automation.settings_from_row(None)["reach_out_wait_for_reply"])
        status, data = self.save(auto_reach_out=True, reach_out_wait_for_reply=False)
        self.assertEqual(status, 200)
        self.assertIs(data["settings"]["reach_out_wait_for_reply"], False)
        with patch.object(server, "oauth_call", side_effect=self.bsky):
            status, data = invoke("do_GET", "/api/characters/1/automation")
        self.assertEqual(status, 200)
        self.assertIs(data["settings"]["reach_out_wait_for_reply"], False)
        self.assertIs(server.RUNNER.targets()[0]["reach_out_wait_for_reply"], False)
        status, data = self.save(auto_reach_out=True)
        self.assertEqual(status, 200)
        self.assertIs(data["settings"]["reach_out_wait_for_reply"], False)
        for value in ("false", 0, None):
            with self.subTest(value=value):
                status, _ = self.save(reach_out_wait_for_reply=value)
                self.assertEqual(status, 400)
                with server.database() as db:
                    target = server.automation_target(db, 1, VISITOR)
                self.assertIs(target["reach_out_wait_for_reply"], False)

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

    def test_auto_reply_judges_a_confession_at_the_last_stage(self):
        self.save(require_unlock=False)
        self.story_day(datetime.datetime.now())
        with server.database() as db:
            server.edit_relationship(db, 1, STRANGER_DID, "stranger.test", {"affection": 90, "trust": 85, "romance": 80}, True, [])
        self.bsky.add_convo("c1", STRANGER_DID, "stranger.test",
                            [(STRANGER_DID, "今日も楽しかった"), (CHAR_DID, "わたしも！"), (STRANGER_DID, "好きです。付き合ってください")])
        judged = []

        def ai(messages, json_mode=False, temperature=0.75, model=None, timeout=120):
            system = messages[0]["content"]
            if "評価係" in system:
                return json.dumps({"evaluations": [{"condition": "confess_sincerely", "score": 1.0, "evidence": "好きです"}],
                                   "reason": "告白", "memories": []}, ensure_ascii=False)
            if "告白判定係" in system:
                judged.append(messages[1]["content"])
                return json.dumps({"clear": True, "accept": True, "reason": "好感度が高い"}, ensure_ascii=False)
            return "うれしい。よろしくね"
        with patch.object(server, "oauth_call", side_effect=self.bsky), patch.object(server, "call_ai", side_effect=ai):
            with server.database() as db:
                target = server.automation_target(db, 1, VISITOR)
            server.RUNNER.reply_all(target, server.RUNNER.load_day(1, datetime.date.today()))
        self.assertEqual(len(judged), 1)
        self.assertIn("プレイヤー: 今日も楽しかった\nキャラクター: わたしも！", judged[0])  # Speakers are not swapped.
        self.assertIn("好きです。付き合ってください", judged[0])
        with server.database() as db:
            self.assertTrue(server.relationship_state(db, 1, STRANGER_DID)["lover"])

    def test_auto_reply_ignores_dms_before_a_context_reset(self):
        self.save(require_unlock=False)
        self.story_day(datetime.datetime.now())
        self.bsky.add_convo("c1", STRANGER_DID, "stranger.test", [(STRANGER_DID, "前に振られた話"), (STRANGER_DID, "新しい話")])
        self.bsky.history["c1"][0]["sentAt"] = "2026-10-20T00:00:00Z"
        self.bsky.history["c1"][1]["sentAt"] = "2999-01-01T00:00:00Z"
        with server.database() as db:
            server.reset_context(db, 1, STRANGER_DID)
        seen = []

        def ai(messages, json_mode=False, temperature=0.75, model=None, timeout=120):
            seen.append("\n".join(str(m["content"]) for m in messages))
            if "評価係" in messages[0]["content"]:
                return json.dumps({"evaluations": [], "reason": "なし", "memories": []})
            return "うんうん"
        with patch.object(server, "oauth_call", side_effect=self.bsky), patch.object(server, "call_ai", side_effect=ai):
            with server.database() as db:
                target = server.automation_target(db, 1, VISITOR)
            server.RUNNER.reply_all(target, server.RUNNER.load_day(1, datetime.date.today()))
        self.assertEqual(len(self.bsky.sent), 1)
        self.assertTrue(any("新しい話" in text for text in seen))
        self.assertFalse(any("前に振られた話" in text for text in seen))

    def reach_out_setup(self, axes, posts):
        self.save(require_unlock=False, auto_reach_out=True)
        self.story_day(datetime.datetime.now())
        with server.database() as db:
            server.edit_relationship(db, 1, STRANGER_DID, "stranger.test", axes, True, [])
        now = time.time()
        feed = [{"uri": f"at://stranger/post/{i}", "date": "x", "text": text, "story": False, "createdAt": now - age}
                for i, (text, age) in enumerate(posts)]
        return patch.object(server, "character_posts", side_effect=lambda did, **kwargs: feed if did == STRANGER_DID else [])

    def reach_ai(self, prompts):
        def ai(messages, json_mode=False, temperature=0.75, model=None, timeout=120):
            prompts.append(messages[0]["content"])
            return "その猫かわいい！名前あるの？"
        return ai

    def test_reach_out_talks_about_a_recent_post_once_a_day(self):
        posts = self.reach_out_setup({"affection": 60, "trust": 50, "romance": 40},
                                     [("昨日の旅行の写真", 4 * 24 * 3600), ("猫を拾った", 3600), ("", 60)])
        prompts = []
        with posts, patch.object(server, "oauth_call", side_effect=self.bsky), patch.object(server, "call_ai", side_effect=self.reach_ai(prompts)):
            with server.database() as db:
                target = server.automation_target(db, 1, VISITOR)
            record = server.RUNNER.reach_out(target)
            self.assertIsNone(server.RUNNER.reach_out(target))  # Once a day per person.
        self.assertEqual((record["handle"], record["post"]), ("stranger.test", "at://stranger/post/1"))  # Newest post with text within 3 days.
        self.assertEqual([item["text"] for item in self.bsky.sent], ["その猫かわいい！名前あるの？"])
        self.assertIn("猫を拾った", prompts[0])
        self.assertNotIn("昨日の旅行の写真", prompts[0])
        self.assertIn("「なかよし」", prompts[0])  # Talks in the current stage's manner.
        log = server.RUNNER.load_day(1, datetime.date.today())["dm_log"]
        self.assertTrue(log[-1]["reachOut"])

    def test_reach_out_only_for_close_people_and_no_double_texting(self):
        posts = self.reach_out_setup({"affection": 40, "trust": 30, "romance": 10}, [("猫を拾った", 3600)])  # 友達 stage.
        with posts, patch.object(server, "oauth_call", side_effect=self.bsky), patch.object(server, "call_ai", side_effect=self.reach_ai([])):
            with server.database() as db:
                target = server.automation_target(db, 1, VISITOR)
                self.assertEqual(server.reach_out_candidates(db, 1), [])
                server.edit_relationship(db, 1, STRANGER_DID, "stranger.test", {"affection": 10, "trust": 10, "romance": 10}, True, [], True)
                self.assertEqual(len(server.reach_out_candidates(db, 1)), 1)  # Lovers always qualify.
            self.bsky.add_convo("c1", STRANGER_DID, "stranger.test", [(STRANGER_DID, "またね"), (CHAR_DID, "またね！")])
            self.assertIsNone(server.RUNNER.reach_out(target))  # The character spoke last: wait for an answer.
            status, data = invoke("do_POST", "/api/characters/1/relationship/reach-out", {"did": STRANGER_DID})
        self.assertEqual(status, 200)  # The admin test button sends anyway.
        self.assertEqual(len(self.bsky.sent), 1)
        self.assertTrue(data["relationships"][0]["lastReachOutAt"])

    def test_hashtag_reach_out_ignores_affinity_and_selects_exact_tag(self):
        posts = self.reach_out_setup({"affection": 5, "trust": 0, "romance": 0},
                                    [("古い写真 #結城めもり", 4 * 24 * 3600),
                                     ("猫を拾った！ #結城めもり", 3600),
                                     ("別のタグ #結城めもり推し", 1800),
                                     ("結城めもりという名前を見た", 1200),
                                     ("#別のタグ", 60)])
        self.save(auto_reach_out=True, reach_out_mode="hashtag", reach_out_hashtag="#結城めもり")
        self.bsky.add_convo("c1", STRANGER_DID, "stranger.test", [(STRANGER_DID, "こんにちは")])
        prompts = []
        with posts, patch.object(server, "oauth_call", side_effect=self.bsky), \
             patch.object(server, "call_ai", side_effect=self.reach_ai(prompts)):
            with server.database() as db:
                target = server.automation_target(db, 1, VISITOR)
            record = server.RUNNER.reach_out(target)
        self.assertIsNotNone(record)
        self.assertEqual(record["post"], "at://stranger/post/1")
        self.assertEqual([item["convoId"] for item in self.bsky.sent], ["c1"])
        self.assertIn("猫を拾った！ #結城めもり", prompts[0])
        self.assertNotIn("#結城めもり推し", prompts[0])
        self.assertNotIn("古い写真", prompts[0])

    def test_hashtag_matches_bluesky_metadata_and_complete_written_tags(self):
        posts = [
            {"text": "猫の写真", "tags": ["結城めもり"]},
            {"text": "猫の写真", "facets": [{"features": [
                {"$type": "app.bsky.richtext.facet#tag", "tag": "結城めもり"}]}]},
            {"text": "猫の写真 ＃結城めもり！"},
            {"text": "#結城めもり"},
        ]
        for post in posts:
            with self.subTest(post=post):
                self.assertTrue(automation.post_hashtag_matches(post, "結城めもり"))
        for text in ("結城めもり", "#結城めもり推し", "#別の結城めもり", "#別のタグ"):
            with self.subTest(text=text):
                self.assertFalse(automation.post_hashtag_matches({"text": text}, "結城めもり"))

    def test_hashtag_reach_out_includes_previous_dm_partner_without_relationship(self):
        self.save(auto_reply=False, auto_reach_out=True, reach_out_mode="hashtag", reach_out_hashtag="結城めもり")
        self.story_day(datetime.datetime.now())
        self.bsky.add_convo("previous", STRANGER_DID, "stranger.test", [(STRANGER_DID, "こんにちは")])
        feed = [{"uri": "at://stranger/post/tagged", "date": "today", "text": "猫かわいい #結城めもり",
                 "createdAt": time.time(), "story": False}]
        with server.database() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM dm_relationships WHERE partner_did=?", (STRANGER_DID,)).fetchone())
        with patch.object(server, "character_posts", return_value=feed), \
             patch.object(server, "oauth_call", side_effect=self.bsky), \
             patch.object(server, "call_ai", side_effect=self.reach_ai([])):
            server.RUNNER.tick()
        self.assertEqual([item["convoId"] for item in self.bsky.sent], ["previous"])

    def test_hashtag_reach_out_does_not_message_unknown_or_empty_conversations(self):
        self.save(auto_reply=False, auto_reach_out=True, reach_out_mode="hashtag", reach_out_hashtag="結城めもり")
        self.story_day(datetime.datetime.now())
        self.bsky.add_convo("empty", STRANGER_DID, "stranger.test", [])
        feed = [{"uri": "at://stranger/post/tagged", "date": "today", "text": "#結城めもり",
                 "createdAt": time.time(), "story": False}]
        with patch.object(server, "character_posts", return_value=feed), \
             patch.object(server, "oauth_call", side_effect=self.bsky) as oauth, \
             patch.object(server, "call_ai", side_effect=self.reach_ai([])) as ai:
            with server.database() as db:
                target = server.automation_target(db, 1, VISITOR)
            self.assertIsNone(server.RUNNER.reach_out(target))
            self.assertIsNone(server.RUNNER.reach_out(target, partner_did=PLAYER_DID))
        self.assertEqual(self.bsky.sent, [])
        self.assertEqual(len(self.bsky.convos), 1)
        self.assertFalse(any(call.args[0]["op"] == "convoWithMember" for call in oauth.call_args_list))
        ai.assert_not_called()

    def test_hashtag_reach_out_checks_later_conversation_pages(self):
        self.save(auto_reply=False, auto_reach_out=True, reach_out_mode="hashtag", reach_out_hashtag="結城めもり")
        self.story_day(datetime.datetime.now())
        self.bsky.add_convo("second-page", STRANGER_DID, "stranger.test", [(STRANGER_DID, "こんにちは")])
        cursors = []

        def paginated(command):
            if command["op"] == "convos":
                cursors.append(command.get("cursor", ""))
                return {"convos": self.bsky.convos if command.get("cursor") else [],
                        "cursor": None if command.get("cursor") else "next"}
            return self.bsky(command)

        feed = [{"uri": "at://stranger/post/tagged", "date": "today", "text": "#結城めもり",
                 "createdAt": time.time(), "story": False}]
        with patch.object(server, "character_posts", return_value=feed), \
             patch.object(server, "oauth_call", side_effect=paginated), \
             patch.object(server, "call_ai", side_effect=self.reach_ai([])):
            with server.database() as db:
                target = server.automation_target(db, 1, VISITOR)
            record = server.RUNNER.reach_out(target)
        self.assertIsNotNone(record)
        self.assertEqual(cursors, ["", "next"])
        self.assertEqual([item["convoId"] for item in self.bsky.sent], ["second-page"])

    def test_hashtag_reach_out_skips_muted_pending_and_group_conversations(self):
        self.save(auto_reply=False, auto_reach_out=True, reach_out_mode="hashtag", reach_out_hashtag="結城めもり")
        self.story_day(datetime.datetime.now())
        for convo_id, did in (("muted", STRANGER_DID), ("pending", PLAYER_DID), ("group", "did:plc:group2345")):
            self.bsky.add_convo(convo_id, did, convo_id + ".test", [(did, "こんにちは")])
        self.bsky.convos[0]["muted"] = True
        self.bsky.convos[1]["status"] = "request"
        self.bsky.convos[2]["members"].append({"did": "did:plc:another2345"})
        feed = [{"uri": "at://stranger/post/tagged", "date": "today", "text": "#結城めもり",
                 "createdAt": time.time(), "story": False}]
        with patch.object(server, "character_posts", return_value=feed), \
             patch.object(server, "oauth_call", side_effect=self.bsky), \
             patch.object(server, "call_ai", side_effect=self.reach_ai([])) as ai:
            with server.database() as db:
                target = server.automation_target(db, 1, VISITOR)
            self.assertIsNone(server.RUNNER.reach_out(target))
        self.assertEqual(self.bsky.sent, [])
        ai.assert_not_called()

    def test_hashtag_reach_out_keeps_cooldown_duplicate_and_reply_wait_guards(self):
        posts = self.reach_out_setup({"affection": 5, "trust": 0, "romance": 0}, [("猫 #結城めもり", 60)])
        self.save(auto_reply=False, auto_reach_out=True, reach_out_mode="hashtag", reach_out_hashtag="結城めもり")
        self.bsky.add_convo("c1", STRANGER_DID, "stranger.test", [(STRANGER_DID, "こんにちは")])
        with posts, patch.object(server, "oauth_call", side_effect=self.bsky), \
             patch.object(server, "call_ai", side_effect=self.reach_ai([])):
            with server.database() as db:
                target = server.automation_target(db, 1, VISITOR)
            self.assertIsNotNone(server.RUNNER.reach_out(target))
            self.assertIsNone(server.RUNNER.reach_out(target))  # Same person within 24 hours.
            with server.database() as db:
                db.execute("UPDATE dm_reach_outs SET sent_at=?", (time.time() - 25 * 3600,))
            self.assertIsNone(server.RUNNER.reach_out(target))  # Same post even after the cooldown.
            with server.database() as db:
                db.execute("DELETE FROM dm_reach_outs")
            self.bsky.add_convo("c1", STRANGER_DID, "stranger.test",
                                [(STRANGER_DID, "こんにちは"), (CHAR_DID, "またね")])
            self.assertIsNone(server.RUNNER.reach_out(target))  # Waiting for the partner's answer.
        self.assertEqual(len(self.bsky.sent), 1)

    def test_hashtag_reach_out_does_not_run_while_busy(self):
        self.save(auto_reply=False, auto_reach_out=True, reach_out_mode="hashtag", reach_out_hashtag="結城めもり")
        self.story_day(datetime.datetime.now())
        today = server.RUNNER.load_day(1, datetime.date.today())
        today["blocks"][0]["status"] = "busy"
        server.RUNNER.save_day(1, today)
        self.bsky.add_convo("c1", STRANGER_DID, "stranger.test", [(STRANGER_DID, "こんにちは")])
        with patch.object(server, "oauth_call", side_effect=self.bsky), \
             patch.object(server.RUNNER, "reach_out") as reach:
            server.RUNNER.tick()
        reach.assert_not_called()

    def test_disabling_cooldown_allows_another_post_today_but_never_repeats_a_post(self):
        self.save(auto_reply=False, auto_reach_out=True, reach_out_mode="hashtag",
                  reach_out_hashtag="結城めもり", reach_out_cooldown_enabled=False)
        self.story_day(datetime.datetime.now())
        self.bsky.add_convo("c1", STRANGER_DID, "stranger.test", [(STRANGER_DID, "こんにちは")])
        feed = [{"uri": "at://stranger/post/one", "date": "today", "text": "猫 #結城めもり",
                 "createdAt": time.time() - 60}]
        with patch.object(server, "character_posts", return_value=feed), \
             patch.object(server, "oauth_call", side_effect=self.bsky), \
             patch.object(server, "call_ai", side_effect=self.reach_ai([])):
            with server.database() as db:
                target = server.automation_target(db, 1, VISITOR)
            self.assertEqual(server.RUNNER.reach_out(target)["post"], "at://stranger/post/one")
            self.assertIsNone(server.RUNNER.reach_out(target))  # The first post stays used.
            feed.append({"uri": "at://stranger/post/two", "date": "today", "text": "お花 #結城めもり",
                         "createdAt": time.time() - 30})
            # A reply arrived before the new tagged post, so the reply-wait guard also permits a message.
            self.bsky.add_convo("c1", STRANGER_DID, "stranger.test",
                                [(CHAR_DID, "気をつけて帰ってね"), (STRANGER_DID, "ありがとう")])
            self.assertEqual(server.RUNNER.reach_out(target)["post"], "at://stranger/post/two")
            self.assertIsNone(server.RUNNER.reach_out(target))
            status, _ = self.save(auto_reply=False, auto_reach_out=True, reach_out_cooldown_enabled=True)
            self.assertEqual(status, 200)
            with server.database() as db:
                target = server.automation_target(db, 1, VISITOR)
            feed.append({"uri": "at://stranger/post/three", "date": "today", "text": "空 #結城めもり",
                         "createdAt": time.time()})
            self.assertIsNone(server.RUNNER.reach_out(target))  # Re-enabling restores the 24-hour limit.
        self.assertEqual(len(self.bsky.sent), 2)

    def test_disabling_cooldown_keeps_reply_wait_and_busy_guards(self):
        self.save(auto_reply=False, auto_reach_out=True, reach_out_mode="hashtag",
                  reach_out_hashtag="結城めもり", reach_out_cooldown_enabled=False)
        self.story_day(datetime.datetime.now())
        self.bsky.add_convo("c1", STRANGER_DID, "stranger.test",
                            [(STRANGER_DID, "こんにちは"), (CHAR_DID, "またね")])
        feed = [{"uri": "at://stranger/post/new", "date": "today", "text": "猫 #結城めもり",
                 "createdAt": time.time()}]
        with patch.object(server, "character_posts", return_value=feed), \
             patch.object(server, "oauth_call", side_effect=self.bsky), \
             patch.object(server, "call_ai", side_effect=self.reach_ai([])) as ai:
            with server.database() as db:
                target = server.automation_target(db, 1, VISITOR)
            self.assertIsNone(server.RUNNER.reach_out(target))
        self.assertEqual(self.bsky.sent, [])
        ai.assert_not_called()
        self.save(auto_reply=False, auto_reach_out=True, reach_out_wait_for_reply=False)
        today = server.RUNNER.load_day(1, datetime.date.today())
        today["blocks"][0]["status"] = "busy"
        server.RUNNER.save_day(1, today)
        with patch.object(server, "oauth_call", side_effect=self.bsky), \
             patch.object(server.RUNNER, "reach_out") as reach:
            server.RUNNER.tick()
        reach.assert_not_called()

    def test_disabling_cooldown_and_reply_wait_reacts_to_each_new_post_after_own_message(self):
        self.save(auto_reply=False, auto_reach_out=True, reach_out_mode="hashtag",
                  reach_out_hashtag="結城めもり", reach_out_cooldown_enabled=False)
        self.story_day(datetime.datetime.now())
        self.bsky.add_convo("c1", STRANGER_DID, "stranger.test",
                            [(STRANGER_DID, "こんにちは"), (CHAR_DID, "またね")])
        feed = [{"uri": "at://stranger/post/one", "date": "today", "text": "猫 #結城めもり",
                 "createdAt": time.time() - 60}]
        with patch.object(server, "character_posts", return_value=feed), \
             patch.object(server, "oauth_call", side_effect=self.bsky), \
             patch.object(server, "call_ai", side_effect=self.reach_ai([])):
            with server.database() as db:
                target = server.automation_target(db, 1, VISITOR)
            self.assertIsNone(server.RUNNER.reach_out(target))  # Reply waiting is independently enabled.
            status, _ = self.save(auto_reply=False, auto_reach_out=True, reach_out_wait_for_reply=False)
            self.assertEqual(status, 200)
            with server.database() as db:
                target = server.automation_target(db, 1, VISITOR)
            self.assertEqual(server.RUNNER.reach_out(target)["post"], "at://stranger/post/one")
            self.assertIsNone(server.RUNNER.reach_out(target))  # The same post cannot trigger again.
            feed.append({"uri": "at://stranger/post/two", "date": "today", "text": "空 #結城めもり",
                         "createdAt": time.time() - 30})
            self.assertEqual(server.RUNNER.reach_out(target)["post"], "at://stranger/post/two")
            status, _ = self.save(auto_reply=False, auto_reach_out=True, reach_out_wait_for_reply=True)
            self.assertEqual(status, 200)
            with server.database() as db:
                target = server.automation_target(db, 1, VISITOR)
            self.assertFalse(target["reach_out_cooldown_enabled"])
            feed.append({"uri": "at://stranger/post/three", "date": "today", "text": "お花 #結城めもり",
                         "createdAt": time.time()})
            self.assertIsNone(server.RUNNER.reach_out(target))  # Restoring reply waiting works without cooldown.
        self.assertEqual(len(self.bsky.sent), 2)

    def test_post_due_posts_latest_and_skips_stale_times(self):
        self.save(auto_reply=False, auto_post=True, post_times="15:00, 09:00,11:50")
        now = datetime.datetime.combine(datetime.date.today(), datetime.time(12, 0))
        day = {"date": now.date().isoformat(), "label": "x", "pattern": "毎日",
               "blocks": [{"start": "00:00", "end": "24:00", "activity": "自由", "status": "free", "detail": "のんびり"}],
               "events": [], "post_log": [], "dm_log": []}
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

    def test_post_prompt_endpoint_shows_the_prompt_parts(self):
        self.save(auto_reply=False, post_prompt="猫の話をする")
        with patch.object(server, "call_ai", return_value=schedule_reply()) as ai:
            status, data = invoke("do_POST", "/api/characters/1/automation/prompt", {})
        self.assertEqual(status, 200)
        parts = {part["key"]: part["content"] for part in data["prompt"]}
        self.assertEqual(parts["topic"], "猫の話をする")
        self.assertIn("のんびりする", parts["schedule"])  # Today's plan reaches the prompt.
        self.assertIn("この時刻に合った投稿", parts["request"])
        self.assertEqual(ai.call_count, 1)  # Only today's schedule is generated; no post text.
        with patch.object(server, "call_ai", return_value="猫がのびをしていた"):
            status, data = invoke("do_POST", "/api/characters/1/automation/preview", {})
        self.assertEqual((status, data["text"]), (200, "猫がのびをしていた"))
        self.assertEqual(data["prompt"][-1]["key"], "request")
        status, _ = invoke("do_POST", "/api/characters/1/automation/prompt", {}, visitor=OTHER_VISITOR)
        self.assertEqual(status, 401)

    def test_post_messages_join_the_parts_like_the_persona(self):
        character, settings = {"name": "n", "profile": "p"}, {"extra_persona": "語尾は〜だよ", "recent_posts": ["前の投稿"]}
        now = datetime.datetime(2026, 10, 24, 14, 12)
        system, user = automation.post_messages(character, settings, ["事実"], now)
        expected = automation.persona(character, settings, automation.DEFAULT_POST_PROMPT, automation.POST_RULES,
                                      automation.facts_text(["事実"]), now=now)
        self.assertEqual(system["content"], expected)
        self.assertIn("- 前の投稿", user["content"])

    def test_post_and_story_times_are_fixed_settings(self):
        self.assertEqual(automation.parse_times("21:00、 08:00,08:00", "投稿時刻"), ["08:00", "21:00"])
        status, data = self.save(post_times="8:00")
        self.assertEqual(status, 400)
        self.assertIn("HH:MM", data["error"])
        status, data = self.save(post_times="", auto_story=True, story_times="20:00")
        self.assertEqual(status, 200)
        self.assertEqual((data["settings"]["post_times"], data["settings"]["story_times"]), ([], ["20:00"]))
        with server.database() as db:
            target = server.automation_target(db, 1, VISITOR)
        self.assertTrue(target["auto_story"])

    def story_day(self, now):
        server.RUNNER.save_day(1, {"date": now.date().isoformat(), "label": "x", "pattern": "毎日",
                                   "blocks": [{"start": "00:00", "end": "24:00", "activity": "自由", "status": "free", "detail": "公園を散歩"}],
                                   "events": [], "post_log": [], "story_log": [], "dm_log": []})

    def test_story_due_posts_an_image_with_the_story_tag(self):
        self.save(auto_reply=False, auto_story=True, story_times="11:50")
        now = datetime.datetime.combine(datetime.date.today(), datetime.time(12, 0))
        self.story_day(now)
        with server.database() as db:
            target = server.automation_target(db, 1, VISITOR)
        prompts = []

        def image(prompt, reference):
            prompts.append(prompt)
            self.assertIsNone(reference)  # No base image: a photo without the character.
            return b"\xff\xd8jpeg"
        story = json.dumps({"caption": "いい天気", "image_prompt": "木漏れ日の遊歩道"}, ensure_ascii=False)
        with patch.object(server, "oauth_call", side_effect=self.bsky), patch.object(server, "call_ai", return_value=story), \
             patch.object(server, "generate_image", side_effect=image):
            server.RUNNER.story_due(target, now)
            server.RUNNER.story_due(target, now)  # Already logged: no second story.
        self.assertEqual(len(self.bsky.stories), 1)
        sent = self.bsky.stories[0]
        self.assertEqual((sent["text"], sent["tag"], sent["mime"]), ("いい天気", "pinkleapStory", "image/jpeg"))
        self.assertEqual(base64.b64decode(sent["image"]), b"\xff\xd8jpeg")
        self.assertTrue(prompts[0].startswith("木漏れ日の遊歩道"))
        self.assertIn(automation.IMAGE_STYLE, prompts[0])
        log = server.RUNNER.load_day(1, now.date())["story_log"]
        self.assertEqual([(item["time"], item["status"]) for item in log], [("11:50", "posted")])

    def test_base_image_is_validated_and_used_as_the_reference(self):
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
        status, data = invoke("do_POST", "/api/characters/1/base-image", {"image": "data:image/png;base64," + base64.b64encode(b"GIF89a").decode()})
        self.assertEqual(status, 400)
        status, _ = invoke("do_POST", "/api/characters/1/base-image", {"image": "data:image/png;base64," + base64.b64encode(png).decode()})
        self.assertEqual(status, 200)
        self.assertEqual(server.base_image(1), (png, "image/png"))
        self.assertEqual(sorted(path.name for path in server.BASE_IMAGE_DIR.iterdir()), ["char.test.png"])  # Named after the handle.

        self.save(auto_reply=False)
        self.story_day(datetime.datetime.now())
        story = json.dumps({"caption": "作業中", "image_prompt": "カフェでノートパソコンを開くわたし"}, ensure_ascii=False)
        with patch.object(server, "call_ai", return_value=story), patch.object(server, "generate_image", return_value=b"img") as image:
            status, data = invoke("do_POST", "/api/characters/1/automation/story-preview", {})
        self.assertEqual(status, 200)
        prompt, reference = image.call_args.args
        self.assertEqual(reference, (png, "image/png"))
        self.assertIn(automation.IMAGE_STYLE_WITH_BASE, prompt)
        parts = {part["key"]: part for part in data["prompt"]}
        self.assertEqual(parts["rules"]["content"], automation.STORY_RULES_WITH_BASE)
        self.assertIn("ベース画像を参照", parts["image"]["label"])

        status, _ = invoke("do_POST", "/api/characters/1/base-image/delete", {})
        self.assertEqual(status, 200)
        self.assertIsNone(server.base_image(1))

    def test_base_image_can_be_dropped_into_the_folder(self):
        server.BASE_IMAGE_DIR.mkdir()
        jpeg = b"\xff\xd8\xff" + b"0" * 10
        (server.BASE_IMAGE_DIR / "char.test.jpg").write_bytes(jpeg)
        self.assertEqual(server.base_image(1), (jpeg, "image/jpeg"))
        (server.BASE_IMAGE_DIR / "char.test.jpg").write_bytes(b"not an image")
        self.assertIsNone(server.base_image(1))  # A broken file is ignored rather than sent.

    def test_story_image_prompt_fills_the_situation_from_the_schedule(self):
        template = "【画風】アニメ調\n【字幕】一言を入れる\n【今回のシチュエーション】\nおまかせ。"
        prompt = automation.image_prompt("カフェで作業", True, template, "カフェきた〜", ["窓辺の光"])
        self.assertTrue(prompt.startswith("【画風】アニメ調\n【字幕】一言を入れる\n【今回のシチュエーション】\nカフェで作業"))
        self.assertNotIn("おまかせ", prompt)
        self.assertIn("「カフェきた〜」", prompt)
        self.assertIn("- 窓辺の光", prompt)
        self.assertNotIn(automation.IMAGE_STYLE_WITH_BASE, prompt)  # The character's own style replaces the built-in one.
        self.assertTrue(automation.image_prompt("散歩", False, "【画風】水彩").endswith("【今回のシチュエーション】\n散歩\n予定の場面・時間帯に合わせて描く。"))

        status, data = self.save(auto_reply=False, story_image_prompt=template)
        self.assertEqual((status, data["settings"]["story_image_prompt"]), (200, template))
        now = datetime.datetime.now()
        self.story_day(now)
        server.RUNNER.append_log(1, now.date(), "story_log", [{"time": "09:00", "imagePrompt": "【画風】\n【今回のシチュエーション】\n朝の散歩\n予定の場面"}])
        story = json.dumps({"caption": "作業中", "image_prompt": "公園のベンチでスケッチ"}, ensure_ascii=False)
        with patch.object(server, "call_ai", return_value=story), patch.object(server, "generate_image", return_value=b"img") as image:
            status, data = invoke("do_POST", "/api/characters/1/automation/story-preview", {})
        self.assertEqual(status, 200)
        sent = image.call_args.args[0]
        self.assertIn("公園のベンチでスケッチ", sent)
        self.assertIn("- 朝の散歩", sent)  # Today's earlier scene, to vary the composition.
        self.assertIn("キャラのストーリー画像の指示", data["prompt"][-1]["label"])

    def test_story_preview_then_post_uses_the_edited_caption(self):
        self.save(auto_reply=False)
        self.story_day(datetime.datetime.now())
        story = json.dumps({"caption": "生成した一言", "image_prompt": "湯気の立つコーヒー"}, ensure_ascii=False)
        status, data = invoke("do_POST", "/api/characters/1/automation/story", {"caption": "x"})
        self.assertEqual(status, 400)  # Nothing generated yet.
        with patch.object(server, "call_ai", return_value=story), patch.object(server, "generate_image", return_value=b"img"):
            status, data = invoke("do_POST", "/api/characters/1/automation/story-preview", {})
        self.assertEqual(status, 200)
        self.assertEqual(data["image"], "data:image/jpeg;base64," + base64.b64encode(b"img").decode())
        self.assertEqual(data["prompt"][-1]["key"], "image")
        with patch.object(server, "oauth_call", side_effect=self.bsky):
            status, data = invoke("do_POST", "/api/characters/1/automation/story", {"caption": "直した一言"})
        self.assertEqual(status, 200)
        self.assertEqual(self.bsky.stories[0]["text"], "直した一言")
        self.assertEqual(data["record"]["status"], "manual")

    def test_dm_reply_knows_both_sides_posts(self):
        captured = []

        def ai(messages, json_mode=False, temperature=0.9):
            captured.append(messages)
            return "見てくれたの？"
        own = [{"date": "2026-10-24 12:00", "text": "プリンを作った", "story": False},
               {"date": "2026-10-24 20:00", "text": "", "story": True}]
        partner = [{"date": "2026-10-23 21:00", "text": "猫を拾った"}]
        posts = automation.posts_text(own, partner, "ハル")
        automation.generate_dm_reply(ai, {"name": "n", "profile": "p"}, {}, [(False, "プリンおいしそう")], "ハル",
                                     [], datetime.datetime(2026, 10, 24, 21, 0), posts=posts)
        system = captured[0][0]["content"]
        self.assertIn("プリンを作った", system)
        self.assertIn("[ストーリー] (画像のみ)", system)
        self.assertIn("ハル が最近 Bluesky に投稿したこと", system)
        self.assertIn("猫を拾った", system)
        self.assertEqual(automation.posts_text([], [], "ハル"), "")

    def test_relationship_can_be_edited_and_reset_by_the_owner(self):
        body = {"did": PLAYER_DID, "axes": {"affection": 80, "trust": 65.5, "romance": 40}, "unlocked": True,
                "memories": [{"kind": "promise", "text": "一緒に映画を見る"}]}
        status, _ = invoke("do_POST", "/api/characters/1/relationship", body, visitor=OTHER_VISITOR)
        self.assertEqual(status, 401)
        status, data = invoke("do_POST", "/api/characters/1/relationship", {**body, "axes": {"affection": 120, "trust": 0, "romance": 0}})
        self.assertEqual(status, 400)
        status, data = invoke("do_POST", "/api/characters/1/relationship", body)
        self.assertEqual(status, 200)
        edited = data["relationships"][0]
        self.assertEqual((edited["axes"], edited["unlocked"]), ({"affection": 80.0, "trust": 65.5, "romance": 40.0}, True))
        self.assertEqual(edited["memories"], [{"kind": "promise", "text": "一緒に映画を見る"}])
        with server.database() as db:
            state = server.relationship_state(db, 1, PLAYER_DID)
        self.assertEqual(state["scores"]["trust"], 65.5)  # The next message starts from the edited values.
        self.assertEqual(state["recent"], [])  # No fake evaluation in the repetition window.

        self.assertFalse(edited["lover"])
        status, data = invoke("do_POST", "/api/characters/1/relationship", {**body, "axes": {"affection": 10, "trust": 10, "romance": 10}, "lover": True})
        self.assertEqual((data["relationships"][0]["lover"], data["relationships"][0]["stage"]["name"]), (True, "恋人"))
        status, data = invoke("do_POST", "/api/characters/1/relationship", {**body, "unlocked": False, "memories": []})
        self.assertEqual((data["relationships"][0]["unlocked"], data["relationships"][0]["memories"]), (False, []))
        status, data = invoke("do_POST", "/api/characters/1/relationship/delete", {"did": PLAYER_DID})
        self.assertEqual((status, data["relationships"]), (200, []))
        status, data = invoke("do_POST", "/api/characters/1/relationship", {**body, "did": CHAR_DID})
        self.assertEqual(status, 400)

    def test_relationship_can_be_added_by_handle(self):
        with patch.object(server, "xrpc", return_value={"did": STRANGER_DID, "handle": "new.bsky.social"}):
            status, data = invoke("do_POST", "/api/characters/1/relationship",
                                  {"handle": "@new.bsky.social", "axes": dict(server.relationship.INITIAL), "unlocked": False})
        self.assertEqual(status, 200)
        self.assertEqual((data["relationships"][0]["did"], data["relationships"][0]["handle"]), (STRANGER_DID, "new.bsky.social"))

    def test_schedule_generation_fills_plans_and_events(self):
        base = automation.parse_schedule_base(json.dumps(automation.DEFAULT_SCHEDULE))
        name = base["week"]["月"]
        keys = [f"{b['start']}〜{b['end']} {b['activity']}" for b in base["patterns"][name] if b["status"] != "sleep"]
        reply = json.dumps({"plans": {key: f"10:00 予定{i}" for i, key in enumerate(keys)},
                            "events": [{"slot": keys[0], "text": "傘を忘れた"}]})
        monday = datetime.date(2026, 10, 19)
        day = automation.generate_day(lambda *args: reply, {"name": "n", "profile": "p"}, {}, base, monday, [])
        self.assertNotIn("post_times", day)  # Posting times are fixed in the settings now.
        self.assertEqual([event["text"] for event in day["events"]], ["傘を忘れた"])
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
