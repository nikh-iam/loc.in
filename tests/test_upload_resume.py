import hashlib
from unittest.mock import Mock
import httpx
from app.config import CHUNK
from app.drive import DriveError
from .test_transfers import start_upload


def test_retry_acknowledged_chunk_does_not_duplicate(lan, runtime):
    key = start_upload(lan, CHUNK + 4)
    assert lan.put(f'/api/files/upload/{key}', content=b'a'*CHUNK).status_code == 200
    assert lan.put(f'/api/files/upload/{key}', content=b'a'*CHUNK).status_code == 409
    status = lan.get(f'/api/files/upload/{key}').json()
    assert status['transferred'] == CHUNK
    assert lan.put(f'/api/files/upload/{key}?offset={CHUNK}', content=b'end!').json()['completed']
    assert runtime.drive.received_sizes == [CHUNK, 4]
    assert lan.get(f'/api/files/upload/{key}').json()['completed']


def test_drive_received_chunk_but_reply_lost(lan, runtime):
    original = runtime.drive.upload_chunk
    def lost_reply(*args):
        original(*args)
        raise DriveError('Temporary connection interruption.', 503)
    runtime.drive.upload_chunk = lost_reply
    key = start_upload(lan, CHUNK+3)
    assert lan.put(f'/api/files/upload/{key}', content=b'x'*CHUNK).status_code == 503
    assert key in runtime.transfers.uploads
    assert lan.get(f'/api/files/upload/{key}').json()['transferred'] == CHUNK
    runtime.drive.upload_chunk = original
    assert lan.put(f'/api/files/upload/{key}?offset={CHUNK}', content=b'end').json()['completed']
    session = next(iter(runtime.drive.sessions.values()))
    assert session['hash'].digest() == hashlib.sha256(b'x'*CHUNK+b'end').digest()


def test_final_reply_lost_resolves_completed(lan, runtime):
    original = runtime.drive.upload_chunk
    def lost_reply(*args):
        original(*args)
        raise DriveError('Temporary interruption.', 503)
    runtime.drive.upload_chunk = lost_reply
    key = start_upload(lan, 3)
    assert lan.put(f'/api/files/upload/{key}', content=b'end').status_code == 503
    assert lan.get(f'/api/files/upload/{key}').json()['completed']
    assert not runtime.transfers.uploads
    assert lan.get(f'/api/files/upload/{key}').json()['completed']


def test_status_hides_sessions_from_other_devices(lan, runtime):
    from fastapi.testclient import TestClient
    from app.main import create_app
    key = start_upload(lan, 1)
    with TestClient(create_app(runtime, host=False), base_url='http://locin.local', client=('192.168.10.9', 1)) as other:
        assert other.get(f'/api/files/upload/{key}').status_code == 404
        assert lan.put(f'/api/files/upload/{key}', content=b'x').status_code == 200
        assert other.get(f'/api/files/upload/{key}').status_code == 404


def test_partial_acknowledgement_resumes_at_storage_offset(lan, runtime):
    original = runtime.drive.upload_chunk
    runtime.drive.upload_chunk = lambda url, data, offset, total: original(url, data[:256*1024], offset, total)
    key = start_upload(lan, CHUNK+1)
    result = lan.put(f'/api/files/upload/{key}', content=b'x'*CHUNK)
    assert result.json()['transferred'] == 256*1024
    runtime.drive.upload_chunk = original
    result = lan.put(f'/api/files/upload/{key}?offset={256*1024}', content=b'x'*(CHUNK+1-256*1024))
    assert result.json()['completed']


def test_expired_drive_session_releases_slot(lan, runtime):
    key = start_upload(lan)
    item = runtime.transfers.uploads[key]
    item['needs_sync'] = True
    runtime.drive.upload_status = Mock(side_effect=DriveError('Session expired.',404))
    assert lan.get(f'/api/files/upload/{key}').status_code == 404
    assert key not in runtime.transfers.uploads


def test_local_resume_uses_saved_bytes(host, tmp_path):
    from .test_local_storage import configure
    folder = configure(host, tmp_path)
    key = start_upload(host, CHUNK+2)
    assert host.put(f'/api/files/upload/{key}', content=b'x'*CHUNK).status_code == 200
    assert host.get(f'/api/files/upload/{key}').json()['transferred'] == CHUNK
    assert host.put(f'/api/files/upload/{key}?offset={CHUNK}', content=b'OK').json()['completed']
    assert (folder/'hello.txt').read_bytes() == b'x'*CHUNK+b'OK'
