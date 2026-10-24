"""Standalone UI preview. No imports from the application, credentials, or network APIs."""
import argparse
import copy
import datetime
import http.server
import json
from pathlib import Path
import threading
import time
import urllib.parse

STATIC = Path(__file__).resolve().parents[1] / 'static'
PLAYER = 'did:plc:ui-preview-player'


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class Preview:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.authenticated = True
        self.scenario = 'normal'
        self.delay = 400
        self.delta = 8
        self.accept_confession = True
        self.fail_next = False
        self.games = {}
        self.messages = {}
        self.settings = {}
        self.characters = [self.character(1, '陽菜', 'assets-kanojo.png'),
                           self.character(2, '蒼', 'assets-karesi.png')]

    def character(self, cid, name, image):
        return dict(id=cid, name=name, handle=f'preview{cid}.example.test',
                    atDid=f'did:plc:ui-preview-{cid}', iconUrl='/' + image,
                    profile=f'{name}です。散歩と映画、ゆっくりお話しする時間が好きです。\n最近は小さなカフェを探しています。',
                    oauthConnected=True, relationshipWeights='', secrets=[
                        dict(level=level, title=title, content='実は、あなたと話せる時間をいつも楽しみにしているんです。\nこれはUI確認用のサンプルです。')
                        for level, title in zip((25, 50, 75, 100), ('お気に入りの場所', '小さな夢', '大切な思い出', 'あなたへの気持ち'))])

    def public_character(self, character):
        return {**character, 'unlock': dict(required=self.scenario == 'locked',
                unlocked=self.scenario != 'locked', score=18, threshold=30)}

    def game(self, cid, fresh=False):
        if fresh or cid not in self.games:
            score = {'secret': 74, 'ending': 95, 'confession': 100, 'lovers': 100}.get(self.scenario, 18)
            self.games[cid] = dict(did=PLAYER, affinity=score, turns=9 if self.scenario == 'ending' else 0,
                                  axes=dict(affection=score, trust=score, romance=score),
                                  relationship='気になる存在', messages=[], ending=None, lastUpdate=None)
            self.games[cid]['previewRomance'] = {'status': 'lovers' if self.scenario == 'lovers' else 'ready' if score == 100 else 'normal'}
            if self.scenario == 'lovers': self.games[cid]['relationship'] = '恋人'
            self.messages[cid] = [dict(id=f'welcome-{cid}', sender={'did': f'did:plc:ui-preview-{cid}'},
                text='来てくれてうれしい。今日はどんな一日だった？', sentAt=now())]
        game = self.games[cid]
        character = next(c for c in self.characters if c['id'] == cid)
        game['secrets'] = [{**s, 'unlocked': game['affinity'] >= s['level'],
                            'read': s.get('read', False)} for s in character['secrets']]
        return game

    def dispatch(self, method, path, query, body):
        if path == '/__debug/state':
            return dict(scenario=self.scenario, delay=self.delay, delta=self.delta, acceptConfession=self.accept_confession)
        if path == '/__debug/config':
            if body.get('reset'):
                self.reset()
            if 'scenario' in body:
                self.scenario = body['scenario']
                self.games.clear()
                self.messages.clear()
                self.authenticated = self.scenario != 'login'
            self.delay = max(0, min(10000, int(body.get('delay', self.delay))))
            self.delta = max(-100, min(100, int(body.get('delta', self.delta))))
            self.accept_confession = body.get('acceptConfession', self.accept_confession)
            self.fail_next = body.get('failNext', False)
            return {'ok': True}
        if self.fail_next:
            self.fail_next = False
            return 503, {'error': 'UI確認用の通信エラーです。「再試行」を試してください。'}
        cid = int(body.get('characterId') or query.get('characterId', ['1'])[0])
        if path == '/api/auth': return {'did': PLAYER if self.authenticated else None}
        if path == '/api/auth/logout':
            self.authenticated = False
            return {'ok': True}
        if path == '/api/oauth/start':
            self.authenticated = True
            if body.get('role') == 'character':
                next(c for c in self.characters if c['id'] == cid)['oauthConnected'] = True
            return {'url': '/characters?oauth=connected' if body.get('role') == 'character' else '/'}
        if path == '/api/profile':
            return {'profile': dict(did=PLAYER, handle='preview.example.test', displayName='プレビューユーザー', description='UIテスト用です', avatar='/avatar-placeholder.svg')}
        if path == '/api/characters':
            return {'characters': [] if self.scenario == 'empty' else [self.public_character(c) for c in self.characters]}
        if path == '/api/relationship/conditions':
            return {'conditions': [dict(id='kindness', axisLabel='好意', weight=2, major=False, label='相手を気遣う')]}
        if path == '/api/game': return {'game': self.game(cid)}
        if path == '/api/game/start': return {'game': self.game(cid, fresh=True)}
        if path == '/api/game/dm':
            self.game(cid)
            return dict(messages=list(reversed(self.messages[cid])), cursor=None, convo={'id': f'preview-{cid}'})
        if path == '/api/game/chat':
            game = self.game(cid)
            before = game['affinity']
            lovers = game['previewRomance']['status'] == 'lovers'
            confessing = bool(body.get('confession')) and before == 100 and not lovers
            accepted = confessing and self.accept_confession
            lovers = lovers or accepted
            score = 100 if lovers or confessing else max(0, min(100, before + self.delta))
            game.update(affinity=score, turns=game['turns'] + 1,
                        axes=dict(affection=score, trust=score, romance=score),
                        relationship='恋人' if lovers else '大切な存在' if score >= 50 else '気になる存在')
            game['previewRomance'] = {'status': 'lovers' if lovers else 'ready' if score == 100 else 'normal',
                                      'declined': confessing and not accepted}
            update = dict(delta=dict(affection=score-before, trust=score-before, romance=score-before),
                          reason='プレビュー用の好感度変化です。', breakdown=[], evaluated=True)
            game['lastUpdate'] = update
            reply = ('私も、あなたが好き。これからは恋人として、ずっと隣にいさせてね。' if accepted else
                     'ありがとう。大切な気持ちだから、もう少し時間をもらってもいい？' if confessing else
                     '大好きだよ。次のお休みは、ふたりでどこに行こうか？' if lovers else
                     'うん、聞かせてくれてありがとう。もっとあなたのことを知りたいな。')
            batch = [dict(id=f'{time.time_ns()}-{i}', sender={'did': did}, text=text, sentAt=now())
                     for i, (did, text) in enumerate([(PLAYER, body.get('message', '')), (f'did:plc:ui-preview-{cid}',
                     reply)])]
            self.messages[cid].extend(batch)
            return dict(game=self.game(cid), dmMessages=batch, convoId=f'preview-{cid}', relationshipUpdate=update)
        if path == '/api/game/secret/read':
            character = next(c for c in self.characters if c['id'] == cid)
            next(s for s in character['secrets'] if s['level'] == body['level'])['read'] = True
            return {'ok': True}
        if path == '/api/characters/save':
            selected = next((c for c in self.characters if c['id'] == body.get('id')), None)
            if selected is None:
                selected = self.character(max((c['id'] for c in self.characters), default=0)+1, '新しい相手', 'avatar-placeholder.svg')
                self.characters.append(selected)
            for key in ('profile', 'handle', 'relationshipWeights', 'secrets'):
                if key in body: selected[key] = body[key]
            return {'character': self.public_character(selected)}
        if path in ('/api/characters/delete', '/api/characters/disconnect'):
            if path.endswith('delete'): self.characters[:] = [c for c in self.characters if c['id'] != body['id']]
            else: next(c for c in self.characters if c['id'] == body['id'])['oauthConnected'] = False
            return {'ok': True}
        parts = path.strip('/').split('/')
        if len(parts) >= 4 and parts[:2] == ['api', 'characters']:
            cid = int(parts[2])
            character = next(c for c in self.characters if c['id'] == cid)
            kind = parts[3]
            if kind == 'secrets': return {'secrets': character['secrets']}
            if kind == 'profile':
                return dict(character=self.public_character(character), profile=dict(did=character['atDid'],
                    displayName=character['name'], handle=character['handle'], avatar=character['iconUrl'],
                    description=character['profile'], followersCount=128, followsCount=42, postsCount=36))
            if kind == 'posts': return dict(feed=[{'post': {'record': {'text': '今日はお気に入りのカフェでひと休み。', 'createdAt': now()}}}], cursor=None)
            if kind == 'convos': return dict(convos=[dict(id=f'preview-{cid}', members=[dict(did=PLAYER, handle='preview.example.test', displayName='あなた')], lastMessage={'text': 'またお話ししようね'})], cursor=None)
            if kind == 'messages':
                self.game(cid)
                return dict(messages=self.messages[cid], cursor=None)
            if kind == 'automation':
                settings = self.settings.setdefault(cid, dict(auto_reply=False, auto_post=False, extra_persona='', post_prompt='', schedule_base='{}', require_unlock=False, unlock_score=30))
                if len(parts) == 4 and method == 'POST': settings.update(body)
                today = dict(blocks=[dict(start='09:00', end='18:00', status='free', activity='休日', detail='のんびり過ごす')], post_times=['12:00'], events=[], post_log=[], dm_log=[])
                if parts[-1] == 'preview': return {'text': '窓の外の空がきれい。今日はいいことがありそう。'}
                return dict(settings=settings, today=today, now='12:00', relationships=[], missingScopes=[], status={})
        return 404, {'error': 'プレビュー未対応のAPI: ' + path}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def do_GET(self): self.handle_request()
    def do_POST(self): self.handle_request()

    def end_headers(self):
        if urllib.parse.urlparse(self.path).path == '/ending-preview.png':
            self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def send_json(self, status, data):
        raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def handle_request(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith(('/api/', '/__debug/')):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
                preview = self.server.preview
                if parsed.path == '/api/game/chat': time.sleep(preview.delay / 1000)
                with preview.lock:
                    result = preview.dispatch(self.command, parsed.path, urllib.parse.parse_qs(parsed.query), body)
                status, data = result if isinstance(result, tuple) else (200, result)
                self.send_json(status, data)
            except (ValueError, KeyError, StopIteration, TypeError):
                self.send_json(400, {'error': 'プレビューの入力値を確認してください。'})
            return
        if self.command != 'GET':
            self.send_json(404, {'error': 'Not found'})
            return
        filename = {'/': 'index.html', '/login': 'login.html', '/characters': 'characters.html'}.get(parsed.path)
        if filename:
            html = (STATIC / filename).read_text(encoding='utf-8')
            html = html.replace('</head>', '<script src="/ui-debug.js" defer></script></head>')
            html = html.replace('<body', '<body data-ui-preview="true"', 1)
            raw = html.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        else:
            super().do_GET()


def main():
    parser = argparse.ArgumentParser(description='外部接続なしのUIプレビュー')
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    preview_server = http.server.ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    preview_server.preview = Preview()
    print(f'UI preview: http://127.0.0.1:{args.port} (Ctrl+C to stop)', flush=True)
    try: preview_server.serve_forever()
    except KeyboardInterrupt: pass
    finally: preview_server.server_close()


if __name__ == '__main__': main()
