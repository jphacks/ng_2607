import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server
import shared_settings

CHAR_DID = "did:plc:character2345"
OWNER = "d" * 64


class SharedSettingsTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()

    def tearDown(self):
        # Close SQLite connections before deleting the directory on Windows.
        self.doCleanups()
        self.folder.cleanup()

    def pc(self, name):
        """A fresh database for one PC."""
        path = Path(self.folder.name) / name
        with patch.object(server, "DATA", path), patch.object(server, "DB_PATH", path / "game.sqlite3"):
            server.init_db()
        db = sqlite3.connect(path / "game.sqlite3")
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        self.addCleanup(db.close)
        return db

    def source(self):
        db = self.pc("source")
        db.execute("""UPDATE characters SET name='結城めもり',profile='明るいエンジニア。''引用符''も入る',handle='memori.test',
                      at_did=?,avatar_url='https://cdn.example/a.png',relationship_weights='{"lie": -8}',
                      oauth_did=?,oauth_owner=?,oauth_scope='atproto' WHERE id=1""", (CHAR_DID, CHAR_DID, OWNER))
        db.execute("INSERT INTO character_secrets(character_id,level,title,content) VALUES(1,25,'朝','朝が苦手')")
        db.execute("""INSERT INTO character_automation(character_id,auto_reply,auto_post,post_prompt,extra_persona,schedule_base,
                      require_unlock,unlock_score,recent_posts,updated_at) VALUES(1,1,1,'話題','口調は〜だよ','{}',1,35,'["秘密の下書き"]',1)""")
        db.execute("INSERT INTO player_auth(visitor,did,updated_at) VALUES(?,?,1)", (OWNER, "did:plc:player2345"))
        db.execute("""INSERT INTO dm_relationships(character_id,partner_did,partner_handle,affection,trust,romance,updated_at)
                      VALUES(1,'did:plc:stranger2345','stranger.test',50,50,50,1)""")
        db.commit()
        return db

    def test_settings_move_between_pcs_without_private_data(self):
        sql = shared_settings.export_sql(self.source())
        for private in (OWNER, "did:plc:player2345", "stranger.test", "秘密の下書き", "atproto"):
            self.assertNotIn(private, sql)

        target = self.pc("target")
        added, updated = shared_settings.import_sql(target, sql)
        self.assertEqual((added, updated), (["memori.test"], []))
        row = target.execute("SELECT * FROM characters WHERE handle='memori.test'").fetchone()
        self.assertEqual((row["name"], row["profile"], row["at_did"]), ("結城めもり", "明るいエンジニア。'引用符'も入る", CHAR_DID))
        self.assertEqual(json.loads(row["relationship_weights"]), {"lie": -8})
        self.assertEqual((row["oauth_did"], row["oauth_owner"]), ("", ""), "OAuth is connected on each PC")
        self.assertEqual(target.execute("SELECT content FROM character_secrets WHERE character_id=?", (row["id"],)).fetchone()[0], "朝が苦手")
        automation = target.execute("SELECT * FROM character_automation WHERE character_id=?", (row["id"],)).fetchone()
        self.assertEqual((automation["auto_reply"], automation["auto_post"]), (0, 0), "never switched on by an import")
        self.assertEqual((automation["extra_persona"], automation["unlock_score"], automation["recent_posts"]), ("口調は〜だよ", 35, "[]"))

        # Importing again updates in place.
        added, updated = shared_settings.import_sql(target, sql)
        self.assertEqual((added, updated), ([], ["memori.test"]))
        self.assertEqual(target.execute("SELECT COUNT(*) FROM characters WHERE handle='memori.test'").fetchone()[0], 1)
        self.assertEqual(target.execute("SELECT COUNT(*) FROM character_secrets").fetchone()[0], 1)

    def test_import_keeps_local_connection_and_switches_but_replaces_content(self):
        sql = shared_settings.export_sql(self.source())
        target = self.pc("target")
        target.execute("""UPDATE characters SET handle='Memori.Test',at_did=?,oauth_did=?,oauth_owner='local',profile='古い' WHERE id=1""",
                       (CHAR_DID, CHAR_DID))
        target.execute("INSERT INTO character_secrets(character_id,level,title,content) VALUES(1,100,'古い','消える')")
        target.execute("INSERT INTO character_automation(character_id,auto_reply,auto_post,updated_at) VALUES(1,1,0,1)")
        target.commit()
        added, updated = shared_settings.import_sql(target, sql)
        self.assertEqual((added, updated), ([], ["memori.test"]))
        row = target.execute("SELECT * FROM characters WHERE id=1").fetchone()
        self.assertEqual((row["profile"], row["oauth_owner"]), ("明るいエンジニア。'引用符'も入る", "local"))
        self.assertEqual([r[0] for r in target.execute("SELECT level FROM character_secrets WHERE character_id=1")], [25])
        self.assertEqual(target.execute("SELECT auto_reply FROM character_automation WHERE character_id=1").fetchone()[0], 1)

    def test_a_different_account_behind_the_handle_drops_the_local_connection(self):
        sql = shared_settings.export_sql(self.source())
        target = self.pc("target")
        target.execute("UPDATE characters SET handle='memori.test',at_did='did:plc:other2345',oauth_did='did:plc:other2345',oauth_owner='local' WHERE id=1")
        target.commit()
        shared_settings.import_sql(target, sql)
        row = target.execute("SELECT * FROM characters WHERE id=1").fetchone()
        self.assertEqual((row["at_did"], row["oauth_did"], row["oauth_owner"]), (CHAR_DID, "", ""))

    def test_only_exported_files_are_accepted(self):
        with self.assertRaises(ValueError):
            shared_settings.import_sql(self.pc("target"), "DELETE FROM characters;")


if __name__ == "__main__":
    unittest.main()
