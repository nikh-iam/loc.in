import hashlib
import time
from fastapi.testclient import TestClient
from app.config import CHUNK
from app.main import create_app


def start_upload(client, size=5, name='hello.txt'):
    r = client.post('/api/files/upload', json={'name': name, 'size': size})
    assert r.status_code == 200, r.text
    assert 'url' not in r.json()
    return r.json()['id']


def test_upload_larger_than_chunk_is_bounded(lan, runtime):
    key = start_upload(lan, CHUNK + 19)
    first = b'a' * CHUNK
    last = b'b' * 19
    r = lan.put(f'/api/files/upload/{key}?offset=0', content=first)
    assert r.json() == {'transferred': CHUNK, 'completed': False}
    r = lan.put(f'/api/files/upload/{key}?offset={CHUNK}', content=last)
    assert r.json() == {'transferred': CHUNK + 19, 'completed': True}
    assert runtime.drive.received_sizes == [CHUNK, 19]
    session = next(iter(runtime.drive.sessions.values()))
    assert session['hash'].digest() == hashlib.sha256(first + last).digest()
    assert runtime.transfers.list()[0]['status'] == 'Completed'
    assert not runtime.transfers.uploads


def test_empty_file_upload(lan, runtime):
    key = start_upload(lan, 0)
    assert lan.put(f'/api/files/upload/{key}', content=b'').json()['completed']
    assert runtime.transfers.list()[0]['status'] == 'Completed'


def test_chunk_too_large_fails_without_sending_to_drive(lan, runtime):
    key = start_upload(lan, 2)
    assert lan.put(f'/api/files/upload/{key}', content=b'abc').status_code == 413
    assert not runtime.drive.received_sizes
    assert runtime.transfers.list()[0]['status'] == 'Failed'
    assert not runtime.transfers.uploads


def test_wrong_offset_and_incomplete_chunk(lan, runtime):
    key = start_upload(lan)
    assert lan.put(f'/api/files/upload/{key}?offset=1', content=b'hello').status_code == 409
    key = start_upload(lan)
    assert lan.put(f'/api/files/upload/{key}', content=b'hi').status_code == 400
    assert not runtime.drive.received_sizes


def test_limit_and_cancel_release_capacity(lan, runtime):
    keys = [start_upload(lan) for _ in range(3)]
    assert lan.post('/api/files/upload', json={'name': 'fourth', 'size': 1}).status_code == 429
    assert lan.delete(f'/api/files/upload/{keys[0]}').status_code == 200
    assert runtime.transfers.list()[-1]['status'] == 'Cancelled'
    start_upload(lan)


def test_upload_and_transfer_history_belong_to_device(lan, runtime):
    key = start_upload(lan)
    with TestClient(create_app(runtime, host=False), base_url='http://locin.loc.in', client=('192.168.10.9', 1), headers={'X-Locin-Request': '1'}) as other:
        assert other.put(f'/api/files/upload/{key}', content=b'hello').status_code == 404
        assert other.delete(f'/api/files/upload/{key}').status_code == 404
        assert other.get('/api/transfers').json()['transfers'] == []


def test_folder_move_during_upload_is_blocked(lan, runtime):
    r = lan.post('/api/files/upload', json={'name': 'test', 'size': 1, 'parent': 'photos'})
    key = r.json()['id']
    runtime.drive.items['photos']['parents'] = ['private']
    assert lan.put(f'/api/files/upload/{key}', content=b'a').status_code == 403
    assert not runtime.drive.received_sizes


def test_stale_upload_reaped(lan, runtime):
    key = start_upload(lan)
    runtime.transfers.uploads[key]['touched'] = time.time() - 700
    runtime.transfers.reap()
    assert not runtime.transfers.uploads
    assert runtime.transfers.list()[0]['status'] == 'Failed'


def test_download_stream_and_cleanup(lan, runtime):
    r = lan.get('/api/files/file1/download')
    assert r.status_code == 200
    assert r.content == b'Welcome to your local space!'
    assert "filename*=UTF-8''Welcome.txt" in r.headers['content-disposition']
    assert runtime.drive.download_closed
    assert not runtime.transfers.downloads
    transfer = runtime.transfers.list()[0]
    assert transfer['status'] == 'Completed'
    assert transfer['transferred'] == len(r.content)


def test_download_error_releases_capacity(lan, runtime):
    assert lan.get('/api/files/photos/download').status_code == 400
    assert not runtime.transfers.downloads
    assert runtime.transfers.list()[0]['status'] == 'Failed'
