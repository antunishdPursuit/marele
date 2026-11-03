import io
import json
import unittest
from email.message import Message
from unittest.mock import Mock, patch

from game import server


class RequestBodyTests(unittest.TestCase):
    def handler(self, payload=b"{}", headers=None):
        handler = object.__new__(server.Handler)
        handler.headers = Message()
        for key, value in headers or [("Content-Length", str(len(payload)))]:
            handler.headers[key] = value
        handler.rfile = Mock(wraps=io.BytesIO(payload))
        handler.connection = Mock()
        handler.connection.gettimeout.return_value = None
        return handler

    def test_valid_object_uses_a_bounded_read_and_restores_timeout(self):
        handler = self.handler(b'{"paused":true}')
        self.assertEqual(handler._body(), {"paused": True})
        handler.rfile.read1.assert_called_once_with(15)
        self.assertEqual(handler.connection.settimeout.call_args_list[-1].args, (None,))

    def test_oversized_body_is_rejected_before_reading_or_starting_a_night(self):
        handler = self.handler(headers=[("Content-Length", str(server.MAX_REQUEST_BYTES + 1))])
        handler.path = "/api/new"
        handler._json = Mock()
        with patch.object(server.NIGHTS, "new") as start:
            handler.do_POST()
        start.assert_not_called()
        handler.rfile.read1.assert_not_called()
        self.assertEqual(handler._json.call_args.args[1], 413)
        self.assertTrue(handler.close_connection)

    def test_bad_lengths_and_unsupported_framing_are_rejected_before_reading(self):
        cases = [
            [("Content-Length", "-1")],
            [("Content-Length", "invalid")],
            [("Content-Length", "")],
            [("Content-Length", "2"), ("Content-Length", "2")],
            [("Transfer-Encoding", "chunked")],
            [("Transfer-Encoding", "chunked"), ("Content-Length", "2")],
        ]
        for headers in cases:
            with self.subTest(headers=headers):
                handler = self.handler(headers=headers)
                with self.assertRaises(server.InvalidRequest):
                    handler._body()
                handler.rfile.read1.assert_not_called()

    def test_invalid_json_and_non_object_values_are_client_errors(self):
        for payload in [b"{", b"\xff", b"[]", b"null", b'"value"', b"1", b"[" * 1100 + b"0" + b"]" * 1100]:
            with self.subTest(payload=payload):
                with self.assertRaises(server.InvalidRequest):
                    self.handler(payload)._body()

    def test_truncated_body_is_rejected(self):
        with self.assertRaises(server.InvalidRequest):
            self.handler(b"{", [("Content-Length", "2")])._body()

    def test_timeout_is_reported_and_previous_socket_timeout_restored(self):
        handler = self.handler()
        handler.rfile.read1.side_effect = TimeoutError()
        with self.assertRaises(server.InvalidRequest) as error:
            handler._body()
        self.assertEqual(error.exception.status, 408)
        self.assertEqual(handler.connection.settimeout.call_args_list[-1].args, (None,))

    def test_slow_chunks_cannot_extend_the_total_read_deadline(self):
        handler = self.handler()
        handler.rfile.read1.side_effect = [b"{", b"}"]
        with patch.object(server.time, "monotonic", side_effect=[0, 1, 11]):
            with self.assertRaises(server.InvalidRequest) as error:
                handler._body()
        self.assertEqual(error.exception.status, 408)
        handler.rfile.read1.assert_called_once_with(2)

    def test_limit_boundary_accepts_a_valid_object(self):
        payload = json.dumps({"signal": "x" * (server.MAX_REQUEST_BYTES - 14)}).encode()
        self.assertEqual(len(payload), server.MAX_REQUEST_BYTES)
        self.assertEqual(self.handler(payload)._body()["signal"], "x" * (server.MAX_REQUEST_BYTES - 14))


if __name__ == "__main__":
    unittest.main()
