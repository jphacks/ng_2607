import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server


ECHO_BRIDGE = r'''
import json
import sys
import time

sys.stdin.reconfigure(encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8')
for line in sys.stdin:
    command = json.loads(line)
    op = command.get('op')
    if op == 'timeout':
        time.sleep(30)
    elif op == 'eof':
        break
    elif op == 'invalid-json':
        print('not valid JSON', flush=True)
    elif op == 'invalid-shape':
        print('[]', flush=True)
    elif op == 'error':
        print(json.dumps({'error': 'テスト用の認証エラー'}, ensure_ascii=False), flush=True)
    else:
        print(json.dumps({'result': command}, ensure_ascii=False), flush=True)
'''


class OAuthBridgeTest(unittest.TestCase):
    """Exercise real local pipes without loading Node.js or reaching any network."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root = Path(self.folder.name)
        (root / 'node_modules' / '@atproto' / 'oauth-client-node').mkdir(parents=True)
        self.real_popen = subprocess.Popen
        self.processes = []
        self.spawn_arguments = []
        for item in (patch.object(server, 'ROOT', root), patch.object(server, 'OAUTH_PROCESS', None),
                     patch.object(server.subprocess, 'check_output', return_value='24.0.0'),
                     patch.object(server.subprocess, 'Popen', side_effect=self.spawn)):
            item.start()
            self.addCleanup(item.stop)
        self.addCleanup(self.stop_children)

    def spawn(self, arguments, **kwargs):
        # Preserve the production pipe options while substituting a deterministic local bridge.
        self.spawn_arguments.append((arguments, kwargs.copy()))
        process = self.real_popen([sys.executable, '-u', '-X', 'utf8', '-c', ECHO_BRIDGE], **kwargs)
        self.processes.append(process)
        return process

    def stop_children(self):
        server.stop_oauth_process()
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            for stream in (process.stdin, process.stdout):
                if stream:
                    stream.close()

    def assert_discarded(self, process):
        self.assertIsNone(server.OAUTH_PROCESS)
        self.assertIsNotNone(process.poll())
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)

    def test_utf8_jsonlines_round_trip_and_sequential_commands_share_one_process(self):
        commands = [{'op': 'echo', 'text': '結城めもりとお話し 🌸'},
                    {'op': 'echo', 'text': '2通目には改行\nと絵文字🐈もある'}]
        for command in commands:
            self.assertEqual(server.oauth_call(command), command)
        self.assertEqual(len(self.processes), 1)
        self.assertEqual(self.spawn_arguments[0][1]['encoding'], 'utf-8')
        self.assertEqual(self.spawn_arguments[0][1]['text'], True)
        self.assertEqual(server.OAUTH_PROCESS, self.processes[0])

    def test_timeout_discards_process_and_next_command_recovers(self):
        with patch.object(server, 'OAUTH_RESPONSE_TIMEOUT', 0.1):
            with self.assertRaisesRegex(RuntimeError, '時間内'):
                server.oauth_call({'op': 'timeout'})
        self.assert_discarded(self.processes[0])
        recovered = {'op': 'echo', 'text': '再接続できた 🔄'}
        self.assertEqual(server.oauth_call(recovered), recovered)
        self.assertEqual(len(self.processes), 2)

    def test_eof_invalid_json_and_invalid_shape_discard_process_then_recover(self):
        for op in ('eof', 'invalid-json', 'invalid-shape'):
            with self.subTest(op=op):
                with self.assertRaisesRegex(RuntimeError, '通信'):
                    server.oauth_call({'op': op})
                self.assert_discarded(self.processes[-1])
                recovered = {'op': 'echo', 'text': '次の要求は正常'}
                self.assertEqual(server.oauth_call(recovered), recovered)

    def test_bridge_reported_error_keeps_working_process_for_next_request(self):
        with self.assertRaisesRegex(RuntimeError, 'テスト用の認証エラー'):
            server.oauth_call({'op': 'error'})
        process = server.OAUTH_PROCESS
        self.assertIsNotNone(process)
        self.assertIsNone(process.poll())
        self.assertEqual(server.oauth_call({'op': 'echo'}), {'op': 'echo'})
        self.assertEqual(len(self.processes), 1)


if __name__ == '__main__':
    unittest.main()
