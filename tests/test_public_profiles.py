import json
from unittest.mock import patch

import public_profiles
import server
import shared_settings
from test_server import ServerFixture, invoke, CHAR_DID


class PublicProfileTest(ServerFixture):
    def test_legacy_extraction_only_uses_explicit_public_facts(self):
        raw = '職業\nソフトウェアエンジニア\n性格\n明るい\n好きなもの\n猫、ゲーム\n年齢\n22歳\nビジュアルコンセプト\nINTERNAL IMAGE PROMPT'
        public = public_profiles.legacy_introduction(raw)
        self.assertEqual(public['likes'], '猫、ゲーム')
        self.assertIn('22歳', public['basics'])
        self.assertNotIn('INTERNAL', json.dumps(public))
        self.assertEqual(public_profiles.legacy_introduction('secret instructions')['intro'], '')

    def test_player_view_uses_public_copy_without_ai_settings(self):
        with server.database() as db:
            db.execute("UPDATE characters SET profile=?,public_profile=? WHERE id=1",
                       ('PRIVATE AI INSTRUCTIONS', json.dumps({'intro': '公開用の紹介', 'likes': '猫'})))
        status, player = invoke('do_GET', '/api/characters?view=player')
        self.assertEqual(status, 200)
        self.assertEqual(player['characters'][0]['profile'], '公開用の紹介')
        self.assertNotIn('PRIVATE', json.dumps(player))
        self.assertNotIn('relationshipWeights', player['characters'][0])
        status, admin = invoke('do_GET', '/api/characters')
        self.assertEqual(admin['characters'][0]['profile'], 'PRIVATE AI INSTRUCTIONS')

    def test_admin_save_validates_and_preserves_separate_fields(self):
        profile = {'did': CHAR_DID, 'handle': 'preview.test', 'displayName': 'Preview'}
        body = {'id': 1, 'handle': 'preview.test', 'profile': 'AI settings',
                'publicProfile': {'intro': 'こんにちは', 'likes': '猫', 'memories': 'エピソード\n設定に基づく文章'}}
        with patch.object(server, 'xrpc', return_value=profile):
            status, saved = invoke('do_POST', '/api/characters/save', body)
        self.assertEqual(status, 200)
        self.assertEqual(saved['character']['publicProfile']['intro'], 'こんにちは')
        self.assertEqual(saved['character']['profile'], 'AI settings')
        self.assertEqual(saved['character']['publicProfile']['memories'], 'エピソード\n設定に基づく文章')
        body['publicProfile']['intro'] = 'x' * 301
        self.assertEqual(invoke('do_POST', '/api/characters/save', body)[0], 400)
        self.assertEqual(invoke('do_GET', '/api/characters')[1]['characters'][0]['publicProfile']['intro'], 'こんにちは')
        # Older clients that do not send publicProfile must not erase it.
        del body['publicProfile']
        with patch.object(server, 'xrpc', return_value=profile):
            status, saved = invoke('do_POST', '/api/characters/save', body)
        self.assertEqual(saved['character']['publicProfile']['intro'], 'こんにちは')

    def test_public_profile_is_exported_and_imported(self):
        with server.database() as db:
            db.execute("UPDATE characters SET handle='shared.test',public_profile=? WHERE id=1",
                       (json.dumps({'intro': '共有の紹介', 'details': '活動について', 'memories': 'アプリ作り\n形になる瞬間が好き'}),))
            sql = shared_settings.export_sql(db)
            db.execute("UPDATE characters SET public_profile='' WHERE id=1")
            shared_settings.import_sql(db, sql)
            result = server.character_json(db.execute('SELECT * FROM characters WHERE id=1').fetchone())
            self.assertEqual(result['publicProfile']['intro'], '共有の紹介')
            self.assertEqual(result['publicProfile']['details'], '活動について')
            self.assertEqual(result['publicProfile']['memories'], 'アプリ作り\n形になる瞬間が好き')

    def test_schema_migration_is_idempotent(self):
        server.init_db()
        server.init_db()
        with server.database() as db:
            self.assertIn('public_profile', {row['name'] for row in db.execute('PRAGMA table_info(characters)')})
