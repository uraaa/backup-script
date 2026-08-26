import os
import tempfile
import unittest
from unittest.mock import patch

import requests

from modules.storage_sharepoint import SharePointClient, SharePointConfig


CHUNK_SIZE = 5 * 1024 * 1024


class FakeResponse:
    def __init__(self, status_code, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._payload


class InterruptedUploadSession:
    def __init__(self):
        self.put_calls = []
        self.status_calls = 0

    def post(self, *_args, **_kwargs):
        return FakeResponse(200, {"uploadUrl": "https://upload.example/session-secret"})

    def put(self, _url, headers, data, **_kwargs):
        self.put_calls.append((headers["Content-Range"], len(data)))
        call_number = len(self.put_calls)
        if call_number == 1:
            return FakeResponse(202, {"nextExpectedRanges": [f"{CHUNK_SIZE}-"]})
        if call_number == 2:
            raise requests.exceptions.SSLError("connection closed during upload")
        return FakeResponse(201, {"name": "backup.tar.gz"})

    def get(self, _url, **_kwargs):
        self.status_calls += 1
        return FakeResponse(200, {"nextExpectedRanges": [f"{CHUNK_SIZE}-"]})


class RangeRecoverySession(InterruptedUploadSession):
    def put(self, _url, headers, data, **_kwargs):
        self.put_calls.append((headers["Content-Range"], len(data)))
        if len(self.put_calls) == 1:
            return FakeResponse(416)
        return FakeResponse(201, {"name": "backup.tar.gz"})


class StalledUploadSession(InterruptedUploadSession):
    def put(self, _url, headers, data, **_kwargs):
        self.put_calls.append((headers["Content-Range"], len(data)))
        if len(self.put_calls) > 3:
            raise AssertionError("upload did not stop after repeated stalled responses")
        return FakeResponse(202, {"nextExpectedRanges": ["0-"]})


class FailingUploadSession(InterruptedUploadSession):
    def put(self, _url, headers, data, **_kwargs):
        self.put_calls.append((headers["Content-Range"], len(data)))
        raise requests.exceptions.SSLError(
            "connection failed at https://upload.example/session-secret"
        )

    def get(self, _url, **_kwargs):
        self.status_calls += 1
        return FakeResponse(200, {"nextExpectedRanges": ["0-"]})


class SharePointUploadTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(delete=False)
        handle.write(b"x" * (CHUNK_SIZE + 3))
        handle.close()
        self.archive_path = handle.name

    def tearDown(self):
        os.unlink(self.archive_path)

    def test_connection_interruption_resumes_from_server_expected_range(self):
        session = InterruptedUploadSession()
        client = SharePointClient(
            SharePointConfig("tenant", "client", "secret", "site", "drive", "/backups"),
            session=session,
        )
        client.token = "token"

        with patch("time.sleep", return_value=None):
            try:
                result = client.upload_file(self.archive_path)
            except requests.exceptions.SSLError as exc:
                self.fail(f"upload did not resume after the connection interruption: {exc}")

        self.assertEqual(result, os.path.basename(self.archive_path))
        self.assertEqual(session.status_calls, 1)
        self.assertEqual(
            session.put_calls,
            [
                (f"bytes 0-{CHUNK_SIZE - 1}/{CHUNK_SIZE + 3}", CHUNK_SIZE),
                (f"bytes {CHUNK_SIZE}-{CHUNK_SIZE + 2}/{CHUNK_SIZE + 3}", 3),
                (f"bytes {CHUNK_SIZE}-{CHUNK_SIZE + 2}/{CHUNK_SIZE + 3}", 3),
            ],
        )

    def test_range_error_uses_server_expected_range(self):
        session = RangeRecoverySession()
        client = SharePointClient(
            SharePointConfig("tenant", "client", "secret", "site", "drive", "/backups"),
            session=session,
        )
        client.token = "token"

        with patch("time.sleep", return_value=None):
            result = client.upload_file(self.archive_path)

        self.assertEqual(result, os.path.basename(self.archive_path))
        self.assertEqual(session.status_calls, 1)
        self.assertEqual(
            session.put_calls,
            [
                (f"bytes 0-{CHUNK_SIZE - 1}/{CHUNK_SIZE + 3}", CHUNK_SIZE),
                (f"bytes {CHUNK_SIZE}-{CHUNK_SIZE + 2}/{CHUNK_SIZE + 3}", 3),
            ],
        )

    def test_repeated_stalled_ranges_stop_after_retry_limit(self):
        session = StalledUploadSession()
        client = SharePointClient(
            SharePointConfig("tenant", "client", "secret", "site", "drive", "/backups"),
            session=session,
        )
        client.token = "token"

        with patch("modules.storage_sharepoint.MAX_CHUNK_RETRIES", 2):
            with self.assertRaisesRegex(RuntimeError, "failed after 2 retries"):
                client.upload_file(self.archive_path)

    def test_retry_exhaustion_does_not_expose_upload_session_url(self):
        session = FailingUploadSession()
        client = SharePointClient(
            SharePointConfig("tenant", "client", "secret", "site", "drive", "/backups"),
            session=session,
        )
        client.token = "token"

        with patch("modules.storage_sharepoint.MAX_CHUNK_RETRIES", 2):
            with patch("time.sleep", return_value=None):
                with self.assertRaises(RuntimeError) as context:
                    client.upload_file(self.archive_path)

        self.assertNotIn("upload.example", str(context.exception))
        self.assertNotIn("session-secret", str(context.exception))


if __name__ == "__main__":
    unittest.main()
