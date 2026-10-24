import json
from unittest.mock import patch
import server
from test_server import ServerFixture, FakeDm, DID, VISITOR, invoke, fake_ai

class ConfessionTest(ServerFixture):
    def start(self, score=100):
        self.connect_character()
        invoke("do_POST", "/api/game/start", {"characterId": 1, "handle": "player.test", "profileContext": "test"})
        with server.database() as db:
            db.execute("INSERT INTO dm_relationships(character_id,partner_did,partner_handle,affection,trust,romance,updated_at) VALUES(1,?,?,?,?,?,1)", (DID, "player.test", score, score, score))
        return FakeDm()

    def send(self, key="confession-1", confession=True):
        return invoke("do_POST", "/api/game/chat", {"characterId":1,"message":"I love you", "clientMessageId":key,"confession":confession})

    def test_rejects_ineligible_confession_before_sending(self):
        self.start(99)
        with patch.object(server,"oauth_call") as oauth:
            self.assertEqual(self.send()[0],400)
        oauth.assert_not_called()

    def test_accepts_once_persists_and_continues_as_lovers(self):
        dm=self.start()
        with patch.object(server,"oauth_call",side_effect=dm), patch.object(server,"evaluate_message",return_value=server.relationship.no_change("test")), patch.object(server,"generate_confession",return_value=("I love you too",True)) as decide:
            status,result=self.send()
            self.assertEqual(status,200)
            self.assertEqual(result["game"]["romance"]["status"],"lovers")
            self.assertEqual(self.send()[0],200)
            self.assertEqual(len(dm.sent),2)
            self.assertEqual(decide.call_count,1)
        invoke("do_POST","/api/game/start",{"characterId":1,"handle":"player.test","profileContext":"test"})
        self.assertEqual(invoke("do_GET","/api/game?characterId=1")[1]["game"]["romance"]["status"],"lovers")
        with patch.object(server,"oauth_call",side_effect=dm),patch.object(server,"call_ai",side_effect=fake_ai()):
            for i in range(12):
                status,result=self.send("lovers-"+str(i),False)
                self.assertEqual(status,200)
                self.assertEqual(result["game"]["affinity"],100)
                self.assertIsNone(result["game"]["ending"])
        with server.database() as db:
            update=server.relationship.no_change("test")
            update["delta"]={axis:-5 for axis in server.relationship.AXES}
            after,_=server.save_relationship(db,1,DID,"player.test","bluesky-lower",update,30)
            self.assertEqual(set(after.values()),{100.0})
        with patch.object(server,"oauth_call") as oauth:
            self.assertEqual(self.send("second-confession")[0],400)
        oauth.assert_not_called()

    def test_declined_confession_does_not_create_lovers(self):
        dm=self.start()
        with patch.object(server,"oauth_call",side_effect=dm),patch.object(server,"evaluate_message",return_value=server.relationship.no_change("test")),patch.object(server,"generate_confession",return_value=("Please wait",False)):
            status,result=self.send()
        self.assertEqual(status,200)
        self.assertEqual(result["game"]["romance"]["status"],"ready")
        self.assertTrue(result["game"]["romance"]["declined"])

    def test_reply_rejection_does_not_commit_lovers_and_retry_keeps_intent(self):
        dm=self.start()
        def reject(command):
            if command["op"]=="sendMessage" and command["did"]!=DID:
                return {"rejected":"test rejection"}
            return dm(command)
        with patch.object(server,"oauth_call",side_effect=reject),patch.object(server,"evaluate_message",return_value=server.relationship.no_change("test")),patch.object(server,"generate_confession",return_value=("Yes",True)):
            self.assertEqual(self.send()[0],503)
        self.assertEqual(invoke("do_GET","/api/game?characterId=1")[1]["game"]["romance"]["status"],"ready")
        with patch.object(server,"oauth_call",side_effect=dm),patch.object(server,"evaluate_message",return_value=server.relationship.no_change("test")),patch.object(server,"generate_confession",return_value=("Yes",True)):
            self.assertEqual(self.send()[1]["game"]["romance"]["status"],"lovers")
        self.assertEqual(len(dm.sent),2)

    def test_confession_flag_cannot_change_during_retry(self):
        dm=self.start()
        with patch.object(server,"oauth_call",side_effect=dm),patch.object(server,"call_ai",side_effect=fake_ai()):
            self.assertEqual(self.send(confession=False)[0],200)
        self.assertEqual(self.send(confession=True)[0],400)

    def test_invalid_decision_never_implies_acceptance(self):
        for value in ['{"reply":"yes"}', '{"reply":"yes","accepted":"true"}', 'null', 'not json']:
            with patch.object(server,"call_ai",return_value=value):
                with self.assertRaises(RuntimeError):server.generate_confession([])
        with patch.object(server,"call_ai",return_value=json.dumps({"reply":"yes","accepted":True})):
            self.assertEqual(server.generate_confession([]),("yes",True))

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
