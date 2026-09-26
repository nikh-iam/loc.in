import base64
import os
import time
import pytest
from app.config import CHUNK


def configure(host, tmp_path):
    folder = tmp_path / 'Shared'
    folder.mkdir()
    result = host.put('/api/settings', json={'local_name': 'vault', 'storage_mode': 'local', 'local_folder': str(folder)})
    assert result.status_code == 200, result.text
    return folder


def begin(host, name='sample.txt', size=4):
    result = host.post('/api/files/upload', json={'name': name, 'size': size})
    assert result.status_code == 200, result.text
    return result.json()['id']


def test_local_without_google_and_switch_back(host, runtime, tmp_path):
    folder = configure(host, tmp_path)
    runtime.drive.credentials = None
    status = host.get('/api/status').json()
    assert status['connected'] and not status['drive_connected']
    assert status['storage_mode'] == 'local'
    assert status['folder_id'] == 'local_root'
    assert host.get('/api/files').json()['files'] == []
    (folder / 'hello.txt').write_text('offline')
    assert host.get('/api/files').json()['files'][0]['name'] == 'hello.txt'
    result = host.put('/api/settings', json={'local_name': 'vault', 'storage_mode': 'drive'})
    assert result.status_code == 200
    assert result.json()['folder_id'] == 'shared'
    assert result.json()['local_folder'] == str(folder)
    assert (folder / 'hello.txt').read_text() == 'offline'


def test_chunked_upload_download_and_collision(host, tmp_path):
    folder = configure(host, tmp_path)
    payload = b'x' * CHUNK + b'end'
    key = begin(host, size=len(payload))
    first = host.put(f'/api/files/upload/{key}', content=payload[:CHUNK])
    assert first.json() == {'transferred': CHUNK, 'completed': False}
    assert host.get('/api/files').json()['files'] == []
    assert host.put(f'/api/files/upload/{key}?offset={CHUNK}', content=b'end').json()['completed']
    assert (folder / 'sample.txt').read_bytes() == payload
    item = host.get('/api/files').json()['files'][0]
    assert host.get('/api/files/'+item['id']+'/download').content == payload
    assert host.post('/api/files/upload', json={'name': 'sample.txt', 'size': 1}).status_code == 409
    assert (folder / 'sample.txt').read_bytes() == payload
    zero = begin(host, name='empty.txt', size=0)
    assert host.put(f'/api/files/upload/{zero}', content=b'').json()['completed']
    assert (folder / 'empty.txt').stat().st_size == 0


@pytest.mark.parametrize('finish', ['cancel', 'invalid', 'reap', 'stop'])
def test_partial_cleanup(host, runtime, tmp_path, finish):
    folder = configure(host, tmp_path)
    key = begin(host)
    if os.name == 'nt':
        assert list(folder.iterdir())  # Windows holds a delete-on-close temporary file.
    assert host.put('/api/settings', json={'local_name': 'vault', 'storage_mode': 'drive'}).status_code == 409
    if finish == 'cancel':
        assert host.delete(f'/api/files/upload/{key}').status_code == 200
    elif finish == 'invalid':
        assert host.put(f'/api/files/upload/{key}', content=b'too long').status_code == 413
    elif finish == 'reap':
        runtime.transfers.uploads[key]['touched'] = time.time() - 700
        runtime.transfers.reap()
    else:
        runtime.transfers.stop()
    assert not list(folder.iterdir())
    assert not runtime.local.sessions


@pytest.mark.parametrize('name', ['../escape', 'a:b', 'CON', 'file.', '.locin-upload-secret', 'x\\y'])
def test_invalid_names(host, tmp_path, name):
    configure(host, tmp_path)
    assert host.post('/api/files/upload', json={'name': name, 'size': 1}).status_code == 400


def test_containment_folders_search_and_pagination(host, tmp_path):
    folder = configure(host, tmp_path)
    (tmp_path / 'private.txt').write_text('private')
    for relative in ['../private.txt', '/private.txt', 'C:/private.txt', 'a/../private.txt']:
        identifier = 'local_' + base64.urlsafe_b64encode(relative.encode()).decode().rstrip('=')
        assert host.get(f'/api/files/{identifier}/download').status_code == 404
    created = host.post('/api/folders', json={'name': 'Photos'}).json()
    assert host.get('/api/files/'+created['id']+'/download').status_code == 400
    assert host.get('/api/files', params={'parent': created['id']}).json()['files'] == []
    for n in range(102):
        (folder / f'file{n:03}.txt').write_text('ok')
    first = host.get('/api/files').json()
    assert len(first['files']) == 100
    assert len(host.get('/api/files', params={'page': first['nextPageToken']}).json()['files']) == 3
    assert len(host.get('/api/files?search=file101').json()['files']) == 1
    assert host.get('/api/files?page=bad').status_code == 400


def test_hardlink_not_exposed(host, tmp_path):
    folder = configure(host, tmp_path)
    outside = tmp_path / 'private.txt'
    outside.write_text('private')
    os.link(outside, folder / 'linked.txt')
    assert host.get('/api/files').json()['files'] == []


def test_local_lan_does_not_expose_path(host, runtime, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    folder = configure(host, tmp_path)
    (folder / 'hello.txt').write_text('hello')
    runtime.gateway.state = 'Running'
    runtime.gateway.ip = '192.168.10.2'
    runtime.gateway.subnet = '192.168.10.0/24'
    with TestClient(create_app(runtime, host=False), base_url='http://vault.loc.in', client=('192.168.10.3', 50000), headers={'X-Locin-Request': '1'}) as client:
        status = client.get('/api/status')
        assert 'local_folder' not in status.json()
        files = client.get('/api/files')
        assert str(folder) not in files.text
        assert client.get('/api/files/'+files.json()['files'][0]['id']+'/download').content == b'hello'
        assert client.post('/api/storage/select-folder').status_code == 404


def test_invalid_folder_and_running_guard(host, runtime, tmp_path):
    assert host.put('/api/settings', json={'local_name': 'vault', 'storage_mode': 'local', 'local_folder': str(tmp_path / 'missing')}).status_code == 400
    assert host.put('/api/settings', json={'local_name': 'vault', 'storage_mode': 'other'}).status_code == 422
    configure(host, tmp_path)
    runtime.gateway.state = 'Running'
    assert host.put('/api/settings', json={'local_name': 'vault', 'storage_mode': 'drive'}).status_code == 409


def test_native_picker_host_only(host, runtime, tmp_path):
    runtime.pick_folder = lambda: str(tmp_path)
    assert host.post('/api/storage/select-folder').json() == {'path': str(tmp_path)}


def test_collision_during_upload_preserves_existing(host, tmp_path):
    folder = configure(host, tmp_path)
    key = begin(host)
    (folder / 'sample.txt').write_bytes(b'original')
    assert host.put(f'/api/files/upload/{key}', content=b'new!').status_code == 409
    assert (folder / 'sample.txt').read_bytes() == b'original'
    assert len(list(folder.iterdir())) == 1


def test_missing_folder_error_does_not_leak_path(host, tmp_path):
    folder = configure(host, tmp_path)
    folder.rmdir()
    status = host.get('/api/status').json()
    assert status['unavailable'] and not status['connected']
    result = host.get('/api/files')
    assert result.status_code == 400
    assert str(folder) not in result.text
