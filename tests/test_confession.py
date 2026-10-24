import json
from unittest.mock import patch
import server
from test_server import ServerFixture, FakeDm, DID, VISITOR, invoke, fake_ai


def judge(verdict, calls=None):
    """AI stand-in: the confession judge answers `verdict`; other prompts get a normal reply."""
    reply = fake_ai("I love you too")

    def ai(messages, json_mode=False, temperature=0.75, model=None, timeout=120):
        if "告白判定係" in messages[0]["content"]:
            if calls is not None:
                calls.append(messages)
            return verdict if isinstance(verdict, str) else json.dumps(verdict)
        return reply(messages, json_mode, temperature)
    return ai


ACCEPT = {"clear": True, "accept": True, "reason": "test"}
REJECT = {"clear": True, "accept": False, "reason": "test"}


class ConfessionTest(ServerFixture):
    def start(self, score=90):
        self.connect_character()
        invoke("do_POST", "/api/game/start", {"characterId": 1, "handle": "player.test", "profileContext": "test"})
        with server.database() as db:
            db.execute("INSERT INTO dm_relationships(character_id,partner_did,partner_handle,affection,trust,romance,updated_at) VALUES(1,?,?,?,?,?,1)", (DID, "player.test", score, score, score))
        return FakeDm()

    def send(self, key="confession-1", confession=True):
        return invoke("do_POST", "/api/game/chat", {"characterId":1,"message":"I love you", "clientMessageId":key,"confession":confession})

    def no_change(self):
        return patch.object(server, "evaluate_message", return_value=server.relationship.no_change("test"))

    def test_rejects_ineligible_confession_before_sending(self):
        self.start(74)  # Below the last stage (75).
        with patch.object(server,"oauth_call") as oauth:
            self.assertEqual(self.send()[0],400)
        oauth.assert_not_called()

    def test_accepts_once_persists_and_continues_as_lovers(self):
        dm=self.start()
        calls=[]
        with patch.object(server,"oauth_call",side_effect=dm), self.no_change(), patch.object(server,"call_ai",side_effect=judge(ACCEPT, calls)):
            status,result=self.send()
            self.assertEqual(status,200)
            self.assertEqual(result["game"]["romance"]["status"],"lovers")
            self.assertEqual(self.send()[0],200)  # The same message again is the same turn.
            self.assertEqual(len(dm.sent),2)
            self.assertEqual(len(calls),1)
        self.assertEqual(result["game"]["affinity"],90)  # Values are kept as they are.
        invoke("do_POST","/api/game/start",{"characterId":1,"handle":"player.test","profileContext":"test"})
        self.assertEqual(invoke("do_GET","/api/game?characterId=1")[1]["game"]["romance"]["status"],"lovers")
        with patch.object(server,"oauth_call",side_effect=dm),patch.object(server,"call_ai",side_effect=fake_ai()):
            for i in range(12):  # No 10-turn ending any more.
                status,result=self.send("lovers-"+str(i),False)
                self.assertEqual(status,200)
                self.assertEqual(result["game"]["relationship"],"恋人")
                self.assertIsNone(result["game"]["ending"])
        with patch.object(server,"oauth_call") as oauth:
            self.assertEqual(self.send("second-confession")[0],400)
        oauth.assert_not_called()

    def test_declined_confession_lowers_the_relationship(self):
        dm=self.start()
        with patch.object(server,"oauth_call",side_effect=dm),self.no_change(),patch.object(server,"call_ai",side_effect=judge(REJECT)):
            status,result=self.send()
        self.assertEqual(status,200)
        self.assertEqual(result["game"]["affinity"],70)  # -20
        self.assertEqual(result["game"]["romance"],{"status":"normal","declined":True})

    def test_reply_rejection_does_not_commit_lovers_and_retry_keeps_intent(self):
        dm=self.start()
        calls=[]
        def reject(command):
            if command["op"]=="sendMessage" and command["did"]!=DID:
                return {"rejected":"test rejection"}
            return dm(command)
        with patch.object(server,"oauth_call",side_effect=reject),self.no_change(),patch.object(server,"call_ai",side_effect=judge(ACCEPT, calls)):
            self.assertEqual(self.send()[0],503)
        self.assertEqual(invoke("do_GET","/api/game?characterId=1")[1]["game"]["romance"]["status"],"ready")
        # The rejected reply was never sent, so the turn (and the verdict) is redone; it is still a confession.
        with patch.object(server,"oauth_call",side_effect=dm),self.no_change(),patch.object(server,"call_ai",side_effect=judge(ACCEPT, calls)):
            self.assertEqual(self.send()[1]["game"]["romance"]["status"],"lovers")
        self.assertEqual(len(dm.sent),2)
        self.assertEqual(len(calls),2)

    def test_confession_flag_cannot_change_during_retry(self):
        dm=self.start()
        with patch.object(server,"oauth_call",side_effect=dm),patch.object(server,"call_ai",side_effect=fake_ai()):
            self.assertEqual(self.send(confession=False)[0],200)
        self.assertEqual(self.send(confession=True)[0],400)

    def test_invalid_decision_never_implies_acceptance(self):
        for index, value in enumerate(['{"clear":true}', '{"clear":"yes","accept":true}', 'null', 'not json']):
            dm=self.start() if index == 0 else FakeDm()
            with patch.object(server,"oauth_call",side_effect=dm),self.no_change(),patch.object(server,"call_ai",side_effect=judge(value)):
                status,result=self.send(f"invalid-{index}")
            self.assertEqual(status,200)
            self.assertEqual(result["relationshipUpdate"]["confession"],"unclear")
            self.assertEqual(result["game"]["romance"]["status"],"ready")

    def test_normal_http_page_loads_romance_without_debug_tools(self):
        import threading
        import urllib.request
        http=server.http.server.ThreadingHTTPServer(("127.0.0.1",0),server.Handler)
        thread=threading.Thread(target=http.serve_forever,daemon=True)
        thread.start()
        try:
            base=f"http://127.0.0.1:{http.server_port}"
            with urllib.request.urlopen(base+"/") as response:
                html=response.read()
                self.assertIn(b'ui-romance.js',html)
                self.assertIn(b'ui-romance.css',html)
                self.assertNotIn(b'ui-debug.js',html)
                self.assertNotIn(b'data-ui-preview',html)
            for name in ('ui-romance.js','ui-romance.css','ending-preview.png'):
                with urllib.request.urlopen(base+'/'+name) as response:
                    self.assertEqual(response.status,200)
                    self.assertTrue(response.read())
        finally:
            http.shutdown();http.server_close();thread.join(timeout=5)

    def test_lovers_from_the_first_implementation_are_migrated(self):
        self.start()
        with server.database() as db:
            db.execute("UPDATE dm_relationships SET is_lovers=1,lover_at=NULL WHERE partner_did=?", (DID,))
        server.init_db()
        with server.database() as db:
            self.assertTrue(server.is_lover(db, 1, DID))
