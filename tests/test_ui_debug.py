import importlib.util
import json
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

spec = importlib.util.spec_from_file_location('ui_debug', Path(__file__).resolve().parents[1] / 'scripts' / 'ui_debug.py')
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)


class UIPreviewTest(unittest.TestCase):
    def test_chat_scenarios_and_reset(self):
        preview = ui.Preview()
        def call(path, body=None):
            return preview.dispatch('POST' if body is not None else 'GET', path, {}, body or {})
        call('/__debug/config', {'scenario': 'secret'})
        self.assertEqual(call('/api/game')['game']['affinity'], 74)
        reply = call('/api/game/chat', {'message': 'こんにちは'})
        self.assertTrue(next(s for s in reply['game']['secrets'] if s['level'] == 75)['unlocked'])
        self.assertEqual(len(reply['dmMessages']), 2)
        call('/__debug/config', {'delta': -3})
        decreased = call('/api/game/chat', {'message': '下降のプレビュー'})
        self.assertEqual(decreased['game']['affinity'], 79)
        self.assertEqual(decreased['relationshipUpdate']['delta']['affection'], -3)
        call('/__debug/config', {'delta': 8})
        call('/__debug/config', {'scenario': 'ending'})
        ready = call('/api/game/chat', {'message': 'また会おう'})['game']
        self.assertIsNone(ready['ending'])
        self.assertEqual(ready['previewRomance']['status'], 'ready')
        self.assertEqual(call('/api/game/chat', {'message': '普段の会話'})['game']['previewRomance']['status'], 'ready')
        call('/__debug/config', {'acceptConfession': False})
        declined = call('/api/game/chat', {'message': '好きです、付き合ってください'})['game']
        self.assertTrue(declined['previewRomance']['declined'])
        self.assertEqual(declined['previewRomance']['status'], 'ready')
        call('/__debug/config', {'acceptConfession': True})
        accepted = call('/api/game/chat', {'message': '好きです、付き合ってください'})['game']
        self.assertEqual(accepted['previewRomance']['status'], 'lovers')
        call('/__debug/config', {'delta': -3})
        for _ in range(12):
            continued = call('/api/game/chat', {'message': '恋人として会話'})['game']
            self.assertIsNone(continued['ending'])
            self.assertEqual(continued['affinity'], 100)
            self.assertEqual(continued['relationship'], '恋人')
        call('/__debug/config', {'scenario': 'login'})
        self.assertIsNone(call('/api/auth')['did'])
        self.assertEqual(call('/api/oauth/start', {'role': 'player'})['url'], '/')
        self.assertIsNotNone(call('/api/auth')['did'])
        call('/__debug/config', {'failNext': True})
        self.assertEqual(call('/api/characters')[0], 503)
        self.assertEqual(len(call('/api/characters')['characters']), 2)
        call('/api/characters/delete', {'id': 1})
        call('/__debug/config', {'reset': True})
        self.assertEqual(len(call('/api/characters')['characters']), 2)

    def test_serves_real_pages_and_assets(self):
        http = ui.http.server.ThreadingHTTPServer(('127.0.0.1', 0), ui.Handler)
        http.preview = ui.Preview()
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{http.server_port}'
        try:
            for path in ('/', '/login', '/characters'):
                with urllib.request.urlopen(base + path) as response:
                    html = response.read()
                    self.assertIn(b'/ui-debug.js', html)
                    self.assertEqual(b'ui-romance.js' in html, path == '/')
            for path in ('/ui-romance.js', '/ui-romance.css', '/ending-preview.png'):
                with urllib.request.urlopen(base + path) as response:
                    self.assertEqual(response.status, 200)
                    self.assertTrue(response.read())
            with urllib.request.urlopen(base + '/ui-debug.js') as response:
                self.assertEqual(response.status, 200)
            with urllib.request.urlopen(base + '/api/characters') as response:
                self.assertEqual(len(json.load(response)['characters']), 2)
            request = urllib.request.Request(base + '/api/game/chat',
                data=json.dumps({'message': 'test'}).encode(), headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request) as response:
                self.assertEqual(len(json.load(response)['dmMessages']), 2)
        finally:
            http.shutdown()
            http.server_close()
            thread.join(timeout=5)
