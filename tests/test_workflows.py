import pytest
from app.database import Database


def test_settings_persist_and_normalize(host, runtime):
    r = host.put('/api/settings', json={'local_name': 'Vault', 'folder_id': 'photos'})
    assert r.status_code == 200
    assert r.json()['local_name'] == 'vault'
    assert r.json()['folder_name'] == 'Photos'
    assert Database(runtime.db.path).settings()['folder_id'] == 'photos'


@pytest.mark.parametrize('name', ['bad.local', '-bad', 'bad-', 'with space', ''])
def test_invalid_hostname(host, name):
    assert host.put('/api/settings', json={'local_name': name}).status_code == 400


def test_settings_locked_while_running(host, runtime):
    runtime.gateway.state = 'Running'
    assert host.put('/api/settings', json={'local_name': 'vault'}).status_code == 409
    assert host.post('/api/drive/default-folder').status_code == 409


def test_drive_picker_only_on_host(host):
    data = host.get('/api/drive/folders').json()
    assert {f['id'] for f in data['files']} == {'shared', 'private'}
    assert host.post('/api/drive/default-folder').json()['id'] == 'shared'


def test_listing_search_and_page_are_forwarded(lan, runtime):
    r = lan.get('/api/files', params={'parent': 'shared', 'search': 'Welcome', 'page': 'next-page'})
    assert [f['id'] for f in r.json()['files']] == ['file1']
    assert runtime.drive.list_calls[-1] == ('shared', 'next-page', 'Welcome', False)


def test_local_shell_survives_internet_failure(lan, runtime):
    runtime.drive.unavailable = True
    assert lan.get('/').status_code == 200
    assert lan.get('/assets/app.js').status_code == 200
    assert lan.get('/api/status').json()['unavailable'] is True
    r = lan.get('/api/files')
    assert r.status_code == 503
    assert 'still running' in r.json()['detail']


def test_disconnected_drive_is_handled(lan, runtime):
    runtime.drive.credentials = None
    assert lan.get('/api/files').status_code == 401
    assert lan.get('/api/status').json()['connected'] is False


def test_devices_use_recent_communication(lan, host, runtime):
    lan.get('/api/status', headers={'User-Agent': 'Mozilla iPhone'})
    devices = host.get('/api/devices').json()['devices']
    assert devices[0]['name'] == 'iPhone'
    assert devices[0]['ip_address'] == '192.168.10.3'
    with runtime.db.connect() as db:
        db.execute('UPDATE devices SET last_seen=0')
    assert host.get('/api/devices').json()['devices'] == []


def test_start_without_drive_returns_actionable_state(host, runtime):
    runtime.drive.credentials = None
    r = host.post('/api/service/start')
    assert r.json()['state'] == 'Error'
    assert 'Connect Google Drive' in r.json()['error']
    assert host.post('/api/service/stop').json()['state'] == 'Stopped'


def test_startup_without_installed_app_is_actionable(host):
    r = host.put('/api/settings', json={'local_name': 'locin', 'start_at_login': True})
    assert r.status_code == 400
    assert 'installed Windows app' in r.json()['detail']
