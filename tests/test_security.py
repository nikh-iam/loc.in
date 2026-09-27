import time
import pytest
from fastapi.testclient import TestClient
from app.main import create_app


def test_host_requires_token(runtime):
    with TestClient(create_app(runtime), base_url='http://127.0.0.1:4028', client=('127.0.0.1', 1)) as c:
        assert c.get('/').status_code == 200
        assert c.get('/api/settings').status_code == 401
        assert c.post('/api/service/start').status_code == 401
        assert c.get('/api/status', headers={'X-Host-Token': 'wrong'}).status_code == 401


def test_host_rejects_remote_peer_and_rebound_host(runtime):
    with TestClient(create_app(runtime), base_url='http://127.0.0.1:4028', client=('192.168.1.9', 1)) as c:
        assert c.get('/').status_code == 403
    with TestClient(create_app(runtime), base_url='http://evil.example', client=('127.0.0.1', 1)) as c:
        assert c.get('/').status_code == 403


def test_host_cookie_and_cross_origin(host):
    response = host.post('/api/session')
    assert 'HttpOnly' in response.headers['set-cookie']
    assert 'SameSite=strict' in response.headers['set-cookie']
    host.headers.pop('X-Host-Token')
    assert host.get('/api/settings').status_code == 200
    assert host.put('/api/settings', json={'local_name': 'bad'}, headers={'Origin': 'https://attacker.example'}).status_code == 403
    assert host.post('/api/service/stop', headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403


def test_lan_cannot_access_controls_or_credentials(lan, runtime):
    for route in ('/api/settings', '/api/devices', '/api/drive/folders', '/auth/callback'):
        assert lan.get(route).status_code == 404
    assert lan.post('/api/auth/google').status_code == 404
    assert lan.post('/api/service/stop').status_code == 404
    response = lan.get('/api/status')
    assert response.status_code == 200
    assert runtime.host_token not in response.text
    assert 'email' not in response.json()
    assert 'folder_id' not in response.json()
    assert 'credentials' not in response.text


def test_lan_rejects_foreign_subnet(lan, runtime):
    with TestClient(create_app(runtime, host=False), base_url='http://locin.loc.in', client=('192.168.11.3', 1)) as c:
        assert c.get('/').status_code == 403


def test_lan_mutation_requires_header(lan):
    lan.headers.pop('X-Locin-Request')
    assert lan.post('/api/folders', json={'name': 'oops'}).status_code == 403


@pytest.mark.parametrize('parent', ['private', 'private-file'])
def test_folder_boundary_applies_to_list_upload_create(lan, parent):
    assert lan.get('/api/files', params={'parent': parent}).status_code == 403
    assert lan.post('/api/files/upload', json={'parent': parent, 'name': 'hello.txt', 'size': 4}).status_code == 403
    assert lan.post('/api/folders', json={'parent': parent, 'name': 'New'}).status_code == 403


def test_download_cannot_escape_or_follow_shortcut(lan):
    assert lan.get('/api/files/private-file/download').status_code == 403
    assert lan.get('/api/files/shortcut/download').status_code == 400


def test_moved_and_trashed_ancestor_revokes_access(lan, runtime):
    runtime.drive.items['file1']['parents'] = ['photos']
    runtime.drive.items['photos']['trashed'] = True
    assert lan.get('/api/files/file1/download').status_code == 403
    runtime.drive.items['photos'].pop('trashed')
    runtime.drive.items['photos']['parents'] = ['private']
    assert lan.get('/api/files/file1/download').status_code == 403


@pytest.mark.parametrize('name', ['../a.txt', 'a\\b.txt', '..', '\x00bad'])
def test_unsafe_names_rejected(lan, name):
    assert lan.post('/api/files/upload', json={'name': name, 'size': 1}).status_code == 400


def test_oauth_callback_requires_unexpired_state(host, runtime):
    assert host.get('/auth/callback?state=bad&code=secret').status_code == 400
    runtime.oauth = ('expected', object(), time.time() - 601)
    assert host.get('/auth/callback?state=expected&code=secret').status_code == 400


def test_oauth_cancel_consumes_state(host, runtime):
    runtime.oauth = ('expected', object(), time.time())
    assert host.get('/auth/callback?state=expected&error=access_denied').status_code == 400
    assert runtime.oauth is None


def test_assets_are_local_and_have_security_headers(lan):
    for path in ('/', '/assets/app.js', '/assets/style.css', '/assets/favicon.svg'):
        r = lan.get(path)
        assert r.status_code == 200
        assert r.headers['x-content-type-options'] == 'nosniff'
        assert "frame-ancestors 'none'" in r.headers['content-security-policy']


def test_local_name_and_ip_serve_only_lan_clients(lan):
    for hostname in ('192.168.10.2', 'locin.local', 'locin.loc.in'):
        assert lan.get('/api/status', headers={'host': hostname}).status_code == 200
    assert lan.get('/api/status', headers={'host': 'other.local'}).status_code == 403
