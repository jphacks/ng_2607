import json
import unittest
from unittest.mock import patch

import relationship as rel
import server
from test_server import CHAR_DID, DID, FakeDm, ServerFixture, fake_ai, invoke

START = dict(rel.INITIAL)


def evaluation(*items, reason="", memories=()):
    return rel.parse_evaluation(json.dumps({"evaluations": [
        {"condition": cid, "score": score, "evidence": "引用"} for cid, score in items], "reason": reason, "memories": list(memories)}))


class RelationshipMathTest(unittest.TestCase):
    def test_design_example_outputs_per_axis_change(self):
        # 「昨日プリンが売り切れだったって投稿してたよね。残念だったね。今度一緒に美味しいお店探さない？」
        result = rel.update(START, evaluation(("sns_reference", 1.0), ("remember_past", 1.0), ("comfort_worry", 0.8),
                                              ("care_condition", 0.8), ("date_proposal", 0.7)), [])
        self.assertEqual(result["delta"], {"affection": 3.0, "trust": 5.0, "romance": 0.7})
        self.assertEqual(result["after"], {"affection": 33.0, "trust": 25.0, "romance": 0.7})
        self.assertEqual(result["overallBefore"], 18)
        # Romance gate at A=30, T=20: 0.2 + 0.8 * 0.3 * 0.2 = 0.248, so 2.8 becomes 0.7.
        self.assertEqual(result["romanceGate"], 0.248)

    def test_romance_grows_freely_once_affection_and_trust_are_high(self):
        high = {"affection": 100.0, "trust": 100.0, "romance": 40.0}
        self.assertEqual(rel.compute(high, evaluation(("date_proposal", 1.0)), [])["delta"]["romance"], 4.0)
        # Losses are not softened by the gate.
        self.assertEqual(rel.compute(START, evaluation(("compare_others", 1.0)), [])["delta"]["romance"], -4.0)

    def test_repeated_actions_are_decayed(self):
        praise = evaluation(("praise_effort", 1.0))
        history = []
        deltas = []
        for _ in range(5):
            result = rel.compute(START, praise, history)
            deltas.append(result["delta"]["affection"])
            history.append(result["breakdown"])
        self.assertEqual(deltas, [3.0, 1.5, 0.6, 0.0, 0.0])
        # Once the praise leaves the window it counts as new again.
        self.assertEqual(rel.compute(START, praise, history[:1] + [[]] * rel.REPEAT_WINDOW)["delta"]["affection"], 3.0)

    def test_per_turn_cap_and_major_event_exception(self):
        many = evaluation(("sns_reference", 1.0), ("praise_effort", 1.0), ("interest_in_hobby", 1.0))
        self.assertEqual(rel.compute(START, many, [])["delta"]["affection"], 5.0)
        threat = evaluation(("threaten", 1.0), ("lie", 1.0))
        self.assertEqual(rel.compute(START, threat, [])["delta"]["trust"], -10.0)
        weak_threat = evaluation(("threaten", 0.5), ("lie", 1.0))
        self.assertEqual(rel.compute(START, weak_threat, [])["delta"]["trust"], -5.0)

    def test_scores_stay_within_zero_and_hundred(self):
        result = rel.update(START, evaluation(("threaten", 1.0)), [])
        self.assertEqual(result["after"]["trust"], 10.0)
        self.assertEqual(rel.update({"affection": 99.0, "trust": 50.0, "romance": 0.0}, evaluation(("praise_effort", 1.0)), [])["after"]["affection"], 100.0)

    def test_invalid_model_output_is_rejected(self):
        parsed = rel.parse_evaluation(json.dumps({"evaluations": [
            {"condition": "made_up", "score": 1.0}, {"condition": "lie", "score": 3},
            {"condition": "praise_effort", "score": "1"}, {"condition": "active_question", "score": 0.5, "evidence": "x" * 500},
        ], "memories": [{"kind": "promise", "text": "週末に映画"}, {"kind": "secret", "text": "不正な種類"}]}))
        self.assertEqual([item["condition"] for item in parsed["evaluations"]], ["active_question"])
        self.assertEqual(len(parsed["evaluations"][0]["evidence"]), rel.MAX_EVIDENCE)
        self.assertEqual(parsed["rejected"], ["made_up", "lie", "praise_effort"])
        self.assertEqual(parsed["memories"], [{"kind": "promise", "text": "週末に映画"}])
        self.assertIsNone(rel.parse_evaluation("not json"))
        self.assertIsNone(rel.parse_evaluation('{"reply": "うん"}'))

    def test_character_weights_override_defaults(self):
        weights = rel.parse_weights('{"lie": -9}')
        self.assertEqual(rel.compute(START, evaluation(("lie", 1.0)), [], weights)["delta"]["trust"], -5.0)  # Still capped.
        self.assertEqual(rel.compute(START, evaluation(("lie", 0.5)), [], weights)["delta"]["trust"], -4.5)
        with self.assertRaises(ValueError):
            rel.parse_weights('{"unknown": 1}')
        with self.assertRaises(ValueError):
            rel.parse_weights('{"lie": 99}')

    def test_labels_and_overall(self):
        self.assertEqual(rel.label(START), "まだ知り合ったばかり")
        self.assertEqual(rel.label({"affection": 60, "trust": 20, "romance": 0}), "好きだけど、まだ信用しきれない")
        self.assertEqual(rel.label({"affection": 70, "trust": 60, "romance": 50}), "大切な存在")
        self.assertEqual(rel.overall({"affection": 70, "trust": 60, "romance": 50}), 61)


class StageTest(unittest.TestCase):
    def test_stages_follow_the_secret_levels(self):
        def scores(total):  # affection=trust=romance gives overall == total
            return {"affection": total, "trust": total, "romance": total}
        self.assertEqual([rel.stage_index(scores(v)) for v in (0, 24, 25, 49, 50, 74, 75, 100)], [0, 0, 1, 1, 2, 2, 3, 3])
        self.assertEqual(tuple(rel.STAGE_MINIMUMS[1:]), tuple(server.SECRET_LEVELS[:3]))
        self.assertEqual(rel.stage_info(scores(10), lover=True)["name"], "恋人")

    def test_confession_is_judged_only_at_the_last_stage(self):
        def update(total, score=1.0):
            return {"after": {"affection": total, "trust": total, "romance": total},
                    "breakdown": [{"condition": rel.CONFESSION, "score": score}]}
        self.assertEqual(rel.confession_outcome(update(80), lover=False), "judge")
        self.assertEqual(rel.confession_outcome(update(80, 0.3), lover=False), "judge")  # The judge decides if it is clear.
        self.assertIsNone(rel.confession_outcome(update(80, 0.2), lover=False))
        self.assertEqual(rel.confession_outcome(update(60), lover=False), "decline")
        self.assertIsNone(rel.confession_outcome(update(60, 0.4), lover=False))
        self.assertIsNone(rel.confession_outcome(update(80), lover=True))  # Already lovers.
        accepting = rel.reply_guidance(update(80)["after"], confession="accept")
        self.assertIn("告白を受け入れて恋人になる", accepting)
        self.assertIn("「恋人」", accepting)
        declining = rel.reply_guidance(update(60)["after"], confession="decline")
        self.assertIn("やんわり受け流す", declining)
        self.assertIn("「なかよし」", declining)

    def test_confession_judge_prompt_parse_and_rejection_penalty(self):
        scores = {"affection": 90, "trust": 85, "romance": 80}
        prompt = rel.confession_messages({"name": "n", "profile": "p"}, scores, "付き合って", [(True, "こんにちは")], [])
        self.assertIn("総合好感度は 86/100", prompt[0]["content"])
        self.assertIn("90以上: 突然の告白でも", prompt[0]["content"])
        self.assertIn("プレイヤー: こんにちは", prompt[1]["content"])
        self.assertEqual(rel.parse_confession('{"clear": false, "accept": true, "reason": "冗談"}'),
                         {"clear": False, "accept": False, "reason": "冗談"})  # Never accepted when unclear.
        self.assertIsNone(rel.parse_confession('{"clear": "yes"}'))
        before = {"affection": 80.0, "trust": 75.0, "romance": 70.0}
        update = {"before": before, "delta": {"affection": 2.0, "trust": 0.0, "romance": 1.0}}
        rejected = rel.reject_confession(update)
        self.assertEqual(rejected["after"], {"affection": 62.0, "trust": 55.0, "romance": 51.0})
        self.assertEqual(rel.overall(before) - rejected["overallAfter"], 19)  # -20 penalty after this turn's +1.

    def test_stage_rules_are_in_the_guidance_and_validated(self):
        custom = [dict(stage) for stage in rel.DEFAULT_STAGES]
        custom[0]["call"] = "苗字にさん付け"
        stages = rel.parse_stages(json.dumps(custom, ensure_ascii=False))
        guidance = rel.reply_guidance(dict(START), stages)
        self.assertIn("段階: 1/4「知り合い」", guidance)
        self.assertIn("- 相手の呼び方: 苗字にさん付け", guidance)
        self.assertEqual(rel.parse_stages(""), rel.DEFAULT_STAGES)
        with self.assertRaises(ValueError):
            rel.parse_stages(json.dumps(custom[:4], ensure_ascii=False))
        custom[2]["name"] = ""
        with self.assertRaises(ValueError):
            rel.parse_stages(json.dumps(custom, ensure_ascii=False))


class RelationshipGameTest(ServerFixture):
    def start_game(self):
        self.connect_character()
        invoke("do_POST", "/api/game/start", {"characterId": 1, "handle": "example.bsky.social", "profileContext": "情報"})

    def test_chat_returns_change_and_records_evaluation_and_memories(self):
        self.start_game()
        dm = FakeDm()
        prompts = []
        first = fake_ai("見てくれてたんだ", [{"condition": "sns_reference", "score": 1.0, "evidence": "プリンの投稿"}],
                        [{"kind": "promise", "text": "今度一緒にお店を探す"}])

        def ai(messages, json_mode=False, temperature=0.75, model=None, timeout=120):
            prompts.append(messages)
            return first(messages, json_mode, temperature)
        posts = [{"uri": "at://post/1", "date": "2026-10-22 20:00", "text": "プリン売り切れだった…"}]
        with patch.object(server, "oauth_call", side_effect=dm), patch.object(server, "call_ai", side_effect=ai), \
             patch.object(server, "character_posts", return_value=posts):
            status, result = self.chat("プリン売り切れだったんだね")
        self.assertEqual(status, 200)
        update = result["relationshipUpdate"]
        self.assertEqual(update["delta"], {"affection": 3.0, "trust": 0.0, "romance": 0.0})
        self.assertEqual(update["breakdown"][0]["evidence"], "プリンの投稿")
        self.assertIn("プリン売り切れだった…", prompts[0][1]["content"])  # SNS posts are evaluation material.
        self.assertIn("評価するプレイヤーの最新の発言:\nプリン売り切れだったんだね", prompts[0][1]["content"])
        self.assertIn("今度一緒にお店を探す", prompts[1][0]["content"])  # New memories reach the reply.
        self.assertEqual(result["game"]["axes"]["affection"], 33.0)
        self.assertEqual(result["game"]["lastUpdate"]["delta"]["affection"], 3.0)

        # The next evaluation remembers the promise and decays the repeated reference.
        prompts.clear()
        with patch.object(server, "oauth_call", side_effect=dm), patch.object(server, "call_ai", side_effect=ai):
            status, result = self.chat("またプリンの話だけど")
        self.assertIn("今度一緒にお店を探す", prompts[0][1]["content"])
        self.assertEqual(result["relationshipUpdate"]["delta"]["affection"], 1.5)

    def test_unreadable_evaluation_changes_nothing_but_still_replies(self):
        self.start_game()
        dm = FakeDm()
        with patch.object(server, "oauth_call", side_effect=dm), \
             patch.object(server, "call_ai", return_value='{"reply":"うん"}') as ai:
            status, result = self.chat("こんにちは")
        self.assertEqual(status, 200)
        self.assertEqual(ai.call_count, 3)  # Two evaluation attempts, then the reply.
        self.assertFalse(result["relationshipUpdate"]["evaluated"])
        self.assertEqual(result["relationshipUpdate"]["delta"], {"affection": 0.0, "trust": 0.0, "romance": 0.0})
        self.assertEqual(result["game"]["turns"], 1)
        self.assertEqual([item["sender"]["did"] for item in dm.messages], [DID, CHAR_DID])

    def test_reply_resume_applies_the_stored_change_once(self):
        self.start_game()
        dm = FakeDm()

        def reject_once(command):
            if command["op"] == "sendMessage" and command["did"] == CHAR_DID and not getattr(reject_once, "done", False):
                reject_once.done = True
                raise RuntimeError("timeout")
            return dm(command)
        ai = fake_ai("うん", [{"condition": "care_condition", "score": 1.0, "evidence": "大丈夫？"}])
        with patch.object(server, "oauth_call", side_effect=reject_once), patch.object(server, "call_ai", side_effect=ai):
            status, _ = self.chat("大丈夫？", client_id="care-1")
            self.assertEqual(status, 503)
        with patch.object(server, "oauth_call", side_effect=dm), patch.object(server, "call_ai", side_effect=ai):
            status, _ = self.chat("大丈夫？", client_id="care-1")
        # The reply status is unknown after the timeout, so the turn waits for confirmation instead of resending.
        self.assertEqual(status, 409)
        _, loaded = invoke("do_GET", "/api/game?characterId=1")
        self.assertEqual(loaded["game"]["axes"]["trust"], 20.0)

    def test_ai_timeout_is_reported_as_ai_error(self):
        with patch.multiple(server, OPENAI_API_KEY="sk-test", AI_MODEL="gpt-test"), \
             patch.object(server.urllib.request, "urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaises(RuntimeError) as caught:
                server.call_ai([{"role": "user", "content": "x"}])
        self.assertIn("AI の応答が時間内", str(caught.exception))

    def test_game_reply_knows_both_sides_posts(self):
        self.start_game()
        prompts = []
        reply = fake_ai("うん")

        def ai(messages, json_mode=False, temperature=0.75, model=None, timeout=120):
            prompts.append(messages)
            return reply(messages, json_mode, temperature)

        def posts(did):
            text = "キャラのプリン" if did == CHAR_DID else "プレイヤーの猫"
            return [{"uri": "", "date": "2026-10-24 12:00", "text": text, "story": False}]
        with patch.object(server, "oauth_call", side_effect=FakeDm()), patch.object(server, "call_ai", side_effect=ai), \
             patch.object(server, "character_posts", side_effect=posts):
            status, _ = self.chat("こんにちは")
        self.assertEqual(status, 200)
        system = prompts[-1][0]["content"]  # The reply prompt comes after the evaluation.
        self.assertIn("キャラのプリン", system)
        self.assertIn("プレイヤー が最近 Bluesky に投稿したこと", system)
        self.assertIn("プレイヤーの猫", system)

    def confess_with(self, axes, verdict=None):
        """One confession turn. verdict: what the confession judge answers. Returns the response,
        the reply prompt, whether they became lovers, and how many times the judge was asked."""
        self.start_game()
        with server.database() as db:
            server.edit_relationship(db, 1, DID, "example.bsky.social", axes, True, [])
        prompts, judged = [], []
        reply = fake_ai("うれしい", [{"condition": "confess_sincerely", "score": 1.0, "evidence": "好きです"}])

        def ai(messages, json_mode=False, temperature=0.75, model=None, timeout=120):
            prompts.append(messages)
            if "告白判定係" in messages[0]["content"]:
                judged.append(messages)
                return json.dumps(verdict, ensure_ascii=False)
            return reply(messages, json_mode, temperature)
        with patch.object(server, "oauth_call", side_effect=FakeDm()), patch.object(server, "call_ai", side_effect=ai):
            status, data = self.chat("ずっと好きでした。付き合ってください")
        self.assertEqual(status, 200)
        with server.database() as db:
            return data, prompts[-1][0]["content"], server.relationship_state(db, 1, DID)["lover"], len(judged)

    def test_accepted_confession_at_the_last_stage_makes_lovers(self):
        data, prompt, lover, judged = self.confess_with({"affection": 85, "trust": 80, "romance": 70},
                                                        {"clear": True, "accept": True, "reason": "流れが自然"})
        self.assertEqual(judged, 1)
        self.assertIn("告白を受け入れて恋人になる", prompt)
        self.assertTrue(lover)
        self.assertEqual(data["game"]["relationship"], "恋人")
        self.assertEqual((data["relationshipUpdate"]["confession"], data["relationshipUpdate"]["confessionReason"]),
                         ("accept", "流れが自然"))

    def test_rejected_confession_lowers_the_relationship_by_about_20(self):
        data, prompt, lover, _ = self.confess_with({"affection": 80, "trust": 75, "romance": 70},
                                                   {"clear": True, "accept": False, "reason": "唐突すぎる"})
        self.assertFalse(lover)
        update = data["relationshipUpdate"]
        self.assertEqual(update["confession"], "reject")
        self.assertLessEqual(update["overallAfter"], update["overallBefore"] - 15)  # -20 penalty plus this turn's change.
        self.assertIn("恋人にはなれない", prompt)
        self.assertIn("「なかよし」", prompt)  # The reply already follows the lowered stage.
        self.assertEqual(data["game"]["axes"], update["after"])

    def test_ambiguous_confession_is_not_judged(self):
        data, prompt, lover, _ = self.confess_with({"affection": 85, "trust": 80, "romance": 70},
                                                   {"clear": False, "accept": False, "reason": "冗談に近い"})
        self.assertFalse(lover)
        self.assertEqual(data["relationshipUpdate"]["confession"], "unclear")
        self.assertIn("はっきりしない", prompt)
        self.assertGreater(data["relationshipUpdate"]["overallAfter"], 75)  # No penalty.

    def test_confession_before_the_last_stage_is_turned_aside_without_judging(self):
        data, prompt, lover, judged = self.confess_with({"affection": 60, "trust": 50, "romance": 40})
        self.assertEqual(judged, 0)
        self.assertIn("やんわり受け流す", prompt)
        self.assertFalse(lover)

    def test_character_stages_are_saved_and_defaults_stay_empty(self):
        custom = [dict(stage) for stage in rel.DEFAULT_STAGES]
        custom[3]["tone"] = "おっとりした敬語"
        with patch.object(server, "xrpc", return_value={"did": CHAR_DID, "handle": "character.bsky.social"}):
            status, saved = invoke("do_POST", "/api/characters/save", {
                "id": 1, "profile": "おっとり", "handle": "character.bsky.social", "relationshipStages": custom})
            self.assertEqual(status, 200)
            self.assertEqual(saved["character"]["relationshipStages"][3]["tone"], "おっとりした敬語")
            invoke("do_POST", "/api/characters/save", {
                "id": 1, "profile": "おっとり", "handle": "character.bsky.social", "relationshipStages": rel.DEFAULT_STAGES})
        with server.database() as db:
            self.assertEqual(db.execute("SELECT relationship_stages FROM characters WHERE id=1").fetchone()[0], "")

    def test_evaluation_can_use_a_separate_model(self):
        self.start_game()
        models = []
        reply = fake_ai("うん")

        def ai(messages, json_mode=False, temperature=0.75, model=None, timeout=120):
            models.append(model)
            return reply(messages, json_mode, temperature)
        with patch.object(server, "oauth_call", side_effect=FakeDm()), patch.object(server, "call_ai", side_effect=ai), \
             patch.object(server, "RELATIONSHIP_MODEL", "gpt-judge"):
            status, _ = self.chat("こんにちは")
        self.assertEqual(status, 200)
        self.assertEqual(models, ["gpt-judge", None])  # Evaluation, then the reply with the default model.

    def test_weights_are_saved_with_the_character_and_conditions_are_listed(self):
        with patch.object(server, "xrpc", return_value={"did": CHAR_DID, "handle": "character.bsky.social"}):
            status, saved = invoke("do_POST", "/api/characters/save", {
                "id": 1, "profile": "誠実さを大事にする", "handle": "character.bsky.social", "relationshipWeights": '{"lie": -8}'})
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(saved["character"]["relationshipWeights"]), {"lie": -8})
            status, error = invoke("do_POST", "/api/characters/save", {
                "id": 1, "profile": "x", "handle": "character.bsky.social", "relationshipWeights": '{"nope": 1}'})
        self.assertEqual(status, 400)
        status, data = invoke("do_GET", "/api/relationship/conditions")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["conditions"]), len(rel.CONDITIONS))

    def test_restart_keeps_the_shared_relationship(self):
        self.start_game()
        dm = FakeDm()
        ai = fake_ai("うん", [{"condition": "praise_effort", "score": 1.0}], [{"kind": "event", "text": "初めて話した"}])
        with patch.object(server, "oauth_call", side_effect=dm), patch.object(server, "call_ai", side_effect=ai):
            self.chat("すごいね")
        _, restarted = invoke("do_POST", "/api/game/start", {"characterId": 1, "handle": "example.bsky.social", "profileContext": "情報"})
        # A new story resets turns, not the relationship that Bluesky DMs share.
        self.assertEqual(restarted["game"]["turns"], 0)
        self.assertEqual(restarted["game"]["axes"]["affection"], 33.0)
        self.assertEqual(restarted["game"]["lastUpdate"]["channel"], "real")
        with server.database() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM dm_relationship_memories").fetchone()[0], 1)

    def test_existing_game_scores_move_into_the_shared_relationship(self):
        self.start_game()
        with server.database() as db:
            db.execute("UPDATE character_games SET affection=60,trust=50,romance=10 WHERE character_id=1")
            db.execute("DELETE FROM meta WHERE key='shared_relationship_migrated'")
        server.init_db()
        server.init_db()
        _, loaded = invoke("do_GET", "/api/game?characterId=1")
        self.assertEqual(loaded["game"]["axes"], {"affection": 60.0, "trust": 50.0, "romance": 10.0})

    def test_bluesky_dm_progress_shows_up_in_the_game(self):
        self.start_game()
        with server.database() as db:
            update = {**rel.update(rel.INITIAL, evaluation(("care_condition", 1.0)), []), "channel": "bluesky"}
            server.save_relationship(db, 1, DID, "example.bsky.social", "app-1", update, 40)
        _, loaded = invoke("do_GET", "/api/game?characterId=1")
        self.assertEqual(loaded["game"]["axes"]["trust"], 23.0)
        self.assertEqual(loaded["game"]["lastUpdate"]["channel"], "bluesky")


if __name__ == "__main__":
    unittest.main()
