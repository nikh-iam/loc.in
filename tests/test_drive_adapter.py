import threading
from unittest.mock import Mock
import httpx
import pytest
from app.drive import Drive, DriveError, API


@pytest.fixture
def drive():
    adapter = Drive.__new__(Drive)
    adapter.credentials = None
    adapter.lock = threading.RLock()
    adapter.unavailable = False
    return adapter


def test_resumable_acknowledgement_uses_google_range(drive):
    drive.request = Mock(return_value=httpx.Response(308, headers={'Range': 'bytes=0-4194303'}))
    assert drive.upload_chunk('https://www.googleapis.com/session', b'chunk', 0, 5000000) == (4194304, False)
    assert drive.request.call_args.kwargs['headers']['Content-Range'] == 'bytes 0-4/5000000'


def test_upload_completion_and_empty_file(drive):
    drive.request = Mock(return_value=httpx.Response(200, json={'id': 'done'}))
    assert drive.upload_chunk('https://www.googleapis.com/session', b'', 0, 0) == (0, True)
    assert drive.request.call_args.kwargs['headers']['Content-Range'] == 'bytes */0'


def test_query_resumable_session_status(drive):
    drive.request = Mock(return_value=httpx.Response(308, headers={'Range':'bytes=0-262143'}))
    assert drive.upload_status('https://www.googleapis.com/session', 5000000) == (262144, False)
    assert drive.request.call_args.kwargs['headers']['Content-Range'] == 'bytes */5000000'
    assert drive.request.call_args.kwargs['content'] == b''
    drive.request.return_value = httpx.Response(200)
    assert drive.upload_status('https://www.googleapis.com/session', 5000000) == (5000000, True)


def test_drive_rate_limit_is_retryable(drive):
    response = httpx.Response(403, json={'error': {'errors': [{'reason': 'userRateLimitExceeded'}]}})
    with pytest.raises(DriveError) as exc:
        drive.check(response)
    assert exc.value.status == 429


@pytest.mark.parametrize('location', ['https://attacker.example/token', 'http://www.googleapis.com/upload', 'https://www.googleapis.com.attacker.example/upload', ''])
def test_upload_session_never_sends_tokens_to_untrusted_origin(drive, location):
    drive.request = Mock(return_value=httpx.Response(200, headers={'Location': location}))
    with pytest.raises(DriveError):
        drive.upload_session('shared', 'test', 10, 'text/plain')


def test_query_escaping_and_pagination(drive):
    drive.request = Mock(return_value=httpx.Response(200, json={'files': [], 'nextPageToken': 'next'}))
    result = drive.listing('shared', 'cursor', "a'b\\c")
    params = drive.request.call_args.kwargs['params']
    assert params['q'] == "'shared' in parents and trashed = false and name contains 'a\\'b\\\\c'"
    assert params['pageToken'] == 'cursor'
    assert result['nextPageToken'] == 'next'


def test_auth_revocation_is_not_returned_as_success(drive):
    drive.credentials = object()
    with pytest.raises(DriveError) as exc:
        drive.check(httpx.Response(401))
    assert exc.value.status == 401
    assert drive.credentials is None


def test_network_error_has_sanitized_message(drive, monkeypatch):
    drive.token = lambda: 'TEST_ACCESS_TOKEN_DO_NOT_LEAK'
    def fail(*args, **kwargs):
        raise httpx.ConnectError('private access_token=TEST_ACCESS_TOKEN_DO_NOT_LEAK')
    monkeypatch.setattr(httpx.Client, 'request', fail)
    with pytest.raises(DriveError) as exc:
        drive.request('GET', '/files')
    assert 'TEST_ACCESS_TOKEN' not in str(exc.value)
    assert drive.unavailable


def test_docs_export_streams_and_adds_extension(drive, monkeypatch):
    drive.token = lambda: 'test-only-token'
    seen = []
    def send(client, request, **kwargs):
        seen.append((request, kwargs))
        return httpx.Response(200, stream=httpx.ByteStream(b'%PDF-test'))
    monkeypatch.setattr(httpx.Client, 'send', send)
    client, response, name, mime = drive.download({'id': 'doc1', 'name': 'Report', 'mimeType': 'application/vnd.google-apps.document'})
    try:
        assert name == 'Report.pdf'
        assert mime == 'application/pdf'
        assert str(seen[0][0].url) == API + '/files/doc1/export?mimeType=application%2Fpdf'
        assert seen[0][1]['stream'] is True
    finally:
        response.close()
        client.close()
