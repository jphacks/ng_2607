import unittest
from unittest.mock import Mock, call, patch

import server


class ServerStartupTest(unittest.TestCase):
    def test_port_is_bound_before_automation_and_resources_close_on_interrupt(self):
        lifecycle = Mock()
        with patch.object(server, "init_db"), \
             patch.object(server.http.server, "ThreadingHTTPServer") as listener, \
             patch.object(server.threading, "Thread") as worker, \
             patch.object(server, "stop_oauth_process") as stop_bridge, \
             patch("builtins.print"):
            lifecycle.attach_mock(listener, "listener")
            lifecycle.attach_mock(worker, "worker")
            lifecycle.attach_mock(stop_bridge, "stop_bridge")
            listener.return_value.serve_forever.side_effect = KeyboardInterrupt
            server.main()
        self.assertEqual(lifecycle.mock_calls, [
            call.listener(("127.0.0.1", server.PORT), server.Handler),
            call.worker(target=server.RUNNER.run_forever, name="automation", daemon=True),
            call.worker().start(),
            call.listener().serve_forever(),
            call.listener().server_close(),
            call.stop_bridge(),
        ])

    def test_busy_port_does_not_start_automation(self):
        with patch.object(server, "init_db"), \
             patch.object(server.http.server, "ThreadingHTTPServer", side_effect=OSError("port already in use")), \
             patch.object(server.threading, "Thread") as worker:
            with self.assertRaises(OSError):
                server.main()
        worker.assert_not_called()
